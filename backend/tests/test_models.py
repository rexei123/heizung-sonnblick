"""Smoke-Tests für ORM-Modelle.

Integration-Tests gegen eine echte Postgres-Instanz folgen in Sprint 3,
sobald pytest-postgres / testcontainers eingerichtet sind. Hier nur
Basis-Checks, die ohne DB-Verbindung laufen.
"""

from __future__ import annotations


def test_all_models_importable() -> None:
    """Wenn das durchläuft, sind alle Enum- und Modell-Dateien syntaktisch OK
    und Base.metadata ist korrekt befüllt."""
    import heizung.models as models

    expected_classes = {
        "RoomType",
        "Room",
        "HeatingZone",
        "Device",
        "Occupancy",
        "RuleConfig",
        "SensorReading",
        "ControlCommand",
        # Sprint 8 (AE-26 bis AE-31)
        "Season",
        "Scenario",
        "ScenarioAssignment",
        "GlobalConfig",
        "ManualSetpointEvent",
        "EventLog",
    }
    exported = set(models.__all__)
    missing = expected_classes - exported
    assert not missing, f"Fehlende Klassen im __all__: {missing}"


def test_metadata_contains_all_tables() -> None:
    """Base.metadata muss die 8 Kern-Tabellen kennen."""
    import heizung.models  # noqa: F401 — registriert die Mapper
    from heizung.db import Base

    expected_tables = {
        "room_type",
        "room",
        "heating_zone",
        "device",
        "occupancy",
        "rule_config",
        "sensor_reading",
        "control_command",
        # Sprint 8
        "season",
        "scenario",
        "scenario_assignment",
        "global_config",
        "manual_setpoint_event",
        "event_log",
    }
    actual_tables = set(Base.metadata.tables.keys())
    missing = expected_tables - actual_tables
    assert not missing, f"Fehlende Tabellen in metadata: {missing}"


def test_room_has_expected_relationships() -> None:
    """Quick-Check der Beziehungen — catcht typische Tippfehler in back_populates."""
    from heizung.models import Room

    rel_names = {r.key for r in Room.__mapper__.relationships}
    for expected in {
        "room_type",
        "heating_zones",
        "occupancies",
        "rule_configs",
        "scenario_assignments",
        "manual_setpoint_events",
    }:
        assert expected in rel_names, f"Room fehlt Beziehung: {expected}"


def test_room_type_has_sprint8_columns() -> None:
    """Sprint 8 hat room_type um 3 Override-Spalten erweitert (AE-30)."""
    from heizung.models import RoomType

    cols = {c.name for c in RoomType.__table__.columns}
    for expected in {
        "max_temp_celsius",
        "min_temp_celsius",
        "treat_unoccupied_as_vacant_after_hours",
    }:
        assert expected in cols, f"room_type fehlt Spalte: {expected}"


def test_rule_config_has_season_id() -> None:
    """Saison-Resolution-Spalte aus AE-26 muss da sein."""
    from sqlalchemy import UniqueConstraint

    from heizung.models import RuleConfig

    cols = {c.name for c in RuleConfig.__table__.columns}
    assert "season_id" in cols

    # UniqueConstraint muss season_id enthalten
    for con in RuleConfig.__table__.constraints:
        if isinstance(con, UniqueConstraint) and con.name == "uq_rule_config_scope_target":
            uq_cols = {c.name for c in con.columns}
            assert uq_cols == {"scope", "room_type_id", "room_id", "season_id"}
            return
    raise AssertionError("uq_rule_config_scope_target nicht gefunden")


def test_global_config_singleton_constraint() -> None:
    """global_config muss CHECK (id = 1) haben."""
    from sqlalchemy import CheckConstraint

    from heizung.models import GlobalConfig

    check_names = {
        c.name for c in GlobalConfig.__table__.constraints if isinstance(c, CheckConstraint)
    }
    assert "ck_global_config_singleton" in check_names


def test_event_log_composite_pk() -> None:
    """event_log ist Hypertable mit 4-spaltigem Composite-PK (time + room + eval + layer)."""
    from heizung.models import EventLog

    pk_cols = [c.name for c in EventLog.__table__.columns if c.primary_key]
    assert pk_cols == ["time", "room_id", "evaluation_id", "layer"]


def test_scenario_assignment_scope_consistency_check() -> None:
    """ScenarioAssignment muss scope-FK-Konsistenz erzwingen (AE-27)."""
    from sqlalchemy import CheckConstraint

    from heizung.models import ScenarioAssignment

    check_names = {
        c.name for c in ScenarioAssignment.__table__.constraints if isinstance(c, CheckConstraint)
    }
    assert "ck_scenario_assignment_scope_consistency" in check_names


def test_manual_setpoint_event_temp_range() -> None:
    """ManualSetpointEvent erlaubt nur 5.0 - 30.0 °C in der DB (Defense-in-Depth)."""
    from sqlalchemy import CheckConstraint

    from heizung.models import ManualSetpointEvent

    check_names = {
        c.name for c in ManualSetpointEvent.__table__.constraints if isinstance(c, CheckConstraint)
    }
    assert "ck_manual_setpoint_event_temp_range" in check_names
    assert "ck_manual_setpoint_event_time_ordered" in check_names


def test_season_dates_ordered_check() -> None:
    """Season starts_on darf nicht nach ends_on liegen."""
    from sqlalchemy import CheckConstraint

    from heizung.models import Season

    check_names = {c.name for c in Season.__table__.constraints if isinstance(c, CheckConstraint)}
    assert "ck_season_dates_ordered" in check_names


def test_rule_config_check_constraint_present() -> None:
    """Der Scope-Konsistenz-CheckConstraint muss in den Table-Args sein."""
    from sqlalchemy import CheckConstraint

    from heizung.models import RuleConfig

    check_names = {
        c.name for c in RuleConfig.__table__.constraints if isinstance(c, CheckConstraint)
    }
    assert "ck_rule_config_scope_consistency" in check_names


def test_enum_values_are_strings() -> None:
    """Alle Enum-Werte müssen lowercase-Strings sein — matcht das Schema."""
    from heizung.models import RoomStatus, RuleConfigScope

    for value in RoomStatus:
        assert isinstance(value.value, str)
        assert value.value == value.value.lower()
    for value in RuleConfigScope:
        assert isinstance(value.value, str)
