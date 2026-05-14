"""Gemeinsame Test-Fixtures."""

import asyncio
import os
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
import pytest_asyncio
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from alembic import command
from heizung.config import get_settings
from heizung.main import app


@pytest.fixture(autouse=True)
def _ensure_test_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stellt sicher, dass ENVIRONMENT + ALLOW_DEFAULT_SECRETS in jedem
    Test gesetzt sind. ENVIRONMENT ist seit H-5 Pflichtfeld (kein Default
    in Settings), daher muss auch der Test-Run die env-Var setzen, sonst
    crasht jeder Settings()-Call ohne explicit environment-kwarg.

    Tests, die explicit ENVIRONMENT testen (z.B. K-3-Validator), nutzen
    monkeypatch.setenv/delenv und ueberschreiben damit diesen Default.
    """
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setenv("ALLOW_DEFAULT_SECRETS", "1")
    # Settings-Cache leeren, damit nachfolgende get_settings() die
    # frischen env-Vars lesen.
    get_settings.cache_clear()


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as c:
        yield c


@pytest_asyncio.fixture(scope="module", autouse=True)
async def _ensure_test_admin() -> AsyncIterator[None]:
    """Sprint 9.17 (AE-50): Alle mutierenden Endpoints erfordern Auth.
    Bei ``AUTH_ENABLED=false`` faellt ``get_current_user`` auf den ersten
    aktiven Admin in der DB zurueck. Diese Fixture stellt sicher, dass
    so ein User in der Test-DB existiert — idempotent.

    Skippt wenn ``DATABASE_URL`` nicht gesetzt ist (Pure-Function-Tests).
    """
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        yield
        return

    backend_root = Path(__file__).resolve().parents[1]
    cfg = Config(str(backend_root / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend_root / "alembic"))
    cfg.set_main_option("sqlalchemy.url", db_url)
    await asyncio.to_thread(command.upgrade, cfg, "head")

    # Lokale Imports nach Migration: das Auth-Modul braucht zur Importzeit
    # vollstaendige Settings (ENVIRONMENT etc.), die ``_ensure_test_env``
    # erst gesetzt hat.
    from heizung.models.enums import UserRole
    from heizung.models.user import User

    engine = create_async_engine(db_url)
    sm = async_sessionmaker(engine, expire_on_commit=False)
    async with sm() as session:
        existing = (
            await session.execute(select(User).where(User.role == UserRole.ADMIN).limit(1))
        ).scalar_one_or_none()
        if existing is None:
            session.add(
                User(
                    email="test-admin@local",
                    password_hash="test-hash-not-used",
                    role=UserRole.ADMIN,
                    is_active=True,
                    must_change_password=False,
                )
            )
            await session.commit()
    await engine.dispose()
    yield
