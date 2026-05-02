"""Regel-Konfiguration auf drei Ebenen (global, Raumtyp, Zimmer).

Ein RuleConfig-Eintrag enthält beliebige Teilmengen der Regel-Parameter.
NULL-Spalten bedeuten: "erbt von höherem Scope".

Auflösungsreihenfolge bei der Regel-Auswertung:
    ROOM > ROOM_TYPE > GLOBAL > hardcoded Default

Hardcoded Defaults stehen in ``heizung.rules.defaults`` (Sprint 3).
Frostschutz (10 °C) ist KEIN Regel-Parameter, sondern Systemkonstante.
"""

from __future__ import annotations

from datetime import datetime, time
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    Time,
    UniqueConstraint,
    func,
)
from sqlalchemy import (
    Enum as SQLEnum,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from heizung.db import Base
from heizung.models.enums import RuleConfigScope, _enum_values

if TYPE_CHECKING:
    from heizung.models.room import Room
    from heizung.models.room_type import RoomType
    from heizung.models.season import Season


class RuleConfig(Base):
    __tablename__ = "rule_config"

    id: Mapped[int] = mapped_column(primary_key=True)

    scope: Mapped[RuleConfigScope] = mapped_column(
        SQLEnum(
            RuleConfigScope,
            name="rule_config_scope",
            native_enum=False,
            length=20,
            values_callable=_enum_values,
        ),
        nullable=False,
    )
    room_type_id: Mapped[int | None] = mapped_column(ForeignKey("room_type.id", ondelete="CASCADE"))
    room_id: Mapped[int | None] = mapped_column(ForeignKey("room.id", ondelete="CASCADE"))

    # Sprint 8 (AE-26): optional saisonal limitiert.
    # NULL = permanente Settings, sonst gilt nur im Saison-Zeitraum.
    season_id: Mapped[int | None] = mapped_column(ForeignKey("season.id", ondelete="CASCADE"))

    # Temperatur-Sollwerte (NULL = erben)
    t_occupied: Mapped[Decimal | None] = mapped_column(Numeric(4, 1))
    t_vacant: Mapped[Decimal | None] = mapped_column(Numeric(4, 1))
    t_night: Mapped[Decimal | None] = mapped_column(Numeric(4, 1))

    # Zeitsteuerung
    night_start: Mapped[time | None] = mapped_column(Time)
    night_end: Mapped[time | None] = mapped_column(Time)
    preheat_minutes_before_checkin: Mapped[int | None] = mapped_column(Integer)
    setback_minutes_after_checkout: Mapped[int | None] = mapped_column(Integer)
    long_vacant_hours: Mapped[int | None] = mapped_column(Integer)
    t_long_vacant: Mapped[Decimal | None] = mapped_column(Numeric(4, 1))

    # Gast-Override
    guest_override_min: Mapped[Decimal | None] = mapped_column(Numeric(4, 1))
    guest_override_max: Mapped[Decimal | None] = mapped_column(Numeric(4, 1))
    guest_override_duration_minutes: Mapped[int | None] = mapped_column(Integer)

    # Fenster-offen-Erkennung
    window_open_drop_celsius: Mapped[Decimal | None] = mapped_column(Numeric(4, 1))
    window_open_window_minutes: Mapped[int | None] = mapped_column(Integer)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    room_type: Mapped[RoomType | None] = relationship(back_populates="rule_configs")
    room: Mapped[Room | None] = relationship(back_populates="rule_configs")
    season: Mapped[Season | None] = relationship(back_populates="rule_configs")

    __table_args__ = (
        # Scope-Konsistenz: die richtige FK muss gesetzt/NULL sein.
        CheckConstraint(
            "(scope = 'global' AND room_type_id IS NULL AND room_id IS NULL)"
            " OR (scope = 'room_type' AND room_type_id IS NOT NULL AND room_id IS NULL)"
            " OR (scope = 'room' AND room_id IS NOT NULL AND room_type_id IS NULL)",
            name="ck_rule_config_scope_consistency",
        ),
        # Ein Eintrag pro Scope-Objekt + Saison-Variante.
        # season_id ist Teil der Uniqueness damit pro Scope sowohl ein
        # permanenter (season_id IS NULL) als auch saisonale Eintraege
        # nebeneinander existieren koennen.
        UniqueConstraint(
            "scope", "room_type_id", "room_id", "season_id",
            name="uq_rule_config_scope_target",
        ),
    )
