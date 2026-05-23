"""Tests fuer services/device_service.py (Sprint 13b.1 T3, AE-57).

Lifecycle-Lese-Helper-Tests:
- get_active_devices_for_zone: Happy, leer, retired-Filter
- get_pool_devices: Happy, leer, retired-Filter

DB-Tests skippen ohne TEST_DATABASE_URL. uuid-Suffix fuer Test-
Eindeutigkeit (§5.18, §5.59).
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from heizung.models.device import Device
from heizung.models.enums import DeviceKind, DeviceVendor, HeatingZoneKind
from heizung.models.heating_zone import HeatingZone
from heizung.models.room import Room
from heizung.models.room_type import RoomType
from heizung.services.device_service import (
    get_active_devices_for_zone,
    get_pool_devices,
)

TEST_DB_URL = os.environ.get("TEST_DATABASE_URL")
SKIP_REASON = "TEST_DATABASE_URL nicht gesetzt - DB-Tests brauchen Postgres"


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


async def _make_zone(session: AsyncSession) -> int:
    """Test-Helper: RoomType + Room + HeatingZone, gibt zone.id zurueck."""
    suffix = uuid.uuid4().hex[:8]
    rt = RoomType(name=f"ds-rt-{suffix}")
    session.add(rt)
    await session.flush()
    room = Room(number=f"ds-{suffix}", room_type_id=rt.id)
    session.add(room)
    await session.flush()
    zone = HeatingZone(
        room_id=room.id,
        kind=HeatingZoneKind.BEDROOM,
        name=f"z-{suffix}",
    )
    session.add(zone)
    await session.flush()
    assert zone.id is not None
    return zone.id


def _make_device(
    *,
    zone_id: int | None,
    suffix: str | None = None,
    retired: bool = False,
) -> Device:
    """Test-Helper: Device-Konstruktion mit explizitem Lifecycle-State."""
    if suffix is None:
        suffix = uuid.uuid4().hex[:8]
    device = Device(
        dev_eui=f"deadbeef{suffix}",
        kind=DeviceKind.THERMOSTAT,
        vendor=DeviceVendor.MCLIMATE,
        model="vicki",
        heating_zone_id=zone_id,
        health_state="healthy",
    )
    if retired:
        device.retired_at = datetime.now(tz=UTC)
        device.retired_reason = "test_fixture"
    return device


@pytest.mark.skipif(not TEST_DB_URL, reason=SKIP_REASON)
async def test_get_active_devices_for_zone_happy(db_session: AsyncSession) -> None:
    """Zone mit zwei aktiven Devices -> beide werden gefunden."""
    zone_id = await _make_zone(db_session)
    dev_a = _make_device(zone_id=zone_id)
    dev_b = _make_device(zone_id=zone_id)
    db_session.add_all([dev_a, dev_b])
    await db_session.flush()

    result = await get_active_devices_for_zone(db_session, zone_id)

    assert len(result) == 2
    assert {d.id for d in result} == {dev_a.id, dev_b.id}


@pytest.mark.skipif(not TEST_DB_URL, reason=SKIP_REASON)
async def test_get_active_devices_for_zone_empty(db_session: AsyncSession) -> None:
    """Zone ohne Devices -> leere Liste, kein Error."""
    zone_id = await _make_zone(db_session)

    result = await get_active_devices_for_zone(db_session, zone_id)

    assert result == []


@pytest.mark.skipif(not TEST_DB_URL, reason=SKIP_REASON)
async def test_get_active_devices_for_zone_ignores_retired(
    db_session: AsyncSession,
) -> None:
    """Zone mit 1 aktivem + 1 retired Device -> nur aktives im Result."""
    zone_id = await _make_zone(db_session)
    active = _make_device(zone_id=zone_id)
    retired = _make_device(zone_id=zone_id, retired=True)
    db_session.add_all([active, retired])
    await db_session.flush()

    result = await get_active_devices_for_zone(db_session, zone_id)

    assert len(result) == 1, (
        f"erwarte 1 aktives Device, gefunden {len(result)} (retired-Filter greift nicht?)"
    )
    assert result[0].id == active.id
    assert result[0].retired_at is None


@pytest.mark.skipif(not TEST_DB_URL, reason=SKIP_REASON)
async def test_get_pool_devices_happy(db_session: AsyncSession) -> None:
    """Zwei Pool-Devices (heating_zone_id=NULL) -> beide werden gefunden."""
    pool_a = _make_device(zone_id=None)
    pool_b = _make_device(zone_id=None)
    db_session.add_all([pool_a, pool_b])
    await db_session.flush()

    result = await get_pool_devices(db_session)

    pool_ids = {d.id for d in result}
    assert pool_a.id in pool_ids
    assert pool_b.id in pool_ids


@pytest.mark.skipif(not TEST_DB_URL, reason=SKIP_REASON)
async def test_get_pool_devices_empty(db_session: AsyncSession) -> None:
    """Keine Pool-Devices in der Session -> leere Liste oder bestehende
    Pool-Devices nicht im Result.

    Hinweis: Test-DB kann Pool-Devices aus anderen Tests enthalten;
    Assertion ist conservativ: gerade angelegtes Active-Device darf
    NICHT in get_pool_devices() auftauchen.
    """
    zone_id = await _make_zone(db_session)
    active = _make_device(zone_id=zone_id)
    db_session.add(active)
    await db_session.flush()

    result = await get_pool_devices(db_session)

    active_ids = {d.id for d in result}
    assert active.id not in active_ids, (
        f"aktives Device mit heating_zone_id={zone_id} darf NICHT in "
        f"Pool sein (heating_zone_id-Filter greift nicht?)"
    )


@pytest.mark.skipif(not TEST_DB_URL, reason=SKIP_REASON)
async def test_get_pool_devices_ignores_retired_pool(
    db_session: AsyncSession,
) -> None:
    """Retired Pool-Device (heating_zone_id=NULL, retired_at=NOW) -> NICHT im Result."""
    active_pool = _make_device(zone_id=None)
    retired_pool = _make_device(zone_id=None, retired=True)
    db_session.add_all([active_pool, retired_pool])
    await db_session.flush()

    result = await get_pool_devices(db_session)

    pool_ids = {d.id for d in result}
    assert active_pool.id in pool_ids
    assert retired_pool.id not in pool_ids, (
        f"retired Pool-Device {retired_pool.id} darf NICHT im Result sein "
        f"(retired-Filter greift nicht?)"
    )
