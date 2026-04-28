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
    }
    actual_tables = set(Base.metadata.tables.keys())
    missing = expected_tables - actual_tables
    assert not missing, f"Fehlende Tabellen in metadata: {missing}"


def test_room_has_expected_relationships() -> None:
    """Quick-Check der Beziehungen — catcht typische Tippfehler in back_populates."""
    from heizung.models import Room

    rel_names = {r.key for r in Room.__mapper__.relationships}
    for expected in {"room_type", "heating_zones", "occupancies", "rule_configs"}:
        assert expected in rel_names, f"Room fehlt Beziehung: {expected}"


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
