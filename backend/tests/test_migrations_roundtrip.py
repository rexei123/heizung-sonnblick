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

§5.49 (Sprint 12c): Room-Fixtures setzen ``guest_override_blocked=false``
explizit im Raw-SQL-INSERT, weil das Feld NOT NULL ohne DB-Server-Default
ist (Default lebt nur im ORM-Modell, Raw-SQL umgeht das).
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from alembic.config import Config

# Leerstring statt None, damit Tests typsicher .replace() etc. nutzen.
# Skip-Logik unten verwendet weiter Falsy-Check, das passt fuer "".
TEST_DB_URL: str = os.environ.get("TEST_DATABASE_URL", "")
SKIP_REASON = (
    "TEST_DATABASE_URL nicht gesetzt — Roundtrip-Test braucht echte "
    "PostgreSQL-Instanz mit TimescaleDB-Extension"
)


@pytest.fixture(scope="module")
def alembic_cfg() -> Config:
    """Alembic-Konfig fuer den Roundtrip-Test (eigene Konfig, isoliert)."""
    if not TEST_DB_URL:
        pytest.skip(SKIP_REASON)

    backend_root = Path(__file__).resolve().parents[1]
    cfg = Config(str(backend_root / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend_root / "alembic"))
    cfg.set_main_option("sqlalchemy.url", TEST_DB_URL)
    return cfg


@pytest.mark.skipif(not TEST_DB_URL, reason=SKIP_REASON)
def test_full_roundtrip_to_0003b(alembic_cfg: Config) -> None:
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
def test_step_through_revisions(alembic_cfg: Config) -> None:
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
def test_global_config_singleton_seeded(alembic_cfg: Config) -> None:
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
def test_global_config_singleton_check_blocks_second_row(alembic_cfg: Config) -> None:
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
def test_event_log_is_hypertable(alembic_cfg: Config) -> None:
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


@pytest.mark.skipif(not TEST_DB_URL, reason=SKIP_REASON)
def test_migration_0012_atomar_auf_ab_auf(alembic_cfg: Config) -> None:
    """Migration 0012 muss upgrade → downgrade → upgrade ohne Fehler durchlaufen.

    B-9.16-2: bisher nur manuell verifiziert, jetzt automatisierter Roundtrip-Test.
    Catcht: Daten-Migrations-Race, DDL-Reihenfolge, Idempotenz bei Re-Run.
    """
    from alembic import command

    command.upgrade(alembic_cfg, "0012_summer_mode_scenario")
    command.downgrade(alembic_cfg, "0011_config_audit")
    command.upgrade(alembic_cfg, "0012_summer_mode_scenario")
    command.upgrade(alembic_cfg, "head")


@pytest.mark.skipif(not TEST_DB_URL, reason=SKIP_REASON)
def test_migration_0012_preserves_summer_mode_active(alembic_cfg: Config) -> None:
    """Migration 0012 muss summer_mode_active-Zustand atomar in scenario_assignment
    spiegeln und beim Downgrade zurueckspielen.

    Szenario:
    1. DB auf 0011 (Spalte global_config.summer_mode_active existiert)
    2. summer_mode_active=true setzen
    3. Upgrade auf 0012 → scenario_assignment(scope='global', is_active=true) angelegt,
       Spalte gedroppt
    4. Downgrade auf 0011 → Spalte wieder da, summer_mode_active=true rekonstruiert
    """
    from sqlalchemy import create_engine, text

    from alembic import command

    command.upgrade(alembic_cfg, "head")
    command.downgrade(alembic_cfg, "0011_config_audit")

    sync_url = TEST_DB_URL.replace("+asyncpg", "")
    engine = create_engine(sync_url)
    with engine.connect() as conn:
        conn.execute(text("UPDATE global_config SET summer_mode_active = true WHERE id = 1"))
        conn.commit()

    command.upgrade(alembic_cfg, "0012_summer_mode_scenario")

    with engine.connect() as conn:
        col_exists = conn.execute(
            text(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_name = 'global_config' AND column_name = 'summer_mode_active'"
            )
        ).fetchone()
        assert col_exists is None, "summer_mode_active-Spalte muss nach 0012 weg sein"

        active = conn.execute(
            text(
                "SELECT sa.is_active FROM scenario_assignment sa "
                "JOIN scenario s ON s.id = sa.scenario_id "
                "WHERE s.code = 'summer_mode' AND sa.scope = 'global' "
                "AND sa.room_type_id IS NULL AND sa.room_id IS NULL "
                "AND sa.season_id IS NULL"
            )
        ).fetchone()
        assert active is not None, "scenario_assignment fuer aktiven Sommermodus fehlt"
        assert active[0] is True, "scenario_assignment.is_active muss true sein"

    command.downgrade(alembic_cfg, "0011_config_audit")

    with engine.connect() as conn:
        restored = conn.execute(
            text("SELECT summer_mode_active FROM global_config WHERE id = 1")
        ).fetchone()
        assert restored is not None
        assert restored[0] is True, "Downgrade muss summer_mode_active=true rekonstruieren"

    command.upgrade(alembic_cfg, "head")


@pytest.mark.skipif(not TEST_DB_URL, reason=SKIP_REASON)
def test_migration_0012_preserves_inactive_state(alembic_cfg: Config) -> None:
    """Inaktiver Sommermodus darf KEIN scenario_assignment erzeugen.

    Komplement zu test_migration_0012_preserves_summer_mode_active. Verhindert,
    dass die Migration unbeabsichtigt einen aktiven Assignment-Stand erzeugt,
    wenn der Ursprung inaktiv war.
    """
    from sqlalchemy import create_engine, text

    from alembic import command

    command.upgrade(alembic_cfg, "head")
    command.downgrade(alembic_cfg, "0011_config_audit")

    sync_url = TEST_DB_URL.replace("+asyncpg", "")
    engine = create_engine(sync_url)
    with engine.connect() as conn:
        conn.execute(text("UPDATE global_config SET summer_mode_active = false WHERE id = 1"))
        conn.commit()

    command.upgrade(alembic_cfg, "0012_summer_mode_scenario")

    with engine.connect() as conn:
        # Scenario muss existieren (Seed ist unbedingt), aber kein aktives Assignment
        scenario = conn.execute(
            text("SELECT id FROM scenario WHERE code = 'summer_mode'")
        ).fetchone()
        assert scenario is not None, "summer_mode-Scenario muss geseeded sein"

        assignment = conn.execute(
            text(
                "SELECT 1 FROM scenario_assignment sa "
                "JOIN scenario s ON s.id = sa.scenario_id "
                "WHERE s.code = 'summer_mode' AND sa.scope = 'global'"
            )
        ).fetchone()
        assert assignment is None, "Inaktiver Sommermodus darf kein Assignment erzeugen"

    command.upgrade(alembic_cfg, "head")


@pytest.mark.skipif(not TEST_DB_URL, reason=SKIP_REASON)
def test_migration_0015_atomar_auf_ab_auf(alembic_cfg: Config) -> None:
    """Migration 0015 muss upgrade -> downgrade -> upgrade ohne Fehler durchlaufen.

    Sprint 11 T1: device.health_state + heating_zone.health_state additiv.
    Catcht: vergessenes drop_constraint im downgrade, falsche Reihenfolge
    der drop-Aufrufe (Constraint vor Column), Idempotenz bei Re-Run.
    """
    from alembic import command

    command.upgrade(alembic_cfg, "0015_health_state")
    command.downgrade(alembic_cfg, "0014_auth_and_business_audit")
    command.upgrade(alembic_cfg, "0015_health_state")
    command.upgrade(alembic_cfg, "head")


@pytest.mark.skipif(not TEST_DB_URL, reason=SKIP_REASON)
def test_migration_0015_default_value_after_upgrade(alembic_cfg: Config) -> None:
    """Bestehende device/heating_zone Rows bekommen nach 0015 health_state='silent'.

    Szenario:
    1. DB auf 0014 (vor 0015, ohne health_state-Spalten)
    2. Test-Rows einfuegen (room_type, room, heating_zone, device)
    3. Upgrade auf 0015 -> Spalten werden mit server_default='silent'
       atomar angelegt und befuellt
    4. Verify: bestehende Rows haben health_state='silent'

    Backfill aller bestehenden Rows ist der Pflicht-Pfad fuer Defensive
    nach S5 — Compute-Task aus T5 hebt spaeter selektiv auf 'healthy'.
    """
    from sqlalchemy import create_engine, text

    from alembic import command

    command.upgrade(alembic_cfg, "head")
    command.downgrade(alembic_cfg, "0014_auth_and_business_audit")

    sync_url = TEST_DB_URL.replace("+asyncpg", "")
    engine = create_engine(sync_url)

    rt_id: int | None = None
    room_id: int | None = None
    zone_id: int | None = None
    dev_id: int | None = None
    try:
        with engine.connect() as conn:
            rt_id = conn.execute(
                text("INSERT INTO room_type (name) VALUES ('rt_0015_default') RETURNING id")
            ).scalar_one()
            # Hinweis: Test inserted bei Revision 0014 (vor 0017),
            # daher KEIN guest_override_blocked in Spalten-Liste — Spalte
            # existiert in dieser Migrations-Stufe noch nicht.
            room_id = conn.execute(
                text(
                    "INSERT INTO room (number, room_type_id, status) "
                    "VALUES ('r-0015d', :rt, 'vacant') RETURNING id"
                ),
                {"rt": rt_id},
            ).scalar_one()
            zone_id = conn.execute(
                text(
                    "INSERT INTO heating_zone "
                    "(room_id, kind, name, is_towel_warmer) "
                    "VALUES (:r, 'bedroom', 'zone-0015d', false) RETURNING id"
                ),
                {"r": room_id},
            ).scalar_one()
            dev_id = conn.execute(
                text(
                    "INSERT INTO device "
                    "(dev_eui, kind, vendor, model, is_active) "
                    "VALUES ('00000000000015de', 'thermostat', 'mclimate', "
                    "'vicki', true) RETURNING id"
                )
            ).scalar_one()
            conn.commit()

        command.upgrade(alembic_cfg, "0015_health_state")

        with engine.connect() as conn:
            dev_hs = conn.execute(
                text("SELECT health_state FROM device WHERE id = :id"),
                {"id": dev_id},
            ).scalar_one()
            zone_hs = conn.execute(
                text("SELECT health_state FROM heating_zone WHERE id = :id"),
                {"id": zone_id},
            ).scalar_one()

        assert dev_hs == "silent", f"device.health_state sollte 'silent' sein, ist {dev_hs!r}"
        assert zone_hs == "silent", (
            f"heating_zone.health_state sollte 'silent' sein, ist {zone_hs!r}"
        )
    finally:
        command.upgrade(alembic_cfg, "head")
        with engine.connect() as conn:
            if dev_id is not None:
                conn.execute(text("DELETE FROM device WHERE id = :id"), {"id": dev_id})
            if zone_id is not None:
                conn.execute(text("DELETE FROM heating_zone WHERE id = :id"), {"id": zone_id})
            if room_id is not None:
                conn.execute(text("DELETE FROM room WHERE id = :id"), {"id": room_id})
            if rt_id is not None:
                conn.execute(text("DELETE FROM room_type WHERE id = :id"), {"id": rt_id})
            conn.commit()


@pytest.mark.skipif(not TEST_DB_URL, reason=SKIP_REASON)
def test_migration_0015_check_constraint_rejects_invalid(alembic_cfg: Config) -> None:
    """CHECK-Constraints blocken health_state='unknown' fuer device UND heating_zone.

    Zwei direkte INSERTs mit invalidem health_state-Wert. Beide muessen
    IntegrityError werfen (CHECK-Verletzung auf DB-Ebene). Sichert die
    Werte-Whitelist gegen Umgehung via Raw-SQL oder Engine-Bug.
    """
    from sqlalchemy import create_engine, text
    from sqlalchemy.exc import IntegrityError

    from alembic import command

    command.upgrade(alembic_cfg, "head")

    sync_url = TEST_DB_URL.replace("+asyncpg", "")
    engine = create_engine(sync_url)

    rt_id: int | None = None
    room_id: int | None = None
    try:
        with engine.connect() as conn:
            rt_id = conn.execute(
                text("INSERT INTO room_type (name) VALUES ('rt_0015_chk') RETURNING id")
            ).scalar_one()
            room_id = conn.execute(
                text(
                    "INSERT INTO room (number, room_type_id, status, guest_override_blocked) "
                    "VALUES ('r-0015c', :rt, 'vacant', false) RETURNING id"
                ),
                {"rt": rt_id},
            ).scalar_one()
            conn.commit()

        # device: invalid health_state -> CHECK-Verletzung
        # §5.56: is_active aus Spaltenliste entfernt (Sprint 13b.1 Migration
        # 0018 dropt die Spalte; Test laeuft an head, ist_active existiert
        # dort nicht mehr). Test prueft CHECK auf health_state, is_active
        # war ungenutzt.
        with engine.connect() as conn, pytest.raises(IntegrityError):
            conn.execute(
                text(
                    "INSERT INTO device "
                    "(dev_eui, kind, vendor, model, health_state) "
                    "VALUES ('00000000000015c1', 'thermostat', 'mclimate', "
                    "'vicki', 'unknown')"
                )
            )
            conn.commit()

        # heating_zone: invalid health_state -> CHECK-Verletzung
        with engine.connect() as conn, pytest.raises(IntegrityError):
            conn.execute(
                text(
                    "INSERT INTO heating_zone "
                    "(room_id, kind, name, is_towel_warmer, health_state) "
                    "VALUES (:r, 'bedroom', 'zone-0015c', false, 'unknown')"
                ),
                {"r": room_id},
            )
            conn.commit()
    finally:
        with engine.connect() as conn:
            if room_id is not None:
                conn.execute(text("DELETE FROM room WHERE id = :id"), {"id": room_id})
            if rt_id is not None:
                conn.execute(text("DELETE FROM room_type WHERE id = :id"), {"id": rt_id})
            conn.commit()


@pytest.mark.skipif(not TEST_DB_URL, reason=SKIP_REASON)
def test_migration_0016_atomar_auf_ab_auf(alembic_cfg: Config) -> None:
    """Migration 0016 muss upgrade -> downgrade -> upgrade ohne Fehler durchlaufen.

    Sprint 12a T1: manual_override.heating_zone_id additiv + FK + Partial
    Index. Catcht: vergessenes drop_index/drop_constraint im downgrade,
    falsche Reihenfolge (Index vor FK vor Column), Idempotenz bei Re-Run.
    """
    from alembic import command

    command.upgrade(alembic_cfg, "0016_manual_override_zone_id")
    command.downgrade(alembic_cfg, "0015_health_state")
    command.upgrade(alembic_cfg, "0016_manual_override_zone_id")
    command.upgrade(alembic_cfg, "head")


@pytest.mark.skipif(not TEST_DB_URL, reason=SKIP_REASON)
def test_migration_0016_existing_rows_keep_null(alembic_cfg: Config) -> None:
    """Bestandsdaten in manual_override behalten heating_zone_id=NULL.

    Lazy-Migration laut Sprint-12a-Brief: Bestands-Overrides bleiben
    Room-Scope (heating_zone_id IS NULL) bis zur naechsten Erneuerung.
    Engine Layer 3 (T5) fuehrt Zone>Room-Fallback durch, kein Backfill
    in der Migration.

    Szenario:
    1. DB auf 0015 (vor 0016, ohne heating_zone_id-Spalte)
    2. manual_override-Row anlegen
    3. Upgrade auf 0016 -> Spalte wird mit nullable=True angelegt
    4. Verify: bestehende Row hat heating_zone_id IS NULL
    """
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import create_engine, text

    from alembic import command

    command.upgrade(alembic_cfg, "head")
    command.downgrade(alembic_cfg, "0015_health_state")

    sync_url = TEST_DB_URL.replace("+asyncpg", "")
    engine = create_engine(sync_url)

    rt_id: int | None = None
    room_id: int | None = None
    override_id: int | None = None
    try:
        with engine.connect() as conn:
            rt_id = conn.execute(
                text("INSERT INTO room_type (name) VALUES ('rt_0016_null') RETURNING id")
            ).scalar_one()
            # Hinweis: Test inserted bei Revision 0015 (vor 0017),
            # daher KEIN guest_override_blocked in Spalten-Liste — Spalte
            # existiert in dieser Migrations-Stufe noch nicht.
            room_id = conn.execute(
                text(
                    "INSERT INTO room (number, room_type_id, status) "
                    "VALUES ('r-0016n', :rt, 'occupied') RETURNING id"
                ),
                {"rt": rt_id},
            ).scalar_one()
            expires_at = datetime.now(tz=UTC) + timedelta(hours=4)
            override_id = conn.execute(
                text(
                    "INSERT INTO manual_override "
                    "(room_id, setpoint, source, expires_at) "
                    "VALUES (:r, 21.0, 'frontend_4h', :exp) RETURNING id"
                ),
                {"r": room_id, "exp": expires_at},
            ).scalar_one()
            conn.commit()

        command.upgrade(alembic_cfg, "0016_manual_override_zone_id")

        with engine.connect() as conn:
            hz_id = conn.execute(
                text("SELECT heating_zone_id FROM manual_override WHERE id = :id"),
                {"id": override_id},
            ).scalar_one()

        assert hz_id is None, (
            f"Bestehende manual_override-Row sollte heating_zone_id=NULL haben, hat {hz_id!r}"
        )
    finally:
        command.upgrade(alembic_cfg, "head")
        with engine.connect() as conn:
            if override_id is not None:
                conn.execute(
                    text("DELETE FROM manual_override WHERE id = :id"),
                    {"id": override_id},
                )
            if room_id is not None:
                conn.execute(text("DELETE FROM room WHERE id = :id"), {"id": room_id})
            if rt_id is not None:
                conn.execute(text("DELETE FROM room_type WHERE id = :id"), {"id": rt_id})
            conn.commit()


@pytest.mark.skipif(not TEST_DB_URL, reason=SKIP_REASON)
def test_migration_0016_fk_set_null_on_zone_delete(alembic_cfg: Config) -> None:
    """FK ON DELETE SET NULL: Zone-Loeschung resetted heating_zone_id im Override.

    Sicherheitsnetz statt Cascade — Override-Audit bleibt erhalten, faellt
    auf Room-Scope zurueck. Catcht: falsches ondelete (CASCADE/RESTRICT
    statt SET NULL).
    """
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import create_engine, text

    from alembic import command

    command.upgrade(alembic_cfg, "head")

    sync_url = TEST_DB_URL.replace("+asyncpg", "")
    engine = create_engine(sync_url)

    rt_id: int | None = None
    room_id: int | None = None
    zone_id: int | None = None
    override_id: int | None = None
    try:
        with engine.connect() as conn:
            rt_id = conn.execute(
                text("INSERT INTO room_type (name) VALUES ('rt_0016_fk') RETURNING id")
            ).scalar_one()
            room_id = conn.execute(
                text(
                    "INSERT INTO room (number, room_type_id, status, guest_override_blocked) "
                    "VALUES ('r-0016f', :rt, 'occupied', false) RETURNING id"
                ),
                {"rt": rt_id},
            ).scalar_one()
            zone_id = conn.execute(
                text(
                    "INSERT INTO heating_zone "
                    "(room_id, kind, name, is_towel_warmer) "
                    "VALUES (:r, 'bedroom', 'zone-0016f', false) RETURNING id"
                ),
                {"r": room_id},
            ).scalar_one()
            expires_at = datetime.now(tz=UTC) + timedelta(hours=4)
            override_id = conn.execute(
                text(
                    "INSERT INTO manual_override "
                    "(room_id, heating_zone_id, setpoint, source, expires_at) "
                    "VALUES (:r, :z, 21.0, 'frontend_4h', :exp) RETURNING id"
                ),
                {"r": room_id, "z": zone_id, "exp": expires_at},
            ).scalar_one()
            conn.commit()

        # Zone loeschen — Override muss erhalten bleiben, heating_zone_id wird NULL
        with engine.connect() as conn:
            conn.execute(text("DELETE FROM heating_zone WHERE id = :id"), {"id": zone_id})
            conn.commit()
            zone_id = None  # Cleanup-Marker: bereits geloescht

            row = conn.execute(
                text("SELECT heating_zone_id FROM manual_override WHERE id = :id"),
                {"id": override_id},
            ).fetchone()

        assert row is not None, "manual_override-Row darf nicht mit-geloescht worden sein"
        assert row[0] is None, (
            f"FK ON DELETE SET NULL: heating_zone_id sollte NULL sein, ist {row[0]!r}"
        )
    finally:
        with engine.connect() as conn:
            if override_id is not None:
                conn.execute(
                    text("DELETE FROM manual_override WHERE id = :id"),
                    {"id": override_id},
                )
            if zone_id is not None:
                conn.execute(text("DELETE FROM heating_zone WHERE id = :id"), {"id": zone_id})
            if room_id is not None:
                conn.execute(text("DELETE FROM room WHERE id = :id"), {"id": room_id})
            if rt_id is not None:
                conn.execute(text("DELETE FROM room_type WHERE id = :id"), {"id": rt_id})
            conn.commit()


@pytest.mark.skipif(not TEST_DB_URL, reason=SKIP_REASON)
def test_migration_0018_atomar_auf_ab_auf(alembic_cfg: Config) -> None:
    """Migration 0018 muss upgrade -> downgrade -> upgrade ohne Fehler durchlaufen.

    Sprint 13b.1 T1 (AE-57): device-Lifecycle. Catcht:
    - vergessenes drop_constraint im downgrade (fk_device_replaced_by
      vor drop_column),
    - falsche Reihenfolge bei Constraint-Swap (Partial-Unique-Index vor
      Voll-Unique-Constraint im downgrade),
    - Backfill-Logic-Fehler im downgrade
      (``UPDATE ... WHERE retired_at IS NOT NULL`` muss VOR
      ``drop_column retired_at`` laufen).
    """
    from alembic import command

    command.upgrade(alembic_cfg, "0018_device_lifecycle")
    command.downgrade(alembic_cfg, "0019_drop_manual_setpoint_event")
    command.upgrade(alembic_cfg, "0018_device_lifecycle")
    command.upgrade(alembic_cfg, "head")


@pytest.mark.skipif(not TEST_DB_URL, reason=SKIP_REASON)
def test_migration_0018_downgrade_backfills_is_active(alembic_cfg: Config) -> None:
    """Downgrade-Backfill setzt is_active=FALSE fuer retired Devices.

    Szenario:
    1. DB auf head (0018 angewendet, kein is_active mehr).
    2. Zwei Test-Devices anlegen: eines aktiv (retired_at=NULL), eines
       retired (retired_at gesetzt).
    3. Downgrade auf 0019 (is_active wird wiederhergestellt).
    4. Verify: aktives Device hat is_active=TRUE, retired Device hat
       is_active=FALSE.

    Schuetzt §5.49-Roundtrip-Pflicht: Backfill-Logic im Downgrade muss
    inhaltlich korrekt sein, nicht nur Schema-Roundtrip.
    """
    from sqlalchemy import create_engine, text

    from alembic import command

    command.upgrade(alembic_cfg, "head")

    sync_url = TEST_DB_URL.replace("+asyncpg", "")
    engine = create_engine(sync_url)

    active_dev_id: int | None = None
    retired_dev_id: int | None = None
    try:
        with engine.connect() as conn:
            active_dev_id = conn.execute(
                text(
                    "INSERT INTO device "
                    "(dev_eui, kind, vendor, model, health_state) "
                    "VALUES ('00000000aa180001', 'thermostat', 'mclimate', "
                    "'vicki', 'silent') RETURNING id"
                )
            ).scalar_one()
            retired_dev_id = conn.execute(
                text(
                    "INSERT INTO device "
                    "(dev_eui, kind, vendor, model, health_state, "
                    "retired_at, retired_reason) "
                    "VALUES ('00000000aa180002', 'thermostat', 'mclimate', "
                    "'vicki', 'silent', NOW(), 'test_backfill') RETURNING id"
                )
            ).scalar_one()
            conn.commit()

        command.downgrade(alembic_cfg, "0019_drop_manual_setpoint_event")

        with engine.connect() as conn:
            active_is_active = conn.execute(
                text("SELECT is_active FROM device WHERE id = :id"),
                {"id": active_dev_id},
            ).scalar_one()
            retired_is_active = conn.execute(
                text("SELECT is_active FROM device WHERE id = :id"),
                {"id": retired_dev_id},
            ).scalar_one()

        assert active_is_active is True, (
            f"aktives Device sollte is_active=TRUE haben, ist {active_is_active!r}"
        )
        assert retired_is_active is False, (
            f"retired Device sollte is_active=FALSE haben "
            f"(Downgrade-Backfill), ist {retired_is_active!r}"
        )
    finally:
        command.upgrade(alembic_cfg, "head")
        with engine.connect() as conn:
            if active_dev_id is not None:
                conn.execute(
                    text("DELETE FROM device WHERE id = :id"),
                    {"id": active_dev_id},
                )
            if retired_dev_id is not None:
                conn.execute(
                    text("DELETE FROM device WHERE id = :id"),
                    {"id": retired_dev_id},
                )
            conn.commit()


@pytest.mark.skipif(not TEST_DB_URL, reason=SKIP_REASON)
def test_migration_0018_partial_unique_allows_retired_duplicates(
    alembic_cfg: Config,
) -> None:
    """Partial-Unique-Index erlaubt mehrere retired Rows mit gleicher DevEUI.

    Szenario:
    1. DB auf head (0018 angewendet).
    2. Aktives Device mit DevEUI X anlegen.
    3. Device retiren (retired_at setzen).
    4. Zweites aktives Device mit derselben DevEUI X anlegen.
    5. Verify: zweites Insert klappt (Partial-Unique-Index greift nur
       fuer retired_at IS NULL).

    Schuetzt AE-57 Entscheidung 1: DevEUI-Wiederverwendung nach Retire
    moeglich; Eindeutigkeit nur unter aktiven Rows.
    """
    from sqlalchemy import create_engine, text

    from alembic import command

    command.upgrade(alembic_cfg, "head")

    sync_url = TEST_DB_URL.replace("+asyncpg", "")
    engine = create_engine(sync_url)

    dup_dev_eui = "00000000aa180003"
    first_id: int | None = None
    second_id: int | None = None
    try:
        with engine.connect() as conn:
            first_id = conn.execute(
                text(
                    "INSERT INTO device "
                    "(dev_eui, kind, vendor, model, health_state) "
                    "VALUES (:eui, 'thermostat', 'mclimate', 'vicki', "
                    "'silent') RETURNING id"
                ),
                {"eui": dup_dev_eui},
            ).scalar_one()
            conn.execute(
                text(
                    "UPDATE device SET retired_at = NOW(), "
                    "retired_reason = 'test_partial_unique' WHERE id = :id"
                ),
                {"id": first_id},
            )
            second_id = conn.execute(
                text(
                    "INSERT INTO device "
                    "(dev_eui, kind, vendor, model, health_state) "
                    "VALUES (:eui, 'thermostat', 'mclimate', 'vicki', "
                    "'silent') RETURNING id"
                ),
                {"eui": dup_dev_eui},
            ).scalar_one()
            conn.commit()

        assert first_id is not None
        assert second_id is not None
        assert first_id != second_id, (
            "Zwei Device-Rows mit gleichem DevEUI muessen unterschiedliche "
            "IDs haben (eine retired, eine aktiv)."
        )
    finally:
        with engine.connect() as conn:
            if second_id is not None:
                conn.execute(
                    text("DELETE FROM device WHERE id = :id"),
                    {"id": second_id},
                )
            if first_id is not None:
                conn.execute(
                    text("DELETE FROM device WHERE id = :id"),
                    {"id": first_id},
                )
            conn.commit()


@pytest.mark.skipif(not TEST_DB_URL, reason=SKIP_REASON)
def test_migration_0020_atomar_auf_ab_auf(alembic_cfg: Config) -> None:
    """Migration 0020 muss upgrade -> downgrade -> upgrade ohne Fehler durchlaufen.

    Sprint 14a (D1): device.hardware_number additiv + Partial-Unique-Index.
    Catcht: vergessenes drop_index im downgrade, falsche Reihenfolge
    (Index vor Column), Idempotenz bei Re-Run. Downgrade-Ziel ist
    ``0018_device_lifecycle`` (echter Vorgaenger-Head, siehe
    Migrations-Datei-Docstring).
    """
    from alembic import command

    command.upgrade(alembic_cfg, "0020_device_hardware_number")
    command.downgrade(alembic_cfg, "0018_device_lifecycle")
    command.upgrade(alembic_cfg, "0020_device_hardware_number")
    command.upgrade(alembic_cfg, "head")


@pytest.mark.skipif(not TEST_DB_URL, reason=SKIP_REASON)
def test_migration_0020_unique_rejects_duplicate_hardware_number(
    alembic_cfg: Config,
) -> None:
    """Partial-Unique-Index blockt zwei aktive Rows mit gleicher hardware_number.

    Szenario:
    1. DB auf head (0020 angewendet).
    2. Device mit hardware_number='MDC5419731K6UF' anlegen.
    3. Zweites Device (anderer DevEUI!) mit derselben hardware_number ->
       IntegrityError (UNIQUE-Verletzung auf ix_device_hardware_number_unique).

    DevEUIs bewusst unterschiedlich, damit nicht der DevEUI-Partial-Unique
    aus 0018 zuerst greift.
    """
    from sqlalchemy import create_engine, text
    from sqlalchemy.exc import IntegrityError

    from alembic import command

    command.upgrade(alembic_cfg, "head")

    sync_url = TEST_DB_URL.replace("+asyncpg", "")
    engine = create_engine(sync_url)

    hw_number = "MDC5419731K6UF"
    try:
        with engine.connect() as conn:
            conn.execute(
                text(
                    "INSERT INTO device "
                    "(dev_eui, kind, vendor, model, health_state, hardware_number) "
                    "VALUES ('00000000aa200001', 'thermostat', 'mclimate', "
                    "'vicki', 'silent', :hw)"
                ),
                {"hw": hw_number},
            )
            conn.commit()

        with engine.connect() as conn, pytest.raises(IntegrityError):
            conn.execute(
                text(
                    "INSERT INTO device "
                    "(dev_eui, kind, vendor, model, health_state, hardware_number) "
                    "VALUES ('00000000aa200002', 'thermostat', 'mclimate', "
                    "'vicki', 'silent', :hw)"
                ),
                {"hw": hw_number},
            )
            conn.commit()
    finally:
        with engine.connect() as conn:
            conn.execute(
                text("DELETE FROM device WHERE hardware_number = :hw"),
                {"hw": hw_number},
            )
            conn.commit()


@pytest.mark.skipif(not TEST_DB_URL, reason=SKIP_REASON)
def test_migration_0020_allows_multiple_null_hardware_number(
    alembic_cfg: Config,
) -> None:
    """Partial-Unique-Index erlaubt beliebig viele Rows mit hardware_number IS NULL.

    Bestands-Vickis ohne erfasste Nummer duerfen koexistieren — Eindeutigkeit
    gilt nur fuer gesetzte Werte (``WHERE hardware_number IS NOT NULL``).
    """
    from sqlalchemy import create_engine, text

    from alembic import command

    command.upgrade(alembic_cfg, "head")

    sync_url = TEST_DB_URL.replace("+asyncpg", "")
    engine = create_engine(sync_url)

    first_id: int | None = None
    second_id: int | None = None
    try:
        with engine.connect() as conn:
            first_id = conn.execute(
                text(
                    "INSERT INTO device "
                    "(dev_eui, kind, vendor, model, health_state) "
                    "VALUES ('00000000aa200003', 'thermostat', 'mclimate', "
                    "'vicki', 'silent') RETURNING id"
                )
            ).scalar_one()
            second_id = conn.execute(
                text(
                    "INSERT INTO device "
                    "(dev_eui, kind, vendor, model, health_state) "
                    "VALUES ('00000000aa200004', 'thermostat', 'mclimate', "
                    "'vicki', 'silent') RETURNING id"
                )
            ).scalar_one()
            conn.commit()

        assert first_id is not None
        assert second_id is not None
        assert first_id != second_id, (
            "Zwei Device-Rows mit hardware_number=NULL muessen koexistieren."
        )
    finally:
        with engine.connect() as conn:
            for dev_id in (second_id, first_id):
                if dev_id is not None:
                    conn.execute(
                        text("DELETE FROM device WHERE id = :id"),
                        {"id": dev_id},
                    )
            conn.commit()
