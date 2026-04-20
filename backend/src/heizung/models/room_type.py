"""Raumtyp-Vorlage.

Raumtypen sind im UI frei editierbar. Neben Hotelzimmern können auch
Seminarräume, Restaurants usw. angelegt werden (Flag ``is_bookable``).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from heizung.db import Base

if TYPE_CHECKING:
    from heizung.models.room import Room
    from heizung.models.rule_config import RuleConfig


class RoomType(Base):
    __tablename__ = "room_type"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(String(500))

    # Belegungsrelevant: Hotelzimmer (ja), Seminarraum/Restaurant (nein).
    # Nur bookable Raumtypen triggern Check-in/out-Regeln.
    is_bookable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # Default-Sollwerte (°C). Werden in rule_config-Hierarchie als
    # Raumtyp-Ebene verwendet, falls kein expliziter RuleConfig-Eintrag
    # auf Raumtyp-Ebene existiert.
    default_t_occupied: Mapped[Decimal] = mapped_column(
        Numeric(4, 1), nullable=False, default=Decimal("21.0")
    )
    default_t_vacant: Mapped[Decimal] = mapped_column(
        Numeric(4, 1), nullable=False, default=Decimal("18.0")
    )
    default_t_night: Mapped[Decimal] = mapped_column(
        Numeric(4, 1), nullable=False, default=Decimal("19.0")
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    rooms: Mapped[list[Room]] = relationship(back_populates="room_type")
    rule_configs: Mapped[list[RuleConfig]] = relationship(
        back_populates="room_type", cascade="all, delete-orphan"
    )
