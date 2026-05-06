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

import logging
from datetime import timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from heizung.models.control_command import ControlCommand
from heizung.models.device import Device
from heizung.models.enums import OverrideSource
from heizung.models.global_config import GlobalConfig
from heizung.models.heating_zone import HeatingZone
from heizung.services import override_service
from heizung.services.occupancy_service import next_active_checkout

if TYPE_CHECKING:
    from datetime import datetime

    from heizung.models.manual_override import ManualOverride

logger = logging.getLogger(__name__)

ACK_WINDOW_SECONDS = 60
TOLERANCE_FPORT1 = Decimal("0.6")
TOLERANCE_FPORT2 = Decimal("0.1")


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
    keiner Zone zugeordnet ist."""
    stmt = (
        select(HeatingZone.room_id)
        .join(Device, Device.heating_zone_id == HeatingZone.id)
        .where(Device.id == device_id)
        .limit(1)
    )
    return await session.scalar(stmt)


async def handle_uplink_for_override(
    session: AsyncSession,
    device_id: int,
    uplink_target_temp: Decimal,
    fport: int,
    received_at: datetime,
) -> ManualOverride | None:
    """Vollstaendiger Pfad: Detection + Override-Erzeugung.

    Aufrufer: ``mqtt_subscriber`` nach erfolgreicher Reading-Persistenz.
    Returns den erzeugten ``ManualOverride`` oder ``None``, wenn keine
    Override-Bedingung erfuellt war (kein Engine-Intent, Ack-Window,
    innerhalb Toleranz, kein Room-Mapping).
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
    )
