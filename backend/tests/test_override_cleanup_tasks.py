"""Sprint 9.9 T7 - Tests fuer den Daily-Cleanup-Task.

Testet die ``_run``-Coroutine direkt - die ist die einzige nicht-triviale
Logik im Task. Der Celery-Sync-Wrapper (``cleanup_expired_overrides``)
ist nur ``asyncio.run(_run())``; im Test wuerde er Loop-Konflikt mit
pytest-asyncio geben.

Setup-Daten werden ueber eine separate async engine commited (eigener
Pool), damit der Task seine eigene engine ueber ``DATABASE_URL`` sieht.
Cleanup ueber direkten DELETE im teardown.
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
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from alembic import command
from heizung.models.enums import OverrideSource
from heizung.models.manual_override import ManualOverride
from heizung.models.room import Room
from heizung.models.room_type import RoomType
from heizung.tasks.override_cleanup_tasks import _run

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


async def _seed_3_expired_2_active(engine: AsyncEngine) -> tuple[int, int]:
    """Legt einen Raum + 3 expired + 2 active Overrides an. Committed.
    Returns ``(room_id, room_type_id)`` fuer Cleanup im Teardown."""
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    short = uuid.uuid4().hex[:8]
    async with sessionmaker() as s:
        rt = RoomType(name=f"t99-{short}")
        s.add(rt)
        await s.flush()
        room = Room(number=f"t99-{short}", room_type_id=rt.id)
        s.add(room)
        await s.flush()
        rid, rt_id = room.id, rt.id

        now = datetime.now(tz=UTC)
        for i in range(3):
            s.add(
                ManualOverride(
                    room_id=rid,
                    setpoint=Decimal("21.0"),
                    source=OverrideSource.FRONTEND_4H,
                    expires_at=now - timedelta(hours=i + 1),
                )
            )
        for i in range(2):
            s.add(
                ManualOverride(
                    room_id=rid,
                    setpoint=Decimal("22.0"),
                    source=OverrideSource.FRONTEND_4H,
                    expires_at=now + timedelta(hours=i + 1),
                )
            )
        await s.commit()
    return rid, rt_id


async def _cleanup_room(engine: AsyncEngine, room_id: int, room_type_id: int) -> None:
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    async with sessionmaker() as s:
        await s.execute(
            text("DELETE FROM manual_override WHERE room_id = :r"),
            {"r": room_id},
        )
        await s.execute(text("DELETE FROM room WHERE id = :r"), {"r": room_id})
        await s.execute(text("DELETE FROM room_type WHERE id = :r"), {"r": room_type_id})
        await s.commit()


async def _room_revoked_counts(engine: AsyncEngine, room_id: int) -> tuple[int, int]:
    """Zaehlt ``(revoked, not_revoked)`` Manual-Overrides fuer den Raum."""
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    async with sessionmaker() as s:
        result = await s.execute(
            text("SELECT revoked_at FROM manual_override WHERE room_id = :r"),
            {"r": room_id},
        )
        rows = list(result)
    revoked = sum(1 for row in rows if row[0] is not None)
    not_revoked = sum(1 for row in rows if row[0] is None)
    return revoked, not_revoked


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_cleanup_marks_only_expired(engine: AsyncEngine) -> None:
    """3 expired + 2 active -> nach Cleanup: 3 revoked, 2 aktiv."""
    rid, rt_id = await _seed_3_expired_2_active(engine)
    try:
        await _run()
        revoked, not_revoked = await _room_revoked_counts(engine, rid)
        assert revoked == 3
        assert not_revoked == 2
    finally:
        await _cleanup_room(engine, rid, rt_id)


async def test_cleanup_idempotent(engine: AsyncEngine) -> None:
    """Zweiter Cleanup-Lauf veraendert den Raum-State nicht."""
    rid, rt_id = await _seed_3_expired_2_active(engine)
    try:
        await _run()
        state_after_first = await _room_revoked_counts(engine, rid)
        assert state_after_first == (3, 2)

        await _run()
        state_after_second = await _room_revoked_counts(engine, rid)
        assert state_after_second == state_after_first
    finally:
        await _cleanup_room(engine, rid, rt_id)
