"""Seed-Skript: minimale Startdaten für das System.

Idempotent — bereits vorhandene Datensätze werden übersprungen.
Aufruf:

    python -m heizung.seed

Wird im Deployment einmalig manuell ausgeführt. Spätere Änderungen
laufen über das Admin-UI.

Annahmen (im MVP austauschbar):
  - 45 Zimmer verteilt auf 3 Stockwerke (101–115, 201–215, 301–315)
  - Alle als Doppelzimmer angelegt — im UI einzeln änderbar
  - Je 2 Heizzonen pro Zimmer (Schlafbereich, Bad mit Handtuchtrockner)
  - Orientation rotierend Nord/Süd/Ost/West
"""

from __future__ import annotations

import asyncio
import logging
from datetime import time
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from heizung.db import SessionLocal
from heizung.models import (
    HeatingZone,
    HeatingZoneKind,
    Orientation,
    Room,
    RoomStatus,
    RoomType,
    RuleConfig,
    RuleConfigScope,
    Scenario,
)

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


# Rotierende Orientation für die 45 Zimmer — Platzhalter bis echte
# Daten aus dem Grundriss eingepflegt sind.
_ORIENTATION_CYCLE: list[Orientation] = [
    Orientation.SOUTH,
    Orientation.EAST,
    Orientation.NORTH,
    Orientation.WEST,
]


async def _seed_room_types(session: AsyncSession) -> dict[str, RoomType]:
    """Standard-Raumtypen anlegen. Weitere Typen können im UI hinzugefügt werden."""
    definitions: list[dict[str, Any]] = [
        {
            "name": "Doppelzimmer",
            "description": "Standard-Zweibettzimmer mit Bad.",
            "is_bookable": True,
            "default_t_occupied": Decimal("21.0"),
            "default_t_vacant": Decimal("18.0"),
            "default_t_night": Decimal("19.0"),
        },
        {
            "name": "Einzelzimmer",
            "description": "Einzelzimmer mit Bad.",
            "is_bookable": True,
            "default_t_occupied": Decimal("21.0"),
            "default_t_vacant": Decimal("18.0"),
            "default_t_night": Decimal("19.0"),
        },
        {
            "name": "Suite",
            "description": "Größere Einheit mit getrenntem Wohnbereich.",
            "is_bookable": True,
            "default_t_occupied": Decimal("21.0"),
            "default_t_vacant": Decimal("18.0"),
            "default_t_night": Decimal("19.0"),
        },
    ]
    result: dict[str, RoomType] = {}
    for defn in definitions:
        existing = await session.scalar(select(RoomType).where(RoomType.name == defn["name"]))
        if existing:
            result[defn["name"]] = existing
            logger.info("RoomType '%s' existiert bereits — übersprungen.", defn["name"])
            continue
        room_type = RoomType(**defn)
        session.add(room_type)
        await session.flush()
        result[defn["name"]] = room_type
        logger.info("RoomType '%s' angelegt (id=%d).", defn["name"], room_type.id)
    return result


async def _seed_global_rule(session: AsyncSession) -> None:
    """Globale Default-Regel für alle 8 Kernregeln (Sprint 2-MVP-Werte)."""
    existing = await session.scalar(
        select(RuleConfig).where(RuleConfig.scope == RuleConfigScope.GLOBAL)
    )
    if existing:
        logger.info("Globale RuleConfig existiert bereits — übersprungen.")
        return

    rule = RuleConfig(
        scope=RuleConfigScope.GLOBAL,
        t_occupied=Decimal("21.0"),
        t_vacant=Decimal("18.0"),
        t_night=Decimal("19.0"),
        night_start=time(0, 0),
        night_end=time(6, 0),
        preheat_minutes_before_checkin=90,
        setback_minutes_after_checkout=30,
        long_vacant_hours=24,
        t_long_vacant=Decimal("15.0"),
        guest_override_min=Decimal("19.0"),
        guest_override_max=Decimal("24.0"),
        guest_override_duration_minutes=240,
        window_open_drop_celsius=Decimal("2.0"),
        window_open_window_minutes=5,
    )
    session.add(rule)
    await session.flush()
    logger.info("Globale RuleConfig angelegt (id=%d).", rule.id)


async def _seed_rooms(session: AsyncSession, dz: RoomType) -> None:
    """45 Doppelzimmer verteilt auf 3 Stockwerke."""
    created = 0
    skipped = 0
    for floor in (1, 2, 3):
        for idx in range(1, 16):  # 15 Zimmer pro Stockwerk
            number = f"{floor}{idx:02d}"  # 101, 102, ..., 115, 201, ...
            existing = await session.scalar(select(Room).where(Room.number == number))
            if existing:
                skipped += 1
                continue
            orientation = _ORIENTATION_CYCLE[(floor * 15 + idx) % len(_ORIENTATION_CYCLE)]
            room = Room(
                number=number,
                display_name=f"Zimmer {number}",
                room_type_id=dz.id,
                floor=floor,
                orientation=orientation,
                status=RoomStatus.VACANT,
            )
            session.add(room)
            await session.flush()

            session.add_all(
                [
                    HeatingZone(
                        room_id=room.id,
                        kind=HeatingZoneKind.BEDROOM,
                        name="Schlafbereich",
                        is_towel_warmer=False,
                    ),
                    HeatingZone(
                        room_id=room.id,
                        kind=HeatingZoneKind.BATHROOM,
                        name="Bad",
                        is_towel_warmer=True,
                    ),
                ]
            )
            created += 1
    logger.info(
        "Zimmer-Seed abgeschlossen: %d neu angelegt, %d übersprungen.",
        created,
        skipped,
    )


async def _seed_system_scenarios(session: AsyncSession) -> None:
    """8 System-Szenarien als Stammdaten anlegen (Sprint 8 / AE-27).

    Diese Szenarien sind ``is_system=True`` — duerfen nicht via API
    veraendert oder geloescht werden. Engine-Logik referenziert die
    ``code``-Werte hart in heizung.rules (Sprint 9).
    """
    definitions: list[dict[str, Any]] = [
        {
            "code": "standard_setpoint",
            "name": "Standard-Wunschtemperatur",
            "description": (
                "Belegungsabhaengiger Standard-Sollwert (R1). Bei besetzt "
                "T_belegt, bei frei T_vacant — aus rule_config-Hierarchie."
            ),
            "default_active": True,
            "default_parameters": None,
        },
        {
            "code": "preheat_checkin",
            "name": "Vorheizen vor Check-in",
            "description": (
                "Vor geplanter Anreise wird der Raum auf T_belegt vorgeheizt (R2). "
                "Lead-Time aus rule_config.preheat_minutes_before_checkin (Default 90 Min)."
            ),
            "default_active": True,
            "default_parameters": {"lead_minutes": 90},
        },
        {
            "code": "checkout_setback",
            "name": "Absenkung nach Check-out",
            "description": (
                "Nach bestaetigtem Check-out auf T_vacant absenken (R3). "
                "Verzoegerung aus rule_config.setback_minutes_after_checkout."
            ),
            "default_active": True,
            "default_parameters": {"delay_minutes": 30},
        },
        {
            "code": "night_setback",
            "name": "Nachtabsenkung",
            "description": (
                "In definiertem Nachtfenster auf T_night reduzieren (R4). "
                "Default 00:00-06:00 auf 19 °C."
            ),
            "default_active": True,
            "default_parameters": {"from_time": "00:00", "to_time": "06:00"},
        },
        {
            "code": "day_setback",
            "name": "Tagabsenkung",
            "description": (
                "In definiertem Tagfenster Offset oder Absoluttemp anwenden (R9, "
                "Betterspace-konform). Default-Off — Hotelier muss bewusst aktivieren."
            ),
            "default_active": False,
            "default_parameters": {
                "from_time": "09:00",
                "to_time": "15:00",
                "offset_celsius": -2,
            },
        },
        {
            "code": "long_vacant",
            "name": "Unbelegt-Langzeit-Absenkung",
            "description": (
                "Nach laengerer Leerstand-Phase auf T_long_vacant reduzieren (R7). "
                "Schwelle aus rule_config.long_vacant_hours (Default 24h)."
            ),
            "default_active": True,
            "default_parameters": {"after_hours": 24},
        },
        {
            "code": "window_detection",
            "name": "Fenster-offen-Erkennung",
            "description": (
                "Bei Vicki-Fenster-offen-Meldung Setpoint auf Frostschutz, "
                "automatische Rueckkehr nach Schliessen (R5, AE-04)."
            ),
            "default_active": True,
            "default_parameters": None,
        },
        {
            "code": "temp_limits",
            "name": "Temperaturgrenzen (Gast-Override-Cap)",
            "description": (
                "Manueller Gast-Override am Vicki wird auf [min, max] geclamped (R6, "
                "AE-10). Grenzen aus rule_config.guest_override_min/max."
            ),
            "default_active": True,
            "default_parameters": None,
        },
    ]
    created = 0
    skipped = 0
    for defn in definitions:
        existing = await session.scalar(select(Scenario).where(Scenario.code == defn["code"]))
        if existing:
            skipped += 1
            continue
        scenario = Scenario(
            code=defn["code"],
            name=defn["name"],
            description=defn["description"],
            is_system=True,
            default_active=defn["default_active"],
            parameter_schema=None,  # Validierung in Service-Layer (Sprint 10)
            default_parameters=defn["default_parameters"],
        )
        session.add(scenario)
        created += 1
    await session.flush()
    logger.info(
        "System-Szenarien-Seed abgeschlossen: %d neu, %d uebersprungen.",
        created,
        skipped,
    )


async def seed() -> None:
    async with SessionLocal() as session, session.begin():
        room_types = await _seed_room_types(session)
        await _seed_global_rule(session)
        await _seed_rooms(session, room_types["Doppelzimmer"])
        await _seed_system_scenarios(session)
    logger.info("Seed fertig.")


def main() -> None:
    asyncio.run(seed())


if __name__ == "__main__":
    main()
