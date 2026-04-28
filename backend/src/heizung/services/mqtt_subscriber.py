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
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from heizung.config import get_settings
from heizung.db import SessionLocal
from heizung.models.device import Device
from heizung.models.sensor_reading import SensorReading

logger = logging.getLogger(__name__)


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
    obj = uplink.object or {}
    rx = uplink.rxInfo[0] if uplink.rxInfo else None
    ts = uplink.time or datetime.now(tz=UTC)

    return {
        "time": ts,
        "device_id": device_id,
        "fcnt": uplink.fCnt,
        "temperature": _to_decimal(obj.get("temperature")),
        "setpoint": _to_decimal(obj.get("target_temperature")),
        "valve_position": obj.get("motor_position"),
        "battery_percent": _battery_pct_from_volts(obj.get("battery_voltage")),
        "rssi_dbm": rx.rssi if rx else None,
        "snr_db": _to_decimal(rx.snr) if rx else None,
        "raw_payload": uplink.data,
    }


# ---------------------------------------------------------------------------
# Persistenz
# ---------------------------------------------------------------------------


async def _persist_uplink(uplink: ChirpStackUplink) -> None:
    """DevEUI -> device_id auflösen, Reading idempotent inserten."""
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
        await session.commit()

        logger.info(
            "uplink persistiert: dev_eui=%s fcnt=%s temp=%s setpoint=%s",
            dev_eui,
            values["fcnt"],
            values["temperature"],
            values["setpoint"],
        )


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

                    try:
                        await _persist_uplink(uplink)
                    except Exception:
                        logger.exception(
                            "uplink-persist-fehler dev_eui=%s",
                            uplink.deviceInfo.devEui,
                        )
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
