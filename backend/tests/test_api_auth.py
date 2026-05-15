"""Sprint 9.17 T12 - API-Tests fuer Auth-Endpoints.

Folgt der DB-Skip-Konvention von ``test_api_device_zone``: separate
async engine fuer Setup, dependency_override teilt diese engine mit
der App. Tests laufen unter ``AUTH_ENABLED=true``, damit der Cookie-
Flow real getestet wird (kein _system_user-Fallback).

Slowapi-Limiter wird per Test resettet, damit Rate-Limit-Tests und
restliche Tests sich nicht in die Quere kommen.

Skip lokal, wenn ``DATABASE_URL`` nicht gesetzt ist.
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
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from alembic import command
from heizung.auth.password import hash_password
from heizung.auth.rate_limit import limiter
from heizung.config import get_settings
from heizung.db import get_session
from heizung.main import app
from heizung.models.business_audit import BusinessAudit
from heizung.models.enums import UserRole
from heizung.models.user import User

DATABASE_URL = os.environ.get("DATABASE_URL")
DATABASE_URL_PRESENT = bool(DATABASE_URL)
SKIP_REASON = "DATABASE_URL nicht gesetzt - API-Tests brauchen Test-DB"


class _Setup(TypedDict):
    suffix: str
    admin_email: str
    admin_password: str
    admin_id: int
    mitarbeiter_email: str
    mitarbeiter_password: str
    mitarbeiter_id: int
    inactive_email: str
    inactive_password: str


@pytest.fixture(autouse=True)
def _auth_test_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Aktiviert AUTH_ENABLED=true fuer dieses Modul. Settings-Cache
    wird geleert, damit get_settings() die neuen ENV-Vars liest.
    Cookie-secure ist false, damit der TestClient ueber http die
    Cookie zurueckspielt.
    """
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setenv("ALLOW_DEFAULT_SECRETS", "1")
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("AUTH_COOKIE_SECURE", "false")
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _reset_limiter() -> Iterator[None]:
    """Slowapi-Limiter teilt Storage ueber Tests; vor und nach jedem
    Test resetten, damit Rate-Limit-Counter sich nicht akkumuliert."""
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
async def setup(setup_engine: AsyncEngine) -> AsyncIterator[_Setup]:
    """Legt drei User an (admin, mitarbeiter, inactive). Cleanup loescht
    alle drei plus business_audit-Eintraege via FK-Cascade.
    """
    sessionmaker = async_sessionmaker(setup_engine, expire_on_commit=False)
    suffix = uuid.uuid4().hex[:8]
    admin_email = f"admin-{suffix}@test.example.com"
    admin_password = "AdminPassword12345!"
    mitarbeiter_email = f"emp-{suffix}@test.example.com"
    mitarbeiter_password = "EmployeePassword12345!"
    inactive_email = f"inactive-{suffix}@test.example.com"
    inactive_password = "InactivePassword12345!"

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
        inactive = User(
            email=inactive_email,
            password_hash=hash_password(inactive_password),
            role=UserRole.MITARBEITER,
            is_active=False,
            must_change_password=False,
        )
        session.add_all([admin, emp, inactive])
        await session.commit()
        await session.refresh(admin)
        await session.refresh(emp)
        data: _Setup = {
            "suffix": suffix,
            "admin_email": admin_email,
            "admin_password": admin_password,
            "admin_id": admin.id,
            "mitarbeiter_email": mitarbeiter_email,
            "mitarbeiter_password": mitarbeiter_password,
            "mitarbeiter_id": emp.id,
            "inactive_email": inactive_email,
            "inactive_password": inactive_password,
        }

    try:
        yield data
    finally:
        async with sessionmaker() as session:
            await session.execute(
                text(
                    "DELETE FROM business_audit WHERE user_id IN "
                    '(SELECT id FROM "user" WHERE email LIKE :pat)'
                ),
                {"pat": f"%-{suffix}@test.example.com"},
            )
            await session.execute(
                text(
                    "DELETE FROM config_audit WHERE user_id IN "
                    '(SELECT id FROM "user" WHERE email LIKE :pat)'
                ),
                {"pat": f"%-{suffix}@test.example.com"},
            )
            await session.execute(
                text('DELETE FROM "user" WHERE email LIKE :pat'),
                {"pat": f"%-{suffix}@test.example.com"},
            )
            await session.commit()


# ---------------------------------------------------------------------------
# POST /api/v1/auth/login
# ---------------------------------------------------------------------------


async def test_login_with_valid_admin_returns_user_and_sets_cookie(
    http_client: httpx.AsyncClient, setup: _Setup
) -> None:
    resp = await http_client.post(
        "/api/v1/auth/login",
        json={"email": setup["admin_email"], "password": setup["admin_password"]},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["user"]["email"] == setup["admin_email"]
    assert body["user"]["role"] == "admin"
    # Cookie ist gesetzt
    assert "heizung_session" in resp.cookies
    assert resp.cookies["heizung_session"]


async def test_login_with_wrong_password_returns_401_generic_message(
    http_client: httpx.AsyncClient, setup: _Setup
) -> None:
    resp = await http_client.post(
        "/api/v1/auth/login",
        json={"email": setup["admin_email"], "password": "WrongPassword12345!"},
    )
    assert resp.status_code == 401
    assert resp.json()["detail"] == "E-Mail oder Passwort falsch"


async def test_login_with_unknown_email_returns_same_generic_401(
    http_client: httpx.AsyncClient, setup: _Setup
) -> None:
    """Kein User-Enumeration: unbekannte E-Mail liefert dieselbe Antwort
    wie ein falsches Passwort."""
    resp = await http_client.post(
        "/api/v1/auth/login",
        json={"email": f"nobody-{setup['suffix']}@test.example.com", "password": "WhateverXXXXX1!"},
    )
    assert resp.status_code == 401
    assert resp.json()["detail"] == "E-Mail oder Passwort falsch"


async def test_login_inactive_user_returns_401(
    http_client: httpx.AsyncClient, setup: _Setup
) -> None:
    resp = await http_client.post(
        "/api/v1/auth/login",
        json={"email": setup["inactive_email"], "password": setup["inactive_password"]},
    )
    assert resp.status_code == 401
    assert resp.json()["detail"] == "E-Mail oder Passwort falsch"


async def test_login_rate_limit_blocks_after_5_attempts_per_ip(
    http_client: httpx.AsyncClient, setup: _Setup
) -> None:
    """slowapi limitert /login auf 5/Minute pro IP (settings-Default).
    Sechster Versuch liefert 429.
    """
    payload = {"email": setup["admin_email"], "password": "WrongPassword12345!"}
    statuses: list[int] = []
    last_body: dict = {}
    for _ in range(6):
        resp = await http_client.post("/api/v1/auth/login", json=payload)
        statuses.append(resp.status_code)
        if resp.status_code == 429:
            last_body = resp.json()
    # Erste 5 sind 401, der 6. ist 429
    assert statuses[:5] == [401, 401, 401, 401, 401]
    assert statuses[5] == 429
    # Sprint 9.17b T3: Body enthaelt slowapi-Detail-String (Frontend mappt
    # 429 auf "Zu viele Versuche..." — siehe login/page.tsx).
    detail = str(last_body.get("error") or last_body.get("detail") or "").lower()
    assert detail, f"Erwartet 429-Body mit error/detail-Feld, war: {last_body}"


# ---------------------------------------------------------------------------
# POST /api/v1/auth/logout + GET /api/v1/auth/me
# ---------------------------------------------------------------------------


async def test_logout_clears_cookie(http_client: httpx.AsyncClient, setup: _Setup) -> None:
    # zuerst einloggen
    login = await http_client.post(
        "/api/v1/auth/login",
        json={"email": setup["admin_email"], "password": setup["admin_password"]},
    )
    assert login.status_code == 200
    # /me funktioniert mit Cookie
    me = await http_client.get("/api/v1/auth/me")
    assert me.status_code == 200
    # logout
    resp = await http_client.post("/api/v1/auth/logout")
    assert resp.status_code == 204
    # Cookie-Jar ist leer
    http_client.cookies.clear()
    me2 = await http_client.get("/api/v1/auth/me")
    assert me2.status_code == 401


async def test_me_without_cookie_returns_401(http_client: httpx.AsyncClient, setup: _Setup) -> None:
    resp = await http_client.get("/api/v1/auth/me")
    assert resp.status_code == 401


async def test_me_with_invalid_cookie_returns_401(
    http_client: httpx.AsyncClient, setup: _Setup
) -> None:
    resp = await http_client.get("/api/v1/auth/me", cookies={"heizung_session": "not-a-real-jwt"})
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# POST /api/v1/auth/change-password
# ---------------------------------------------------------------------------


async def test_change_password_with_correct_current_succeeds_and_audits(
    http_client: httpx.AsyncClient, setup_engine: AsyncEngine, setup: _Setup
) -> None:
    login = await http_client.post(
        "/api/v1/auth/login",
        json={"email": setup["mitarbeiter_email"], "password": setup["mitarbeiter_password"]},
    )
    assert login.status_code == 200

    new_password = "BrandNewPassword99!"
    resp = await http_client.post(
        "/api/v1/auth/change-password",
        json={
            "current_password": setup["mitarbeiter_password"],
            "new_password": new_password,
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["must_change_password"] is False

    # business_audit-Eintrag muss existieren
    sessionmaker = async_sessionmaker(setup_engine, expire_on_commit=False)
    async with sessionmaker() as session:
        stmt = (
            select(BusinessAudit)
            .where(BusinessAudit.user_id == setup["mitarbeiter_id"])
            .where(BusinessAudit.action == "PASSWORD_CHANGE")
        )
        audit = (await session.execute(stmt)).scalars().first()
        assert audit is not None
        assert audit.target_type == "user"
        assert audit.target_id == setup["mitarbeiter_id"]

    # Login mit neuem Passwort funktioniert; mit altem nicht.
    http_client.cookies.clear()
    bad = await http_client.post(
        "/api/v1/auth/login",
        json={"email": setup["mitarbeiter_email"], "password": setup["mitarbeiter_password"]},
    )
    assert bad.status_code == 401
    good = await http_client.post(
        "/api/v1/auth/login",
        json={"email": setup["mitarbeiter_email"], "password": new_password},
    )
    assert good.status_code == 200


async def test_change_password_with_wrong_current_returns_400(
    http_client: httpx.AsyncClient, setup: _Setup
) -> None:
    login = await http_client.post(
        "/api/v1/auth/login",
        json={"email": setup["admin_email"], "password": setup["admin_password"]},
    )
    assert login.status_code == 200

    resp = await http_client.post(
        "/api/v1/auth/change-password",
        json={
            "current_password": "WrongCurrent12!",
            "new_password": "BrandNewPassword99!",
        },
    )
    assert resp.status_code == 400
    assert "Aktuelles Passwort falsch" in resp.json()["detail"]


async def test_change_password_with_too_short_new_password_returns_422(
    http_client: httpx.AsyncClient, setup: _Setup
) -> None:
    login = await http_client.post(
        "/api/v1/auth/login",
        json={"email": setup["admin_email"], "password": setup["admin_password"]},
    )
    assert login.status_code == 200

    resp = await http_client.post(
        "/api/v1/auth/change-password",
        json={
            "current_password": setup["admin_password"],
            "new_password": "tooShort",
        },
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Sprint 9.17b T2 — Logout-Cookie-Invalidierung (B-9.17a-1)
# Bug 9.17: _clear_auth_cookie wirkte auf injizierten response-Parameter,
# wurde durch explizit zurueckgegebenes neues Response-Objekt ueberschrieben.
# Logout lieferte 204 OHNE Set-Cookie-Header → Cookie blieb im Browser.
# Test prueft direkt den Response-Header — der frueher gruene
# test_logout_clears_cookie hat manuell cookies.clear() gemacht und das
# Symptom verdeckt.
# ---------------------------------------------------------------------------


async def test_logout_response_carries_cookie_deletion_header(
    http_client: httpx.AsyncClient, setup: _Setup
) -> None:
    login = await http_client.post(
        "/api/v1/auth/login",
        json={"email": setup["admin_email"], "password": setup["admin_password"]},
    )
    assert login.status_code == 200

    resp = await http_client.post("/api/v1/auth/logout")
    assert resp.status_code == 204

    set_cookie = resp.headers.get("set-cookie")
    assert set_cookie is not None, (
        "Logout-Response muss set-cookie-Header liefern, sonst behaelt der "
        "Browser das JWT-Cookie. Siehe CLAUDE.md §5.31."
    )
    assert "heizung_session" in set_cookie, set_cookie
    # Cookie-Loeschung manifestiert sich als Max-Age=0 ODER Expires-Datum
    # in der Vergangenheit. Starlette schickt "Max-Age=0; ...; expires=Thu, 01 Jan 1970 ...".
    lowered = set_cookie.lower()
    assert "max-age=0" in lowered or "expires=thu, 01 jan 1970" in lowered, set_cookie


async def test_change_password_without_cookie_under_auth_enabled_returns_401(
    http_client: httpx.AsyncClient, setup: _Setup
) -> None:
    """Sprint 9.17a T3: AUTH_ENABLED=true + kein Cookie -> 401 (nicht 503,
    weil Auth grundsaetzlich aktiv ist; nur das Cookie fehlt)."""
    http_client.cookies.clear()
    resp = await http_client.post(
        "/api/v1/auth/change-password",
        json={
            "current_password": "Whatever1234567!",
            "new_password": "BrandNewPassword99!",
        },
    )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Sprint 9.17a T3 - Identitaets-kritische Endpoints unter AUTH_ENABLED=false
# B-9.17-10: /me und /change-password duerfen NICHT den System-User-Fallback
# nutzen. 503 statt Falsch-Identitaet.
# ---------------------------------------------------------------------------


async def test_me_under_auth_disabled_returns_503(
    http_client: httpx.AsyncClient, setup: _Setup, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AUTH_ENABLED", "false")
    get_settings.cache_clear()
    try:
        resp = await http_client.get("/api/v1/auth/me")
        assert resp.status_code == 503
        assert "Wartungsmodus" in resp.json()["detail"]
    finally:
        get_settings.cache_clear()


async def test_change_password_under_auth_disabled_returns_503(
    http_client: httpx.AsyncClient, setup: _Setup, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AUTH_ENABLED", "false")
    get_settings.cache_clear()
    try:
        resp = await http_client.post(
            "/api/v1/auth/change-password",
            json={
                "current_password": "Whatever1234567!",
                "new_password": "BrandNewPassword99!",
            },
        )
        assert resp.status_code == 503
        assert "Wartungsmodus" in resp.json()["detail"]
    finally:
        get_settings.cache_clear()


async def test_logout_under_auth_disabled_still_works(
    http_client: httpx.AsyncClient, setup: _Setup, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Brief T3: /logout laeuft auch unter AUTH_ENABLED=false
    (Cookie-Cleanup ist unschaedlich)."""
    monkeypatch.setenv("AUTH_ENABLED", "false")
    get_settings.cache_clear()
    try:
        resp = await http_client.post("/api/v1/auth/logout")
        assert resp.status_code == 204
    finally:
        get_settings.cache_clear()
