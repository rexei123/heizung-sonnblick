"""Enums für das Domain-Model.

Alle Enums werden als String-Enums in PostgreSQL gespeichert
(native_enum=False), damit spätere Erweiterungen via Migration einfach sind.

Bei SQLAlchemy-``Enum``-Spalten muss ``values_callable=_enum_values``
gesetzt werden, damit die ``.value`` (lowercase-Strings) persistiert
werden — nicht die Python-``.name`` (UPPERCASE).
"""

import enum
from collections.abc import Iterable


def _enum_values(enum_cls: Iterable[enum.Enum]) -> list[str]:
    """Helper für ``sa.Enum(..., values_callable=_enum_values)``.

    SQLAlchemy liefert die Enum-Klasse selbst als Iterable der Member.
    """
    return [member.value for member in enum_cls]


class RoomStatus(enum.StrEnum):
    """Operativer Status eines Zimmers.

    OCCUPIED und RESERVED steuern Vorheizen/Absenken, CLEANING hält
    komfortabel, BLOCKED setzt den Raum aus der Regel-Engine heraus
    (nur Frostschutz aktiv).
    """

    VACANT = "vacant"
    OCCUPIED = "occupied"
    RESERVED = "reserved"
    CLEANING = "cleaning"
    BLOCKED = "blocked"


class HeatingZoneKind(enum.StrEnum):
    """Funktionaler Zonen-Typ. Steuert teilweise Regel-Defaults."""

    BEDROOM = "bedroom"
    BATHROOM = "bathroom"
    LIVING = "living"
    HALLWAY = "hallway"
    OTHER = "other"


class Orientation(enum.StrEnum):
    """Himmelsrichtung der Außenfassade. Für spätere KI-Optimierung
    (solare Gewinne bei Südzimmern)."""

    NORTH = "N"
    NORTH_EAST = "NE"
    EAST = "E"
    SOUTH_EAST = "SE"
    SOUTH = "S"
    SOUTH_WEST = "SW"
    WEST = "W"
    NORTH_WEST = "NW"


class DeviceKind(enum.StrEnum):
    THERMOSTAT = "thermostat"
    SENSOR = "sensor"


class DeviceVendor(enum.StrEnum):
    """Hersteller — relevant für den passenden Treiber in der
    Geräte-Abstraktionsschicht."""

    MCLIMATE = "mclimate"
    MILESIGHT = "milesight"
    MANUAL = "manual"  # Platzhalter für manuelle Eingabe / Tests


class OccupancySource(enum.StrEnum):
    MANUAL = "manual"
    PMS = "pms"


class RuleConfigScope(enum.StrEnum):
    """Gültigkeitsbereich einer Regelkonfiguration.

    Auflösung bei Regel-Evaluierung: ROOM > ROOM_TYPE > GLOBAL > hardcoded.
    """

    GLOBAL = "global"
    ROOM_TYPE = "room_type"
    ROOM = "room"


class CommandReason(enum.StrEnum):
    """Warum wurde ein Steuerbefehl erzeugt. Reine Audit-Information."""

    OCCUPIED_SETPOINT = "occupied_setpoint"
    VACANT_SETPOINT = "vacant_setpoint"
    NIGHT_SETBACK = "night_setback"
    PREHEAT_CHECKIN = "preheat_checkin"
    CHECKOUT_SETBACK = "checkout_setback"
    WINDOW_OPEN = "window_open"
    GUEST_OVERRIDE = "guest_override"
    LONG_VACANT = "long_vacant"
    FROST_PROTECTION = "frost_protection"
    MANUAL = "manual"
