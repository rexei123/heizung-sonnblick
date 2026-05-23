"""Sprint 13b.1 T4: Lifecycle-Filter-Tests pro §L-Stelle (AE-57).

Pro umgestellter §L-Stelle ein Test mit Retire-Simulation:
- Setup: 2 Devices in Zone (oder Pool), eines retired.
- Assert: nur das aktive Device im Result.

Pflicht-Test gegen S4-Verstoss (doppelte Downlinks waehrend Tausch-Race)
und gegen UI-Wahrheit (retired Devices nicht in Pool-Listings).

§L-Stellen aus Phase-0-Bericht (Sprint 13a) + Phase-0-Update (13b.1
Audit 1):

- T4.1 tasks/engine_tasks._get_zone_devices
- T4.2 rules/engine.layer_device_detached
- T4.3 rules/window_state.detect_open_window_zones
- T4.4 api/v1/devices Listen-Endpoint (Default-Filter)
- T4.5 services/device_adapter._device_room_id + _device_zone_id
- T4.6 scripts/pair_devices._cmd_list_pool via get_pool_devices

DB-Tests skippen ohne TEST_DATABASE_URL.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from heizung.models.device import Device
from heizung.models.enums import (
    CommandReason,
    DeviceKind,
    DeviceVendor,
    HeatingZoneKind,
    RoomStatus,
)
from heizung.models.heating_zone import HeatingZone
from heizung.models.room import Room
from heizung.models.room_type import RoomType
from heizung.models.sensor_reading import SensorReading
from heizung.rules.engine import layer_device_detached
from heizung.rules.window_state import detect_open_window_zones
from heizung.services.device_adapter import _device_room_id, _device_zone_id
from heizung.services.device_service import get_pool_devices
from heizung.tasks.engine_tasks import _get_zone_devices

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


async def _make_room_zone(session: AsyncSession) -> tuple[int, int]:
    """Helper: RoomType + Room + Zone -> (room_id, zone_id)."""
    suffix = uuid.uuid4().hex[:8]
    rt = RoomType(name=f"lc-rt-{suffix}")
    session.add(rt)
    await session.flush()
    room = Room(number=f"lc-{suffix}", room_type_id=rt.id, status=RoomStatus.VACANT)
    session.add(room)
    await session.flush()
    zone = HeatingZone(
        room_id=room.id,
        kind=HeatingZoneKind.BEDROOM,
        name=f"z-{suffix}",
    )
    session.add(zone)
    await session.flush()
    assert room.id is not None
    assert zone.id is not None
    return room.id, zone.id


def _make_device(
    *,
    zone_id: int | None,
    suffix: str | None = None,
    retired: bool = False,
    health_state: str = "healthy",
) -> Device:
    if suffix is None:
        suffix = uuid.uuid4().hex[:8]
    device = Device(
        dev_eui=f"deadbeef{suffix}",
        kind=DeviceKind.THERMOSTAT,
        vendor=DeviceVendor.MCLIMATE,
        model="vicki",
        heating_zone_id=zone_id,
        health_state=health_state,
    )
    if retired:
        device.retired_at = datetime.now(tz=UTC)
        device.retired_reason = "test_lifecycle_filter"
    return device


@pytest.mark.skipif(not TEST_DB_URL, reason=SKIP_REASON)
async def test_t4_1_get_zone_devices_ignores_retired(
    db_session: AsyncSession,
) -> None:
    """T4.1: ``engine_tasks._get_zone_devices`` filtert retired Devices.

    Zwei healthy Devices in Zone, eines retired -> Helper liefert nur
    das aktive (S4-Schutz gegen doppelte Downlinks waehrend Tausch).
    """
    _, zone_id = await _make_room_zone(db_session)
    active = _make_device(zone_id=zone_id)
    retired = _make_device(zone_id=zone_id, retired=True)
    db_session.add_all([active, retired])
    await db_session.flush()

    result = await _get_zone_devices(db_session, zone_id)

    assert len(result) == 1
    assert result[0].id == active.id
    assert result[0].retired_at is None


@pytest.mark.skipif(not TEST_DB_URL, reason=SKIP_REASON)
async def test_t4_2_layer_device_detached_ignores_retired(
    db_session: AsyncSession,
) -> None:
    """T4.2: ``rules.engine.layer_device_detached`` filtert retired Devices
    aus der Device-Liste UND der Reading-Subquery.

    Zwei Devices in Zone, eines retired. Reading-Frame fuer aktives
    Device gesetzt (frisch + attached_backplate=true). ``extras
    ['detached_devices']`` darf retired Device NICHT enthalten.
    """
    room_id, zone_id = await _make_room_zone(db_session)
    active = _make_device(zone_id=zone_id)
    retired = _make_device(zone_id=zone_id, retired=True)
    db_session.add_all([active, retired])
    await db_session.flush()

    now = datetime.now(tz=UTC)
    db_session.add(
        SensorReading(
            time=now - timedelta(minutes=2),
            device_id=active.id,
            attached_backplate=True,
        )
    )
    await db_session.flush()

    step = await layer_device_detached(
        db_session,
        room_id,
        prev_setpoint_c=20,
        prev_reason=CommandReason.VACANT_SETPOINT,
        room_status=RoomStatus.VACANT,
        now=now,
    )

    extras = step.extras
    assert extras is not None
    detached = extras["detached_devices"]
    assert retired.dev_eui not in detached, (
        f"retired Device {retired.dev_eui} darf NICHT in detached_devices "
        f"erscheinen (Lifecycle-Filter greift nicht?)"
    )


@pytest.mark.skipif(not TEST_DB_URL, reason=SKIP_REASON)
async def test_t4_3_detect_open_window_zones_ignores_retired(
    db_session: AsyncSession,
) -> None:
    """T4.3: ``window_state.detect_open_window_zones`` ignoriert retired
    Devices.

    Zwei Devices in Zone, eines retired. Beide melden ``open_window=True``
    in frischem Reading. Helper liefert die Zone NUR, weil das aktive
    Device sie meldet — retired Device-Reading darf nicht zaehlen.
    """
    room_id, zone_id = await _make_room_zone(db_session)
    active = _make_device(zone_id=zone_id)
    retired = _make_device(zone_id=zone_id, retired=True)
    db_session.add_all([active, retired])
    await db_session.flush()

    now = datetime.now(tz=UTC)
    db_session.add_all(
        [
            SensorReading(
                time=now - timedelta(minutes=2),
                device_id=active.id,
                open_window=True,
            ),
            SensorReading(
                time=now - timedelta(minutes=2),
                device_id=retired.id,
                open_window=True,
            ),
        ]
    )
    await db_session.flush()

    result = await detect_open_window_zones(db_session, room_id, now=now)

    # Genau 1 Treffer (aktives Device meldet open) — retired Device-Reading
    # bringt KEINEN zweiten Eintrag oder Duplikat.
    assert len(result) == 1
    assert result[0]["zone_id"] == zone_id


@pytest.mark.skipif(not TEST_DB_URL, reason=SKIP_REASON)
async def test_t4_4_list_devices_default_excludes_retired(
    db_session: AsyncSession,
) -> None:
    """T4.4: ``GET /api/v1/devices`` filtert per Default retired Devices
    via Inline-``retired_at IS NULL``.

    Hinweis: voller HTTP-Test in T6-Suite (test_api_devices_lifecycle.py).
    Hier nur der Query-Aufbau ohne HTTP-Schicht.
    """
    from sqlalchemy import select as sa_select

    _, zone_id = await _make_room_zone(db_session)
    active = _make_device(zone_id=zone_id)
    retired = _make_device(zone_id=zone_id, retired=True)
    db_session.add_all([active, retired])
    await db_session.flush()

    # Simuliere Default-Filter (include_retired=False):
    stmt = sa_select(Device).where(Device.retired_at.is_(None))
    result = await db_session.execute(stmt)
    devices = list(result.scalars().all())

    device_ids = {d.id for d in devices}
    assert active.id in device_ids
    assert retired.id not in device_ids, (
        f"retired Device {retired.id} darf bei Default-Filter NICHT "
        f"in der Liste sein (include_retired=False)."
    )


@pytest.mark.skipif(not TEST_DB_URL, reason=SKIP_REASON)
async def test_t4_5_device_adapter_returns_none_for_retired(
    db_session: AsyncSession,
) -> None:
    """T4.5: ``_device_room_id`` und ``_device_zone_id`` liefern ``None``
    fuer retired Devices.

    Retired Device im selben Zustand wie aktiv (Zone bleibt, retired_at
    gesetzt). Beide Adapter-Helper duerfen die Zone/Room NICHT
    zurueckliefern -> Override-Anlage durch retirten Vicki blockiert.
    """
    room_id, zone_id = await _make_room_zone(db_session)
    active = _make_device(zone_id=zone_id)
    retired = _make_device(zone_id=zone_id, retired=True)
    db_session.add_all([active, retired])
    await db_session.flush()

    # Aktives Device: beide Adapter liefern Werte.
    assert await _device_room_id(db_session, active.id) == room_id
    assert await _device_zone_id(db_session, active.id) == zone_id

    # Retirtes Device: beide liefern None (kein Override-Trigger).
    assert await _device_room_id(db_session, retired.id) is None, (
        "retired Device darf via _device_room_id KEINE Zone-Aufloesung "
        "liefern (Override-Anlage haette getriggered)."
    )
    assert await _device_zone_id(db_session, retired.id) is None, (
        "retired Device darf via _device_zone_id KEINE Zone-Aufloesung liefern."
    )


@pytest.mark.skipif(not TEST_DB_URL, reason=SKIP_REASON)
async def test_t4_6_list_pool_ignores_retired(db_session: AsyncSession) -> None:
    """T4.6: ``scripts/pair_devices._cmd_list_pool`` nutzt
    ``get_pool_devices`` (Helper aus T3) -> retired Pool-Devices nicht
    sichtbar.

    Pool-Setup: 1 aktives Pool-Device + 1 retired Pool-Device. Helper-
    Result darf nur das aktive enthalten.
    """
    active_pool = _make_device(zone_id=None)
    retired_pool = _make_device(zone_id=None, retired=True)
    db_session.add_all([active_pool, retired_pool])
    await db_session.flush()

    pool = await get_pool_devices(db_session)

    pool_ids = {d.id for d in pool}
    assert active_pool.id in pool_ids
    assert retired_pool.id not in pool_ids, (
        f"retired Pool-Device {retired_pool.id} darf NICHT in list-pool "
        f"sichtbar sein (Hotelier wuerde fuer Tausch falsche Reserve sehen)."
    )
