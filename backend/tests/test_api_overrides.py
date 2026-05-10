"""Sprint 9.9 T4 - REST-API-Tests fuer Manual-Override.

httpx.AsyncClient mit ASGITransport gegen die echte App. Setup-Daten
ueber eine SEPARATE async engine (eigener Pool) - so kollidieren die
asyncpg-Connections der Setup-Sessions nicht mit denen, die der
Endpoint via App-eigenem ``SessionLocal`` zieht.

Migration via ``alembic.command.upgrade`` in ``asyncio.to_thread``,
weil alembic env.py intern ``asyncio.run`` aufruft - das wuerde im
laufenden pytest-asyncio-Loop ``loop already running`` werfen.

Skip lokal, wenn ``DATABASE_URL`` nicht gesetzt ist.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest
import pytest_asyncio
from alembic.config import Config
from httpx import ASGITransport
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from alembic import command
from heizung.db import get_session
from heizung.main import app
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
    """Async engine fuer Setup + dependency_override. Pro Test ein eigener
    Pool, alle Connections im aktuellen pytest-asyncio-Loop -> kein
    "another operation in progress" und kein "different loop"."""
    if not DATABASE_URL_PRESENT:
        pytest.skip(SKIP_REASON)
    engine = create_async_engine(DATABASE_URL or "")
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def http_client(setup_engine: AsyncEngine) -> AsyncIterator[httpx.AsyncClient]:
    """AsyncClient + dependency_override: App nutzt dieselbe engine wie das
    Test-Setup, damit beide Pools im gleichen Loop laufen."""
    sessionmaker = async_sessionmaker(setup_engine, expire_on_commit=False)

    async def _override_get_session() -> AsyncIterator:
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
    sessionmaker = async_sessionmaker(setup_engine, expire_on_commit=False)
    # ``room.number`` ist VARCHAR(20). Kompaktes prefix + 12-stelliges suffix
    # passt sicher rein (4 + 12 = 16 chars).
    suffix = datetime.now(tz=UTC).strftime("%H%M%S%f")
    async with sessionmaker() as session:
        rt = RoomType(name=f"t99api-{suffix}")
        session.add(rt)
        await session.flush()
        room = Room(number=f"t99-{suffix}", room_type_id=rt.id)
        session.add(room)
        await session.commit()
        rid, rt_id = room.id, rt.id

    try:
        yield rid
    finally:
        async with sessionmaker() as session:
            await session.execute(
                text("DELETE FROM manual_override WHERE room_id = :r"),
                {"r": rid},
            )
            await session.execute(text("DELETE FROM occupancy WHERE room_id = :r"), {"r": rid})
            await session.execute(text("DELETE FROM room WHERE id = :r"), {"r": rid})
            await session.execute(text("DELETE FROM room_type WHERE id = :r"), {"r": rt_id})
            await session.commit()


# ---------------------------------------------------------------------------
# POST /rooms/{room_id}/overrides
# ---------------------------------------------------------------------------


async def test_post_frontend_4h_returns_201(http_client: httpx.AsyncClient, room_id: int) -> None:
    before = datetime.now(tz=UTC)
    resp = await http_client.post(
        f"/api/v1/rooms/{room_id}/overrides",
        json={"setpoint": "22", "source": "frontend_4h", "reason": "API-Test"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["room_id"] == room_id
    assert body["source"] == "frontend_4h"
    assert Decimal(body["setpoint"]) == Decimal("22")
    expires = datetime.fromisoformat(body["expires_at"])
    delta = expires - before
    assert timedelta(hours=3, minutes=55) < delta < timedelta(hours=4, minutes=5)


async def test_post_frontend_checkout_without_occupancy_returns_422(
    http_client: httpx.AsyncClient, room_id: int
) -> None:
    resp = await http_client.post(
        f"/api/v1/rooms/{room_id}/overrides",
        json={"setpoint": "22.0", "source": "frontend_checkout"},
    )
    assert resp.status_code == 422, resp.text


async def test_post_setpoint_above_max_returns_422(http_client: httpx.AsyncClient) -> None:
    resp = await http_client.post(
        "/api/v1/rooms/1/overrides",
        json={"setpoint": "35.0", "source": "frontend_4h"},
    )
    assert resp.status_code == 422, resp.text


async def test_post_source_device_returns_422(http_client: httpx.AsyncClient) -> None:
    resp = await http_client.post(
        "/api/v1/rooms/1/overrides",
        json={"setpoint": "22.0", "source": "device"},
    )
    assert resp.status_code == 422, resp.text


async def test_post_unknown_room_returns_404(http_client: httpx.AsyncClient) -> None:
    resp = await http_client.post(
        "/api/v1/rooms/9999999/overrides",
        json={"setpoint": "22.0", "source": "frontend_4h"},
    )
    assert resp.status_code == 404, resp.text


# ---------------------------------------------------------------------------
# GET /rooms/{room_id}/overrides
# ---------------------------------------------------------------------------


async def test_get_history_includes_revoked(http_client: httpx.AsyncClient, room_id: int) -> None:
    create_resp = await http_client.post(
        f"/api/v1/rooms/{room_id}/overrides",
        json={"setpoint": "22.0", "source": "frontend_4h"},
    )
    assert create_resp.status_code == 201
    override_id = create_resp.json()["id"]
    revoke_resp = await http_client.request(
        "DELETE",
        f"/api/v1/overrides/{override_id}",
        json={"revoked_reason": "test cleanup"},
    )
    assert revoke_resp.status_code == 200

    list_resp = await http_client.get(f"/api/v1/rooms/{room_id}/overrides")
    assert list_resp.status_code == 200
    items = list_resp.json()
    assert len(items) >= 1
    assert any(item["id"] == override_id and item["revoked_at"] is not None for item in items)


# ---------------------------------------------------------------------------
# DELETE /overrides/{override_id}
# ---------------------------------------------------------------------------


async def test_delete_then_double_revoke_returns_409(
    http_client: httpx.AsyncClient, room_id: int
) -> None:
    create_resp = await http_client.post(
        f"/api/v1/rooms/{room_id}/overrides",
        json={"setpoint": "22.0", "source": "frontend_4h"},
    )
    override_id = create_resp.json()["id"]

    first = await http_client.request(
        "DELETE",
        f"/api/v1/overrides/{override_id}",
        json={"revoked_reason": "erstmal"},
    )
    assert first.status_code == 200, first.text
    assert first.json()["revoked_at"] is not None

    second = await http_client.request(
        "DELETE",
        f"/api/v1/overrides/{override_id}",
        json={"revoked_reason": "zweites mal"},
    )
    assert second.status_code == 409, second.text


async def test_delete_unknown_override_returns_404(http_client: httpx.AsyncClient) -> None:
    resp = await http_client.request("DELETE", "/api/v1/overrides/9999999")
    assert resp.status_code == 404, resp.text


# ---------------------------------------------------------------------------
# Sprint 9.9a Hotfix - Engine-Re-Eval-Trigger + Integer-Setpoint
# ---------------------------------------------------------------------------


async def test_post_triggers_evaluate_room(http_client: httpx.AsyncClient, room_id: int) -> None:
    """A1: POST muss ``evaluate_room.delay(room_id)`` triggern (analog
    zu occupancies, AE-07)."""
    with patch("heizung.api.v1.overrides._evaluate_room_task") as mock_task:
        resp = await http_client.post(
            f"/api/v1/rooms/{room_id}/overrides",
            json={"setpoint": "22", "source": "frontend_4h"},
        )
        assert resp.status_code == 201, resp.text
        mock_task.delay.assert_called_once_with(room_id)


async def test_delete_triggers_evaluate_room(http_client: httpx.AsyncClient, room_id: int) -> None:
    """A1: DELETE muss ebenfalls ``evaluate_room.delay`` triggern."""
    create_resp = await http_client.post(
        f"/api/v1/rooms/{room_id}/overrides",
        json={"setpoint": "22", "source": "frontend_4h"},
    )
    override_id = create_resp.json()["id"]

    with patch("heizung.api.v1.overrides._evaluate_room_task") as mock_task:
        resp = await http_client.request("DELETE", f"/api/v1/overrides/{override_id}")
        assert resp.status_code == 200, resp.text
        mock_task.delay.assert_called_once_with(room_id)


async def test_post_setpoint_with_half_step_returns_422(
    http_client: httpx.AsyncClient, room_id: int
) -> None:
    """A2: API akzeptiert nur ganze Grad - sonst Diskrepanz UI vs.
    Engine-Trace (rules.engine._quantize rundet auf int)."""
    resp = await http_client.post(
        f"/api/v1/rooms/{room_id}/overrides",
        json={"setpoint": "22.5", "source": "frontend_4h"},
    )
    assert resp.status_code == 422, resp.text
    assert "ganzen °C-Schritten" in resp.text
