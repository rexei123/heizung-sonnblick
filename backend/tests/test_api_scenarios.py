"""Sprint 9.16 T10 - API-Tests fuer scenarios (GET / activate / deactivate).

Folgt der DB-Skip-Konvention von ``test_api_rule_configs``.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from alembic.config import Config
from httpx import ASGITransport
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from alembic import command
from heizung.db import get_session
from heizung.main import app
from heizung.models.config_audit import ConfigAudit
from heizung.models.enums import ScenarioScope
from heizung.models.scenario import Scenario
from heizung.models.scenario_assignment import ScenarioAssignment

DATABASE_URL = os.environ.get("DATABASE_URL")
DATABASE_URL_PRESENT = bool(DATABASE_URL)
SKIP_REASON = "DATABASE_URL nicht gesetzt - API-Tests brauchen Test-DB"

SUMMER_CODE = "summer_mode"


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


@pytest_asyncio.fixture
async def clean_state(setup_engine: AsyncEngine) -> AsyncIterator[None]:
    """Setzt summer_mode-Assignment + config_audit fuer rule_config /
    global_config / scenario_assignment auf einen sauberen Stand. Cleanup
    danach analog."""
    sessionmaker = async_sessionmaker(setup_engine, expire_on_commit=False)

    async def _clear() -> None:
        async with sessionmaker() as session:
            await session.execute(
                text("DELETE FROM config_audit WHERE table_name = 'scenario_assignment'")
            )
            await session.execute(
                text(
                    "DELETE FROM scenario_assignment "
                    "WHERE scenario_id IN ("
                    "  SELECT id FROM scenario WHERE code = :c"
                    ")"
                ),
                {"c": SUMMER_CODE},
            )
            await session.commit()

    await _clear()
    try:
        yield
    finally:
        await _clear()


# ---------------------------------------------------------------------------
# GET /api/v1/scenarios
# ---------------------------------------------------------------------------


async def test_list_scenarios_shows_summer_mode_inactive_by_default(
    http_client: httpx.AsyncClient, clean_state: None
) -> None:
    resp = await http_client.get("/api/v1/scenarios")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    summer = next((s for s in body if s["code"] == SUMMER_CODE), None)
    assert summer is not None, f"summer_mode nicht gefunden in {body}"
    assert summer["current_global_assignment_active"] is False


# ---------------------------------------------------------------------------
# POST /activate
# ---------------------------------------------------------------------------


async def test_activate_endpoint_creates_global_assignment(
    http_client: httpx.AsyncClient, setup_engine: AsyncEngine, clean_state: None
) -> None:
    resp = await http_client.post(
        f"/api/v1/scenarios/{SUMMER_CODE}/activate",
        json={"scope": "global"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["current_global_assignment_active"] is True

    sessionmaker = async_sessionmaker(setup_engine, expire_on_commit=False)
    async with sessionmaker() as session:
        rows = list(
            (
                await session.execute(
                    select(ScenarioAssignment)
                    .join(Scenario, Scenario.id == ScenarioAssignment.scenario_id)
                    .where(Scenario.code == SUMMER_CODE)
                    .where(ScenarioAssignment.scope == ScenarioScope.GLOBAL)
                )
            )
            .scalars()
            .all()
        )
    assert len(rows) == 1
    assert rows[0].is_active is True


async def test_activate_endpoint_idempotent(
    http_client: httpx.AsyncClient, setup_engine: AsyncEngine, clean_state: None
) -> None:
    for _ in range(3):
        resp = await http_client.post(
            f"/api/v1/scenarios/{SUMMER_CODE}/activate",
            json={"scope": "global"},
        )
        assert resp.status_code == 200, resp.text

    sessionmaker = async_sessionmaker(setup_engine, expire_on_commit=False)
    async with sessionmaker() as session:
        count = (
            await session.execute(
                select(ScenarioAssignment)
                .join(Scenario, Scenario.id == ScenarioAssignment.scenario_id)
                .where(Scenario.code == SUMMER_CODE)
                .where(ScenarioAssignment.scope == ScenarioScope.GLOBAL)
            )
        ).all()
    assert len(count) == 1, "Doppel-Aktivierung haette zweite Row angelegt"


async def test_activate_writes_config_audit(
    http_client: httpx.AsyncClient, setup_engine: AsyncEngine, clean_state: None
) -> None:
    resp = await http_client.post(
        f"/api/v1/scenarios/{SUMMER_CODE}/activate",
        json={"scope": "global"},
    )
    assert resp.status_code == 200, resp.text

    sessionmaker = async_sessionmaker(setup_engine, expire_on_commit=False)
    async with sessionmaker() as session:
        audits = list(
            (
                await session.execute(
                    select(ConfigAudit)
                    .where(ConfigAudit.table_name == "scenario_assignment")
                    .order_by(ConfigAudit.id)
                )
            )
            .scalars()
            .all()
        )
    assert len(audits) == 1
    a = audits[0]
    assert a.source == "api"
    assert a.scope_qualifier == "global"
    assert a.column_name == "is_active"
    assert a.new_value == {"scenario_code": SUMMER_CODE, "scope": "global", "is_active": True}
    assert a.old_value == {
        "scenario_code": SUMMER_CODE,
        "scope": "global",
        "is_active": False,
    }


# ---------------------------------------------------------------------------
# POST /deactivate
# ---------------------------------------------------------------------------


async def test_deactivate_writes_config_audit(
    http_client: httpx.AsyncClient, setup_engine: AsyncEngine, clean_state: None
) -> None:
    await http_client.post(
        f"/api/v1/scenarios/{SUMMER_CODE}/activate",
        json={"scope": "global"},
    )
    resp = await http_client.post(
        f"/api/v1/scenarios/{SUMMER_CODE}/deactivate",
        json={"scope": "global"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["current_global_assignment_active"] is False

    sessionmaker = async_sessionmaker(setup_engine, expire_on_commit=False)
    async with sessionmaker() as session:
        audits = list(
            (
                await session.execute(
                    select(ConfigAudit)
                    .where(ConfigAudit.table_name == "scenario_assignment")
                    .order_by(ConfigAudit.id)
                )
            )
            .scalars()
            .all()
        )
    assert len(audits) == 2  # activate + deactivate
    deactivate_audit = audits[-1]
    assert deactivate_audit.new_value["is_active"] is False
    assert deactivate_audit.old_value["is_active"] is True


# ---------------------------------------------------------------------------
# Scope-Beschraenkung
# ---------------------------------------------------------------------------


async def test_non_global_scope_returns_4xx(
    http_client: httpx.AsyncClient, clean_state: None
) -> None:
    # Pydantic Literal['global'] lehnt 'room_type' direkt mit 422 ab.
    resp = await http_client.post(
        f"/api/v1/scenarios/{SUMMER_CODE}/activate",
        json={"scope": "room_type"},
    )
    assert resp.status_code in (400, 422), resp.text
    assert "scope" in resp.text.lower()


async def test_unknown_scenario_returns_404(
    http_client: httpx.AsyncClient, clean_state: None
) -> None:
    resp = await http_client.post(
        "/api/v1/scenarios/does_not_exist/activate",
        json={"scope": "global"},
    )
    assert resp.status_code == 404, resp.text
