"""Belegungszeitraum eines Zimmers.

Quelle ist zunächst manuell (Admin-UI), später optional PMS-Connector.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    func,
)
from sqlalchemy import (
    Enum as SQLEnum,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from heizung.db import Base
from heizung.models.enums import OccupancySource, _enum_values

if TYPE_CHECKING:
    from heizung.models.room import Room


class Occupancy(Base):
    __tablename__ = "occupancy"

    id: Mapped[int] = mapped_column(primary_key=True)
    room_id: Mapped[int] = mapped_column(
        ForeignKey("room.id", ondelete="CASCADE"), nullable=False
    )

    check_in: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    check_out: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # Anzahl Personen (für spätere KI — Korrelation mit Energieverbrauch).
    guest_count: Mapped[int | None] = mapped_column(Integer)

    source: Mapped[OccupancySource] = mapped_column(
        SQLEnum(
            OccupancySource,
            name="occupancy_source",
            native_enum=False,
            length=20,
            values_callable=_enum_values,
        ),
        nullable=False,
        default=OccupancySource.MANUAL,
    )
    # Externe Referenz (PMS-Reservierungsnummer), wenn über Connector angelegt.
    external_id: Mapped[str | None] = mapped_column(String(100))

    # Stornos behalten wir im Log — deshalb flag statt delete.
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    room: Mapped[Room] = relationship(back_populates="occupancies")

    __table_args__ = (
        Index("ix_occupancy_room_checkin", "room_id", "check_in"),
        Index("ix_occupancy_checkin_checkout", "check_in", "check_out"),
    )
