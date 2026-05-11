"""Sprint 9.11y T4 — Layer-4-Pipeline E2E Synthetic-Tests.

Macht die drei Layer-4-Pfade (Vicki-Window, Detached, Inferred-Window)
ohne Hardware-Abhaengigkeit deterministisch testbar — Pflicht-Anker
fuer AE-47-Strategie ausserhalb der Heizperiode (Algorithmus-Traegheit
des Vicki-Hardware-Sensors macht Live-Tests im Sommer unpraktisch).

Tests:
  1. ``open_window=True`` → Frostschutz via Engine-Pipeline
  2. ``attached_backplate=False, False`` → device_detached via Engine
  3. Inferred-Window: Δ-T 1.0 °C, stehender Setpoint → passiver Log,
     KEIN Setpoint-Effekt
  4. Stabile Temperatur → kein Inferred-Log
  5. Setpoint-Wechsel an Lookback-Boundary (20 → 18 vor 1 Min) → kein
     Inferred-Trigger, weil Setpoint NICHT stehend war
  6. Pre-Window-Baseline (nur CC vor Lookback, keiner im Window) →
     Trigger mit ``setpoint_c`` aus Pre-Window-Baseline

Tests 1+2 nutzen ``evaluate_room`` (Engine-Pipeline). Tests 3-6 nutzen
``detect_inferred_window`` direkt (Off-Pipeline-Detector, vom
Engine-Tasks-Caller aufgerufen).

Konvention wie ``test_engine_layer4_detached.py`` — Reading-Alter via
``time=now-age_min`` ohne ``freezegun``, ``now``-Parameter explizit
durchgereicht im Inferred-Detector.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from heizung.models.control_command import ControlCommand
from heizung.models.device import Device
from heizung.models.enums import (
    CommandReason,
    DeviceKind,
    DeviceVendor,
    EventLogLayer,
    HeatingZoneKind,
)
from heizung.models.heating_zone import HeatingZone
from heizung.models.room import Room
from heizung.models.room_type import RoomType
from heizung.models.sensor_reading import SensorReading
from heizung.rules.engine import MIN_SETPOINT_C, evaluate_room
from heizung.rules.inferred_window import detect_inferred_window

TEST_DB_URL = os.environ.get("TEST_DATABASE_URL")
SKIP_REASON = "TEST_DATABASE_URL nicht gesetzt - DB-Tests brauchen Postgres"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    if not TEST_DB_URL:
        pytest.skip(SKIP_REASON)
    engine = create_async_engine(TEST_DB_URL)
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    async with sessionmaker() as session:
        try:
            yield session
        finally:
            await session.rollback()
    await engine.dispose()


@pytest_asyncio.fixture
async def setup_room(db_session: AsyncSession) -> AsyncIterator[dict[str, Any]]:
    """Raum + 1 Heizzone + 1 Device. Default-Status vacant → Layer 1 = 18 °C."""
    suffix = uuid.uuid4().hex[:8]
    rt = RoomType(name=f"l4s-rt-{suffix}")
    db_session.add(rt)
    await db_session.flush()

    room = Room(number=f"l4s-{suffix}", room_type_id=rt.id)
    db_session.add(room)
    await db_session.flush()

    zone = HeatingZone(room_id=room.id, kind=HeatingZoneKind.BEDROOM, name="bedroom")
    db_session.add(zone)
    await db_session.flush()

    device = Device(
        dev_eui=f"deadbeef{suffix}",
        kind=DeviceKind.THERMOSTAT,
        vendor=DeviceVendor.MCLIMATE,
        model="vicki",
        heating_zone_id=zone.id,
    )
    db_session.add(device)
    await db_session.flush()

    yield {
        "room_id": room.id,
        "zone_id": zone.id,
        "device_id": device.id,
        "dev_eui": device.dev_eui,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _add_reading(
    session: AsyncSession,
    *,
    device_id: int,
    age_min: int,
    temperature: Decimal | None = None,
    open_window: bool | None = None,
    attached_backplate: bool | None = None,
) -> None:
    reading = SensorReading(
        time=datetime.now(tz=UTC) - timedelta(minutes=age_min),
        device_id=device_id,
        fcnt=age_min,
        temperature=temperature,
        open_window=open_window,
        attached_backplate=attached_backplate,
    )
    session.add(reading)
    await session.flush()


async def _add_control_command(
    session: AsyncSession,
    *,
    device_id: int,
    setpoint_c: Decimal,
    age_min: int,
    reason: CommandReason = CommandReason.VACANT_SETPOINT,
) -> None:
    cc = ControlCommand(
        device_id=device_id,
        target_setpoint=setpoint_c,
        reason=reason,
        issued_at=datetime.now(tz=UTC) - timedelta(minutes=age_min),
    )
    session.add(cc)
    await session.flush()


# ---------------------------------------------------------------------------
# Test 1 — Vicki openWindow=True → Frostschutz via Engine-Pipeline
# ---------------------------------------------------------------------------


async def test_engine_layer4_window_synthetic(
    db_session: AsyncSession, setup_room: dict[str, Any]
) -> None:
    """E2E: frisches Reading mit open_window=True triggert Layer 4
    Window-Safety. evaluate_room muss Setpoint auf MIN_SETPOINT_C
    setzen mit reason=WINDOW_OPEN."""
    await _add_reading(
        db_session,
        device_id=setup_room["device_id"],
        age_min=2,
        temperature=Decimal("21.0"),
        open_window=True,
    )

    result = await evaluate_room(db_session, setup_room["room_id"])
    assert result is not None
    assert result.setpoint_c == MIN_SETPOINT_C
    assert result.base_reason == CommandReason.WINDOW_OPEN
    window_layer = next(
        layer for layer in result.layers if layer.layer == EventLogLayer.WINDOW_SAFETY
    )
    assert window_layer.setpoint_c == MIN_SETPOINT_C
    assert window_layer.reason == CommandReason.WINDOW_OPEN


# ---------------------------------------------------------------------------
# Test 2 — Vicki attached_backplate=False, False → device_detached
# ---------------------------------------------------------------------------


async def test_engine_layer4_detached_synthetic(
    db_session: AsyncSession, setup_room: dict[str, Any]
) -> None:
    """E2E: 2 frische Frames mit attached_backplate=False triggern
    Layer 4 Detached. AND-Semantik ueber Single-Device-Zone ist hier
    automatisch erfuellt."""
    dev_id = setup_room["device_id"]
    await _add_reading(db_session, device_id=dev_id, age_min=15, attached_backplate=False)
    await _add_reading(db_session, device_id=dev_id, age_min=2, attached_backplate=False)

    result = await evaluate_room(db_session, setup_room["room_id"])
    assert result is not None
    assert result.setpoint_c == MIN_SETPOINT_C
    assert result.base_reason == CommandReason.DEVICE_DETACHED


# ---------------------------------------------------------------------------
# Test 3 — Inferred-Window: Δ-T 1.0 °C, stehender Setpoint → passiver Trigger
# ---------------------------------------------------------------------------


async def test_inferred_window_detects_falling_temp_steady_setpoint(
    db_session: AsyncSession, setup_room: dict[str, Any]
) -> None:
    """3 SensorReadings 21.0 → 20.5 → 20.0 °C ueber 10 Min, stehender
    Setpoint 20.0 → detector returnt Result mit delta_c=1.0,
    devices_observed=[dev_eui], setpoint_c=20.

    Kein Setpoint-Effekt: Brief T3-Garantie, dass Inferred-Detector
    rein observational ist. Hier wird das nur ueber den Result-Vergleich
    geprueft — die Engine-Pipeline laeuft in T1/T2 separat ab und
    schreibt ControlCommands, der Detector ist davon entkoppelt.
    """
    dev_id = setup_room["device_id"]
    # Stehender Setpoint im Lookback: 2 CCs mit 20.0
    await _add_control_command(db_session, device_id=dev_id, setpoint_c=Decimal("20.0"), age_min=8)
    await _add_control_command(db_session, device_id=dev_id, setpoint_c=Decimal("20.0"), age_min=2)
    # Falling temperature 21.0 → 20.5 → 20.0 ueber 10 Min
    await _add_reading(db_session, device_id=dev_id, age_min=9, temperature=Decimal("21.0"))
    await _add_reading(db_session, device_id=dev_id, age_min=5, temperature=Decimal("20.5"))
    await _add_reading(db_session, device_id=dev_id, age_min=1, temperature=Decimal("20.0"))

    now = datetime.now(tz=UTC)
    result = await detect_inferred_window(db_session, setup_room["room_id"], now)
    assert result is not None
    assert result.delta_c == Decimal("1.0")
    assert result.devices_observed == [setup_room["dev_eui"]]
    assert result.setpoint_c == 20


# ---------------------------------------------------------------------------
# Test 4 — Stabile Temperatur → kein Inferred-Trigger
# ---------------------------------------------------------------------------


async def test_inferred_window_no_trigger_when_stable(
    db_session: AsyncSession, setup_room: dict[str, Any]
) -> None:
    """3 SensorReadings stabil bei 21.0 °C → Δ-T=0 → kein Trigger."""
    dev_id = setup_room["device_id"]
    await _add_control_command(db_session, device_id=dev_id, setpoint_c=Decimal("20.0"), age_min=5)
    await _add_reading(db_session, device_id=dev_id, age_min=9, temperature=Decimal("21.0"))
    await _add_reading(db_session, device_id=dev_id, age_min=5, temperature=Decimal("21.0"))
    await _add_reading(db_session, device_id=dev_id, age_min=1, temperature=Decimal("21.0"))

    now = datetime.now(tz=UTC)
    result = await detect_inferred_window(db_session, setup_room["room_id"], now)
    assert result is None


# ---------------------------------------------------------------------------
# Test 5 — Setpoint-Wechsel an Lookback-Boundary → kein Trigger
# ---------------------------------------------------------------------------


async def test_inferred_window_no_trigger_on_setpoint_change_boundary(
    db_session: AsyncSession, setup_room: dict[str, Any]
) -> None:
    """ControlCommand-History:
      - 30 Min zurueck: setpoint 20.0, reason=preheat_checkin
      - 1 Min zurueck: setpoint 18.0, reason=checkout_setback

    SensorReadings im Lookback: 21.0 → 20.5 → 20.0 °C (Δ-T=1.0).

    Trotz Δ-T-Schwelle erreicht: KEIN Inferred-Trigger, weil der
    Setpoint im Lookback NICHT stehend war (20 → 18 Wechsel).
    Δ-T koennte aus Setpoint-Absenkung kommen, nicht aus offenem
    Fenster.

    Wachposten gegen Naive-Implementierung (nur CCs >= threshold
    pruefen) — ohne Pre-Window-Baseline waere der Wechsel an der
    Boundary unsichtbar.
    """
    dev_id = setup_room["device_id"]
    # Setpoint-Wechsel: 20 (vor 30 Min) → 18 (vor 1 Min)
    await _add_control_command(
        db_session,
        device_id=dev_id,
        setpoint_c=Decimal("20.0"),
        age_min=30,
        reason=CommandReason.PREHEAT_CHECKIN,
    )
    await _add_control_command(
        db_session,
        device_id=dev_id,
        setpoint_c=Decimal("18.0"),
        age_min=1,
        reason=CommandReason.CHECKOUT_SETBACK,
    )
    # Falling temperature 21.0 → 20.5 → 20.0
    await _add_reading(db_session, device_id=dev_id, age_min=9, temperature=Decimal("21.0"))
    await _add_reading(db_session, device_id=dev_id, age_min=5, temperature=Decimal("20.5"))
    await _add_reading(db_session, device_id=dev_id, age_min=1, temperature=Decimal("20.0"))

    now = datetime.now(tz=UTC)
    result = await detect_inferred_window(db_session, setup_room["room_id"], now)
    assert result is None, (
        f"erwarte kein Trigger (Setpoint-Wechsel 20→18 im Lookback), gefunden: {result}"
    )


# ---------------------------------------------------------------------------
# Test 6 — Pre-Window-Baseline (CC vor Lookback) → Trigger mit setpoint_c=20
# ---------------------------------------------------------------------------


async def test_inferred_window_pre_window_baseline_triggers(
    db_session: AsyncSession, setup_room: dict[str, Any]
) -> None:
    """ControlCommand-History: 30 Min zurueck setpoint 20.0, dann nichts mehr.

    SensorReadings: 21.0 → 20.5 → 20.0 °C im Lookback (Δ-T=1.0).

    Inferred-Trigger feuert mit ``setpoint_c=20`` (= Pre-Window-Baseline,
    war waehrend des gesamten Lookback stehend bei 20.0). Wachposten
    gegen Bug "setpoint_c = juengster CC ueberhaupt" — juengster CC
    ist hier 30 Min alt und das ist der STEHENDE Wert, deshalb passt
    setpoint_c=20.
    """
    dev_id = setup_room["device_id"]
    # NUR ein CC, 30 Min alt (= Pre-Window-Baseline, kein CC im Lookback)
    await _add_control_command(
        db_session,
        device_id=dev_id,
        setpoint_c=Decimal("20.0"),
        age_min=30,
        reason=CommandReason.VACANT_SETPOINT,
    )
    await _add_reading(db_session, device_id=dev_id, age_min=9, temperature=Decimal("21.0"))
    await _add_reading(db_session, device_id=dev_id, age_min=5, temperature=Decimal("20.5"))
    await _add_reading(db_session, device_id=dev_id, age_min=1, temperature=Decimal("20.0"))

    now = datetime.now(tz=UTC)
    result = await detect_inferred_window(db_session, setup_room["room_id"], now)
    assert result is not None
    assert result.delta_c == Decimal("1.0")
    assert result.setpoint_c == 20, (
        f"erwarte setpoint_c=20 (Pre-Window-Baseline), gefunden: {result.setpoint_c}"
    )
