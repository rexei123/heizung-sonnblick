"""Szenario-Engine-Auflösung (Sprint 9.16, AE-49).

Heute nur ein einziges aktivierbares Szenario: ``summer_mode``. Layer 0
der Engine liest seinen Aktivierungsstatus ueber den Helper
``is_summer_mode_active`` aus ``scenario_assignment`` (scope=global).

Weitere Szenarien (Tagabsenkung, Wartung, etc.) und Auflösung pro
Raum/Raumtyp folgen mit Sprint 9.16b nach erstem Winter mit Live-Daten.
Bis dahin: keine generische ``is_scenario_active(code, room_id)``-API,
sondern bewusst nur dieser Single-Purpose-Helper.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select

from heizung.models.enums import ScenarioScope
from heizung.models.scenario import Scenario
from heizung.models.scenario_assignment import ScenarioAssignment

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


SUMMER_MODE_CODE = "summer_mode"


async def is_summer_mode_active(session: AsyncSession) -> bool:
    """Liefert True, wenn ``scenario_assignment(code='summer_mode',
    scope='global', is_active=True)`` existiert.

    Singleton-Semantik: pro Code+Scope+Saison ist nur eine Row erlaubt
    (UNIQUE-Constraint). Eine fehlende oder ``is_active=False``-Row
    bedeutet: Sommermodus ist aus.
    """
    stmt = (
        select(ScenarioAssignment.id)
        .join(Scenario, Scenario.id == ScenarioAssignment.scenario_id)
        .where(Scenario.code == SUMMER_MODE_CODE)
        .where(ScenarioAssignment.scope == ScenarioScope.GLOBAL)
        .where(ScenarioAssignment.room_type_id.is_(None))
        .where(ScenarioAssignment.room_id.is_(None))
        .where(ScenarioAssignment.season_id.is_(None))
        .where(ScenarioAssignment.is_active.is_(True))
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none() is not None
