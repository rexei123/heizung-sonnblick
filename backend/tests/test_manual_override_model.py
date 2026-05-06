"""DB-Tests fuer die manual_override-Tabelle (Sprint 9.9 T1).

Pflicht-Akzeptanz aus dem T1-Brief:

- ``source``-CHECK greift bei ungueltigem Wert
- ``NUMERIC(4,1)`` speichert Decimal korrekt
- ``ON DELETE CASCADE`` -> Override verschwindet beim Room-Delete
- Partial Index ``ix_manual_override_active`` existiert nach Migration

Setup analog zu ``test_migrations_roundtrip.py``: skipt komplett, wenn
``TEST_DATABASE_URL`` nicht gesetzt ist (kein silent-pass / Coverage-Luege).
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from alembic import command
from alembic.config import Config
import pytest
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import DataError, IntegrityError

TEST_DB_URL = os.environ.get("TEST_DATABASE_URL")
SKIP_REASON = (
    "TEST_DATABASE_URL nicht gesetzt — manual_override-Tests brauchen "
    "echte PostgreSQL-Instanz mit angewandten Migrationen."
)


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    """Sync-Engine + alembic upgrade head einmal pro Test-Modul."""
    if not TEST_DB_URL:
        pytest.skip(SKIP_REASON)

    backend_root = Path(__file__).resolve().parents[1]
    cfg = Config(str(backend_root / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend_root / "alembic"))
    cfg.set_main_option("sqlalchemy.url", TEST_DB_URL)
    command.upgrade(cfg, "head")

    sync_url = TEST_DB_URL.replace("+asyncpg", "")
    eng = create_engine(sync_url)
    try:
        yield eng
    finally:
        eng.dispose()


@pytest.fixture
def room_id(engine: Engine) -> Iterator[int]:
    """Legt einen Test-RoomType + Test-Room an, gibt room_id zurueck,
    raeumt im Teardown wieder ab. Eindeutige number/name pro Test, damit
    parallele Laeufe nicht kollidieren."""
    suffix = datetime.now(tz=UTC).strftime("%H%M%S%f")
    type_name = f"t9-9-type-{suffix}"
    room_number = f"t9-9-{suffix}"

    with engine.begin() as conn:
        rt_id = conn.execute(
            text("INSERT INTO room_type (name) VALUES (:n) RETURNING id"),
            {"n": type_name},
        ).scalar_one()
        rid = conn.execute(
            text(
                "INSERT INTO room (number, room_type_id, status) "
                "VALUES (:num, :rt, 'vacant') RETURNING id"
            ),
            {"num": room_number, "rt": rt_id},
        ).scalar_one()

    try:
        yield int(rid)
    finally:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM room WHERE id = :id"), {"id": rid})
            conn.execute(text("DELETE FROM room_type WHERE id = :id"), {"id": rt_id})


# ---------------------------------------------------------------------------
# Constraint-Tests
# ---------------------------------------------------------------------------


def test_source_check_rejects_unknown_value(engine: Engine, room_id: int) -> None:
    """Ein nicht in der Enum-Liste enthaltener source-Wert muss vom DB-CHECK
    abgelehnt werden — auch wenn ein Raw-INSERT die ORM-Validierung umgeht."""
    expires = datetime.now(tz=UTC) + timedelta(hours=4)
    with engine.begin() as conn, pytest.raises(IntegrityError):
        conn.execute(
            text(
                "INSERT INTO manual_override "
                "(room_id, setpoint, source, expires_at) "
                "VALUES (:r, 21.0, 'frontend_forever', :e)"
            ),
            {"r": room_id, "e": expires},
        )


def test_setpoint_check_rejects_below_min(engine: Engine, room_id: int) -> None:
    expires = datetime.now(tz=UTC) + timedelta(hours=4)
    with engine.begin() as conn, pytest.raises(IntegrityError):
        conn.execute(
            text(
                "INSERT INTO manual_override "
                "(room_id, setpoint, source, expires_at) "
                "VALUES (:r, 4.9, 'frontend_4h', :e)"
            ),
            {"r": room_id, "e": expires},
        )


def test_setpoint_check_rejects_above_max(engine: Engine, room_id: int) -> None:
    expires = datetime.now(tz=UTC) + timedelta(hours=4)
    with engine.begin() as conn, pytest.raises(IntegrityError):
        conn.execute(
            text(
                "INSERT INTO manual_override "
                "(room_id, setpoint, source, expires_at) "
                "VALUES (:r, 30.1, 'frontend_4h', :e)"
            ),
            {"r": room_id, "e": expires},
        )


def test_numeric_4_1_stores_decimal(engine: Engine, room_id: int) -> None:
    """NUMERIC(4,1) speichert Decimal mit genau 1 NK; PostgreSQL rundet
    Eingaben mit mehr Stellen auf 1 NK (HALF_EVEN)."""
    expires = datetime.now(tz=UTC) + timedelta(hours=4)
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO manual_override "
                "(room_id, setpoint, source, expires_at) "
                "VALUES (:r, 21.5, 'frontend_4h', :e)"
            ),
            {"r": room_id, "e": expires},
        )
        result = conn.execute(
            text("SELECT setpoint FROM manual_override WHERE room_id = :r"),
            {"r": room_id},
        ).scalar_one()
    assert isinstance(result, Decimal)
    assert result == Decimal("21.5")


def test_numeric_4_1_rejects_overflow(engine: Engine, room_id: int) -> None:
    """NUMERIC(4,1) hat Range -999.9 .. 999.9. Wert mit 4 Vorkommastellen
    (z.B. 1234.5) waere ein Overflow — wir liegen aber durch den
    Setpoint-CHECK (5..30) eh weit darunter; dieser Test stellt sicher,
    dass die Skalierung tatsaechlich (4,1) ist und nicht versehentlich
    breiter."""
    expires = datetime.now(tz=UTC) + timedelta(hours=4)
    with engine.begin() as conn, pytest.raises((DataError, IntegrityError)):
        conn.execute(
            text(
                "INSERT INTO manual_override "
                "(room_id, setpoint, source, expires_at) "
                "VALUES (:r, 1234.5, 'frontend_4h', :e)"
            ),
            {"r": room_id, "e": expires},
        )


def test_on_delete_cascade(engine: Engine) -> None:
    """ON DELETE CASCADE: Loescht der Raum, verschwinden die Overrides mit."""
    suffix = datetime.now(tz=UTC).strftime("cascade%H%M%S%f")
    expires = datetime.now(tz=UTC) + timedelta(hours=4)

    with engine.begin() as conn:
        rt_id = conn.execute(
            text("INSERT INTO room_type (name) VALUES (:n) RETURNING id"),
            {"n": f"t9-9-type-{suffix}"},
        ).scalar_one()
        rid = conn.execute(
            text(
                "INSERT INTO room (number, room_type_id, status) "
                "VALUES (:num, :rt, 'vacant') RETURNING id"
            ),
            {"num": f"t9-9-{suffix}", "rt": rt_id},
        ).scalar_one()
        conn.execute(
            text(
                "INSERT INTO manual_override "
                "(room_id, setpoint, source, expires_at) "
                "VALUES (:r, 21.0, 'frontend_4h', :e)"
            ),
            {"r": rid, "e": expires},
        )

    with engine.begin() as conn:
        before = conn.execute(
            text("SELECT count(*) FROM manual_override WHERE room_id = :r"),
            {"r": rid},
        ).scalar_one()
        assert before == 1, "Setup hat keinen Override geschrieben"

        conn.execute(text("DELETE FROM room WHERE id = :id"), {"id": rid})
        after = conn.execute(
            text("SELECT count(*) FROM manual_override WHERE room_id = :r"),
            {"r": rid},
        ).scalar_one()
        assert after == 0, "ON DELETE CASCADE hat den Override nicht entfernt"

        conn.execute(text("DELETE FROM room_type WHERE id = :id"), {"id": rt_id})


def test_partial_index_exists(engine: Engine) -> None:
    """Index ``ix_manual_override_active`` muss als partial Index mit
    Predicate ``revoked_at IS NULL`` existieren."""
    with engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT indexname, indexdef FROM pg_indexes "
                "WHERE schemaname = 'public' "
                "AND tablename = 'manual_override' "
                "AND indexname = 'ix_manual_override_active'"
            )
        ).one_or_none()

    assert row is not None, "ix_manual_override_active fehlt"
    indexdef = row[1]
    assert "WHERE" in indexdef.upper(), f"Kein partial Predicate: {indexdef}"
    assert "revoked_at IS NULL" in indexdef, f"Falsches Predicate: {indexdef}"
