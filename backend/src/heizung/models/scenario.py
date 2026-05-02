"""Szenario-Stammdaten (Stammtabelle, NICHT die Aktivierung).

Ein Szenario ist ein **Konzept**, das die Engine kennt — z.B. "Tagabsenkung",
"Realtime Check-in". Die tatsaechliche Aktivierung pro Hotel/Raumtyp/Raum
liegt in ``scenario_assignment`` (AE-27).

System-Szenarien (``is_system=True``) werden vom Seed-Skript angelegt und
duerfen NICHT von Hoteliers geloescht werden — die Engine-Logik kennt deren
``code``. Custom-Szenarien (Phase 2) bekommen ``is_system=False``.

Das ``parameter_schema``-Feld ist ein Zod-aequivalentes JSON-Schema, das
beschreibt welche Parameter pro Aktivierung erlaubt sind. Validierung
passiert in der Pydantic-Layer beim Aktivieren (nicht hier in der DB).
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    DateTime,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from heizung.db import Base

if TYPE_CHECKING:
    from heizung.models.scenario_assignment import ScenarioAssignment


class Scenario(Base):
    __tablename__ = "scenario"

    id: Mapped[int] = mapped_column(primary_key=True)

    # Eindeutiger Code, von Engine-Logik referenziert (z.B. "day_setback").
    # snake_case, max 50 Zeichen. Nicht aenderbar nach Anlage.
    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)

    # Anzeigename in der UI (deutsch, Hotelier-freundlich).
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(String(1000))

    # System-Stammdaten (mitgeliefert) vs. Custom (Phase 2).
    is_system: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Default-Aktivierung wenn kein scenario_assignment-Eintrag existiert.
    # Beispiel: "frost_protection" hat default_active=True (immer an).
    default_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # JSON-Schema (Zod-aequivalent) fuer erlaubte Parameter pro Aktivierung.
    # Beispiel fuer "day_setback":
    #   {"type":"object", "properties":{
    #      "from_time":{"type":"string","format":"time"},
    #      "to_time":{"type":"string","format":"time"},
    #      "offset_celsius":{"type":"number","minimum":-10,"maximum":0}
    #   }, "required":["from_time","to_time","offset_celsius"]}
    parameter_schema: Mapped[dict | None] = mapped_column(JSONB)

    # Default-Parameter (werden beim Anlegen einer Activation als Vorlage genommen).
    default_parameters: Mapped[dict | None] = mapped_column(JSONB)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    assignments: Mapped[list[ScenarioAssignment]] = relationship(
        back_populates="scenario", cascade="all, delete-orphan"
    )
