"""Sprint 9.9 T2 - override_service-Tests.

Pure-Function-Tests fuer ``compute_expires_at`` laufen ohne DB. Die
restlichen Tests nutzen ein async ``db_session``-Fixture und skippen,
wenn ``TEST_DATABASE_URL`` nicht gesetzt ist.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from heizung.models.enums import OverrideSource
from heizung.models.global_config import GlobalConfig
from heizung.models.manual_override import ManualOverride
from heizung.models.room import Room
from heizung.models.room_type import RoomType
from heizung.services import override_service

TEST_DB_URL = os.environ.get("TEST_DATABASE_URL")
SKIP_REASON = "TEST_DATABASE_URL nicht gesetzt - DB-Tests brauchen Postgres"


# ---------------------------------------------------------------------------
# Pure-Function-Tests fuer compute_expires_at (kein DB)
# ---------------------------------------------------------------------------


def test_compute_expires_at_frontend_4h() -> None:
    now = datetime(2026, 5, 6, 12, 0, tzinfo=UTC)
    result = override_service.compute_expires_at(OverrideSource.FRONTEND_4H, now)
    assert result == now + timedelta(hours=4)


def test_compute_expires_at_frontend_midnight_default_tz() -> None:
    """Default-Timezone Europe/Vienna. Mai = CEST (UTC+2). 23:59 lokal = 21:59 UTC."""
    now = datetime(2026, 5, 6, 12, 0, tzinfo=UTC)
    result = override_service.compute_expires_at(OverrideSource.FRONTEND_MIDNIGHT, now)
    expected = datetime(2026, 5, 6, 23, 59, tzinfo=ZoneInfo("Europe/Vienna"))
    assert result == expected.astimezone(UTC)


def test_compute_expires_at_frontend_midnight_with_hotel_config() -> None:
    """``hotel_config.timezone = 'UTC'`` -> 23:59 UTC heute."""
    now = datetime(2026, 5, 6, 12, 0, tzinfo=UTC)
    cfg = GlobalConfig(id=1, timezone="UTC")
    result = override_service.compute_expires_at(
        OverrideSource.FRONTEND_MIDNIGHT, now, hotel_config=cfg
    )
    assert result == datetime(2026, 5, 6, 23, 59, tzinfo=UTC)


def test_compute_expires_at_frontend_checkout_with_next() -> None:
    now = datetime(2026, 5, 6, 12, 0, tzinfo=UTC)
    next_co = datetime(2026, 5, 8, 11, 0, tzinfo=UTC)
    result = override_service.compute_expires_at(
        OverrideSource.FRONTEND_CHECKOUT, now, next_checkout_at=next_co
    )
    assert result == next_co


def test_compute_expires_at_frontend_checkout_without_next_falls_back_to_7_days() -> None:
    now = datetime(2026, 5, 6, 12, 0, tzinfo=UTC)
    result = override_service.compute_expires_at(OverrideSource.FRONTEND_CHECKOUT, now)
    assert result == now + timedelta(days=7)


def test_compute_expires_at_device_with_next() -> None:
    now = datetime(2026, 5, 6, 12, 0, tzinfo=UTC)
    next_co = datetime(2026, 5, 8, 11, 0, tzinfo=UTC)
    result = override_service.compute_expires_at(
        OverrideSource.DEVICE, now, next_checkout_at=next_co
    )
    assert result == next_co


def test_compute_expires_at_device_without_next_caps_at_7_days() -> None:
    now = datetime(2026, 5, 6, 12, 0, tzinfo=UTC)
    result = override_service.compute_expires_at(OverrideSource.DEVICE, now)
    assert result == now + timedelta(days=7)


def test_compute_expires_at_caps_when_next_checkout_too_far() -> None:
    """Hard-Cap greift, auch wenn next_checkout in 10 Tagen liegt."""
    now = datetime(2026, 5, 6, 12, 0, tzinfo=UTC)
    next_co = now + timedelta(days=10)
    result = override_service.compute_expires_at(
        OverrideSource.FRONTEND_CHECKOUT, now, next_checkout_at=next_co
    )
    assert result == now + timedelta(days=7)


# ---------------------------------------------------------------------------
# DB-Tests (async fixture, skip ohne TEST_DATABASE_URL)
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
async def room_id(db_session: AsyncSession) -> AsyncIterator[int]:
    """RoomType + Room als Test-Setup. Wird via session.rollback aufgeraeumt."""
    suffix = datetime.now(tz=UTC).strftime("%H%M%S%f")
    rt = RoomType(name=f"t9-9-svc-{suffix}")
    db_session.add(rt)
    await db_session.flush()
    room = Room(number=f"t9-9-{suffix}", room_type_id=rt.id)
    db_session.add(room)
    await db_session.flush()
    yield room.id


async def test_create_quantizes_setpoint(db_session: AsyncSession, room_id: int) -> None:
    expires = datetime.now(tz=UTC) + timedelta(hours=4)
    o = await override_service.create(
        db_session,
        room_id=room_id,
        setpoint=Decimal("21.55"),
        source=OverrideSource.FRONTEND_4H,
        expires_at=expires,
    )
    assert o.setpoint == Decimal("21.6")


async def test_create_rejects_setpoint_below_min(db_session: AsyncSession, room_id: int) -> None:
    expires = datetime.now(tz=UTC) + timedelta(hours=4)
    with pytest.raises(ValueError):
        await override_service.create(
            db_session,
            room_id=room_id,
            setpoint=Decimal("4.9"),
            source=OverrideSource.FRONTEND_4H,
            expires_at=expires,
        )


async def test_create_rejects_setpoint_above_max(db_session: AsyncSession, room_id: int) -> None:
    expires = datetime.now(tz=UTC) + timedelta(hours=4)
    with pytest.raises(ValueError):
        await override_service.create(
            db_session,
            room_id=room_id,
            setpoint=Decimal("30.1"),
            source=OverrideSource.FRONTEND_4H,
            expires_at=expires,
        )


async def test_create_caps_long_expires_at(db_session: AsyncSession, room_id: int) -> None:
    """``expires_at > now+7d`` wird hart auf ``now+7d`` gecappt."""
    far_future = datetime.now(tz=UTC) + timedelta(days=30)
    o = await override_service.create(
        db_session,
        room_id=room_id,
        setpoint=Decimal("21.0"),
        source=OverrideSource.DEVICE,
        expires_at=far_future,
    )
    assert o.expires_at <= datetime.now(tz=UTC) + timedelta(days=7, seconds=1)


async def test_get_active_returns_only_non_revoked(db_session: AsyncSession, room_id: int) -> None:
    """Revokierter Override wird uebersprungen; aktiver gewinnt."""
    expires = datetime.now(tz=UTC) + timedelta(hours=4)
    revoked = await override_service.create(
        db_session,
        room_id=room_id,
        setpoint=Decimal("20.0"),
        source=OverrideSource.FRONTEND_4H,
        expires_at=expires,
    )
    await override_service.revoke(db_session, revoked.id, reason="test")
    active = await override_service.create(
        db_session,
        room_id=room_id,
        setpoint=Decimal("22.0"),
        source=OverrideSource.FRONTEND_4H,
        expires_at=expires,
    )
    found = await override_service.get_active(db_session, room_id)
    assert found is not None
    assert found.id == active.id
    assert found.setpoint == Decimal("22.0")


async def test_get_active_returns_none_if_all_revoked(
    db_session: AsyncSession, room_id: int
) -> None:
    expires = datetime.now(tz=UTC) + timedelta(hours=4)
    o = await override_service.create(
        db_session,
        room_id=room_id,
        setpoint=Decimal("21.0"),
        source=OverrideSource.FRONTEND_4H,
        expires_at=expires,
    )
    await override_service.revoke(db_session, o.id, reason="test")
    active = await override_service.get_active(db_session, room_id)
    assert active is None


async def test_get_active_returns_none_if_all_expired(
    db_session: AsyncSession, room_id: int
) -> None:
    """Override mit ``expires_at < now`` zaehlt nicht als aktiv."""
    past = datetime.now(tz=UTC) - timedelta(hours=1)
    o = ManualOverride(
        room_id=room_id,
        setpoint=Decimal("21.0"),
        source=OverrideSource.FRONTEND_4H,
        expires_at=past,
    )
    db_session.add(o)
    await db_session.flush()
    active = await override_service.get_active(db_session, room_id)
    assert active is None


async def test_revoke_double_raises(db_session: AsyncSession, room_id: int) -> None:
    expires = datetime.now(tz=UTC) + timedelta(hours=4)
    o = await override_service.create(
        db_session,
        room_id=room_id,
        setpoint=Decimal("21.0"),
        source=OverrideSource.FRONTEND_4H,
        expires_at=expires,
    )
    await override_service.revoke(db_session, o.id, reason="erstmal")
    with pytest.raises(ValueError):
        await override_service.revoke(db_session, o.id, reason="zweites mal")


async def test_revoke_device_overrides_only_device(db_session: AsyncSession, room_id: int) -> None:
    expires = datetime.now(tz=UTC) + timedelta(hours=4)
    device = await override_service.create(
        db_session,
        room_id=room_id,
        setpoint=Decimal("23.0"),
        source=OverrideSource.DEVICE,
        expires_at=expires,
    )
    frontend = await override_service.create(
        db_session,
        room_id=room_id,
        setpoint=Decimal("21.0"),
        source=OverrideSource.FRONTEND_4H,
        expires_at=expires,
    )
    count = await override_service.revoke_device_overrides(db_session, room_id)
    assert count == 1
    await db_session.refresh(device)
    await db_session.refresh(frontend)
    assert device.revoked_at is not None
    assert frontend.revoked_at is None


async def test_cleanup_expired_marks_only_expired(db_session: AsyncSession, room_id: int) -> None:
    past = datetime.now(tz=UTC) - timedelta(hours=2)
    future = datetime.now(tz=UTC) + timedelta(hours=4)
    expired = ManualOverride(
        room_id=room_id,
        setpoint=Decimal("20.0"),
        source=OverrideSource.FRONTEND_4H,
        expires_at=past,
    )
    active = ManualOverride(
        room_id=room_id,
        setpoint=Decimal("22.0"),
        source=OverrideSource.FRONTEND_4H,
        expires_at=future,
    )
    db_session.add_all([expired, active])
    await db_session.flush()

    count = await override_service.cleanup_expired(db_session)
    assert count == 1
    await db_session.refresh(expired)
    await db_session.refresh(active)
    assert expired.revoked_at is not None
    assert expired.revoked_reason == "auto: expired"
    assert active.revoked_at is None
