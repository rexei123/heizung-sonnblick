"""Sprint 15e (AE-66) — API-Tests fuer die Integrations-Endpoints.

Endpoint A (POST occupancy-import, X-Webhook-Token) + Endpoint B
(GET .../log, Login-Session). Skip ohne ``DATABASE_URL``.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from alembic.config import Config
from httpx import ASGITransport
from sqlalchemy import and_, select, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from alembic import command
from heizung.config import get_settings
from heizung.db import get_session
from heizung.main import app
from heizung.models.enums import OccupancySource, RoomStatus
from heizung.models.occupancy import Occupancy
from heizung.models.room import Room
from heizung.models.room_type import RoomType
from tests.conftest import purge_test_data_by_prefix

DATABASE_URL = os.environ.get("DATABASE_URL")
DATABASE_URL_PRESENT = bool(DATABASE_URL)
SKIP_REASON = "DATABASE_URL nicht gesetzt - API-Tests brauchen Test-DB"
PREFIX = "t15e"
TOKEN = "test-webhook-secret-0123456789abcdef"


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setenv("ALLOW_DEFAULT_SECRETS", "1")
    monkeypatch.setenv("OCCUPANCY_IMPORT_TOKEN", TOKEN)
    # Engine-Trigger nicht real abfeuern (kein Redis/Worker im Test).
    monkeypatch.setattr(
        "heizung.api.v1.integrations._evaluate_room_task.delay", lambda *a, **k: None
    )
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


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
async def http_client(engine: AsyncEngine) -> AsyncIterator[httpx.AsyncClient]:
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)

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


@pytest_asyncio.fixture(autouse=True)
async def _isolate(engine: AsyncEngine) -> AsyncIterator[None]:
    async def _wipe() -> None:
        sm = async_sessionmaker(engine, expire_on_commit=False)
        async with sm() as s:
            await s.execute(
                text("DELETE FROM business_audit WHERE action LIKE 'OCCUPANCY_IMPORT%'")
            )
            await s.commit()
            await purge_test_data_by_prefix(s, PREFIX)

    await _wipe()
    yield
    await _wipe()


async def _seed_room(engine: AsyncEngine, number: str) -> int:
    sm = async_sessionmaker(engine, expire_on_commit=False)
    async with sm() as s:
        rt = RoomType(name=f"{PREFIX}-{uuid.uuid4().hex[:8]}")
        s.add(rt)
        await s.flush()
        room = Room(number=number, room_type_id=rt.id, status=RoomStatus.VACANT)
        s.add(room)
        await s.flush()
        room_id = room.id
        await s.commit()
    return room_id


async def _count_active_pms(engine: AsyncEngine, room_id: int) -> int:
    sm = async_sessionmaker(engine, expire_on_commit=False)
    async with sm() as s:
        rows = (
            await s.execute(
                select(Occupancy.id).where(
                    and_(
                        Occupancy.room_id == room_id,
                        Occupancy.is_active.is_(True),
                        Occupancy.source == OccupancySource.PMS,
                    )
                )
            )
        ).all()
    return len(rows)


def _body(number: str) -> dict[str, object]:
    return {
        "id": uuid.uuid4().hex,
        "received_at": "2026-06-06 07:14:15",
        "liste": [
            {
                "Zimmer": number,
                "Anreise": "04.06.2026",
                "Abreise": "06.06.2026",
                "Aufenthaltstyp": "Abreise",
            }
        ],
    }


async def test_import_with_valid_token_applies(
    http_client: httpx.AsyncClient, engine: AsyncEngine
) -> None:
    number = f"{PREFIX}-{uuid.uuid4().hex[:6]}-101"
    room_id = await _seed_room(engine, number)

    resp = await http_client.post(
        "/api/v1/integrations/occupancy-import",
        json=_body(number),
        headers={"X-Webhook-Token": TOKEN},
    )

    assert resp.status_code == 200
    assert resp.json()["status"] == "applied"
    assert await _count_active_pms(engine, room_id) == 1


async def test_import_missing_token_401(http_client: httpx.AsyncClient) -> None:
    resp = await http_client.post("/api/v1/integrations/occupancy-import", json=_body("t15e-x-1"))
    assert resp.status_code == 401


async def test_import_wrong_token_401(http_client: httpx.AsyncClient) -> None:
    resp = await http_client.post(
        "/api/v1/integrations/occupancy-import",
        json=_body("t15e-x-1"),
        headers={"X-Webhook-Token": "falsch"},
    )
    assert resp.status_code == 401


async def test_import_unknown_room_422(http_client: httpx.AsyncClient) -> None:
    body = _body("t15e-does-not-exist-999")
    resp = await http_client.post(
        "/api/v1/integrations/occupancy-import",
        json=body,
        headers={"X-Webhook-Token": TOKEN},
    )
    assert resp.status_code == 422


async def test_log_endpoint_returns_shape(
    http_client: httpx.AsyncClient, engine: AsyncEngine
) -> None:
    # AUTH_ENABLED default false -> require_user faellt auf System-Admin zurueck.
    number = f"{PREFIX}-{uuid.uuid4().hex[:6]}-101"
    await _seed_room(engine, number)
    await http_client.post(
        "/api/v1/integrations/occupancy-import",
        json=_body(number),
        headers={"X-Webhook-Token": TOKEN},
    )

    resp = await http_client.get("/api/v1/integrations/occupancy-import/log")
    assert resp.status_code == 200
    data = resp.json()
    assert set(data) == {
        "status",
        "last_success_at",
        "expected_by_local",
        "today_received",
        "imports",
    }
    assert data["status"] in {"green", "yellow", "red"}
    assert len(data["imports"]) >= 1
    assert data["imports"][0]["result"] == "applied"


async def test_log_endpoint_without_login_401(
    http_client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AUTH_ENABLED", "true")
    get_settings.cache_clear()
    resp = await http_client.get("/api/v1/integrations/occupancy-import/log")
    assert resp.status_code == 401
