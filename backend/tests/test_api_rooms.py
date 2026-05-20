"""Sprint 12c - REST-API-Tests fuer PATCH /rooms/{id}/override-block-state.

Pattern-Spiegel zu ``test_api_overrides.py``: dedizierter setup_engine,
``alembic upgrade head`` im Thread (env.py-asyncio-Konflikt), Room-Fixture
ohne Belegung (Toggle-State haengt nicht an OCCUPIED-Gate, daher VACANT
ausreichend).

Brief: Sprint 12c T5.2 — fuenf Cases:
- Toggle-On revoked aktive Overrides + schreibt Audit mit Count
- Toggle-Off laesst Overrides unangetastet
- Idempotenz (old == new) -> kein Audit, kein Revoke
- ``require_mitarbeiter``-Dependency-Wiring (via dependency_override
  validiert, weil ``AUTH_ENABLED=false`` im Test-Env auf System-Admin
  faellt)
- 404 fuer unbekannten Raum
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from alembic.config import Config
from fastapi import HTTPException, status
from httpx import ASGITransport
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from alembic import command
from heizung.auth.dependencies import require_mitarbeiter
from heizung.db import get_session
from heizung.main import app
from heizung.models.business_audit import BusinessAudit
from heizung.models.enums import OverrideSource
from heizung.models.manual_override import ManualOverride
from heizung.models.room import Room
from heizung.models.room_type import RoomType

DATABASE_URL = os.environ.get("DATABASE_URL")
DATABASE_URL_PRESENT = bool(DATABASE_URL)
SKIP_REASON = "DATABASE_URL nicht gesetzt - API-Tests brauchen Test-DB"


@pytest_asyncio.fixture(scope="module", autouse=True)
async def _migrate_db() -> None:
    """``alembic upgrade head`` im Thread, einmal pro Modul."""
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


@pytest_asyncio.fixture
async def room_id(setup_engine: AsyncEngine) -> AsyncIterator[int]:
    """Room ohne Belegung — ausreichend fuer Toggle-State-Tests.

    Block-Toggle ist unabhaengig vom OCCUPIED-Gate. Wir brauchen nur
    einen Raum mit ``guest_override_blocked=False`` (Default).
    """
    sessionmaker = async_sessionmaker(setup_engine, expire_on_commit=False)
    suffix = datetime.now(tz=UTC).strftime("%H%M%S%f")
    async with sessionmaker() as session:
        rt = RoomType(name=f"t12c-{suffix}")
        session.add(rt)
        await session.flush()
        room = Room(number=f"t12c-{suffix}", room_type_id=rt.id)
        session.add(room)
        await session.commit()
        rid, rt_id = room.id, rt.id

    try:
        yield rid
    finally:
        async with sessionmaker() as session:
            await session.execute(
                text("DELETE FROM business_audit WHERE target_type='room' AND target_id=:r"),
                {"r": rid},
            )
            await session.execute(
                text("DELETE FROM manual_override WHERE room_id = :r"),
                {"r": rid},
            )
            await session.execute(text("DELETE FROM room WHERE id = :r"), {"r": rid})
            await session.execute(text("DELETE FROM room_type WHERE id = :r"), {"r": rt_id})
            await session.commit()


async def _seed_active_overrides(
    setup_engine: AsyncEngine, *, room_id: int, count: int
) -> list[int]:
    """Legt ``count`` aktive Overrides direkt via ORM an — umgeht das
    OCCUPIED-Gate aus ``override_service.create`` (Raum ist VACANT)."""
    sessionmaker = async_sessionmaker(setup_engine, expire_on_commit=False)
    now = datetime.now(tz=UTC)
    expires = now + timedelta(hours=4)
    ids: list[int] = []
    async with sessionmaker() as session:
        for _ in range(count):
            ov = ManualOverride(
                room_id=room_id,
                setpoint=22,
                source=OverrideSource.FRONTEND_4H,
                expires_at=expires,
                reason="seed",
            )
            session.add(ov)
            await session.flush()
            ids.append(ov.id)
        await session.commit()
    return ids


# ---------------------------------------------------------------------------
# PATCH /rooms/{room_id}/override-block-state
# ---------------------------------------------------------------------------


async def test_patch_override_block_state_toggle_on_revokes_active_overrides(
    http_client: httpx.AsyncClient,
    setup_engine: AsyncEngine,
    room_id: int,
) -> None:
    """Toggle-On (False -> True): alle aktiven Overrides werden revoked,
    Audit-Eintrag enthaelt revoked_overrides_count=2."""
    override_ids = await _seed_active_overrides(setup_engine, room_id=room_id, count=2)

    resp = await http_client.patch(
        f"/api/v1/rooms/{room_id}/override-block-state",
        json={"blocked": True},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["guest_override_blocked"] is True
    assert body["id"] == room_id

    sessionmaker = async_sessionmaker(setup_engine, expire_on_commit=False)
    async with sessionmaker() as session:
        # Beide Overrides revoked mit Sprint-12c-Reason
        rows = list(
            (
                await session.execute(
                    select(ManualOverride).where(ManualOverride.id.in_(override_ids))
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 2
        for ov in rows:
            assert ov.revoked_at is not None
            assert ov.revoked_reason == "room_override_blocked"

        # Audit-Eintrag mit revoked_overrides_count
        audits = list(
            (
                await session.execute(
                    select(BusinessAudit)
                    .where(BusinessAudit.target_type == "room")
                    .where(BusinessAudit.target_id == room_id)
                    .where(BusinessAudit.action == "ROOM_OVERRIDE_BLOCK_TOGGLED")
                )
            )
            .scalars()
            .all()
        )
        assert len(audits) == 1
        audit = audits[0]
        assert audit.old_value == {"blocked": False}
        assert audit.new_value == {"blocked": True, "revoked_overrides_count": 2}


async def test_patch_override_block_state_toggle_off_does_not_touch_overrides(
    http_client: httpx.AsyncClient,
    setup_engine: AsyncEngine,
    room_id: int,
) -> None:
    """Toggle-Off (True -> False): Override-Tabelle bleibt unangetastet."""
    sessionmaker = async_sessionmaker(setup_engine, expire_on_commit=False)
    async with sessionmaker() as session:
        room = await session.get(Room, room_id)
        assert room is not None
        room.guest_override_blocked = True
        await session.commit()

    override_ids = await _seed_active_overrides(setup_engine, room_id=room_id, count=1)

    resp = await http_client.patch(
        f"/api/v1/rooms/{room_id}/override-block-state",
        json={"blocked": False},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["guest_override_blocked"] is False

    async with sessionmaker() as session:
        ov = await session.get(ManualOverride, override_ids[0])
        assert ov is not None
        assert ov.revoked_at is None
        assert ov.revoked_reason is None

        audits = list(
            (
                await session.execute(
                    select(BusinessAudit)
                    .where(BusinessAudit.target_type == "room")
                    .where(BusinessAudit.target_id == room_id)
                    .where(BusinessAudit.action == "ROOM_OVERRIDE_BLOCK_TOGGLED")
                )
            )
            .scalars()
            .all()
        )
        assert len(audits) == 1
        assert audits[0].new_value == {"blocked": False, "revoked_overrides_count": 0}


async def test_patch_override_block_state_idempotent_no_audit(
    http_client: httpx.AsyncClient,
    setup_engine: AsyncEngine,
    room_id: int,
) -> None:
    """Idempotenz (§S2): old_blocked == new_blocked -> 200 ohne Audit,
    ohne Revoke."""
    override_ids = await _seed_active_overrides(setup_engine, room_id=room_id, count=1)

    # Default ist False, sende ebenfalls False
    resp = await http_client.patch(
        f"/api/v1/rooms/{room_id}/override-block-state",
        json={"blocked": False},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["guest_override_blocked"] is False

    sessionmaker = async_sessionmaker(setup_engine, expire_on_commit=False)
    async with sessionmaker() as session:
        ov = await session.get(ManualOverride, override_ids[0])
        assert ov is not None
        assert ov.revoked_at is None

        audits = list(
            (
                await session.execute(
                    select(BusinessAudit)
                    .where(BusinessAudit.target_type == "room")
                    .where(BusinessAudit.target_id == room_id)
                    .where(BusinessAudit.action == "ROOM_OVERRIDE_BLOCK_TOGGLED")
                )
            )
            .scalars()
            .all()
        )
        assert audits == []


async def test_patch_override_block_state_requires_mitarbeiter(
    http_client: httpx.AsyncClient,
    room_id: int,
) -> None:
    """Dependency-Wiring-Test: ``require_mitarbeiter`` ist tatsaechlich am
    Endpoint angeschlossen. ``AUTH_ENABLED=false`` im Test-Env faellt
    sonst auf System-Admin, daher kein realer Forbidden-Pfad. Wir
    overriden ``require_mitarbeiter`` mit einem 403-Raiser und pruefen,
    dass der Status sauber an den Client durchgereicht wird (was nur
    funktioniert, wenn der Endpoint exakt diese Dependency benutzt)."""

    def _forbidden() -> None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="forbidden by test",
        )

    app.dependency_overrides[require_mitarbeiter] = _forbidden
    try:
        resp = await http_client.patch(
            f"/api/v1/rooms/{room_id}/override-block-state",
            json={"blocked": True},
        )
    finally:
        del app.dependency_overrides[require_mitarbeiter]
    assert resp.status_code == 403, resp.text


async def test_patch_override_block_state_404_unknown_room(
    http_client: httpx.AsyncClient,
) -> None:
    """Unbekannte Room-ID -> 404."""
    resp = await http_client.patch(
        "/api/v1/rooms/999999/override-block-state",
        json={"blocked": True},
    )
    assert resp.status_code == 404, resp.text
