"""Sprint 9.14 T6 - API-Tests fuer rule_configs (GET/PATCH global) +
config_audit-Integration + Engine-Read-Verifikation.

Folgt der DB-Skip-Konvention von ``test_api_device_zone``: separate
async engine fuer Setup, dependency_override teilt diese engine mit der App.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncIterator
from datetime import time
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from alembic.config import Config
from httpx import ASGITransport
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from alembic import command
from heizung.db import get_session
from heizung.main import app
from heizung.models.config_audit import ConfigAudit
from heizung.models.enums import RuleConfigScope
from heizung.models.rule_config import RuleConfig

DATABASE_URL = os.environ.get("DATABASE_URL")
DATABASE_URL_PRESENT = bool(DATABASE_URL)
SKIP_REASON = "DATABASE_URL nicht gesetzt - API-Tests brauchen Test-DB"


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
async def global_rule_config(setup_engine: AsyncEngine) -> AsyncIterator[int]:
    """Stellt sicher, dass exactly EINE scope=global rule_config-Row
    existiert. Cleanup: alle config_audit-Eintraege fuer diesen Test
    wieder entfernen (Singleton-Row bleibt).

    Wenn die Row schon existiert (echtes DB-Setup nach Seed): wir nehmen
    sie und setzen sie nach dem Test auf den Vor-Test-Stand zurueck.
    """
    sessionmaker = async_sessionmaker(setup_engine, expire_on_commit=False)
    async with sessionmaker() as session:
        stmt = (
            select(RuleConfig)
            .where(RuleConfig.scope == RuleConfigScope.GLOBAL)
            .where(RuleConfig.room_type_id.is_(None))
            .where(RuleConfig.room_id.is_(None))
            .where(RuleConfig.season_id.is_(None))
        )
        rc = (await session.execute(stmt)).scalar_one_or_none()
        if rc is None:
            rc = RuleConfig(
                scope=RuleConfigScope.GLOBAL,
                t_occupied=Decimal("21.0"),
                t_vacant=Decimal("18.0"),
                t_night=Decimal("19.0"),
                night_start=time(0, 0),
                night_end=time(6, 0),
                preheat_minutes_before_checkin=90,
            )
            session.add(rc)
            await session.commit()
            await session.refresh(rc)
            created_here = True
        else:
            created_here = False
        rc_id = rc.id
        snapshot = {
            "t_occupied": rc.t_occupied,
            "t_vacant": rc.t_vacant,
            "t_night": rc.t_night,
            "night_start": rc.night_start,
            "night_end": rc.night_end,
            "preheat_minutes_before_checkin": rc.preheat_minutes_before_checkin,
        }

    try:
        yield rc_id
    finally:
        async with sessionmaker() as session:
            await session.execute(
                text(
                    "DELETE FROM config_audit WHERE table_name IN ('rule_config', 'global_config')"
                )
            )
            if created_here:
                await session.execute(text("DELETE FROM rule_config WHERE id = :i"), {"i": rc_id})
            else:
                rc = await session.get(RuleConfig, rc_id)
                if rc is not None:
                    for field, value in snapshot.items():
                        setattr(rc, field, value)
            await session.commit()


# ---------------------------------------------------------------------------
# GET /api/v1/rule-configs/global
# ---------------------------------------------------------------------------


async def test_get_global_returns_six_fields(
    http_client: httpx.AsyncClient, global_rule_config: int
) -> None:
    resp = await http_client.get("/api/v1/rule-configs/global")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    expected_keys = {
        "id",
        "t_occupied",
        "t_vacant",
        "t_night",
        "night_start",
        "night_end",
        "preheat_minutes_before_checkin",
        "created_at",
        "updated_at",
    }
    assert set(body.keys()) == expected_keys


# ---------------------------------------------------------------------------
# Test 1 — Validierung Temperatur-Range
# ---------------------------------------------------------------------------


async def test_rule_config_patch_validates_temp_range(
    http_client: httpx.AsyncClient, global_rule_config: int
) -> None:
    # t_occupied range 16.0–26.0; 30 ist drueber
    resp = await http_client.patch("/api/v1/rule-configs/global", json={"t_occupied": "30.0"})
    assert resp.status_code == 422, resp.text

    # 12 ist unter t_vacant (10.0–22.0)? 12 ist OK fuer t_vacant aber unter
    # t_occupied-Range. Hier explizit unter t_occupied-Untergrenze 16:
    resp = await http_client.patch("/api/v1/rule-configs/global", json={"t_occupied": "12.0"})
    assert resp.status_code == 422, resp.text

    # Innerhalb: 21 ist OK
    resp = await http_client.patch("/api/v1/rule-configs/global", json={"t_occupied": "21.5"})
    assert resp.status_code == 200, resp.text


# ---------------------------------------------------------------------------
# Test 2 — config_audit pro geaendertem Feld
# ---------------------------------------------------------------------------


async def test_rule_config_patch_writes_config_audit_per_field(
    http_client: httpx.AsyncClient,
    setup_engine: AsyncEngine,
    global_rule_config: int,
) -> None:
    resp = await http_client.patch(
        "/api/v1/rule-configs/global",
        json={
            "t_occupied": "22.0",
            "preheat_minutes_before_checkin": 120,
        },
    )
    assert resp.status_code == 200, resp.text

    sessionmaker = async_sessionmaker(setup_engine, expire_on_commit=False)
    async with sessionmaker() as session:
        rows = (
            (
                await session.execute(
                    select(ConfigAudit)
                    .where(ConfigAudit.table_name == "rule_config")
                    .where(ConfigAudit.scope_qualifier == "global")
                    .order_by(ConfigAudit.column_name)
                )
            )
            .scalars()
            .all()
        )

    columns = [r.column_name for r in rows]
    assert columns == ["preheat_minutes_before_checkin", "t_occupied"]
    by_col = {r.column_name: r for r in rows}
    assert by_col["t_occupied"].new_value == "22.0"
    assert by_col["preheat_minutes_before_checkin"].new_value == 120
    # source-Marker
    for r in rows:
        assert r.source == "api"


# ---------------------------------------------------------------------------
# Test 3 — Decimal-Praezision (kein Float)
# ---------------------------------------------------------------------------


async def test_rule_config_patch_decimal_not_float(
    http_client: httpx.AsyncClient,
    setup_engine: AsyncEngine,
    global_rule_config: int,
) -> None:
    # Schicken Dezimal-Wert mit einem Nachkomma. Wenn der Pfad Float
    # waere, koennte 21.1 als 21.10000000000... gespeichert werden.
    resp = await http_client.patch("/api/v1/rule-configs/global", json={"t_occupied": "21.1"})
    assert resp.status_code == 200, resp.text

    sessionmaker = async_sessionmaker(setup_engine, expire_on_commit=False)
    async with sessionmaker() as session:
        rc = await session.get(RuleConfig, global_rule_config)
    assert rc is not None
    # DB-Wert ist Decimal (Numeric(4,1)) und exakt 21.1
    assert rc.t_occupied == Decimal("21.1")
    # Audit-Spalte ist JSONB-string mit exakter Dezimal-Repraesentation
    async with sessionmaker() as session:
        audit = (
            await session.execute(
                select(ConfigAudit).where(ConfigAudit.column_name == "t_occupied")
            )
        ).scalar_one()
    assert audit.new_value == "21.1"
    assert not isinstance(audit.new_value, float)


# ---------------------------------------------------------------------------
# Test 4 — Nachtfenster-Validierung
# ---------------------------------------------------------------------------


async def test_rule_config_patch_night_window_validation(
    http_client: httpx.AsyncClient, global_rule_config: int
) -> None:
    # Beide gleich -> 422 (Nullfenster)
    resp = await http_client.patch(
        "/api/v1/rule-configs/global",
        json={"night_start": "22:00:00", "night_end": "22:00:00"},
    )
    assert resp.status_code == 422, resp.text

    # Wrap ueber Mitternacht ist erlaubt
    resp = await http_client.patch(
        "/api/v1/rule-configs/global",
        json={"night_start": "22:00:00", "night_end": "06:00:00"},
    )
    assert resp.status_code == 200, resp.text


# ---------------------------------------------------------------------------
# Test 5 — Engine liest den neuen Wert nach PATCH (kein Cache)
# ---------------------------------------------------------------------------


async def test_engine_reads_updated_value_after_patch(
    http_client: httpx.AsyncClient,
    setup_engine: AsyncEngine,
    global_rule_config: int,
) -> None:
    """Verifiziert AE-46: Engine hat keinen Cache, ein PATCH wirkt beim
    naechsten Read auf die Hierarchie. Wir umgehen den Beat-Tick und
    lesen die Hierarchie direkt via ``_resolve_field`` mit dem
    aktualisierten ``_RoomContext``.
    """
    from heizung.rules.engine import _resolve_field, _RoomContext

    suffix = uuid.uuid4().hex[:8]

    # PATCH den globalen Wert.
    resp = await http_client.patch("/api/v1/rule-configs/global", json={"t_occupied": "23.0"})
    assert resp.status_code == 200, resp.text

    # RuleConfigs frisch aus der DB laden — wie Engine es per
    # _load_room_context im Beat-Tick tut.
    sessionmaker = async_sessionmaker(setup_engine, expire_on_commit=False)
    async with sessionmaker() as session:
        rcs = list(
            (
                await session.execute(
                    select(RuleConfig).where(RuleConfig.scope == RuleConfigScope.GLOBAL)
                )
            )
            .scalars()
            .all()
        )

    # Wir brauchen einen _RoomContext-Stub fuer _resolve_field; Room und
    # RoomType sind irrelevant fuer diesen Hierarchie-Lookup.
    ctx = _RoomContext(
        room=None,  # type: ignore[arg-type]
        room_type=None,  # type: ignore[arg-type]
        rule_configs=rcs,
    )
    value = _resolve_field("t_occupied", ctx)
    assert value == Decimal("23.0"), f"expected 23.0, got {value!r} (suffix={suffix})"
