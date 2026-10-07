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
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import aiomqtt
import redis
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from heizung.config import get_settings
from heizung.db import SessionLocal
from heizung.models.device import Device
from heizung.models.heating_zone import HeatingZone
from heizung.models.sensor_reading import SensorReading
from heizung.rules.constants import PLAUSI_TEMP_MAX_C, PLAUSI_TEMP_MIN_C
from heizung.services import redis_client
from heizung.services.device_adapter import handle_uplink_for_override
from heizung.tasks.engine_tasks import evaluate_room

logger = logging.getLogger(__name__)

# Sprint 9.11x.b T6: Codec setzt ``report_type`` fuer alle Command-Replies
# (cmd-byte != 0x01/0x81 Periodic). Subscriber skipped sensor_reading-
# Insert fuer alle Replies — Reply-Frames haben weder temperature noch
# valve_position und wuerden nur NULL-Garbage in der Hypertable erzeugen.
# Sprint 20f (T1/T2): ``report_type`` des 0x28-Frames. Bewusst **kein**
# Reply-Typ (siehe ``REPLY_REPORT_TYPES`` unten) — der Frame traegt einen
# vollstaendigen Keep-alive, der als Reading gespeichert werden soll. Dient
# gleichzeitig als Diskriminator fuer die Override-Quelle: nur hier hat die
# Vicki die Drehung **gemeldet**, sonst ist sie abgeleitet.
MANUAL_TARGET_REPORT_TYPE = "manual_target_change"

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


# Sprint 15b (AE-64): Vicki-2xAA-Alkaline-Entladekurve. Stuetzstellen
# aus Live-Kalibrierung der 4 produktiven Vickis auf heizung-test
# (2026-06-02): 3x Codec-Saettigung 3.5 V (Nibble 15) plus 1x 3.0 V —
# zellbestueckung einheitlich Alkaline. Anker auf MClimate-Spec
# (Betriebsspannung 2.7-3.6 VDC, Wechsel-Empfehlung < 2.8 V) verankert,
# Zwischenpunkte an realer Alkaline-Entladekurve unter LoRaWAN-Sende-
# Last:
#   2.70 V =   0 %  (Geraete-Mindestbetrieb, Wechsel ueberfaellig)
#   2.80 V =  10 %  (MClimate-Warnschwelle — Vicki funktioniert noch)
#   2.90 V =  30 %  (Knie der Alkaline-Entladekurve)
#   3.00 V =  50 %  (Mitte; entspricht der schwaechsten der 4 Vickis)
#   3.20 V =  80 %  (Plateau "gut")
#   3.50 V = 100 %  (Codec-Saettigung, frische 2xAA)
#
# WICHTIG — Codec-Saettigung: Nibble 15 ist das 4-Bit-MAXIMUM des
# Codec-Felds, NICHT "genau 3.5 V". Vicki-Firmware clamped intern bei
# nibble >= 15. Oberhalb ~3.4 V tatsaechlicher Geraete-Spannung gibt
# es keine Codec-Aufloesung mehr — frische Batterien sitzen am oberen
# Anschlag (Live-Beleg: 3 von 4 Vickis dauerhaft auf nibble=15).
#
# Quelle:
# - Codec ``infra/chirpstack/codecs/mclimate-vicki.js:119-121``: Geraete-
#   Spannung = 2.0 + Nibble * 0.1, 0.1-V-Raster, Wertebereich 2.0-3.5 V.
# - MClimate-Hauptdoku: Power 2x AA (1.5 V Alkaline, keine Akkus,
#   Lithium-AA optional bis 3.6 V Geraete-Spannung), Betriebsbereich
#   2.7-3.6 VDC.
# - Live-Kalibrierung 4 Vickis heizung-test 2026-06-02
#   (B-15b-1-Vorlauf: Vergleich battery_percent alt vs. raw_payload
#   Byte 7 high-nibble decoded).
#
# Die alte lineare LiPo-Skala (3.0-4.2 V) war doppelt falsch: falscher
# Spannungsbereich UND falsche Kurvenform — produzierte 0 % bei
# intakter 2xAA-Batterie (Cowork-Befund Sprint 15a).
BATTERY_CURVE_2XAA: tuple[tuple[Decimal, int], ...] = (
    (Decimal("2.70"), 0),
    (Decimal("2.80"), 10),
    (Decimal("2.90"), 30),
    (Decimal("3.00"), 50),
    (Decimal("3.20"), 80),
    (Decimal("3.50"), 100),
)


def _battery_pct_from_volts(volts: float | None) -> int | None:
    """Vicki-2xAA-Alkaline Batterie-Prozent aus Codec-Geraete-Spannung.

    **Ohne Konsumenten seit Sprint 20 (AE-72).** Die drei Batterie-Stufen
    rechnen seit Migration 0024 direkt auf ``sensor_reading.battery_voltage``
    (``services/battery_health.py``); Prozent wird weiter geschrieben, aber
    nirgends mehr gelesen. Grund fuer das Weiterschreiben: Rueckfallpfad,
    falls die Stufen-Umstellung zurueckgedreht werden muss — ein Rollback
    braucht die Spalte befuellt, nicht nachtraeglich rekonstruiert.

    Dieser Vermerk ist eine Aussage ueber den heutigen Code, keine dauerhafte
    Eigenschaft (CLAUDE.md §5.77): wer Prozent wieder an einen Konsumenten
    haengt, streicht ihn hier und in CLAUDE.md §5.72 im selben PR.

    Stuetzstellen-Interpolation nach ``BATTERY_CURVE_2XAA``. Linear
    zwischen zwei umfassenden Anchors, geclampt 0..100 ausserhalb der
    Endpunkte (``volts <= 2.80`` -> 0, ``volts >= 3.00`` -> 100).

    Decimal-Vergleich gegen Float-Drift an den Anker-Schwellen: der
    Codec emittiert exakte 0.1-V-Werte (``parseFloat(volts.toFixed(2))``),
    aber IEEE-754-Repraesentation von z. B. ``2.8`` ist nicht exakt — der
    ``Decimal(str(volts))``-Konversionspfad ist exakt und vermeidet
    Off-by-Epsilon an der Wechsel-Schwelle.

    :param volts: ``object.battery_voltage`` aus Codec-Output (Float).
        Realer Wertebereich 2.0-3.5 V in 0.1-V-Schritten.
    :returns: Integer 0..100. ``None`` wenn ``volts`` ``None`` ist.
    """
    if volts is None:
        return None

    v = Decimal(str(volts))

    # Clamps an den Kennlinien-Raendern
    lo_v, lo_pct = BATTERY_CURVE_2XAA[0]
    hi_v, hi_pct = BATTERY_CURVE_2XAA[-1]
    if v <= lo_v:
        return lo_pct
    if v >= hi_v:
        return hi_pct

    # Lineare Interpolation zwischen den zwei umfassenden Stuetzstellen
    for (v_lo, p_lo), (v_hi, p_hi) in zip(
        BATTERY_CURVE_2XAA[:-1], BATTERY_CURVE_2XAA[1:], strict=True
    ):
        if v_lo <= v <= v_hi:
            span_v = v_hi - v_lo
            span_p = Decimal(p_hi - p_lo)
            pct = Decimal(p_lo) + (v - v_lo) / span_v * span_p
            return int(pct.to_integral_value(rounding=ROUND_HALF_UP))

    # Unreachable (Clamps decken Ausserhalb-Faelle ab); fuer mypy noetig.
    return hi_pct


def _to_decimal(v: Any) -> Decimal | None:
    if v is None:
        return None
    try:
        return Decimal(str(v))
    except (ValueError, ArithmeticError):
        return None


def _snr_db(rx: _RxInfo | None) -> Decimal | None:
    """SNR aus den Empfangsdaten — mit der 0-dB-Luecke von protojson.

    **Befund 07.10.2026, Geraet 001.** Die Signal-Kachel zeigte "–" statt
    eines SNR-Werts. Messung ueber sieben Tage:

        zeilen 1004 | mit_snr 976 | genau_null 0 | kleinster -8.0 | mit_rssi 1004

    Drei Zahlen zusammen sind der Beleg:

    1. ``mit_rssi = zeilen`` — die Empfangsdaten (``rxInfo``) waren in
       **jedem** Frame da. Es fehlt also nicht der Block, sondern ein Feld
       darin.
    2. ``kleinster = -8.0`` — negative Werte kommen durch. Es ist also kein
       Vorzeichen- oder Typproblem.
    3. ``genau_null = 0`` in 976 Messwerten, obwohl Geraet 001 nachweislich
       um 0 dB herum funkt. Ein Wert, der nie auftritt, obwohl er der
       haeufigste sein muesste.

    **Ursache:** ``chirpstack.toml`` setzt ``[integration.mqtt] json = true``.
    ChirpStack serialisiert das Event dann ueber protojson, und protojson
    laesst Felder mit **Default-Wert** weg. ``"snr": 0.0`` steht also gar
    nicht im JSON; ``_RxInfo.snr`` bleibt ``None``, und die Spalte bekam
    NULL.

    Fuer diesen Erzeuger heisst "Feld fehlt, Block vorhanden" damit
    **genau 0**. Das ist der Schluss, den diese Funktion zieht — und er ist
    nur zulaessig, weil Punkt 1 ihn traegt: ohne ``rxInfo`` wissen wir
    nichts und die Spalte bleibt NULL.

    **Warum nicht dasselbe fuer ``rssi``.** Dort gilt die Lueckenlogik
    technisch genauso, aber 0 dBm am Empfaenger waere 1 mW — physikalisch
    nicht vorstellbar, und die Messung zeigt ``mit_rssi = zeilen``. Eine
    Regel fuer einen Fall, der nicht vorkommt, waere eine Annahme mehr
    (§0 S6). Wer sie doch braucht, hat dann einen Befund und nicht eine
    Vermutung.

    **Warum kein Codec- oder ChirpStack-Eingriff.** ``EmitUnpopulated``
    liesse sich serverseitig setzen, dann kaeme die 0 mit. Das waere die
    Ursache statt der Wirkung — aber es aendert das Format **aller** Events
    fuer **alle** Felder, auf einem Server, der die Heizung steuert, und
    ohne Testpfad dafuer. Die zwei Zeilen hier sind der kleinere Eingriff;
    der andere Weg steht im Backlog.
    """
    if rx is None:
        return None
    if rx.snr is None:
        # Block da, Feld weg -> protojson hat die 0 verschluckt.
        return Decimal("0")
    return _to_decimal(rx.snr)


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
        # Sprint 20 (AE-72): die Spannung selbst, Raster 0.1 V. Quelle der
        # drei Batterie-Stufen seit Migration 0024. NULL wenn das Feld fehlt.
        "battery_voltage": _to_decimal(obj.get("battery_voltage")),
        # Rueckfallpfad, ohne Konsumenten — siehe Docstring von
        # ``_battery_pct_from_volts``.
        "battery_percent": _battery_pct_from_volts(obj.get("battery_voltage")),
        "rssi_dbm": rx.rssi if rx else None,
        # Sprint 20e-Nachtrag: ``0`` statt NULL, wenn ``rxInfo`` da ist und
        # ``snr`` fehlt — protojson laesst den Default-Wert weg. Beleg und
        # Begruendung im Docstring von ``_snr_db``.
        "snr_db": _snr_db(rx),
        # Sprint 9.10: Vicki openWindow durchreichen (NULL wenn Feld fehlt,
        # nicht False).
        "open_window": obj.get("openWindow"),
        # Sprint 9.11x: Vicki attachedBackplate (FW >= 4.1) durchreichen.
        # NULL wenn Feld fehlt (alter Codec) — Layer 4 Detached behandelt
        # NULL als "Device unklar", nicht als detached.
        "attached_backplate": obj.get("attachedBackplate"),
        # Sprint 19 (PR B): brokenSensor durchreichen (Migration 0023).
        # NULL wenn das Feld fehlt — nur True ist ein Defekt.
        "broken_sensor": obj.get("brokenSensor"),
        # Sprint 20f (T7): calibrationFailed durchreichen (Migration 0025).
        # Der Codec setzt das Bit seit Sprint 6.8; bis hierher stand an
        # dieser Stelle nichts, und der Wert wurde bei jedem Frame
        # verworfen. NULL wenn das Feld fehlt — nur True ist ein Befund.
        "calibration_failed": obj.get("calibrationFailed"),
        "raw_payload": uplink.data,
    }


# ---------------------------------------------------------------------------
# Implausible-Counter (Sprint 11 T5, AE-53)
# ---------------------------------------------------------------------------


async def _increment_implausible_counter(dev_eui: str) -> None:
    """Erhoeht den ``implausible:{dev_eui}``-Counter in Redis um 1.

    Pipeline (INCR + EXPIRE 86400) ist atomar — Counter bekommt bei
    Erstanlage automatisch eine 24h-Lebensdauer (rolling 24h-Fenster).
    Health-Compute-Task (5-min-Beat) liest den Counter und triggert
    silent-State bei >= 10 (Stufe-3-Trigger).

    Sync-Redis-Client via ``asyncio.to_thread``, damit der Event-Loop
    nicht blockiert. Bei Redis-Offline: Logger-Warning, kein Subscriber-
    Crash, Counter-Verlust akzeptiert (S6, nicht-kritischer Audit).
    """

    def _sync_incr() -> None:
        client = redis_client.get_redis_client()
        pipe = client.pipeline()
        pipe.incr(f"implausible:{dev_eui}")
        pipe.expire(f"implausible:{dev_eui}", 86400)
        pipe.execute()

    try:
        await asyncio.to_thread(_sync_incr)
    except redis.RedisError as exc:
        logger.warning(
            "implausible_counter_failed",
            extra={"dev_eui": dev_eui, "error": str(exc)},
        )


# ---------------------------------------------------------------------------
# Persistenz
# ---------------------------------------------------------------------------


async def _maybe_confirm_mounted(
    session: AsyncSession,
    device_id: int,
    values: dict[str, Any],
    seen_at: datetime,
) -> None:
    """Sprint 20e (T3): den Montage-Nachweis setzen, wenn dieser Frame ihn belegt.

    **Die Bedingung ist ein einzelner Frame, nicht die Historie.** Beide
    Merkmale muessen zusammen in derselben Meldung stehen:

    - ``attached_backplate is True`` — der Taster hinter dem Geraet war
      gedrueckt, als der Frame entstand.
    - ``valve_position > 0`` — der Motor hat das Ventil geoeffnet, also
      sitzt das Geraet auf einem Ventil und nicht auf dem Tisch.

    Zwei Frames, von denen je einer eines der Merkmale traegt, sind kein
    Nachweis: ein Geraet auf dem Werkstatt-Tisch kann den Taster per Hand
    gedrueckt bekommen, und ein Geraet in der Hand kann den Motor fahren.
    Erst die Gleichzeitigkeit schliesst beides aus.

    **Zone-Pflicht.** Ohne ``heating_zone_id`` gibt es keinen Nachweis, denn
    "montiert" ist eine Aussage ueber einen Heizkoerper, nicht ueber ein
    Geraet. Ein Pool-Vicki, der beim Eingangstest auf dem Tisch vollstaendig
    durchfaehrt, soll hinterher nicht als montiert gelten.

    **Ein Schreibvorgang je Geraet und Lebenszeit.** ``WHERE
    mounted_confirmed_at IS NULL`` steht in der ``UPDATE``-Bedingung und
    nicht als Python-Vorabpruefung (§5.60): bei 104 Geraeten und einem
    Keep-alive alle zehn Minuten laufen hier rund 15 000 Frames am Tag
    durch, und zwei parallele Subscriber-Durchlaeufe duerfen den Zeitstempel
    nicht gegenseitig ueberschreiben. Die Datenbank entscheidet, nicht die
    Reihenfolge der Tasks.

    ``retired_at IS NULL`` ebenfalls in der Bedingung: ein ausgemustertes
    Geraet, das noch sendet (abgenommen, aber nicht entpaart), bekommt
    keinen frischen Nachweis.

    Der Aufruf sitzt in derselben Transaktion wie der Reading-Insert — der
    Nachweis und der Frame, der ihn belegt, sind damit entweder beide da
    oder beide nicht.
    """
    if values.get("attached_backplate") is not True:
        return

    ventil = values.get("valve_position")
    if ventil is None or ventil <= 0:
        return

    await session.execute(
        update(Device)
        .where(Device.id == device_id)
        .where(Device.mounted_confirmed_at.is_(None))
        .where(Device.heating_zone_id.is_not(None))
        .where(Device.retired_at.is_(None))
        .values(mounted_confirmed_at=seen_at)
    )


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

        # Sprint 11 T2 (AE-53): Plausi-Filter auf Ist-Temperatur. Werte
        # ausserhalb [-20, 60] °C werden verworfen — kein Insert in
        # sensor_reading, kein evaluate_room.delay-Trigger. Engine sieht
        # den Wert nie. Defensive nach S5 (externe Quelle = Vicki +
        # Codec-Drift). Decimal-Vergleich, kein Float. None bleibt None
        # (reines Battery-Frame ohne Temperatur faellt nicht hierdurch).
        obj = uplink.object or {}
        temperature = _to_decimal(obj.get("temperature"))
        if temperature is not None and not (PLAUSI_TEMP_MIN_C <= temperature <= PLAUSI_TEMP_MAX_C):
            logger.warning(
                "implausible_reading",
                extra={
                    "dev_eui": dev_eui,
                    "temperature": str(temperature),
                    "raw_payload": uplink.data,
                    "reason": "out_of_bounds",
                    "bounds": f"[{PLAUSI_TEMP_MIN_C}, {PLAUSI_TEMP_MAX_C}]",
                },
            )
            await _increment_implausible_counter(dev_eui)
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

        # Sprint 20e (T3): Montage-Nachweis auf demselben Frame.
        await _maybe_confirm_mounted(session, device_id, values, seen_at)

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
    """Handverstellung am Drehrad -> Override. **Nur fuer ``0x28``.**

    Sprint 9.9 T5 hat das als Vergleich gebaut: Uplink-Setpoint gegen den
    letzten Engine-Send, und bei genuegend Unterschied einen
    ``device``-Override (AE-45). Das war die einzige Moeglichkeit, solange
    keine ausdrueckliche Meldung existierte.

    **Sprint 20f-b: der Vergleichspfad ist entfernt, und zwar wegen eines
    belegten Produktionsfehlers.**

    Zeitlinie vom 05.10.2026, Zimmer 101 (Geraete 009 und 010):

        20:00:59  Engine sendet Nachtabsenkung 19 °C
        20:03:25  Keep-alive meldet noch **21** — Class-A-Latenz, das
                  Geraet hat den Befehl noch nicht umgesetzt
                  -> alte Erkennung sieht "21 statt 19" und legt
                     Override 40 mit **21 °C** an, Ablauf Check-out
        (Engine regelt jetzt auf 21, weil der Override das sagt)
        20:13:36  Geraet meldet **19** — der erste Befehl ist angekommen
                  -> alte Erkennung sieht "19 statt 21" und legt
                     Override 42 mit **19 °C** an

    Ping-Pong. Beide Overrides sind Phantome: niemand hat gedreht.

    **Und es war kein Einzelfall, sondern der Normalfall.** Die Bedingung
    ist "Engine aendert den Sollwert in einem belegten Zimmer" — also
    **jede Nachtabsenkung in jedem belegten Zimmer, jede Nacht**. Jede
    davon haette einen Phantom-Override bis zum Check-out erzeugt.

    Das 60-s-Ack-Fenster haette das abfangen sollen und kann es nicht: es
    wird ab dem **MQTT-Publish** gemessen (``engine_tasks.py``, nicht ab
    dem Funk-Versand), und bei Class A liegen dazwischen bis zu eine
    Keep-alive-Periode. 20:00:59 bis 20:03:25 sind 146 Sekunden.

    Seit Sprint 20f T1 ist der Vergleich auch nicht mehr noetig: der
    ``0x28``-Frame **meldet** die Drehung. Ein Sollwert-Unterschied **ohne**
    ``0x28`` ist damit kein Gastwunsch, sondern Drift — und fuer Drift gibt
    es seit T3 die richtige Antwort: der Engine-Abgleich holt den Sollwert
    zurueck, statt die Abweichung zu adoptieren (AE-76).

    Failure ist non-fatal; wir loggen und blockieren die Subscriber-Loop
    nicht.
    """
    obj = uplink.object or {}

    # **Sprint 20f-b: der Torwaechter.** Nur ein Frame, in dem die Vicki die
    # Drehung ausdruecklich meldet, fuehrt zu einem Override. Alles andere —
    # Keep-alive, Setpoint-Reply, FW-Antwort — kehrt hier um.
    #
    # Das ist die eine Zeile, die den Phantom-Override verhindert. Sie steht
    # in der Funktion und nicht an der Aufrufstelle, damit sie gilt, egal wer
    # ruft, und damit ein Test sie direkt pruefen kann.
    if obj.get("report_type") != MANUAL_TARGET_REPORT_TYPE:
        return

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
                # Sprint 15c (AE-63): dev_eui + current_fcnt fuer Reboot-Gate.
                # Beide Pflicht-Felder im Schema (kein None-Fallback noetig).
                dev_eui=dev_eui,
                current_fcnt=uplink.fCnt,
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
                        # Sprint 20f-b: **hier stand ein Aufruf von
                        # ``_handle_override_detection``**, und er war die
                        # Haelfte des Phantom-Override-Befunds.
                        #
                        # Der alte Kommentar dazu lautete "der Drehring meldet
                        # seinen Setpoint hier zurueck" — das war richtig,
                        # solange ``0x52`` die einzige Spur einer Drehung war.
                        # Seit Sprint 20f T1 den ``0x28``-Frame dekodiert, ist
                        # ``0x52`` nur noch die **Bestaetigung des eigenen
                        # Downlinks**, und die als Gastwunsch zu lesen ist
                        # zirkulaer: die Engine adoptiert ihren eigenen Befehl.
                        #
                        # FW + OW-Status bleiben, sie haben mit Overrides
                        # nichts zu tun.
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

                    # Sprint 20f-b: die Funktion prueft selbst, ob der Frame
                    # eine Handverstellung ist, und kehrt sonst sofort zurueck.
                    # Die Bedingung steht dort und nicht hier, damit sie
                    # unabhaengig von der Aufrufstelle gilt und testbar ist.
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
