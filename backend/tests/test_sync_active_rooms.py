"""Sprint 15g T3 - Tests fuer den periodischen room.status-Sync.

DB-Tests (async, skippen ohne ``TEST_DATABASE_URL``). Alle Belegungen +
sync-Aufrufe nutzen ABSOLUTE Zeiten und uebergeben ``now`` explizit an
``sync_active_rooms`` — kein ``freeze_time`` noetig, weil die Funktion ein
explizites ``now`` akzeptiert (umschifft die §5.59 freezegun/Fixture-Falle).

§5.49: ``Room.number`` ist VARCHAR(20). Prefix ``t15g-`` (5) + uuid-Suffix
(8) = 13 chars, passt.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from heizung.models.business_audit import BusinessAudit
from heizung.models.enums import OverrideSource, RoomStatus
from heizung.models.manual_override import ManualOverride
from heizung.models.occupancy import Occupancy
from heizung.models.room import Room
from heizung.models.room_type import RoomType
from heizung.services.occupancy_service import sync_active_rooms

TEST_DB_URL = os.environ.get("TEST_DATABASE_URL")
SKIP_REASON = "TEST_DATABASE_URL nicht gesetzt - DB-Tests brauchen Postgres"

# Bezugszeiten: 14:00 / 11:00 Europe/Vienna (CEST, Juni) == 12:00 / 09:00 UTC.
# Die Hotelzeiten stecken als UTC-Timestamp in check_in/check_out (Import-
# Defaults). Fuer den Sync zaehlt der absolute Timestamp, nicht die lokale
# Wanduhr — daher reicht UTC hier aus.
CHECK_IN = datetime(2026, 6, 15, 12, 0, tzinfo=UTC)  # Anreise 14:00 lokal
CHECK_OUT = datetime(2026, 6, 17, 9, 0, tzinfo=UTC)  # Abreise 11:00 lokal


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


async def _make_room(session: AsyncSession, *, status: RoomStatus = RoomStatus.VACANT) -> int:
    """RoomType + Room anlegen, ``room.id`` zurueck. §5.49: 13-char number."""
    suffix = uuid.uuid4().hex[:8]
    rt = RoomType(name=f"t15g-rt-{suffix}")
    session.add(rt)
    await session.flush()
    room = Room(number=f"t15g-{suffix}", room_type_id=rt.id, status=status)
    session.add(room)
    await session.flush()
    return room.id


async def _add_occupancy(
    session: AsyncSession,
    room_id: int,
    *,
    check_in: datetime,
    check_out: datetime,
    is_active: bool = True,
) -> None:
    session.add(
        Occupancy(
            room_id=room_id,
            check_in=check_in,
            check_out=check_out,
            is_active=is_active,
        )
    )
    await session.flush()


async def _status(session: AsyncSession, room_id: int) -> RoomStatus:
    room = await session.get(Room, room_id)
    assert room is not None
    return room.status


# ---------------------------------------------------------------------------
# DATUM (Ganztags-Uebergaenge)
# ---------------------------------------------------------------------------


async def test_active_stay_occupied(db_session: AsyncSession) -> None:
    now = datetime(2026, 6, 16, 12, 0, tzinfo=UTC)
    rid = await _make_room(db_session)
    await _add_occupancy(
        db_session, rid, check_in=now - timedelta(days=1), check_out=now + timedelta(days=1)
    )
    synced = await sync_active_rooms(db_session, now)
    assert synced >= 1
    assert await _status(db_session, rid) == RoomStatus.OCCUPIED


async def test_departed_stay_vacant(db_session: AsyncSession) -> None:
    now = datetime(2026, 6, 16, 12, 0, tzinfo=UTC)
    rid = await _make_room(db_session, status=RoomStatus.OCCUPIED)
    await _add_occupancy(
        db_session, rid, check_in=now - timedelta(days=3), check_out=now - timedelta(days=1)
    )
    await sync_active_rooms(db_session, now)
    assert await _status(db_session, rid) == RoomStatus.VACANT


async def test_future_stay_reserved(db_session: AsyncSession) -> None:
    now = datetime(2026, 6, 16, 12, 0, tzinfo=UTC)
    rid = await _make_room(db_session)
    await _add_occupancy(
        db_session, rid, check_in=now + timedelta(days=1), check_out=now + timedelta(days=3)
    )
    await sync_active_rooms(db_session, now)
    assert await _status(db_session, rid) == RoomStatus.RESERVED


# ---------------------------------------------------------------------------
# UHRZEIT-Grenzen (Kern dieses Fixes) — check_in 14:00 / check_out 11:00
# ---------------------------------------------------------------------------


async def test_checkin_boundary_before_reserved(db_session: AsyncSession) -> None:
    rid = await _make_room(db_session)
    await _add_occupancy(db_session, rid, check_in=CHECK_IN, check_out=CHECK_OUT)
    await sync_active_rooms(db_session, CHECK_IN - timedelta(minutes=1))
    assert await _status(db_session, rid) == RoomStatus.RESERVED


async def test_checkin_boundary_after_occupied(db_session: AsyncSession) -> None:
    rid = await _make_room(db_session)
    await _add_occupancy(db_session, rid, check_in=CHECK_IN, check_out=CHECK_OUT)
    await sync_active_rooms(db_session, CHECK_IN + timedelta(minutes=1))
    assert await _status(db_session, rid) == RoomStatus.OCCUPIED


async def test_checkout_boundary_before_occupied(db_session: AsyncSession) -> None:
    rid = await _make_room(db_session)
    await _add_occupancy(db_session, rid, check_in=CHECK_IN, check_out=CHECK_OUT)
    await sync_active_rooms(db_session, CHECK_OUT - timedelta(minutes=1))
    assert await _status(db_session, rid) == RoomStatus.OCCUPIED


async def test_checkout_boundary_after_vacant(db_session: AsyncSession) -> None:
    rid = await _make_room(db_session)
    await _add_occupancy(db_session, rid, check_in=CHECK_IN, check_out=CHECK_OUT)
    await sync_active_rooms(db_session, CHECK_OUT + timedelta(minutes=1))
    assert await _status(db_session, rid) == RoomStatus.VACANT


async def test_back_to_back_gap_reserved(db_session: AsyncSession) -> None:
    """Back-to-back-Gap (Abreise 11:00, neue Anreise 14:00) -> RESERVED.

    Entscheidung A (Strategie-Chat Sprint 15g): im 11:00-14:00-Fenster ist
    der Raum fuer den Folgegast reserviert, nicht frei. derive_room_status
    liefert RESERVED, weil die neue Belegung eine zukuenftige aktive
    Belegung ist — bewusst unveraendert. VACANT wuerde das Zimmer im Gap
    auskuehlen lassen; RESERVED erhaelt das Vorheizen fuer den Folgegast.
    """
    now = datetime(2026, 6, 16, 10, 0, tzinfo=UTC)  # zwischen 09:00 und 12:00 UTC
    rid = await _make_room(db_session)
    await _add_occupancy(
        db_session,
        rid,
        check_in=now - timedelta(days=2),
        check_out=datetime(2026, 6, 16, 9, 0, tzinfo=UTC),  # Abreise 11:00 lokal
    )
    await _add_occupancy(
        db_session,
        rid,
        check_in=datetime(2026, 6, 16, 12, 0, tzinfo=UTC),  # neue Anreise 14:00 lokal
        check_out=now + timedelta(days=2),
    )
    await sync_active_rooms(db_session, now)
    assert await _status(db_session, rid) == RoomStatus.RESERVED


# ---------------------------------------------------------------------------
# Robustheit: lange Aufenthalte, manuelle Stati, stornierte Belegungen
# ---------------------------------------------------------------------------


async def test_long_stay_not_missed(db_session: AsyncSession) -> None:
    """30-Tage-Aufenthalt ueberlappt das +-1-Tag-Fenster -> OCCUPIED."""
    now = datetime(2026, 6, 16, 12, 0, tzinfo=UTC)
    rid = await _make_room(db_session)
    await _add_occupancy(
        db_session, rid, check_in=now - timedelta(days=15), check_out=now + timedelta(days=15)
    )
    synced = await sync_active_rooms(db_session, now)
    assert synced >= 1
    assert await _status(db_session, rid) == RoomStatus.OCCUPIED


async def test_cleaning_not_overwritten(db_session: AsyncSession) -> None:
    now = datetime(2026, 6, 16, 12, 0, tzinfo=UTC)
    rid = await _make_room(db_session, status=RoomStatus.CLEANING)
    await _add_occupancy(
        db_session, rid, check_in=now - timedelta(days=1), check_out=now + timedelta(days=1)
    )
    await sync_active_rooms(db_session, now)
    assert await _status(db_session, rid) == RoomStatus.CLEANING


async def test_blocked_not_overwritten(db_session: AsyncSession) -> None:
    now = datetime(2026, 6, 16, 12, 0, tzinfo=UTC)
    rid = await _make_room(db_session, status=RoomStatus.BLOCKED)
    await _add_occupancy(
        db_session, rid, check_in=now - timedelta(days=1), check_out=now + timedelta(days=1)
    )
    await sync_active_rooms(db_session, now)
    assert await _status(db_session, rid) == RoomStatus.BLOCKED


async def test_cancelled_occupancy_not_selected(db_session: AsyncSession) -> None:
    """Nur eine stornierte Belegung -> Raum wird nicht selektiert; ein stale
    OCCUPIED bleibt unangetastet (beweist is_active-Filter in der Selektion)."""
    now = datetime(2026, 6, 16, 12, 0, tzinfo=UTC)
    rid = await _make_room(db_session, status=RoomStatus.OCCUPIED)
    await _add_occupancy(
        db_session,
        rid,
        check_in=now - timedelta(days=1),
        check_out=now + timedelta(days=1),
        is_active=False,
    )
    await sync_active_rooms(db_session, now)
    assert await _status(db_session, rid) == RoomStatus.OCCUPIED


# ---------------------------------------------------------------------------
# Idempotenz: Checkout-Revoke schreibt genau EINEN business_audit, Re-Run no-op
# ---------------------------------------------------------------------------


async def test_idempotent_checkout_revoke_audit(db_session: AsyncSession) -> None:
    rid = await _make_room(db_session, status=RoomStatus.OCCUPIED)
    await _add_occupancy(db_session, rid, check_in=CHECK_IN, check_out=CHECK_OUT)
    # Aktiver Override direkt eingefuegt (umgeht das OCCUPIED-Gate von create()).
    db_session.add(
        ManualOverride(
            room_id=rid,
            setpoint=Decimal("21.0"),
            source=OverrideSource.FRONTEND_4H,
            expires_at=CHECK_OUT + timedelta(days=5),
        )
    )
    await db_session.flush()

    now = CHECK_OUT + timedelta(hours=1)  # nach Abreise, kein Folgegast

    async def _audit_count() -> int:
        result = await db_session.scalar(
            select(func.count())
            .select_from(BusinessAudit)
            .where(
                BusinessAudit.target_type == "room",
                BusinessAudit.target_id == rid,
                BusinessAudit.action == "OVERRIDES_AUTO_REVOKED_ON_CHECKOUT",
            )
        )
        return int(result or 0)

    assert await _audit_count() == 0
    await sync_active_rooms(db_session, now)
    assert await _status(db_session, rid) == RoomStatus.VACANT
    assert await _audit_count() == 1  # genau ein Revoke-Audit beim echten Wechsel

    # Re-Run bei unveraendertem Status -> kein neues Audit (Idempotenz).
    await sync_active_rooms(db_session, now)
    assert await _audit_count() == 1
