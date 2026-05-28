"""Sprint 14c T1 — DB-Tests fuer ``services/dashboard_aggregates.py``.

Prueft die 6 Hotel-Aggregat-Helper gegen TimescaleDB. Die Counts sind
global (ueber den ganzen Bestand), daher arbeiten die Tests mit **Delta-
Asserts** (Wert vor/nach dem Anlegen der Test-Rows) statt absoluter
Erwartung — robust gegen Leftover-Daten aus anderen Suites (§5.39).

Ausnahme ``avg_room_temperature``: globaler Mittelwert laesst sich nicht
delta-pruefen. Der Happy-Path purged zuerst die Test-Daten dieses Files
und legt genau eine healthy-Zone an; ``last_engine_tick`` nutzt
Far-Future-Timestamps, die jeden Bestand dominieren.

DB-Tests skippen ohne ``TEST_DATABASE_URL`` (§5.50: lokal mit Postgres-
Container verifizieren, sonst CI).
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import delete as sa_delete
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from heizung.models.device import Device
from heizung.models.enums import (
    CommandReason,
    DeviceKind,
    DeviceVendor,
    EventLogLayer,
    HeatingZoneKind,
    OverrideSource,
    RoomStatus,
)
from heizung.models.event_log import EventLog
from heizung.models.heating_zone import HeatingZone
from heizung.models.manual_override import ManualOverride
from heizung.models.room import Room
from heizung.models.room_type import RoomType
from heizung.models.sensor_reading import SensorReading
from heizung.services import dashboard_aggregates as agg

TEST_DB_URL = os.environ.get("TEST_DATABASE_URL")
SKIP_REASON = "TEST_DATABASE_URL nicht gesetzt — DB-Tests brauchen Postgres"

pytestmark = pytest.mark.asyncio


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


async def _purge(session: AsyncSession) -> None:
    """Loescht t14c-Test-Daten + deadc14c-SensorReadings (§5.39)."""
    device_ids = list(
        (await session.execute(select(Device.id).where(Device.dev_eui.like("deadc14c%"))))
        .scalars()
        .all()
    )
    if device_ids:
        await session.execute(
            sa_delete(SensorReading).where(SensorReading.device_id.in_(device_ids))
        )
    rooms = list(
        (await session.execute(select(Room).where(Room.number.like("t14c-%")))).scalars().all()
    )
    for room in rooms:
        await session.delete(room)
    room_types = list(
        (await session.execute(select(RoomType).where(RoomType.name.like("t14c-%"))))
        .scalars()
        .all()
    )
    for room_type in room_types:
        await session.delete(room_type)
    await session.commit()


async def _mk_room(session: AsyncSession, suffix: str, status: RoomStatus) -> Room:
    rt = RoomType(name=f"t14c-rt-{suffix}")
    session.add(rt)
    await session.flush()
    room = Room(number=f"t14c-{suffix}", room_type_id=rt.id, status=status)
    session.add(room)
    await session.flush()
    return room


async def _mk_zone(session: AsyncSession, room_id: int, suffix: str) -> HeatingZone:
    zone = HeatingZone(room_id=room_id, kind=HeatingZoneKind.BEDROOM, name=f"z-{suffix}")
    session.add(zone)
    await session.flush()
    return zone


async def _mk_device(
    session: AsyncSession,
    suffix: str,
    *,
    zone_id: int | None,
    health_state: str,
    retired: bool = False,
) -> Device:
    # dev_eui ist VARCHAR(16) (§5.49): Prefix "deadc14c" (8) + 8 Hex = 16 exakt.
    device = Device(
        dev_eui=f"deadc14c{uuid.uuid4().hex[:8]}",
        kind=DeviceKind.THERMOSTAT,
        vendor=DeviceVendor.MCLIMATE,
        model="vicki",
        label=f"vicki-{suffix}",
        heating_zone_id=zone_id,
        health_state=health_state,
        retired_at=datetime.now(tz=UTC) if retired else None,
    )
    session.add(device)
    await session.flush()
    return device


async def _mk_reading(
    session: AsyncSession,
    device_id: int,
    *,
    temperature: Decimal | None,
    open_window: bool | None,
    when: datetime,
) -> None:
    session.add(
        SensorReading(
            time=when,
            device_id=device_id,
            temperature=temperature,
            open_window=open_window,
        )
    )
    await session.flush()


async def test_count_rooms_occupied_delta(db_session: AsyncSession) -> None:
    occ0, total0 = await agg.count_rooms_occupied(db_session)
    s = uuid.uuid4().hex[:8]
    await _mk_room(db_session, f"{s}a", RoomStatus.OCCUPIED)
    await _mk_room(db_session, f"{s}b", RoomStatus.OCCUPIED)
    await _mk_room(db_session, f"{s}c", RoomStatus.VACANT)
    occ1, total1 = await agg.count_rooms_occupied(db_session)
    assert occ1 - occ0 == 2
    assert total1 - total0 == 3


async def test_count_devices_online_delta_and_lifecycle_filter(db_session: AsyncSession) -> None:
    on0, total0 = await agg.count_devices_online(db_session)
    s = uuid.uuid4().hex[:8]
    room = await _mk_room(db_session, s, RoomStatus.VACANT)
    zone = await _mk_zone(db_session, room.id, s)
    await _mk_device(db_session, f"{s}1", zone_id=zone.id, health_state="healthy")
    await _mk_device(db_session, f"{s}2", zone_id=zone.id, health_state="degraded")
    await _mk_device(db_session, f"{s}3", zone_id=zone.id, health_state="silent")
    # retired healthy: weder online noch total (Lifecycle-Filter §5.58)
    await _mk_device(db_session, f"{s}4", zone_id=zone.id, health_state="healthy", retired=True)
    on1, total1 = await agg.count_devices_online(db_session)
    assert on1 - on0 == 2, "healthy + degraded online, silent + retired nicht"
    assert total1 - total0 == 3, "3 aktive (healthy+degraded+silent), retired ausgeschlossen"


async def test_count_active_overrides_excludes_revoked_and_expired(
    db_session: AsyncSession,
) -> None:
    base = await agg.count_active_overrides(db_session)
    s = uuid.uuid4().hex[:8]
    room = await _mk_room(db_session, s, RoomStatus.OCCUPIED)
    now = datetime.now(tz=UTC)
    db_session.add_all(
        [
            ManualOverride(
                room_id=room.id,
                setpoint=Decimal("21.0"),
                source=OverrideSource.FRONTEND_4H,
                expires_at=now + timedelta(hours=4),
            ),
            ManualOverride(  # revoked -> nicht aktiv
                room_id=room.id,
                setpoint=Decimal("21.0"),
                source=OverrideSource.FRONTEND_4H,
                expires_at=now + timedelta(hours=4),
                revoked_at=now,
            ),
            ManualOverride(  # abgelaufen -> nicht aktiv
                room_id=room.id,
                setpoint=Decimal("21.0"),
                source=OverrideSource.FRONTEND_4H,
                expires_at=now - timedelta(hours=1),
            ),
        ]
    )
    await db_session.flush()
    assert await agg.count_active_overrides(db_session) - base == 1


async def test_last_engine_tick_filters_hard_clamp(db_session: AsyncSession) -> None:
    s = uuid.uuid4().hex[:8]
    room = await _mk_room(db_session, s, RoomStatus.VACANT)
    hard_clamp_time = datetime(2099, 1, 1, 12, 0, tzinfo=UTC)
    later_other_layer = datetime(2099, 6, 1, 12, 0, tzinfo=UTC)
    db_session.add_all(
        [
            EventLog(
                time=hard_clamp_time,
                room_id=room.id,
                evaluation_id=uuid.uuid4(),
                layer=EventLogLayer.HARD_CLAMP,
                reason=CommandReason.OCCUPIED_SETPOINT,
            ),
            EventLog(  # spaeter, aber andere Schicht -> darf NICHT gewinnen
                time=later_other_layer,
                room_id=room.id,
                evaluation_id=uuid.uuid4(),
                layer=EventLogLayer.BASE_TARGET,
                reason=CommandReason.OCCUPIED_SETPOINT,
            ),
        ]
    )
    await db_session.flush()
    tick = await agg.last_engine_tick(db_session)
    assert tick == hard_clamp_time, "MAX(time) WHERE layer='hard_clamp', andere Layer ignoriert"


async def test_avg_room_temperature_happy_path_isolated(db_session: AsyncSession) -> None:
    """Genau eine healthy-Zone nach Purge -> globaler Mittel = Zonen-Mittel."""
    await _purge(db_session)
    s = uuid.uuid4().hex[:8]
    room = await _mk_room(db_session, s, RoomStatus.OCCUPIED)
    zone = await _mk_zone(db_session, room.id, s)
    now = datetime.now(tz=UTC)
    d1 = await _mk_device(db_session, f"{s}1", zone_id=zone.id, health_state="healthy")
    d2 = await _mk_device(db_session, f"{s}2", zone_id=zone.id, health_state="healthy")
    # silent device mit absurder Temp -> darf NICHT einfliessen
    d3 = await _mk_device(db_session, f"{s}3", zone_id=zone.id, health_state="silent")
    await _mk_reading(db_session, d1.id, temperature=Decimal("20.0"), open_window=False, when=now)
    await _mk_reading(db_session, d2.id, temperature=Decimal("22.0"), open_window=False, when=now)
    await _mk_reading(db_session, d3.id, temperature=Decimal("99.0"), open_window=True, when=now)
    avg = await agg.avg_room_temperature(db_session)
    assert avg == Decimal("21.0"), f"Mittel aus 20.0+22.0 healthy, silent ignoriert; war {avg}"


async def test_avg_room_temperature_none_when_no_healthy_temp(db_session: AsyncSession) -> None:
    """Zone nur mit silent-Device -> traegt nichts bei; nach Purge global None."""
    await _purge(db_session)
    s = uuid.uuid4().hex[:8]
    room = await _mk_room(db_session, s, RoomStatus.VACANT)
    zone = await _mk_zone(db_session, room.id, s)
    d1 = await _mk_device(db_session, f"{s}1", zone_id=zone.id, health_state="silent")
    await _mk_reading(
        db_session, d1.id, temperature=Decimal("21.0"), open_window=False, when=datetime.now(tz=UTC)
    )
    assert await agg.avg_room_temperature(db_session) is None


async def test_count_zones_window_open_delta(db_session: AsyncSession) -> None:
    base = await agg.count_zones_window_open(db_session)
    s = uuid.uuid4().hex[:8]
    room = await _mk_room(db_session, s, RoomStatus.OCCUPIED)
    now = datetime.now(tz=UTC)
    # Zone A: healthy Vicki meldet open_window=True -> zaehlt
    zone_a = await _mk_zone(db_session, room.id, f"{s}a")
    da = await _mk_device(db_session, f"{s}a", zone_id=zone_a.id, health_state="healthy")
    await _mk_reading(db_session, da.id, temperature=Decimal("19.0"), open_window=True, when=now)
    # Zone B: healthy Vicki open_window=False -> zaehlt nicht
    zone_b = await _mk_zone(db_session, room.id, f"{s}b")
    db = await _mk_device(db_session, f"{s}b", zone_id=zone_b.id, health_state="healthy")
    await _mk_reading(db_session, db.id, temperature=Decimal("21.0"), open_window=False, when=now)
    assert await agg.count_zones_window_open(db_session) - base == 1
