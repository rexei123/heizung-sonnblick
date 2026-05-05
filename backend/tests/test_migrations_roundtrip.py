"""Migrations-Roundtrip-Tests fuer Sprint 8 (0003a + 0003b).

Pflicht-Test pro neuer Migration: ``upgrade head -> downgrade base -> upgrade head``
muss durchlaufen. Catcht typische Bugs: vergessenes drop_index/drop_constraint
im downgrade, falsche Reihenfolge, Hypertable-Cleanup-Probleme.

Setup-Anforderungen:
- PostgreSQL mit TimescaleDB-Extension verfuegbar
- TEST_DATABASE_URL als env-Var (asyncpg-Dialect)
- alembic-Konfig liest TEST_DATABASE_URL bevorzugt vor DATABASE_URL

Wenn TEST_DATABASE_URL nicht gesetzt -> Test wird skipped. CI muss die
Variable setzen, sonst silent-pass = Test-Coverage-Luege.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

TEST_DB_URL = os.environ.get("TEST_DATABASE_URL")
SKIP_REASON = (
    "TEST_DATABASE_URL nicht gesetzt — Roundtrip-Test braucht echte "
    "PostgreSQL-Instanz mit TimescaleDB-Extension"
)


@pytest.fixture(scope="module")
def alembic_cfg():
    """Alembic-Konfig fuer den Roundtrip-Test (eigene Konfig, isoliert)."""
    if not TEST_DB_URL:
        pytest.skip(SKIP_REASON)

    from alembic.config import Config

    backend_root = Path(__file__).resolve().parents[1]
    cfg = Config(str(backend_root / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend_root / "alembic"))
    cfg.set_main_option("sqlalchemy.url", TEST_DB_URL)
    return cfg


@pytest.mark.skipif(not TEST_DB_URL, reason=SKIP_REASON)
def test_full_roundtrip_to_0003b(alembic_cfg) -> None:
    """upgrade head -> downgrade base -> upgrade head muss klappen.

    Catcht: vergessenes drop_table/drop_index/drop_constraint im downgrade,
    falsche Reihenfolge der drop-Aufrufe (FK-Verletzungen), Hypertable-
    Cleanup-Probleme.
    """
    from alembic import command

    # Komplett auf head
    command.upgrade(alembic_cfg, "head")
    # Alles wieder abbauen
    command.downgrade(alembic_cfg, "base")
    # Erneut auf head
    command.upgrade(alembic_cfg, "head")


@pytest.mark.skipif(not TEST_DB_URL, reason=SKIP_REASON)
def test_step_through_revisions(alembic_cfg) -> None:
    """Jede Revision einzeln rauf und runter, simuliert Inkrement-Deploy."""
    from alembic import command

    revisions = ["0001_initial", "0002_lorawan", "0003a_stammdaten", "0003b_event_log"]
    # Auf null
    command.downgrade(alembic_cfg, "base")
    # Schritt fuer Schritt rauf
    for rev in revisions:
        command.upgrade(alembic_cfg, rev)
    # Schritt fuer Schritt runter
    for rev in reversed(revisions[:-1]):
        command.downgrade(alembic_cfg, rev)
    command.downgrade(alembic_cfg, "base")
    # Final wieder auf head fuer Folge-Tests
    command.upgrade(alembic_cfg, "head")


@pytest.mark.skipif(not TEST_DB_URL, reason=SKIP_REASON)
def test_global_config_singleton_seeded(alembic_cfg) -> None:
    """Nach Migration 0003a muss genau eine global_config-Row mit id=1 existieren."""
    from sqlalchemy import create_engine, text

    from alembic import command

    command.upgrade(alembic_cfg, "head")

    sync_url = TEST_DB_URL.replace("+asyncpg", "")
    engine = create_engine(sync_url)
    with engine.connect() as conn:
        result = conn.execute(text("SELECT id, hotel_name, timezone FROM global_config"))
        rows = result.fetchall()

    assert len(rows) == 1, f"global_config sollte 1 Row haben, hat {len(rows)}"
    assert rows[0][0] == 1
    assert rows[0][1] == "Hotel Sonnblick"
    assert rows[0][2] == "Europe/Vienna"


@pytest.mark.skipif(not TEST_DB_URL, reason=SKIP_REASON)
def test_global_config_singleton_check_blocks_second_row(alembic_cfg) -> None:
    """CHECK (id = 1) muss INSERT mit anderer id ablehnen."""
    from sqlalchemy import create_engine, text
    from sqlalchemy.exc import IntegrityError

    from alembic import command

    command.upgrade(alembic_cfg, "head")

    sync_url = TEST_DB_URL.replace("+asyncpg", "")
    engine = create_engine(sync_url)
    with engine.connect() as conn, pytest.raises(IntegrityError):
        conn.execute(text("INSERT INTO global_config (id, hotel_name) VALUES (2, 'X')"))
        conn.commit()


@pytest.mark.skipif(not TEST_DB_URL, reason=SKIP_REASON)
def test_event_log_is_hypertable(alembic_cfg) -> None:
    """event_log muss in TimescaleDB als Hypertable registriert sein."""
    from sqlalchemy import create_engine, text

    from alembic import command

    command.upgrade(alembic_cfg, "head")

    sync_url = TEST_DB_URL.replace("+asyncpg", "")
    engine = create_engine(sync_url)
    with engine.connect() as conn:
        result = conn.execute(
            text(
                "SELECT hypertable_name FROM timescaledb_information.hypertables"
                " WHERE hypertable_name = 'event_log'"
            )
        )
        rows = result.fetchall()

    assert len(rows) == 1, "event_log ist nicht als Hypertable registriert"
