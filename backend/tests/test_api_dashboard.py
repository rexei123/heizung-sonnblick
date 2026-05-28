"""Sprint 14c T2 — API-Tests fuer ``GET /api/v1/dashboard/kpi``.

Prueft Auth (401 ohne Cookie, 200 fuer admin + mitarbeiter), Schema-
Konformitaet und dass der Lifecycle-Filter (``retired_at IS NULL``, §5.58)
durch den Endpoint wirkt (retired Device erhoeht ``devices_total`` nicht).

Skip lokal ohne ``DATABASE_URL`` (CI hat Postgres-Service).
"""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from alembic.config import Config
from httpx import ASGITransport
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
from heizung.models.device import Device
from heizung.models.enums import DeviceKind, DeviceVendor, UserRole
from heizung.models.user import User

DATABASE_URL = os.environ.get("DATABASE_URL")
DATABASE_URL_PRESENT = bool(DATABASE_URL)
SKIP_REASON = "DATABASE_URL nicht gesetzt - API-Tests brauchen Test-DB"

pytestmark = pytest.mark.asyncio

_EXPECTED_KEYS = {
    "rooms_occupied",
    "rooms_total",
    "avg_temperature_celsius",
    "devices_online",
    "devices_total",
    "active_overrides",
    "zones_window_open",
    "last_engine_tick",
}


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


@pytest_asyncio.fixture
async def users(setup_engine: AsyncEngine) -> AsyncIterator[dict[str, str]]:
    sessionmaker = async_sessionmaker(setup_engine, expire_on_commit=False)
    suffix = uuid.uuid4().hex[:8]
    admin_email = f"d-admin-{suffix}@test.example.com"
    emp_email = f"d-emp-{suffix}@test.example.com"
    pw = "DashboardPassword12345!"
    async with sessionmaker() as session:
        session.add_all(
            [
                User(
                    email=admin_email,
                    password_hash=hash_password(pw),
                    role=UserRole.ADMIN,
                    is_active=True,
                    must_change_password=False,
                ),
                User(
                    email=emp_email,
                    password_hash=hash_password(pw),
                    role=UserRole.MITARBEITER,
                    is_active=True,
                    must_change_password=False,
                ),
            ]
        )
        await session.commit()
    try:
        yield {"admin": admin_email, "mitarbeiter": emp_email, "password": pw}
    finally:
        async with sessionmaker() as session:
            from sqlalchemy import text

            await session.execute(
                text('DELETE FROM "user" WHERE email LIKE :p'),
                {"p": f"%-{suffix}@test.example.com"},
            )
            await session.commit()


async def _login(client: httpx.AsyncClient, email: str, password: str) -> None:
    resp = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, resp.text


async def test_dashboard_kpi_without_cookie_returns_401(http_client: httpx.AsyncClient) -> None:
    http_client.cookies.clear()
    resp = await http_client.get("/api/v1/dashboard/kpi")
    assert resp.status_code == 401


async def test_dashboard_kpi_admin_200_schema(
    http_client: httpx.AsyncClient, users: dict[str, str]
) -> None:
    await _login(http_client, users["admin"], users["password"])
    resp = await http_client.get("/api/v1/dashboard/kpi")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert set(body.keys()) == _EXPECTED_KEYS
    for key in (
        "rooms_occupied",
        "rooms_total",
        "devices_online",
        "devices_total",
        "active_overrides",
        "zones_window_open",
    ):
        assert isinstance(body[key], int), f"{key} muss int sein, war {body[key]!r}"
    assert body["avg_temperature_celsius"] is None or isinstance(
        body["avg_temperature_celsius"], (int, float)
    )
    assert body["last_engine_tick"] is None or isinstance(body["last_engine_tick"], str)


async def test_dashboard_kpi_mitarbeiter_allowed(
    http_client: httpx.AsyncClient, users: dict[str, str]
) -> None:
    await _login(http_client, users["mitarbeiter"], users["password"])
    resp = await http_client.get("/api/v1/dashboard/kpi")
    assert resp.status_code == 200, resp.text


async def test_dashboard_kpi_lifecycle_filter_excludes_retired(
    http_client: httpx.AsyncClient, users: dict[str, str], setup_engine: AsyncEngine
) -> None:
    """retired Device erhoeht ``devices_total`` NICHT, aktives schon (§5.58)."""
    await _login(http_client, users["admin"], users["password"])
    baseline = (await http_client.get("/api/v1/dashboard/kpi")).json()["devices_total"]

    sessionmaker = async_sessionmaker(setup_engine, expire_on_commit=False)
    suffix = uuid.uuid4().hex[:8]
    async with sessionmaker() as session:
        session.add(
            Device(
                dev_eui=f"deade14c{suffix[:8]}"[:16],
                kind=DeviceKind.THERMOSTAT,
                vendor=DeviceVendor.MCLIMATE,
                model="vicki",
                health_state="healthy",
                retired_at=datetime.now(tz=UTC),  # retired -> ausgeschlossen
            )
        )
        await session.commit()
    after_retired = (await http_client.get("/api/v1/dashboard/kpi")).json()["devices_total"]
    assert after_retired == baseline, "retired Device darf devices_total nicht erhoehen"

    async with sessionmaker() as session:
        session.add(
            Device(
                dev_eui=f"deada14c{suffix[:8]}"[:16],
                kind=DeviceKind.THERMOSTAT,
                vendor=DeviceVendor.MCLIMATE,
                model="vicki",
                health_state="healthy",
            )
        )
        await session.commit()
    after_active = (await http_client.get("/api/v1/dashboard/kpi")).json()["devices_total"]
    assert after_active == baseline + 1, "aktives Device muss devices_total erhoehen"

    # Cleanup
    async with sessionmaker() as session:
        from sqlalchemy import text

        await session.execute(
            text("DELETE FROM device WHERE dev_eui LIKE :p"), {"p": f"dead%14c{suffix[:8]}"}
        )
        await session.commit()
