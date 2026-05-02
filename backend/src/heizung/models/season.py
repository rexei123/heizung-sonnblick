"""Saison-Zeitraum mit Override-Faehigkeit fuer rule_config-Eintraege.

Eine Saison ist ein Datums-Zeitraum (z.B. "Skisaison 2026/27", "Sommerpause").
``rule_config``-Eintraege koennen optional einer Saison zugeordnet werden
(``rule_config.season_id``). Solche Eintraege gelten dann NUR im Saison-Zeitraum
und ueberschreiben die permanenten Settings (AE-26).

Konflikt-Aufloesung bei mehreren aktiven Saisons fuer ein Datum: spaeteres
``starts_on`` gewinnt; bei Gleichstand hoechste ``id`` (AE-33).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Index,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from heizung.db import Base

if TYPE_CHECKING:
    from heizung.models.rule_config import RuleConfig
    from heizung.models.scenario_assignment import ScenarioAssignment


class Season(Base):
    __tablename__ = "season"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)

    starts_on: Mapped[date] = mapped_column(Date, nullable=False)
    ends_on: Mapped[date] = mapped_column(Date, nullable=False)

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    notes: Mapped[str | None] = mapped_column(String(1000))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    rule_configs: Mapped[list[RuleConfig]] = relationship(back_populates="season")
    scenario_assignments: Mapped[list[ScenarioAssignment]] = relationship(back_populates="season")

    __table_args__ = (
        # starts_on darf nicht nach ends_on liegen
        CheckConstraint("starts_on <= ends_on", name="ck_season_dates_ordered"),
        # Index fuer Engine-Lookup "welche Saisons sind heute aktiv"
        Index("ix_season_active_range", "is_active", "starts_on", "ends_on"),
    )
