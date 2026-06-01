"""Vicki-Device-Adapter (Sprint 9.9 T5).

Erkennt Drehknopf-Setpoints aus Vicki-Uplinks und erzeugt automatisch
``device``-Quelle-Overrides via ``override_service``.

**Diff-Detection-Strategie:** Vicki-Codec liefert nur ein einzelnes
``target_temperature``-Feld - keine Quellen-Unterscheidung. Wir
vergleichen den Uplink-Setpoint mit dem letzten ControlCommand fuer
dasselbe Geraet (``sent_to_gateway_at IS NOT NULL``); Diff > Toleranz
und ausserhalb des Acknowledgment-Windows = User-Override.

**Toleranzen:**
- ``fPort 1`` (Periodic Status Report, ``uint8`` Grad): ``0.6 degC``
  - deckt die uint8-Rundung ab (Engine-Setpoint 21.5 vs. Vicki-Report
  21 ist KEIN Override).
- ``fPort 2`` (Setpoint-Reply ``0x52``, decimal): ``0.1 degC`` - volle
  Praezision.

**Acknowledgment-Window:** 60 Sekunden nach ``sent_to_gateway_at``.
Reply in diesem Fenster ist erwartet -> kein Override.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from heizung.models.control_command import ControlCommand
from heizung.models.device import Device
from heizung.models.enums import CommandReason, EventLogLayer, OverrideSource, RoomStatus
from heizung.models.event_log import EventLog
from heizung.models.global_config import GlobalConfig
from heizung.models.heating_zone import HeatingZone
from heizung.models.room import Room
from heizung.models.sensor_reading import SensorReading
from heizung.rules.window_state import detect_open_window_zones
from heizung.services import override_service, resync_flag
from heizung.services.occupancy_service import derive_room_status, next_active_checkout

if TYPE_CHECKING:
    from datetime import datetime

    from heizung.models.manual_override import ManualOverride

logger = logging.getLogger(__name__)

ACK_WINDOW_SECONDS = 60
TOLERANCE_FPORT1 = Decimal("0.6")
TOLERANCE_FPORT2 = Decimal("0.1")

# Sprint 15c (AE-63): Reboot-Diskriminator-Schwelle. Vicki startet nach
# Reboot bei fcnt=0 und zaehlt einzeln hoch. ``current < FCNT_REBOOT_THRESHOLD``
# kombiniert mit ``current < prior`` ist robuste Reboot-Erkennung — Late-
# Arrival-Out-of-Order-Frames haben nach > 10 Frames Uptime nahezu nie
# einen fcnt unterhalb dieser Schwelle. 32-Bit-Wraparound ist ueber Vicki-
# Lebensdauer ausgeschlossen (Sprint-15c-Task-0-Beleg).
FCNT_REBOOT_THRESHOLD = 10


def is_reboot_frame(prior_fcnt: int | None, current_fcnt: int) -> bool:
    """Erkennt Vicki-Reboot-Frame anhand fcnt-Reset (Sprint 15c, AE-63).

    True wenn ``current_fcnt < prior_fcnt`` UND
    ``current_fcnt < FCNT_REBOOT_THRESHOLD``. ``prior_fcnt is None``
    (kein Vorframe in ``sensor_reading``) -> False, weil ohne Vorgaenger
    nicht entscheidbar.

    Reine Funktion — keine DB- oder Redis-Zugriffe, deterministisch
    testbar.

    :param prior_fcnt: fcnt des unmittelbaren Vorgaenger-Frames.
    :param current_fcnt: fcnt des aktuellen Uplinks.
    """
    if prior_fcnt is None:
        return False
    return current_fcnt < prior_fcnt and current_fcnt < FCNT_REBOOT_THRESHOLD


async def _get_prior_fcnt(
    session: AsyncSession,
    device_id: int,
    received_at: datetime,
) -> int | None:
    """fcnt des unmittelbaren Vorgaenger-Frames aus ``sensor_reading``.

    Nutzt ``ix_sensor_reading_device_time`` (Index (device_id, time) aus
    Migration 0001). ``time < received_at`` macht den Lookup eindeutig in
    beiden Subscriber-Pfaden — Periodic (aktueller Frame ist bereits
    committed) und Reply (Frame wird gar nicht ins ``sensor_reading``
    geschrieben). Keine neue Spalte, keine Migration.
    """
    stmt = (
        select(SensorReading.fcnt)
        .where(SensorReading.device_id == device_id)
        .where(SensorReading.time < received_at)
        .order_by(SensorReading.time.desc())
        .limit(1)
    )
    return await session.scalar(stmt)


async def _write_reboot_resync_event_log(
    session: AsyncSession,
    *,
    room_id: int,
    device_id: int,
    received_at: datetime,
    prior_fcnt: int | None,
    current_fcnt: int,
    uplink_setpoint: Decimal,
    flag_set: bool,
) -> None:
    """Off-pipeline ``REBOOT_RESYNC``-Audit-Eintrag (Sprint 15c, AE-63).

    Pattern analog ``_write_blocked_event_log`` (AE-58 §9): synthetische
    ``evaluation_id`` (uuid4), gehoert keiner Engine-Tick-Eval. ``details``
    traegt fcnt-Uebergang plus ``flag_set``-Beleg, damit im Live-Bug-
    Verfolg sichtbar ist, ob der Re-Sync-Flag erfolgreich in Redis
    landete oder ob Redis offline war.
    """
    entry = EventLog(
        time=received_at,
        room_id=room_id,
        evaluation_id=uuid.uuid4(),
        layer=EventLogLayer.REBOOT_RESYNC,
        device_id=device_id,
        setpoint_in=None,
        setpoint_out=None,
        reason=CommandReason.REBOOT_RESYNC,
        details={
            "source": "device_adapter",
            "prior_fcnt": prior_fcnt,
            "current_fcnt": current_fcnt,
            "uplink_setpoint": str(uplink_setpoint),
            "resync_flag_set": flag_set,
        },
    )
    session.add(entry)
    await session.flush()


async def detect_user_override(
    session: AsyncSession,
    device_id: int,
    uplink_target_temp: Decimal,
    fport: int,
    received_at: datetime,
) -> Decimal | None:
    """Returns user-Setpoint (Decimal) wenn Drehknopf-Override erkannt,
    sonst ``None``.

    Logik:

    1. Letzter ControlCommand fuer ``device_id`` mit
       ``sent_to_gateway_at IS NOT NULL``, sortiert ``DESC``.
    2. Kein Treffer -> kein Engine-Intent bekannt -> ``None``.
    3. Ack-Window: ``received_at - sent_to_gateway_at <= 60 s`` ->
       erwarteter Reply -> ``None``.
    4. Toleranz nach ``fport`` (0.6 fuer 1, 0.1 fuer 2).
    5. ``|uplink - last_engine| <= tolerance`` -> Rundungsdifferenz
       -> ``None``.
    6. Sonst -> ``uplink_target_temp`` (= User-Setpoint).
    """
    stmt = (
        select(ControlCommand.target_setpoint, ControlCommand.sent_to_gateway_at)
        .where(ControlCommand.device_id == device_id)
        .where(ControlCommand.sent_to_gateway_at.is_not(None))
        .order_by(ControlCommand.sent_to_gateway_at.desc())
        .limit(1)
    )
    row = (await session.execute(stmt)).first()
    if row is None:
        return None

    last_setpoint, sent_at = row
    if sent_at is None:
        return None

    if received_at - sent_at <= timedelta(seconds=ACK_WINDOW_SECONDS):
        return None

    tolerance = TOLERANCE_FPORT2 if fport == 2 else TOLERANCE_FPORT1
    if abs(uplink_target_temp - last_setpoint) <= tolerance:
        return None

    return uplink_target_temp


async def _device_room_id(session: AsyncSession, device_id: int) -> int | None:
    """``Device -> HeatingZone -> room_id``. ``None`` wenn das Geraet
    keiner Zone zugeordnet ist ODER retired ist.

    Sprint 13b.1 (AE-57): inline ``retired_at IS NULL``-Filter. Helper
    ``get_active_devices_for_zone`` waere unpassend (hier ID-Lookup, kein
    Zone-Scan). Retirte Devices, die noch funken, duerfen KEINE Override-
    Anlage triggern (Anti-Strategie nach Retire).
    """
    stmt = (
        select(HeatingZone.room_id)
        .join(Device, Device.heating_zone_id == HeatingZone.id)
        .where(Device.id == device_id)
        .where(Device.retired_at.is_(None))
        .limit(1)
    )
    room_id: int | None = await session.scalar(stmt)
    return room_id


async def _device_zone_id(session: AsyncSession, device_id: int) -> int | None:
    """``Device.heating_zone_id`` direkt. ``None`` wenn nicht zugeordnet
    ODER retired.

    Sprint 12a T4 (AE-58): separater Helper analog ``_device_room_id``.
    Sprint 13b.1 (AE-57): inline ``retired_at IS NULL``-Filter (analog
    ``_device_room_id``). Retired Devices liefern ``None`` zurueck —
    Aufrufer behandeln das wie "Device nicht zugeordnet".
    """
    stmt = (
        select(Device.heating_zone_id)
        .where(Device.id == device_id)
        .where(Device.retired_at.is_(None))
        .limit(1)
    )
    zone_id: int | None = await session.scalar(stmt)
    return zone_id


async def _write_blocked_event_log(
    session: AsyncSession,
    *,
    room_id: int,
    device_id: int,
    received_at: datetime,
    reason: CommandReason,
    uplink_setpoint: Decimal,
) -> None:
    """Off-pipeline event_log-Audit fuer device_adapter Pre-Insert-Skip.

    Sprint 12a T4 (AE-58): Vicki-Drehring in VACANT-Raum oder bei Fenster
    offen wird im device_adapter ohne manual_override-Insert verworfen.
    Damit der Befund auditierbar bleibt (S3), schreibt der Skip-Pfad einen
    eigenstaendigen ``MANUAL_OVERRIDE_BLOCKED``-Eintrag mit synthetischer
    ``evaluation_id`` (gehoert keiner Engine-Tick-Eval an). ``setpoint_in``
    / ``setpoint_out`` bleiben ``None`` — es entstand keine Steuer-
    Entscheidung. ``details`` traegt den verworfenen User-Setpoint.
    """
    entry = EventLog(
        time=received_at,
        room_id=room_id,
        evaluation_id=uuid.uuid4(),
        layer=EventLogLayer.MANUAL_OVERRIDE_BLOCKED,
        device_id=device_id,
        setpoint_in=None,
        setpoint_out=None,
        reason=reason,
        details={
            "source": "device_adapter",
            "uplink_setpoint": str(uplink_setpoint),
        },
    )
    session.add(entry)
    await session.flush()


async def handle_uplink_for_override(
    session: AsyncSession,
    device_id: int,
    uplink_target_temp: Decimal,
    fport: int,
    received_at: datetime,
    *,
    dev_eui: str | None = None,
    current_fcnt: int | None = None,
) -> ManualOverride | None:
    """Vollstaendiger Pfad: Detection + Pre-Insert-Gates + Override-Erzeugung.

    Aufrufer: ``mqtt_subscriber`` nach erfolgreicher Reading-Persistenz.
    Gate-Reihenfolge (AE-58 + AE-63):

    pre-r) **Reboot-Gate** (Sprint 15c, AE-63): Vicki-Reboot via fcnt-Reset
       erkannt (``current_fcnt < prior_fcnt`` UND
       ``current_fcnt < FCNT_REBOOT_THRESHOLD``) -> silent skip + Redis-Re-
       Sync-Flag ``resync_pending:{dev_eui}`` (TTL 1 h) +
       ``REBOOT_RESYNC``-event_log mit fcnt-Uebergang. Der Re-Sync-Flag
       wird im naechsten Engine-Tick im
       ``engine_tasks._dispatch_downlinks_per_zone``-Loop konsumiert
       (Hysterese-Bypass fuer genau EINEN Downlink). Greift nur wenn
       ``dev_eui`` und ``current_fcnt`` gesetzt sind (Backward-Compat fuer
       Aufrufer ohne fcnt-Kontext).
    pre-a) **Block-Gate** (Sprint 12c): ``room.guest_override_blocked``
       gesetzt -> silent skip + ``MANUAL_OVERRIDE_BLOCKED``-event_log-
       Eintrag mit ``reason=DEVICE_BLOCKED_ROOM_BLOCKED``. Spiegelt das
       Single-Source-of-Truth-Gate in ``override_service.create`` und
       schreibt zusaetzlich Audit (S3), weil der Skip nicht durch den
       Service laeuft.
    a) **OCCUPIED-Gate** (Sprint 12a T4, via ``derive_room_status``):
       VACANT/RESERVED/CLEANING/BLOCKED -> silent skip +
       ``MANUAL_OVERRIDE_BLOCKED``-event_log-Eintrag mit
       ``reason=DEVICE_BLOCKED_VACANT``. KEIN ``RoomNotOccupiedError``-
       Raise — der mqtt_subscriber-Aufrufer darf nicht crashen.
    b) **Window-Offen-Gate** (via ``detect_open_window_zones``):
       mindestens eine Zone des Raums meldet ``open_window=True`` ->
       silent skip + event_log mit ``reason=DEVICE_BLOCKED_WINDOW``.
       Reuse des Sprint-12-T4-Helpers, gleiche Filter-Semantik (healthy
       Devices, frische Readings).
    c) **Zone-Lookup**: ``_device_zone_id``. ``None`` -> Warning
       ``device_without_zone_mapping`` + Room-Scope-Fallback
       (``heating_zone_id=None``). Im aktuellen Schema unerreichbar
       (Vicki ohne Zone hat auch keinen Raum-Link), bleibt aber als
       defensiver Branch gegen Schema-Erweiterung.
    d) ``override_service.create(..., heating_zone_id=...)``.

    Returns:
        ``ManualOverride`` bei erfolgreicher Anlage.
        ``None`` bei: kein Engine-Intent, Ack-Window, innerhalb Toleranz,
        kein Room-Mapping, Reboot-Gate-Skip, Block-Gate-Skip,
        OCCUPIED-Gate-Skip, Window-Gate-Skip.
    """
    user_setpoint = await detect_user_override(
        session,
        device_id=device_id,
        uplink_target_temp=uplink_target_temp,
        fport=fport,
        received_at=received_at,
    )
    if user_setpoint is None:
        return None

    room_id = await _device_room_id(session, device_id)
    if room_id is None:
        logger.warning(
            "device-override skip: device_id=%s ohne Heizzonen-/Raum-Mapping",
            device_id,
        )
        return None

    # Gate (pre-r): Reboot-Gate (Sprint 15c, AE-63). Vicki-Reboot via
    # fcnt-Reset erkannt -> Adopt ueberspringen + Re-Sync-Flag setzen +
    # event_log. Greift nur wenn dev_eui und current_fcnt vorhanden sind
    # (Tests / Legacy-Aufrufer ohne fcnt-Kontext laufen wie bisher).
    if dev_eui is not None and current_fcnt is not None:
        prior_fcnt = await _get_prior_fcnt(session, device_id, received_at)
        if is_reboot_frame(prior_fcnt, current_fcnt):
            # Redis-mark_pending ist sync -> asyncio.to_thread, damit der
            # Event-Loop nicht blockiert. Failure (Redis offline) ist
            # akzeptiert: flag_set landet im event_log fuer Diagnose; der
            # naechste 60-s-Beat-Tick wuerde den Re-Sync trotzdem ausloesen
            # sobald der Vicki nach Heartbeat-Ablauf ohnehin gesendet bekommt.
            flag_set = await asyncio.to_thread(resync_flag.mark_pending, dev_eui)
            logger.info(
                "reboot-frame erkannt dev_eui=%s device_id=%s prior_fcnt=%s "
                "current_fcnt=%s uplink_setpoint=%s resync_flag_set=%s",
                dev_eui,
                device_id,
                prior_fcnt,
                current_fcnt,
                user_setpoint,
                flag_set,
            )
            await _write_reboot_resync_event_log(
                session,
                room_id=room_id,
                device_id=device_id,
                received_at=received_at,
                prior_fcnt=prior_fcnt,
                current_fcnt=current_fcnt,
                uplink_setpoint=user_setpoint,
                flag_set=flag_set,
            )
            return None

    # Gate (pre-a): Sperre-Check (Sprint 12c, AE-58). Spiegelt den Block-Gate
    # in ``override_service.create``. Wenn der Raum aus dem Mapping nicht
    # existiert (Race / DB-Drift), kein EventLog — defensive Edge.
    room = await session.get(Room, room_id)
    if room is None:
        return None
    if room.guest_override_blocked:
        logger.info(
            "device-override skip: room_id=%s guest_override_blocked=True — device_id=%s",
            room_id,
            device_id,
        )
        await _write_blocked_event_log(
            session,
            room_id=room_id,
            device_id=device_id,
            received_at=received_at,
            reason=CommandReason.DEVICE_BLOCKED_ROOM_BLOCKED,
            uplink_setpoint=user_setpoint,
        )
        return None

    # Gate (a): OCCUPIED-Check (AE-58).
    room_status = await derive_room_status(session, room_id, received_at)
    if room_status != RoomStatus.OCCUPIED:
        logger.info(
            "device-override skip: room_id=%s nicht OCCUPIED (status=%s) — device_id=%s",
            room_id,
            room_status.value,
            device_id,
        )
        await _write_blocked_event_log(
            session,
            room_id=room_id,
            device_id=device_id,
            received_at=received_at,
            reason=CommandReason.DEVICE_BLOCKED_VACANT,
            uplink_setpoint=user_setpoint,
        )
        return None

    # Gate (b): Window-Offen-Check (AE-52, Sprint 12 T4 Helper reuse).
    open_zones = await detect_open_window_zones(session, room_id, received_at)
    if open_zones:
        logger.info(
            "device-override skip: room_id=%s window_open in zone(s)=%s — device_id=%s",
            room_id,
            [z.get("zone_id") for z in open_zones],
            device_id,
        )
        await _write_blocked_event_log(
            session,
            room_id=room_id,
            device_id=device_id,
            received_at=received_at,
            reason=CommandReason.DEVICE_BLOCKED_WINDOW,
            uplink_setpoint=user_setpoint,
        )
        return None

    # Gate (c): Zone-Lookup mit Room-Scope-Fallback (AE-58).
    heating_zone_id = await _device_zone_id(session, device_id)
    if heating_zone_id is None:
        logger.warning(
            "device_without_zone_mapping: device_id=%s room_id=%s — Override mit "
            "heating_zone_id=NULL angelegt (Room-Scope-Fallback)",
            device_id,
            room_id,
        )

    # Gate (d): Override anlegen.
    next_checkout = await next_active_checkout(session, room_id, now=received_at)
    hotel_config = await session.get(GlobalConfig, 1)

    expires_at = override_service.compute_expires_at(
        OverrideSource.DEVICE,
        received_at,
        next_checkout_at=next_checkout,
        hotel_config=hotel_config,
    )

    return await override_service.create(
        session,
        room_id=room_id,
        setpoint=user_setpoint,
        source=OverrideSource.DEVICE,
        expires_at=expires_at,
        reason="auto: detected user setpoint change",
        heating_zone_id=heating_zone_id,
    )
