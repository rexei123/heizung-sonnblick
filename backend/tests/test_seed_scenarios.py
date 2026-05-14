"""Sprint 9.16a T4 - Encoding-Regression-Tests fuer scenario-Seed.

Verifiziert nach Auf-Lauf der Migrations (inkl. 0012 + 0013), dass
``scenario.description='summer_mode'`` korrekte UTF-8-Umlaute traegt
und nicht in die ASCII-Replacement-Variante (``ue``/``ae``) zurueckfaellt.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from alembic.config import Config
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from alembic import command
from heizung.models.scenario import Scenario

DATABASE_URL = os.environ.get("DATABASE_URL")
DATABASE_URL_PRESENT = bool(DATABASE_URL)
SKIP_REASON = "DATABASE_URL nicht gesetzt - DB-Tests brauchen Postgres"


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


async def test_summer_mode_description_uses_utf8_umlauts(
    setup_engine: AsyncEngine,
) -> None:
    """Stand nach 0012 (korrigiert) + 0013 (UPDATE fuer Live-DBs):
    description traegt deutsche Umlaute korrekt, keine ASCII-Replacements.
    """
    sessionmaker = async_sessionmaker(setup_engine, expire_on_commit=False)
    async with sessionmaker() as session:
        scenario = (
            await session.execute(select(Scenario).where(Scenario.code == "summer_mode"))
        ).scalar_one()

    desc = scenario.description or ""
    # Positiv
    assert "übernimmt" in desc, f"Umlaut-Fix nicht angekommen: {desc!r}"
    assert "Räume" in desc, f"Umlaut-Fix nicht angekommen: {desc!r}"
    # Negativ-Regression
    assert "uebernimmt" not in desc, f"Mojibake-Regression: {desc!r}"
    assert "Raeume" not in desc, f"Mojibake-Regression: {desc!r}"
