"""Sprint 9.9 T6 - PMS Auto-Revoke Tests.

DB-Tests: skip ohne ``DATABASE_URL`` (CI-Pattern, vgl. T4/T5).
"""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
import pytest_asyncio
from alembic.config import Config
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from alembic import command
from heizung.models.device import Device
from heizung.models.enums import (
    DeviceKind,
    DeviceVendor,
    HeatingZoneKind,
    OverrideSource,
    RoomStatus,
)
from heizung.models.heating_zone import HeatingZone
from heizung.models.manual_override import ManualOverride
from heizung.models.occupancy import Occupancy
from heizung.models.room import Room
from heizung.models.room_type import RoomType
from heizung.services.override_pms_hook import auto_revoke_on_checkout

DATABASE_URL = os.environ.get("DATABASE_URL")
DATABASE_URL_PRESENT = bool(DATABASE_URL)
SKIP_REASON = "DATABASE_URL nicht gesetzt - DB-Tests brauchen Test-DB"


@pytest_asyncio.fixture(scope="module", autouse=True)
async def _migrate_db() -> None:
    if not DATABASE_URL_PRESENT:
        return
    backend_root = Path(__file__).resolve().parents[1]
    cfg = Config(str(backend_root / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend_root / "alembic"))
    cfg.set_main_option("sqlalchemy.url", DATABASE_URL or "")
    await asyncio.to_thread(command.upgrade, cfg, "head")


@pytest_asyncio.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    if not DATABASE_URL_PRESENT:
        pytest.skip(SKIP_REASON)
    eng = create_async_engine(DATABASE_URL or "")
    try:
        yield eng
    finally:
        await eng.dispose()


@pytest_asyncio.fixture
async def session(engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    async with sessionmaker() as s:
        try:
            yield s
        finally:
            await s.rollback()


def _short() -> str:
    return uuid.uuid4().hex[:8]


def _eui() -> str:
    return uuid.uuid4().hex[:16]


async def _seed_room_with_device(s: AsyncSession) -> tuple[int, int]:
    """Legt RoomType + Room + HeatingZone + Device an, returns (room_id, device_id)."""
    short = _short()
    rt = RoomType(name=f"t99-{short}")
    s.add(rt)
    await s.flush()
    room = Room(number=f"t99-{short}", room_type_id=rt.id, status=RoomStatus.OCCUPIED)
    s.add(room)
    await s.flush()
    hz = HeatingZone(room_id=room.id, kind=HeatingZoneKind.BEDROOM, name="zone-1")
    s.add(hz)
    await s.flush()
    device = Device(
        dev_eui=_eui(),
        kind=DeviceKind.THERMOSTAT,
        vendor=DeviceVendor.MCLIMATE,
        model="Vicki",
        heating_zone_id=hz.id,
    )
    s.add(device)
    await s.flush()
    return room.id, device.id


async def _add_device_override(s: AsyncSession, room_id: int, expires: datetime) -> ManualOverride:
    o = ManualOverride(
        room_id=room_id,
        setpoint=Decimal("23.0"),
        source=OverrideSource.DEVICE,
        expires_at=expires,
    )
    s.add(o)
    await s.flush()
    return o


# ---------------------------------------------------------------------------
# 5 Tests
# ---------------------------------------------------------------------------


async def test_occupied_to_vacant_no_followup_revokes(session: AsyncSession) -> None:
    now = datetime.now(tz=UTC)
    room_id, _ = await _seed_room_with_device(session)
    override = await _add_device_override(session, room_id, now + timedelta(days=2))

    revoked = await auto_revoke_on_checkout(
        session,
        room_id,
        previous_status=RoomStatus.OCCUPIED,
        new_status=RoomStatus.VACANT,
        now=now,
    )
    assert revoked == 1
    await session.refresh(override)
    assert override.revoked_at is not None
    assert override.revoked_reason == "auto: guest checked out"


async def test_occupied_to_vacant_with_followup_in_2h_does_not_revoke(
    session: AsyncSession,
) -> None:
    now = datetime.now(tz=UTC)
    room_id, _ = await _seed_room_with_device(session)
    override = await _add_device_override(session, room_id, now + timedelta(days=2))
    # Folgegast in 2 Stunden -> Auto-Revoke darf NICHT triggern
    session.add(
        Occupancy(
            room_id=room_id,
            check_in=now + timedelta(hours=2),
            check_out=now + timedelta(days=3),
        )
    )
    await session.flush()

    revoked = await auto_revoke_on_checkout(
        session,
        room_id,
        previous_status=RoomStatus.OCCUPIED,
        new_status=RoomStatus.VACANT,
        now=now,
    )
    assert revoked == 0
    await session.refresh(override)
    assert override.revoked_at is None


async def test_vacant_to_occupied_does_not_revoke(session: AsyncSession) -> None:
    now = datetime.now(tz=UTC)
    room_id, _ = await _seed_room_with_device(session)
    override = await _add_device_override(session, room_id, now + timedelta(days=2))

    revoked = await auto_revoke_on_checkout(
        session,
        room_id,
        previous_status=RoomStatus.VACANT,
        new_status=RoomStatus.OCCUPIED,
        now=now,
    )
    assert revoked == 0
    await session.refresh(override)
    assert override.revoked_at is None


async def test_occupied_to_cleaning_does_not_revoke(session: AsyncSession) -> None:
    """Nur ``OCCUPIED -> VACANT`` triggert. CLEANING hat eigenen Lifecycle."""
    now = datetime.now(tz=UTC)
    room_id, _ = await _seed_room_with_device(session)
    override = await _add_device_override(session, room_id, now + timedelta(days=2))

    revoked = await auto_revoke_on_checkout(
        session,
        room_id,
        previous_status=RoomStatus.OCCUPIED,
        new_status=RoomStatus.CLEANING,
        now=now,
    )
    assert revoked == 0
    await session.refresh(override)
    assert override.revoked_at is None


async def test_occupied_to_vacant_no_overrides_returns_zero(session: AsyncSession) -> None:
    """Trigger-Bedingung erfuellt, aber kein device-Override aktiv -> 0,
    kein Fehler."""
    now = datetime.now(tz=UTC)
    room_id, _ = await _seed_room_with_device(session)

    revoked = await auto_revoke_on_checkout(
        session,
        room_id,
        previous_status=RoomStatus.OCCUPIED,
        new_status=RoomStatus.VACANT,
        now=now,
    )
    assert revoked == 0
