"""Heizzone innerhalb eines Zimmers.

Ein Zimmer hat 1..n Zonen (Standard-DZ: Schlafzimmer + Bad). Jede Zone
hat 0..1 Thermostat-Geräte. Handtuchtrockner werden als eigene Zone mit
``is_towel_warmer=True`` modelliert (eigene Regel-Logik in Sprint 3).
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy import (
    Enum as SQLEnum,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from heizung.db import Base
from heizung.models.enums import HeatingZoneKind, _enum_values

if TYPE_CHECKING:
    from heizung.models.device import Device
    from heizung.models.room import Room


class HeatingZone(Base):
    __tablename__ = "heating_zone"

    id: Mapped[int] = mapped_column(primary_key=True)
    room_id: Mapped[int] = mapped_column(ForeignKey("room.id", ondelete="CASCADE"), nullable=False)

    kind: Mapped[HeatingZoneKind] = mapped_column(
        SQLEnum(
            HeatingZoneKind,
            name="heating_zone_kind",
            native_enum=False,
            length=20,
            values_callable=_enum_values,
        ),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)

    # Handtuchtrockner im Bad — wasserbasiert, eigene Logik:
    # bei Belegung an, sonst Frostschutz.
    is_towel_warmer: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    room: Mapped[Room] = relationship(back_populates="heating_zones")
    devices: Mapped[list[Device]] = relationship(back_populates="heating_zone")

    __table_args__ = (UniqueConstraint("room_id", "name", name="uq_heating_zone_room_name"),)
