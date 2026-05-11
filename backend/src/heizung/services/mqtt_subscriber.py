"""MQTT-Subscriber fuer ChirpStack-Application-Uplinks.

Sprint 5 (LoRaWAN-Foundation):
Konsumiert Uplink-Events von ChirpStack v4 ueber Mosquitto, validiert sie
mit Pydantic und persistiert die dekodierten Werte in ``sensor_reading``.

- Topic: ``application/+/device/+/event/up`` (alle Apps, alle Devices)
- QoS 1, persistente Session ueber fixe Client-ID, Auto-Reconnect mit
  Exponential Backoff
- Idempotenz: ON CONFLICT (time, device_id) DO NOTHING auf der Hypertable
- Unbekannte DevEUIs werden geloggt + verworfen (kein Auto-Create -
  Geraete legt der Admin in der Backend-API an)

Lebenszyklus: gestartet als asyncio-Background-Task aus FastAPI-Lifespan.
Skalierung > 1 Replica: separater Worker-Container in spaeterem Sprint.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import aiomqtt
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from heizung.config import get_settings
from heizung.db import SessionLocal
from heizung.models.device import Device
from heizung.models.heating_zone import HeatingZone
from heizung.models.sensor_reading import SensorReading
from heizung.services.device_adapter import handle_uplink_for_override
from heizung.tasks.engine_tasks import evaluate_room

logger = logging.getLogger(__name__)

# Sprint 9.11x.b T6: Codec setzt ``report_type`` fuer alle Command-Replies
# (cmd-byte != 0x01/0x81 Periodic). Subscriber skipped sensor_reading-
# Insert fuer alle Replies — Reply-Frames haben weder temperature noch
# valve_position und wuerden nur NULL-Garbage in der Hypertable erzeugen.
REPLY_REPORT_TYPES: frozenset[str] = frozenset(
    {
        "setpoint_reply",  # 0x52 — Drehring/Setpoint-Ack (Sprint 9.0)
        "firmware_version_reply",  # 0x04 — FW-Query (Sprint 9.11x.b)
        "open_window_status_reply",  # 0x46 — OW-Get (Sprint 9.11x.b)
    }
)


# ---------------------------------------------------------------------------
# Pydantic-Schemas fuer ChirpStack-v4-Uplink-JSON
# ---------------------------------------------------------------------------


class _DeviceInfo(BaseModel):
    devEui: str  # noqa: N815  - ChirpStack-Field-Casing


class _RxInfo(BaseModel):
    rssi: int | None = None
    snr: float | None = None


class ChirpStackUplink(BaseModel):
    """Subset des ChirpStack-v4-Application-Event-Up-Schemas."""

    deviceInfo: _DeviceInfo  # noqa: N815
    fCnt: int = Field(..., ge=0)  # noqa: N815
    fPort: int | None = None  # noqa: N815
    time: datetime | None = None
    object: dict[str, Any] | None = None
    rxInfo: list[_RxInfo] = Field(default_factory=list)  # noqa: N815
    data: str | None = None  # base64-encoded raw payload


# ---------------------------------------------------------------------------
# Mapping: ChirpStack-Object -> SensorReading-Spalten
# ---------------------------------------------------------------------------


def _battery_pct_from_volts(volts: float | None) -> int | None:
    """Linear 3.0 V (0 %) bis 4.2 V (100 %), geclampt 0..100."""
    if volts is None:
        return None
    pct = int(round((volts - 3.0) / 1.2 * 100))
    return max(0, min(100, pct))


def _to_decimal(v: Any) -> Decimal | None:
    if v is None:
        return None
    try:
        return Decimal(str(v))
    except (ValueError, ArithmeticError):
        return None


def _map_to_reading(uplink: ChirpStackUplink, device_id: int) -> dict[str, Any]:
    """Periodic-Report (fPort 1) -> SensorReading-Row.

    Sprint 9.0: Subscriber liest jetzt `valve_openness` aus dem Codec-Output
    (Wert 0..100 % geclampt, statt raw `motor_position`-Zahlen wie 1984).
    Fallback auf `motor_position` bleibt fuer den Uebergang, falls Server
    noch alten Codec hat.
    """
    obj = uplink.object or {}
    rx = uplink.rxInfo[0] if uplink.rxInfo else None
    ts = uplink.time or datetime.now(tz=UTC)

    valve_pct = obj.get("valve_openness")
    if valve_pct is None:
        # Fallback auf alten Codec-Output. motor_position ist KEIN Prozent —
        # Wert wird damit zwar persistiert, ist aber semantisch falsch.
        # Greift nur bis ChirpStack-Codec auf Sprint-9.0-Version aktualisiert ist.
        valve_pct = obj.get("motor_position")

    return {
        "time": ts,
        "device_id": device_id,
        "fcnt": uplink.fCnt,
        "temperature": _to_decimal(obj.get("temperature")),
        "setpoint": _to_decimal(obj.get("target_temperature")),
        "valve_position": valve_pct,
        "battery_percent": _battery_pct_from_volts(obj.get("battery_voltage")),
        "rssi_dbm": rx.rssi if rx else None,
        "snr_db": _to_decimal(rx.snr) if rx else None,
        # Sprint 9.10: Vicki openWindow durchreichen (NULL wenn Feld fehlt,
        # nicht False).
        "open_window": obj.get("openWindow"),
        # Sprint 9.11x: Vicki attachedBackplate (FW >= 4.1) durchreichen.
        # NULL wenn Feld fehlt (alter Codec) — Layer 4 Detached behandelt
        # NULL als "Device unklar", nicht als detached.
        "attached_backplate": obj.get("attachedBackplate"),
        "raw_payload": uplink.data,
    }


# ---------------------------------------------------------------------------
# Persistenz
# ---------------------------------------------------------------------------


async def _persist_uplink(uplink: ChirpStackUplink) -> None:
    """DevEUI -> device_id aufloesen, Reading idempotent inserten,
    last_seen_at am Device aktualisieren (M-6 / QA-Audit 2026-04-29).
    """
    dev_eui = uplink.deviceInfo.devEui.lower()

    async with SessionLocal() as session:
        result = await session.execute(select(Device.id).where(Device.dev_eui == dev_eui))
        device_id = result.scalar_one_or_none()

        if device_id is None:
            logger.warning(
                "uplink für unbekannte DevEUI verworfen: %s (fcnt=%s)",
                dev_eui,
                uplink.fCnt,
            )
            return

        values = _map_to_reading(uplink, device_id)
        stmt = (
            pg_insert(SensorReading)
            .values(**values)
            .on_conflict_do_nothing(index_elements=["time", "device_id"])
        )
        await session.execute(stmt)

        # last_seen_at = uplink.time (vom Gateway, monotone Zeit) wenn vorhanden,
        # sonst now() (Subscriber-Empfangszeit). Decreasing-Updates werden mit
        # WHERE last_seen_at < new_value abgewehrt (Late-Arrivals nach Re-Sync).
        seen_at = uplink.time or datetime.now(tz=UTC)
        await session.execute(
            update(Device)
            .where(Device.id == device_id)
            .where((Device.last_seen_at.is_(None)) | (Device.last_seen_at < seen_at))
            .values(last_seen_at=seen_at)
        )
        await session.commit()

        logger.info(
            "uplink persistiert: dev_eui=%s fcnt=%s temp=%s setpoint=%s seen_at=%s",
            dev_eui,
            values["fcnt"],
            values["temperature"],
            values["setpoint"],
            seen_at.isoformat(),
        )

        # Sprint 9.10 T3: Re-Eval-Trigger. Jedes frische Reading kann den
        # Engine-State aendern (Layer 4 Window-Detection braucht aktuelles
        # open_window). Ohne Trigger wuerde Layer 4 erst beim naechsten
        # 60-s-Beat-Tick reagieren — fuer Fenster-Auf-Erkennung zu lahm.
        # Race-Condition mit parallelen evaluate_room ist durch
        # AE-40 (Redis-SETNX-Lock in evaluate_room) abgedeckt.
        room_id = (
            await session.execute(
                select(HeatingZone.room_id)
                .join(Device, Device.heating_zone_id == HeatingZone.id)
                .where(Device.id == device_id)
            )
        ).scalar_one_or_none()
        if room_id is not None:
            evaluate_room.delay(room_id)
            logger.info(
                "evaluate_room geschedult room_id=%s dev_eui=%s",
                room_id,
                dev_eui,
            )
        else:
            logger.warning(
                "device_id=%s ohne heating_zone -> kein Re-Eval geschedult",
                device_id,
            )


async def _handle_open_window_status_report(uplink: ChirpStackUplink) -> None:
    """Sprint 9.11x.b T5: loggt OW-Status aus Codec-Output (S6: Logger,
    kein DB-Insert, kein Schema-Drift).

    Codec emittiert nach Antwort auf 0x46-Downlink (Vendor-Doku §04):
        - ``open_window_detection_enabled``: bool
        - ``open_window_detection_duration_min``: int (= byte * 5)
        - ``open_window_detection_delta_c``: float (= byte / 10)

    Audit-Trail via journalctl (event_type-Marker im Log-String macht
    den Eintrag grep-bar). Bewusste S6-Entscheidung statt event_log-DB-
    Insert: Maintenance-Reports sind seltene Events (~1x pro Bulk-
    Aktivierung), DB-Audit waere Overkill.
    """
    obj = uplink.object or {}
    if "open_window_detection_enabled" not in obj:
        return
    dev_eui = uplink.deviceInfo.devEui.lower()
    logger.info(
        "event_type=MAINTENANCE_VICKI_CONFIG_REPORT dev_eui=%s "
        "enabled=%s duration_min=%s delta_c=%s",
        dev_eui,
        obj.get("open_window_detection_enabled"),
        obj.get("open_window_detection_duration_min"),
        obj.get("open_window_detection_delta_c"),
    )


async def _handle_firmware_version_report(uplink: ChirpStackUplink) -> None:
    """Sprint 9.11x.b T4: persistiert ``firmware_version`` aus Codec-Output.

    Codec emittiert ``firmware_version: "{FW_major}.{FW_minor}"`` (z.B.
    ``"4.5"``) nach Antwort auf 0x04-Downlink (Vendor-Doku §04). Wird
    in ``device.firmware_version`` (VARCHAR(8) NULL, Migration 0010)
    persistiert, separater UPDATE — nicht Teil von sensor_reading.

    Defensive: None / leerer String / > 8 Zeichen / nicht-String werden
    als Warning geloggt, kein DB-Write. Failure ist non-fatal — wir
    loggen und blockieren die Subscriber-Loop nicht.
    """
    obj = uplink.object or {}
    fw = obj.get("firmware_version")
    if fw is None:
        return
    dev_eui = uplink.deviceInfo.devEui.lower()
    if not isinstance(fw, str) or not fw or len(fw) > 8:
        logger.warning(
            "firmware_version-Format ungueltig dev_eui=%s value=%r",
            dev_eui,
            fw,
        )
        return
    rowcount: int | None = None
    try:
        async with SessionLocal() as session:
            result = await session.execute(
                update(Device).where(Device.dev_eui == dev_eui).values(firmware_version=fw)
            )
            await session.commit()
            # rowcount ist auf SQLAlchemy-AsyncResult fuer UPDATE-Statements
            # vorhanden, aber nicht im statischen Result[Any]-Typ — getattr
            # mit Default umgeht den mypy-attr-defined-Error.
            rowcount = getattr(result, "rowcount", None)
    except Exception:
        logger.exception("firmware_version-update-fehler dev_eui=%s", dev_eui)
        return

    # Sprint 9.11x.c (B-9.11x.b-6 Fix): Log AUSSERHALB des async-with-
    # Blocks und mit rowcount-Diagnose. In 9.11x.b feuerte der info-Log
    # auf heizung-test nicht zuverlaessig (vermutlich Context-Manager-
    # Exit-Race oder Buffer). Plus: UPDATE auf nicht-existente dev_eui
    # waere bisher silent durchgelaufen — jetzt sichtbar als WARNING.
    if rowcount == 0:
        logger.warning(
            "firmware_version: UPDATE matched 0 rows dev_eui=%s — Device nicht in DB? fw=%s",
            dev_eui,
            fw,
        )
        return
    logger.info(
        "firmware_version persistiert dev_eui=%s fw=%s rows=%s",
        dev_eui,
        fw,
        rowcount if rowcount is not None else "?",
    )


async def _handle_override_detection(uplink: ChirpStackUplink) -> None:
    """Sprint 9.9 T5: Drehknopf-Override-Detection nach Reading-Persistenz.

    Vergleicht den Uplink-Setpoint mit dem letzten Engine-Send fuer
    dasselbe Geraet (siehe ``device_adapter.detect_user_override``).
    Bei Diff > Toleranz und ausserhalb des Acknowledgment-Windows wird
    ein ``device``-Override angelegt. Failure ist non-fatal; wir loggen
    und blockieren die Subscriber-Loop nicht.
    """
    obj = uplink.object or {}
    target_temp_raw = obj.get("target_temperature")
    if target_temp_raw is None:
        return

    dev_eui = uplink.deviceInfo.devEui.lower()
    try:
        async with SessionLocal() as session:
            row = await session.execute(select(Device.id).where(Device.dev_eui == dev_eui))
            device_id = row.scalar_one_or_none()
            if device_id is None:
                return

            received_at = uplink.time or datetime.now(tz=UTC)
            override = await handle_uplink_for_override(
                session,
                device_id=device_id,
                uplink_target_temp=Decimal(str(target_temp_raw)),
                fport=uplink.fPort or 1,
                received_at=received_at,
            )
            if override is not None:
                await session.commit()
                logger.info(
                    "device-override erkannt dev_eui=%s setpoint=%s expires_at=%s",
                    dev_eui,
                    override.setpoint,
                    override.expires_at.isoformat(),
                )
    except Exception:
        logger.exception("override-detection-fehler dev_eui=%s", dev_eui)


# ---------------------------------------------------------------------------
# Subscriber-Loop
# ---------------------------------------------------------------------------


async def _consume_loop() -> None:
    """Reconnect-fester MQTT-Subscriber. Laeuft bis Cancellation."""
    settings = get_settings()
    backoff = 1.0

    while True:
        try:
            async with aiomqtt.Client(
                hostname=settings.mqtt_host,
                port=settings.mqtt_port,
                username=settings.mqtt_user,
                password=settings.mqtt_password,
                identifier=settings.mqtt_client_id,
                clean_session=False,
                keepalive=30,
            ) as client:
                logger.info(
                    "MQTT verbunden host=%s topic=%s",
                    settings.mqtt_host,
                    settings.mqtt_topic,
                )
                await client.subscribe(settings.mqtt_topic, qos=1)
                backoff = 1.0  # nach erfolgreichem Verbinden zuruecksetzen

                async for message in client.messages:
                    try:
                        uplink = ChirpStackUplink.model_validate_json(message.payload)
                    except ValidationError as e:
                        logger.warning(
                            "uplink-validierung fehlgeschlagen topic=%s err=%s",
                            message.topic,
                            e.errors()[:3],
                        )
                        continue
                    except Exception:
                        logger.exception("uplink-decode-fehler topic=%s", message.topic)
                        continue

                    # Sprint 9.10c: Codec routet ueber Cmd-Byte (0x52 -> Reply,
                    # sonst -> Periodic), siehe ``infra/chirpstack/codecs/
                    # mclimate-vicki.js``. Vickis schicken Periodic-Reports
                    # auch auf fPort 2 (Live-Beleg 2026-05-07) — fPort allein
                    # ist also kein zuverlaessiges Routing-Signal. Wir
                    # entscheiden hier ausschliesslich nach
                    # ``report_type == 'setpoint_reply'``.
                    #
                    # Setpoint-Replies (cmd 0x52) haben kein temperature/
                    # valve_position. Skip SensorReading-Insert, aber
                    # Override-Detection (Sprint 9.9 T5) laeuft trotzdem —
                    # der Drehring meldet seinen Setpoint hier zurueck.
                    obj = uplink.object or {}
                    if obj.get("report_type") in REPLY_REPORT_TYPES:
                        logger.info(
                            "command-reply dev_eui=%s report_type=%s — skip reading-insert",
                            uplink.deviceInfo.devEui,
                            obj.get("report_type"),
                        )
                        await _handle_override_detection(uplink)
                        # Sprint 9.11x.b: FW + OW-Status sind eigene Reply-
                        # Typen (siehe REPLY_REPORT_TYPES). Override-Detection
                        # ist defensive (fehlt target_temperature -> return),
                        # daher safe fuer alle Reply-Typen aufzurufen.
                        await _handle_firmware_version_report(uplink)
                        await _handle_open_window_status_report(uplink)
                        continue

                    try:
                        await _persist_uplink(uplink)
                    except Exception:
                        logger.exception(
                            "uplink-persist-fehler dev_eui=%s",
                            uplink.deviceInfo.devEui,
                        )

                    await _handle_override_detection(uplink)
                    await _handle_firmware_version_report(uplink)
                    await _handle_open_window_status_report(uplink)
        except asyncio.CancelledError:
            logger.info("MQTT-Subscriber beendet (CancelledError)")
            raise
        except aiomqtt.MqttError as e:
            logger.warning("MQTT-Verbindung verloren, Reconnect in %.1fs: %s", backoff, e)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30.0)
        except Exception:
            logger.exception("MQTT-Loop unerwarteter Fehler, Reconnect in %.1fs", backoff)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30.0)


# ---------------------------------------------------------------------------
# Public Lifespan-Hooks
# ---------------------------------------------------------------------------


_task: asyncio.Task[None] | None = None


def start_subscriber() -> None:
    """Startet den Subscriber als Background-Task (idempotent)."""
    global _task
    if _task is not None and not _task.done():
        return
    _task = asyncio.create_task(_consume_loop(), name="mqtt-subscriber")
    logger.info("MQTT-Subscriber-Task gestartet")


async def stop_subscriber() -> None:
    """Cancelt den Subscriber-Task und wartet auf sauberen Stop."""
    global _task
    if _task is None:
        return
    _task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await _task
    _task = None
    logger.info("MQTT-Subscriber-Task gestoppt")
