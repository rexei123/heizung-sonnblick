"""Sprint 14d — Override-Sichtbarkeit (Block A + FU-5).

Prueft:
- ``override_service.get_rooms_with_active_override`` (EXISTS-Semantik:
  room-scope/zone-scope -> true, revoked/expired -> false).
- ``GET /api/v1/rooms`` befuellt ``has_active_override`` und macht dafuer
  **genau einen** ``manual_override``-Query (R-D: kein N+1).
- ``GET /api/v1/rooms/{id}/heating-zones`` liefert ``active_override`` (FU-5).

DB-Tests; skip ohne ``DATABASE_URL`` / ``TEST_DATABASE_URL`` (§5.50).
"""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from alembic.config import Config
from httpx import ASGITransport
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from alembic import command
from heizung.auth.password import hash_password
from heizung.auth.rate_limit import limiter
from heizung.config import get_settings
from heizung.db import get_session
from heizung.main import app
from heizung.models.enums import HeatingZoneKind, OverrideSource, RoomStatus, UserRole
from heizung.models.heating_zone import HeatingZone
from heizung.models.manual_override import ManualOverride
from heizung.models.room import Room
from heizung.models.room_type import RoomType
from heizung.models.user import User
from heizung.services import override_service

DATABASE_URL = os.environ.get("DATABASE_URL")
DATABASE_URL_PRESENT = bool(DATABASE_URL)
SKIP_REASON = "DATABASE_URL nicht gesetzt - DB-Tests brauchen Test-DB"

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _auth_test_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setenv("ALLOW_DEFAULT_SECRETS", "1")
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("AUTH_COOKIE_SECURE", "false")
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _reset_limiter() -> Iterator[None]:
    limiter.reset()
    yield
    limiter.reset()


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
async def setup_engine() -> AsyncIterator[AsyncEngine]:
    if not DATABASE_URL_PRESENT:
        pytest.skip(SKIP_REASON)
    engine = create_async_engine(DATABASE_URL or "")
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def http_client(setup_engine: AsyncEngine) -> AsyncIterator[httpx.AsyncClient]:
    sessionmaker = async_sessionmaker(setup_engine, expire_on_commit=False)

    async def _override_get_session() -> AsyncIterator[AsyncSession]:
        async with sessionmaker() as session:
            yield session

    app.dependency_overrides[get_session] = _override_get_session
    try:
        transport = ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            yield client
    finally:
        app.dependency_overrides.clear()


async def _login_admin(client: httpx.AsyncClient, sm: async_sessionmaker[AsyncSession]) -> str:
    suffix = uuid.uuid4().hex[:8]
    email = f"d14d-admin-{suffix}@test.example.com"
    pw = "Override14dPassword!"
    async with sm() as session:
        session.add(
            User(
                email=email,
                password_hash=hash_password(pw),
                role=UserRole.ADMIN,
                is_active=True,
                must_change_password=False,
            )
        )
        await session.commit()
    resp = await client.post("/api/v1/auth/login", json={"email": email, "password": pw})
    assert resp.status_code == 200, resp.text
    return email


async def _mk_room(
    sm: async_sessionmaker[AsyncSession], suffix: str, status: RoomStatus
) -> tuple[int, int]:
    """Legt RoomType + Room an, gibt (room_id, room_type_id)."""
    async with sm() as session:
        rt = RoomType(name=f"t14d-rt-{suffix}")
        session.add(rt)
        await session.flush()
        room = Room(number=f"t14d-{suffix}", room_type_id=rt.id, status=status)
        session.add(room)
        await session.flush()
        await session.commit()
        return room.id, rt.id


async def _mk_zone(sm: async_sessionmaker[AsyncSession], room_id: int, suffix: str) -> int:
    async with sm() as session:
        zone = HeatingZone(room_id=room_id, kind=HeatingZoneKind.BEDROOM, name=f"z-{suffix}")
        session.add(zone)
        await session.flush()
        await session.commit()
        return zone.id


async def _mk_override(
    sm: async_sessionmaker[AsyncSession],
    room_id: int,
    *,
    heating_zone_id: int | None,
    expires_in: timedelta,
    revoked: bool,
    setpoint: Decimal = Decimal("21.0"),
) -> None:
    """Direkter Insert (umgeht die Create-Gates — hier wird der Read-Aggregat
    getestet, nicht die Anlage)."""
    now = datetime.now(tz=UTC)
    async with sm() as session:
        session.add(
            ManualOverride(
                room_id=room_id,
                heating_zone_id=heating_zone_id,
                setpoint=setpoint,
                source=OverrideSource.FRONTEND_4H,
                expires_at=now + expires_in,
                revoked_at=now if revoked else None,
            )
        )
        await session.commit()


async def _cleanup(sm: async_sessionmaker[AsyncSession]) -> None:
    async with sm() as session:
        await session.execute(text("DELETE FROM room WHERE number LIKE 't14d-%'"))
        await session.execute(text("DELETE FROM room_type WHERE name LIKE 't14d-rt-%'"))
        await session.execute(
            text("""DELETE FROM "user" WHERE email LIKE 'd14d-%@test.example.com'""")
        )
        await session.commit()


async def test_get_rooms_with_active_override_semantics(setup_engine: AsyncEngine) -> None:
    sm = async_sessionmaker(setup_engine, expire_on_commit=False)
    s = uuid.uuid4().hex[:8]
    try:
        room_a, _ = await _mk_room(sm, f"{s}a", RoomStatus.OCCUPIED)  # room-scope aktiv
        room_b, _ = await _mk_room(sm, f"{s}b", RoomStatus.OCCUPIED)  # zone-scope aktiv
        room_c, _ = await _mk_room(sm, f"{s}c", RoomStatus.OCCUPIED)  # revoked
        room_d, _ = await _mk_room(sm, f"{s}d", RoomStatus.OCCUPIED)  # expired
        zone_b = await _mk_zone(sm, room_b, f"{s}b")
        await _mk_override(
            sm, room_a, heating_zone_id=None, expires_in=timedelta(hours=4), revoked=False
        )
        await _mk_override(
            sm, room_b, heating_zone_id=zone_b, expires_in=timedelta(hours=4), revoked=False
        )
        await _mk_override(
            sm, room_c, heating_zone_id=None, expires_in=timedelta(hours=4), revoked=True
        )
        await _mk_override(
            sm, room_d, heating_zone_id=None, expires_in=timedelta(hours=-1), revoked=False
        )

        async with sm() as session:
            result = await override_service.get_rooms_with_active_override(session)

        assert room_a in result, "room-scope-Override -> true"
        assert room_b in result, "zone-scope-Override -> true"
        assert room_c not in result, "revoked -> false"
        assert room_d not in result, "expired -> false"
    finally:
        await _cleanup(sm)


async def test_list_rooms_has_active_override_single_query(
    http_client: httpx.AsyncClient, setup_engine: AsyncEngine
) -> None:
    sm = async_sessionmaker(setup_engine, expire_on_commit=False)
    s = uuid.uuid4().hex[:8]
    try:
        await _login_admin(http_client, sm)
        room_on, _ = await _mk_room(sm, f"{s}on", RoomStatus.OCCUPIED)
        room_off, _ = await _mk_room(sm, f"{s}off", RoomStatus.OCCUPIED)
        await _mk_override(
            sm, room_on, heating_zone_id=None, expires_in=timedelta(hours=4), revoked=False
        )

        # R-D-Beleg: manual_override-Statements waehrend GET /rooms zaehlen.
        override_queries = {"n": 0}

        def _count(conn, cursor, statement, parameters, context, executemany):  # type: ignore[no-untyped-def]
            if "manual_override" in statement.lower():
                override_queries["n"] += 1

        event.listen(setup_engine.sync_engine, "before_cursor_execute", _count)
        try:
            resp = await http_client.get("/api/v1/rooms?limit=1000")
        finally:
            event.remove(setup_engine.sync_engine, "before_cursor_execute", _count)

        assert resp.status_code == 200, resp.text
        assert override_queries["n"] == 1, (
            f"erwarte genau 1 manual_override-Query (R-D), war {override_queries['n']}"
        )

        by_id = {r["id"]: r for r in resp.json()}
        assert by_id[room_on]["has_active_override"] is True
        assert by_id[room_off]["has_active_override"] is False
    finally:
        await _cleanup(sm)


async def test_heating_zone_read_active_override_roundtrip(
    http_client: httpx.AsyncClient, setup_engine: AsyncEngine
) -> None:
    sm = async_sessionmaker(setup_engine, expire_on_commit=False)
    s = uuid.uuid4().hex[:8]
    try:
        await _login_admin(http_client, sm)
        room_id, _ = await _mk_room(sm, s, RoomStatus.OCCUPIED)
        zone_with = await _mk_zone(sm, room_id, f"{s}w")
        zone_without = await _mk_zone(sm, room_id, f"{s}n")
        await _mk_override(
            sm,
            room_id,
            heating_zone_id=zone_with,
            expires_in=timedelta(hours=4),
            revoked=False,
            setpoint=Decimal("22.5"),
        )

        resp = await http_client.get(f"/api/v1/rooms/{room_id}/heating-zones")
        assert resp.status_code == 200, resp.text
        by_id = {z["id"]: z for z in resp.json()}

        ov = by_id[zone_with]["active_override"]
        assert ov is not None
        assert ov["setpoint_celsius"] == 22.5  # field_serializer -> JSON-Zahl
        assert ov["source"] == "frontend_4h"
        assert ov["expires_at"] is not None
        assert by_id[zone_without]["active_override"] is None
    finally:
        await _cleanup(sm)
