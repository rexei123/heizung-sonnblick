"""Aktivierung eines Szenarios pro Scope (global, Raumtyp, Raum).

Ein Eintrag = "Szenario X ist aktiv im Scope Y mit Parametern Z".
Pro Saison kann der Eintrag zusaetzlich saisonal limitiert werden
(``season_id``).

Resolution-Reihenfolge bei der Engine-Auswertung (gemaess AE-27):
    Saison-spezifisch ROOM > Saison-spezifisch ROOM_TYPE > Saison-spezifisch GLOBAL
    > Permanent ROOM > Permanent ROOM_TYPE > Permanent GLOBAL
    > scenario.default_active

Die ``parameters``-JSONB enthaelt die Override-Werte gegenueber
``scenario.default_parameters``. Validiert via Pydantic-Schema beim
Anlegen, nicht in der DB.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    UniqueConstraint,
    func,
)
from sqlalchemy import (
    Enum as SQLEnum,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from heizung.db import Base
from heizung.models.enums import ScenarioScope, _enum_values

if TYPE_CHECKING:
    from heizung.models.room import Room
    from heizung.models.room_type import RoomType
    from heizung.models.scenario import Scenario
    from heizung.models.season import Season


class ScenarioAssignment(Base):
    __tablename__ = "scenario_assignment"

    id: Mapped[int] = mapped_column(primary_key=True)

    scenario_id: Mapped[int] = mapped_column(
        ForeignKey("scenario.id", ondelete="CASCADE"), nullable=False
    )

    scope: Mapped[ScenarioScope] = mapped_column(
        SQLEnum(
            ScenarioScope,
            name="scenario_scope",
            native_enum=False,
            length=20,
            values_callable=_enum_values,
        ),
        nullable=False,
    )
    room_type_id: Mapped[int | None] = mapped_column(
        ForeignKey("room_type.id", ondelete="CASCADE")
    )
    room_id: Mapped[int | None] = mapped_column(ForeignKey("room.id", ondelete="CASCADE"))

    # Optional saisonal limitiert (NULL = ganzjaehrig)
    season_id: Mapped[int | None] = mapped_column(ForeignKey("season.id", ondelete="CASCADE"))

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # Override-Parameter gegenueber scenario.default_parameters.
    # Validiert in der Service-Layer gegen scenario.parameter_schema.
    parameters: Mapped[dict | None] = mapped_column(JSONB)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    scenario: Mapped[Scenario] = relationship(back_populates="assignments")
    room_type: Mapped[RoomType | None] = relationship(back_populates="scenario_assignments")
    room: Mapped[Room | None] = relationship(back_populates="scenario_assignments")
    season: Mapped[Season | None] = relationship(back_populates="scenario_assignments")

    __table_args__ = (
        # Scope-Konsistenz (gleiches Pattern wie rule_config)
        CheckConstraint(
            "(scope = 'global' AND room_type_id IS NULL AND room_id IS NULL)"
            " OR (scope = 'room_type' AND room_type_id IS NOT NULL AND room_id IS NULL)"
            " OR (scope = 'room' AND room_id IS NOT NULL AND room_type_id IS NULL)",
            name="ck_scenario_assignment_scope_consistency",
        ),
        # Eindeutig pro Szenario+Scope+Saison
        UniqueConstraint(
            "scenario_id",
            "scope",
            "room_type_id",
            "room_id",
            "season_id",
            name="uq_scenario_assignment_scope_target",
        ),
        # Index fuer Engine-Lookup pro Szenario
        Index("ix_scenario_assignment_scenario_active", "scenario_id", "is_active"),
    )
