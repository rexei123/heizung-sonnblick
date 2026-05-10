"""Sprint 9.11x T6 — Engine Layer 4 (Device-Detached) Integrations-Tests.

AND-Semantik des Detached-Frostschutz-Triggers verifizieren:
  - Single-Device 1-4: attached / hysterese / detached / NULL-only.
  - Multi-Device 5-8: AND-Wachposten gegen versehentlichen OR-Refactor.
  - Test 9: Reason-Prioritaet (§5.23 Pass-Through) bei Window+Detached.
  - Test 10: NULL-Glitch-Robustheit — juengster NULL darf einen sonst
    eindeutigen Trigger nicht maskieren (Frische-Filter
    ``attached_backplate IS NOT NULL``).

DB-Tests skippen ohne ``TEST_DATABASE_URL``. Reading-Alter ueber
``time=now - timedelta(minutes=age_min)`` ohne ``freezegun`` (analog
``test_engine_layer4.py``). Pro Device verschiedene ``age_min`` damit
der Composite-PK ``(time, device_id)`` nicht kollidiert.
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
from heizung.rules.engine import (
    MIN_SETPOINT_C,
    LayerStep,
    evaluate_room,
)

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
async def setup_single_device(
    db_session: AsyncSession,
) -> AsyncIterator[dict[str, Any]]:
    """Raum + 1 Heizzone + 1 Device. Default-Status vacant -> Layer 1 = 18 degC.

    Suffix per UUID-Hex: room.number ist String(20), dev_eui String(16) —
    8 Hex-Zeichen reichen fuer Test-Eindeutigkeit innerhalb der Session.
    """
    suffix = uuid.uuid4().hex[:8]
    rt = RoomType(name=f"l4d-rt-{suffix}")
    db_session.add(rt)
    await db_session.flush()

    room = Room(number=f"l4d-{suffix}", room_type_id=rt.id)
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


@pytest_asyncio.fixture
async def setup_two_devices(
    db_session: AsyncSession,
) -> AsyncIterator[dict[str, Any]]:
    """Raum + 2 Heizzonen + 2 Devices (1 pro Zone, beide demselben Raum).

    Multi-Device-Setup ist der Wachposten gegen einen versehentlichen OR-
    Refactor: Tests 5/6/8 schicken jeweils 1 detached Device + 1 nicht-
    detached und erwarten KEIN Trigger; Test 7 schickt beide detached und
    erwartet Trigger.
    """
    suffix = uuid.uuid4().hex[:8]
    rt = RoomType(name=f"l4d-rt-{suffix}")
    db_session.add(rt)
    await db_session.flush()

    room = Room(number=f"l4d-{suffix}", room_type_id=rt.id)
    db_session.add(room)
    await db_session.flush()

    zone_a = HeatingZone(room_id=room.id, kind=HeatingZoneKind.BEDROOM, name="bedroom")
    zone_b = HeatingZone(room_id=room.id, kind=HeatingZoneKind.BATHROOM, name="bathroom")
    db_session.add_all([zone_a, zone_b])
    await db_session.flush()

    device_a = Device(
        dev_eui=f"aabbccdd{suffix}",
        kind=DeviceKind.THERMOSTAT,
        vendor=DeviceVendor.MCLIMATE,
        model="vicki",
        heating_zone_id=zone_a.id,
    )
    device_b = Device(
        dev_eui=f"11223344{suffix}",
        kind=DeviceKind.THERMOSTAT,
        vendor=DeviceVendor.MCLIMATE,
        model="vicki",
        heating_zone_id=zone_b.id,
    )
    db_session.add_all([device_a, device_b])
    await db_session.flush()

    yield {
        "room_id": room.id,
        "device_a_id": device_a.id,
        "device_b_id": device_b.id,
        "dev_eui_a": device_a.dev_eui,
        "dev_eui_b": device_b.dev_eui,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _detached_step(layers: tuple[LayerStep, ...]) -> LayerStep:
    matches = [layer for layer in layers if layer.layer == EventLogLayer.DEVICE_DETACHED]
    assert len(matches) == 1, f"erwarte genau 1 Detached-Eintrag, gefunden {len(matches)}"
    return matches[0]


async def _add_reading(
    session: AsyncSession,
    *,
    device_id: int,
    attached_backplate: bool | None,
    age_min: int,
    open_window: bool | None = None,
) -> None:
    reading = SensorReading(
        time=datetime.now(tz=UTC) - timedelta(minutes=age_min),
        device_id=device_id,
        fcnt=age_min,
        temperature=Decimal("21.0"),
        open_window=open_window,
        attached_backplate=attached_backplate,
    )
    session.add(reading)
    await session.flush()


# ---------------------------------------------------------------------------
# Test 1 — Single-Device, true,true -> kein Trigger (attached)
# ---------------------------------------------------------------------------


async def test_detached_single_true_true_no_trigger(
    db_session: AsyncSession, setup_single_device: dict[str, Any]
) -> None:
    dev_id = setup_single_device["device_id"]
    await _add_reading(db_session, device_id=dev_id, attached_backplate=True, age_min=15)
    await _add_reading(db_session, device_id=dev_id, attached_backplate=True, age_min=2)

    result = await evaluate_room(db_session, setup_single_device["room_id"])
    assert result is not None
    detached = _detached_step(result.layers)
    assert detached.setpoint_c == 18  # vacant default
    assert detached.reason == CommandReason.VACANT_SETPOINT
    assert detached.detail == "device_attached"
    assert detached.extras is not None
    assert detached.extras["detached_devices"] == []
    assert result.setpoint_c == 18


# ---------------------------------------------------------------------------
# Test 2 — Single-Device, false,true -> kein Trigger (Hysterese, juengster True)
# ---------------------------------------------------------------------------


async def test_detached_single_false_true_no_trigger(
    db_session: AsyncSession, setup_single_device: dict[str, Any]
) -> None:
    dev_id = setup_single_device["device_id"]
    await _add_reading(db_session, device_id=dev_id, attached_backplate=False, age_min=15)
    await _add_reading(db_session, device_id=dev_id, attached_backplate=True, age_min=2)

    result = await evaluate_room(db_session, setup_single_device["room_id"])
    assert result is not None
    detached = _detached_step(result.layers)
    assert detached.detail == "device_attached"
    assert detached.extras is not None
    assert detached.extras["detached_devices"] == []
    assert result.setpoint_c == 18


# ---------------------------------------------------------------------------
# Test 3 — Single-Device, false,false -> Trigger
# ---------------------------------------------------------------------------


async def test_detached_single_false_false_triggers(
    db_session: AsyncSession, setup_single_device: dict[str, Any]
) -> None:
    dev_id = setup_single_device["device_id"]
    await _add_reading(db_session, device_id=dev_id, attached_backplate=False, age_min=15)
    await _add_reading(db_session, device_id=dev_id, attached_backplate=False, age_min=2)

    result = await evaluate_room(db_session, setup_single_device["room_id"])
    assert result is not None
    detached = _detached_step(result.layers)
    assert detached.setpoint_c == MIN_SETPOINT_C
    assert detached.reason == CommandReason.DEVICE_DETACHED
    assert detached.extras is not None
    assert detached.extras["detached_devices"] == [setup_single_device["dev_eui"]]
    assert result.setpoint_c == MIN_SETPOINT_C


# ---------------------------------------------------------------------------
# Test 4 — Single-Device, NULL,NULL -> kein Trigger (Backwards-Compat)
# ---------------------------------------------------------------------------


async def test_detached_single_null_null_no_trigger(
    db_session: AsyncSession, setup_single_device: dict[str, Any]
) -> None:
    dev_id = setup_single_device["device_id"]
    await _add_reading(db_session, device_id=dev_id, attached_backplate=None, age_min=15)
    await _add_reading(db_session, device_id=dev_id, attached_backplate=None, age_min=2)

    result = await evaluate_room(db_session, setup_single_device["room_id"])
    assert result is not None
    detached = _detached_step(result.layers)
    assert detached.detail == "device_unclear"
    assert detached.extras is not None
    assert detached.extras["detached_devices"] == []
    assert result.setpoint_c == 18


# ---------------------------------------------------------------------------
# Test 5 — Multi A:F,F / B:T,T -> kein Trigger (B attached, AND-Wachposten)
# ---------------------------------------------------------------------------


async def test_detached_multi_a_detached_b_attached_no_trigger(
    db_session: AsyncSession, setup_two_devices: dict[str, Any]
) -> None:
    a = setup_two_devices["device_a_id"]
    b = setup_two_devices["device_b_id"]
    await _add_reading(db_session, device_id=a, attached_backplate=False, age_min=15)
    await _add_reading(db_session, device_id=a, attached_backplate=False, age_min=2)
    await _add_reading(db_session, device_id=b, attached_backplate=True, age_min=15)
    await _add_reading(db_session, device_id=b, attached_backplate=True, age_min=2)

    result = await evaluate_room(db_session, setup_two_devices["room_id"])
    assert result is not None
    detached = _detached_step(result.layers)
    assert detached.detail == "device_attached"
    assert detached.extras is not None
    # detached_devices listet A diagnostisch (auch ohne Trigger).
    assert detached.extras["detached_devices"] == [setup_two_devices["dev_eui_a"]]
    assert result.setpoint_c == 18  # kein Frostschutz, vacant default


# ---------------------------------------------------------------------------
# Test 6 — Multi A:F,F / B:offline -> kein Trigger (B unklar, AND-Wachposten)
# ---------------------------------------------------------------------------


async def test_detached_multi_a_detached_b_offline_no_trigger(
    db_session: AsyncSession, setup_two_devices: dict[str, Any]
) -> None:
    a = setup_two_devices["device_a_id"]
    b = setup_two_devices["device_b_id"]
    await _add_reading(db_session, device_id=a, attached_backplate=False, age_min=15)
    await _add_reading(db_session, device_id=a, attached_backplate=False, age_min=2)
    # B: nur stale Frame (>30min) -> 0 frische -> "unklar".
    await _add_reading(db_session, device_id=b, attached_backplate=False, age_min=60)

    result = await evaluate_room(db_session, setup_two_devices["room_id"])
    assert result is not None
    detached = _detached_step(result.layers)
    assert detached.detail == "device_unclear"
    assert detached.extras is not None
    assert detached.extras["detached_devices"] == [setup_two_devices["dev_eui_a"]]
    assert result.setpoint_c == 18


# ---------------------------------------------------------------------------
# Test 7 — Multi A:F,F / B:F,F -> Trigger, beide dev_euis gelistet
# ---------------------------------------------------------------------------


async def test_detached_multi_both_detached_triggers(
    db_session: AsyncSession, setup_two_devices: dict[str, Any]
) -> None:
    a = setup_two_devices["device_a_id"]
    b = setup_two_devices["device_b_id"]
    await _add_reading(db_session, device_id=a, attached_backplate=False, age_min=15)
    await _add_reading(db_session, device_id=a, attached_backplate=False, age_min=2)
    await _add_reading(db_session, device_id=b, attached_backplate=False, age_min=15)
    await _add_reading(db_session, device_id=b, attached_backplate=False, age_min=2)

    result = await evaluate_room(db_session, setup_two_devices["room_id"])
    assert result is not None
    detached = _detached_step(result.layers)
    assert detached.setpoint_c == MIN_SETPOINT_C
    assert detached.reason == CommandReason.DEVICE_DETACHED
    assert detached.extras is not None
    assert sorted(detached.extras["detached_devices"]) == sorted(
        [setup_two_devices["dev_eui_a"], setup_two_devices["dev_eui_b"]]
    )
    assert result.setpoint_c == MIN_SETPOINT_C


# ---------------------------------------------------------------------------
# Test 8 — Multi A:F,F / B:F,T -> kein Trigger (B Hysterese, AND-Wachposten)
# ---------------------------------------------------------------------------


async def test_detached_multi_a_detached_b_hysterese_no_trigger(
    db_session: AsyncSession, setup_two_devices: dict[str, Any]
) -> None:
    a = setup_two_devices["device_a_id"]
    b = setup_two_devices["device_b_id"]
    await _add_reading(db_session, device_id=a, attached_backplate=False, age_min=15)
    await _add_reading(db_session, device_id=a, attached_backplate=False, age_min=2)
    await _add_reading(db_session, device_id=b, attached_backplate=False, age_min=15)
    await _add_reading(db_session, device_id=b, attached_backplate=True, age_min=2)

    result = await evaluate_room(db_session, setup_two_devices["room_id"])
    assert result is not None
    detached = _detached_step(result.layers)
    assert detached.detail == "device_attached"
    assert detached.extras is not None
    assert detached.extras["detached_devices"] == [setup_two_devices["dev_eui_a"]]
    assert result.setpoint_c == 18


# ---------------------------------------------------------------------------
# Test 9 — Reason-Prioritaet: open_window=True UND alle F,F
#          -> superseded_by_window (§5.23 Pass-Through)
# ---------------------------------------------------------------------------


async def test_detached_superseded_by_window(
    db_session: AsyncSession, setup_single_device: dict[str, Any]
) -> None:
    dev_id = setup_single_device["device_id"]
    # Aelterer Frame: attached=False, open_window=False/None.
    await _add_reading(db_session, device_id=dev_id, attached_backplate=False, age_min=15)
    # Juengster Frame: attached=False, open_window=True
    # -> Window-Layer aktiv (juengster Frame gewinnt via DISTINCT ON device),
    # Detached-Layer sieht alle F,F als detached, prev_reason=WINDOW_OPEN
    # -> §5.23 Pass-Through.
    await _add_reading(
        db_session,
        device_id=dev_id,
        attached_backplate=False,
        open_window=True,
        age_min=2,
    )

    result = await evaluate_room(db_session, setup_single_device["room_id"])
    assert result is not None
    detached = _detached_step(result.layers)
    # Pass-Through: setpoint von Window (MIN), reason WINDOW_OPEN durchgereicht.
    assert detached.setpoint_c == MIN_SETPOINT_C
    assert detached.reason == CommandReason.WINDOW_OPEN
    assert detached.detail == "superseded_by_window"
    # extras listet Device als detached (Audit-Trail).
    assert detached.extras is not None
    assert detached.extras["detached_devices"] == [setup_single_device["dev_eui"]]
    assert result.setpoint_c == MIN_SETPOINT_C


# ---------------------------------------------------------------------------
# Test 10 — NULL-Glitch: juengster NULL, davor 2x False -> Trigger
#           (Frische-Filter ``attached_backplate IS NOT NULL`` ist scharf)
# ---------------------------------------------------------------------------


async def test_detached_null_glitch_does_not_mask_trigger(
    db_session: AsyncSession, setup_single_device: dict[str, Any]
) -> None:
    dev_id = setup_single_device["device_id"]
    # Drei FRISCHE Frames (alle <30min): aelteste False, mittlere False,
    # juengster NULL (Codec-Glitch). Frische-Filter
    # ``attached_backplate IS NOT NULL`` filtert NULL raus, die letzten 2
    # nicht-NULL Frames sind beide False -> Trigger.
    await _add_reading(db_session, device_id=dev_id, attached_backplate=False, age_min=20)
    await _add_reading(db_session, device_id=dev_id, attached_backplate=False, age_min=10)
    await _add_reading(db_session, device_id=dev_id, attached_backplate=None, age_min=2)

    result = await evaluate_room(db_session, setup_single_device["room_id"])
    assert result is not None
    detached = _detached_step(result.layers)
    assert detached.setpoint_c == MIN_SETPOINT_C
    assert detached.reason == CommandReason.DEVICE_DETACHED
    assert detached.extras is not None
    assert detached.extras["detached_devices"] == [setup_single_device["dev_eui"]]
    assert result.setpoint_c == MIN_SETPOINT_C
