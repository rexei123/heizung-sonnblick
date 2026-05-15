"""Sprint 9.17 T12 - API-Tests fuer User-Verwaltung.

Pflicht-Coverage:
- admin-only Schutz (mitarbeiter -> 403)
- Bricked-System-Schutz (letzter Admin)
- Audit-Eintraege (config_audit fuer CRUD, business_audit fuer
  PASSWORD_RESET_BY_ADMIN)

Tests laufen unter ``AUTH_ENABLED=true``, mit echten Login-Cookies.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import TypedDict

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
from heizung.auth.password import hash_password
from heizung.auth.rate_limit import limiter
from heizung.config import get_settings
from heizung.db import get_session
from heizung.main import app
from heizung.models.business_audit import BusinessAudit
from heizung.models.config_audit import ConfigAudit
from heizung.models.enums import UserRole
from heizung.models.user import User

DATABASE_URL = os.environ.get("DATABASE_URL")
DATABASE_URL_PRESENT = bool(DATABASE_URL)
SKIP_REASON = "DATABASE_URL nicht gesetzt - API-Tests brauchen Test-DB"


class _Setup(TypedDict):
    suffix: str
    domain: str
    admin_email: str
    admin_password: str
    admin_id: int
    mitarbeiter_email: str
    mitarbeiter_password: str
    mitarbeiter_id: int


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
async def setup(setup_engine: AsyncEngine) -> AsyncIterator[_Setup]:
    """Legt einen frischen Suffix-isolierten Admin + Mitarbeiter an.
    Cleanup loescht beide plus alle User mit Suffix-Match (in
    Tests neu erzeugte).
    """
    sessionmaker = async_sessionmaker(setup_engine, expire_on_commit=False)
    suffix = uuid.uuid4().hex[:8]
    domain = f"t917u-{suffix}.example.com"
    admin_email = f"admin@{domain}"
    admin_password = "AdminPassword12345!"
    mitarbeiter_email = f"emp@{domain}"
    mitarbeiter_password = "EmployeePassword12345!"

    async with sessionmaker() as session:
        admin = User(
            email=admin_email,
            password_hash=hash_password(admin_password),
            role=UserRole.ADMIN,
            is_active=True,
            must_change_password=False,
        )
        emp = User(
            email=mitarbeiter_email,
            password_hash=hash_password(mitarbeiter_password),
            role=UserRole.MITARBEITER,
            is_active=True,
            must_change_password=False,
        )
        session.add_all([admin, emp])
        await session.commit()
        await session.refresh(admin)
        await session.refresh(emp)
        data: _Setup = {
            "suffix": suffix,
            "domain": domain,
            "admin_email": admin_email,
            "admin_password": admin_password,
            "admin_id": admin.id,
            "mitarbeiter_email": mitarbeiter_email,
            "mitarbeiter_password": mitarbeiter_password,
            "mitarbeiter_id": emp.id,
        }

    try:
        yield data
    finally:
        async with sessionmaker() as session:
            await session.execute(
                text(
                    "DELETE FROM business_audit WHERE user_id IN "
                    '(SELECT id FROM "user" WHERE email LIKE :pat) '
                    "OR target_id IN "
                    '(SELECT id FROM "user" WHERE email LIKE :pat)'
                ),
                {"pat": f"%@{domain}"},
            )
            await session.execute(
                text(
                    "DELETE FROM config_audit WHERE user_id IN "
                    '(SELECT id FROM "user" WHERE email LIKE :pat) '
                    "OR scope_qualifier LIKE 'user:%' AND scope_qualifier IN "
                    "(SELECT 'user:'||id::text FROM \"user\" WHERE email LIKE :pat)"
                ),
                {"pat": f"%@{domain}"},
            )
            await session.execute(
                text('DELETE FROM "user" WHERE email LIKE :pat'),
                {"pat": f"%@{domain}"},
            )
            await session.commit()


async def _login(client: httpx.AsyncClient, email: str, password: str) -> None:
    resp = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, resp.text


# ---------------------------------------------------------------------------
# GET /api/v1/users
# ---------------------------------------------------------------------------


async def test_list_users_unauthenticated_returns_401(
    http_client: httpx.AsyncClient, setup: _Setup
) -> None:
    resp = await http_client.get("/api/v1/users")
    assert resp.status_code == 401


async def test_list_users_as_mitarbeiter_returns_403(
    http_client: httpx.AsyncClient, setup: _Setup
) -> None:
    await _login(http_client, setup["mitarbeiter_email"], setup["mitarbeiter_password"])
    resp = await http_client.get("/api/v1/users")
    assert resp.status_code == 403


async def test_list_users_as_admin_returns_list(
    http_client: httpx.AsyncClient, setup: _Setup
) -> None:
    await _login(http_client, setup["admin_email"], setup["admin_password"])
    resp = await http_client.get("/api/v1/users")
    assert resp.status_code == 200
    emails = {u["email"] for u in resp.json()}
    assert setup["admin_email"] in emails
    assert setup["mitarbeiter_email"] in emails


# ---------------------------------------------------------------------------
# POST /api/v1/users
# ---------------------------------------------------------------------------


async def test_create_user_as_admin_succeeds_and_logs_config_audit(
    http_client: httpx.AsyncClient, setup_engine: AsyncEngine, setup: _Setup
) -> None:
    await _login(http_client, setup["admin_email"], setup["admin_password"])
    new_email = f"newhire@{setup['domain']}"
    resp = await http_client.post(
        "/api/v1/users",
        json={
            "email": new_email,
            "role": "mitarbeiter",
            "initial_password": "TempPassword12345!",
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["email"] == new_email
    assert body["role"] == "mitarbeiter"
    assert body["must_change_password"] is True

    sessionmaker = async_sessionmaker(setup_engine, expire_on_commit=False)
    async with sessionmaker() as session:
        audit_stmt = (
            select(ConfigAudit)
            .where(ConfigAudit.table_name == "user")
            .where(ConfigAudit.scope_qualifier == f"user:{body['id']}")
            .where(ConfigAudit.column_name == "created")
        )
        audit = (await session.execute(audit_stmt)).scalars().first()
        assert audit is not None
        assert audit.user_id == setup["admin_id"]


async def test_create_user_as_mitarbeiter_returns_403(
    http_client: httpx.AsyncClient, setup: _Setup
) -> None:
    await _login(http_client, setup["mitarbeiter_email"], setup["mitarbeiter_password"])
    resp = await http_client.post(
        "/api/v1/users",
        json={
            "email": f"newhire@{setup['domain']}",
            "role": "mitarbeiter",
            "initial_password": "TempPassword12345!",
        },
    )
    assert resp.status_code == 403


async def test_create_user_with_duplicate_email_returns_409(
    http_client: httpx.AsyncClient, setup: _Setup
) -> None:
    await _login(http_client, setup["admin_email"], setup["admin_password"])
    resp = await http_client.post(
        "/api/v1/users",
        json={
            "email": setup["mitarbeiter_email"],
            "role": "mitarbeiter",
            "initial_password": "TempPassword12345!",
        },
    )
    assert resp.status_code == 409


# ---------------------------------------------------------------------------
# PATCH /api/v1/users/{id}
# ---------------------------------------------------------------------------


async def test_patch_user_role_succeeds(http_client: httpx.AsyncClient, setup: _Setup) -> None:
    await _login(http_client, setup["admin_email"], setup["admin_password"])
    resp = await http_client.patch(
        f"/api/v1/users/{setup['mitarbeiter_id']}",
        json={"role": "admin"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["role"] == "admin"


async def test_admin_cannot_change_own_role_to_mitarbeiter(
    http_client: httpx.AsyncClient, setup: _Setup
) -> None:
    await _login(http_client, setup["admin_email"], setup["admin_password"])
    resp = await http_client.patch(
        f"/api/v1/users/{setup['admin_id']}",
        json={"role": "mitarbeiter"},
    )
    assert resp.status_code == 400
    assert "eigene Rolle" in resp.json()["detail"]


async def test_last_active_admin_cannot_be_deactivated(
    http_client: httpx.AsyncClient, setup_engine: AsyncEngine, setup: _Setup
) -> None:
    """In der Test-DB existieren mehrere Admins (test-admin@local +
    setup-admin@... + ggf. weitere). Wir muessen erst alle anderen
    Admins deaktivieren / loeschen, damit setup-admin der letzte ist.
    Wir loeschen am Ende der Fixture wieder via Suffix-Cleanup; den
    test-admin lassen wir aber als Bootstrap weiterhin aktiv.

    Daher loeschen wir den test-admin temporaer und setzen ihn am Ende
    wieder. (Stattdessen einfacher: alle ANDEREN aktiven Admins kurz
    inaktivieren, am Ende re-aktivieren.)
    """
    await _login(http_client, setup["admin_email"], setup["admin_password"])

    sessionmaker = async_sessionmaker(setup_engine, expire_on_commit=False)
    # alle anderen aktiven Admins inaktivieren
    async with sessionmaker() as session:
        stmt = (
            select(User)
            .where(User.role == UserRole.ADMIN)
            .where(User.is_active.is_(True))
            .where(User.id != setup["admin_id"])
        )
        other_admins = list((await session.execute(stmt)).scalars().all())
        for u in other_admins:
            u.is_active = False
        await session.commit()

    try:
        resp = await http_client.patch(
            f"/api/v1/users/{setup['admin_id']}",
            json={"is_active": False},
        )
        assert resp.status_code == 400
        assert "Letzter aktiver Admin" in resp.json()["detail"]
    finally:
        async with sessionmaker() as session:
            for u in other_admins:
                fresh = await session.get(User, u.id)
                if fresh is not None:
                    fresh.is_active = True
            await session.commit()


# ---------------------------------------------------------------------------
# POST /api/v1/users/{id}/reset-password
# ---------------------------------------------------------------------------


async def test_reset_password_marks_must_change_and_logs_business_audit(
    http_client: httpx.AsyncClient, setup_engine: AsyncEngine, setup: _Setup
) -> None:
    await _login(http_client, setup["admin_email"], setup["admin_password"])
    new_password = "ResetPassword12345!"
    resp = await http_client.post(
        f"/api/v1/users/{setup['mitarbeiter_id']}/reset-password",
        json={"new_password": new_password},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["must_change_password"] is True

    sessionmaker = async_sessionmaker(setup_engine, expire_on_commit=False)
    async with sessionmaker() as session:
        stmt = (
            select(BusinessAudit)
            .where(BusinessAudit.action == "PASSWORD_RESET_BY_ADMIN")
            .where(BusinessAudit.target_id == setup["mitarbeiter_id"])
        )
        audit = (await session.execute(stmt)).scalars().first()
        assert audit is not None
        assert audit.user_id == setup["admin_id"]

    # Mitarbeiter kann mit neuem Passwort einloggen
    http_client.cookies.clear()
    login_new = await http_client.post(
        "/api/v1/auth/login",
        json={"email": setup["mitarbeiter_email"], "password": new_password},
    )
    assert login_new.status_code == 200


# ---------------------------------------------------------------------------
# DELETE /api/v1/users/{id}
# ---------------------------------------------------------------------------


async def test_delete_user_as_admin_succeeds(
    http_client: httpx.AsyncClient, setup_engine: AsyncEngine, setup: _Setup
) -> None:
    await _login(http_client, setup["admin_email"], setup["admin_password"])
    # zuerst neuen User anlegen, damit wir den loeschen koennen
    new_email = f"deleteme@{setup['domain']}"
    create = await http_client.post(
        "/api/v1/users",
        json={
            "email": new_email,
            "role": "mitarbeiter",
            "initial_password": "DeleteMe12345!",
        },
    )
    assert create.status_code == 201
    new_id = create.json()["id"]

    resp = await http_client.delete(f"/api/v1/users/{new_id}")
    assert resp.status_code == 204

    sessionmaker = async_sessionmaker(setup_engine, expire_on_commit=False)
    async with sessionmaker() as session:
        gone = await session.get(User, new_id)
        assert gone is None


async def test_last_active_admin_cannot_be_deleted(
    http_client: httpx.AsyncClient, setup_engine: AsyncEngine, setup: _Setup
) -> None:
    await _login(http_client, setup["admin_email"], setup["admin_password"])

    sessionmaker = async_sessionmaker(setup_engine, expire_on_commit=False)
    async with sessionmaker() as session:
        stmt = (
            select(User)
            .where(User.role == UserRole.ADMIN)
            .where(User.is_active.is_(True))
            .where(User.id != setup["admin_id"])
        )
        other_admins = list((await session.execute(stmt)).scalars().all())
        for u in other_admins:
            u.is_active = False
        await session.commit()

    try:
        resp = await http_client.delete(f"/api/v1/users/{setup['admin_id']}")
        assert resp.status_code == 400
        assert "Letzter aktiver Admin" in resp.json()["detail"]
    finally:
        async with sessionmaker() as session:
            for u in other_admins:
                fresh = await session.get(User, u.id)
                if fresh is not None:
                    fresh.is_active = True
            await session.commit()
