"""Zimmer/Raum — die Belegungseinheit.

Ein Room hat 1..n HeatingZones. Die Belegung (Occupancy) hängt am Room,
nicht an der Zone: die Zimmer-Buchung steuert alle Zonen im Zimmer.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
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
from heizung.models.enums import Orientation, RoomStatus, _enum_values

if TYPE_CHECKING:
    from heizung.models.heating_zone import HeatingZone
    from heizung.models.manual_setpoint_event import ManualSetpointEvent
    from heizung.models.occupancy import Occupancy
    from heizung.models.room_type import RoomType
    from heizung.models.rule_config import RuleConfig
    from heizung.models.scenario_assignment import ScenarioAssignment


class Room(Base):
    __tablename__ = "room"

    id: Mapped[int] = mapped_column(primary_key=True)

    # Zimmer-Nummer wie im Hotel (kann String sein: "101", "201b").
    number: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(100))

    room_type_id: Mapped[int] = mapped_column(
        ForeignKey("room_type.id", ondelete="RESTRICT"), nullable=False
    )

    floor: Mapped[int | None] = mapped_column(Integer)
    orientation: Mapped[Orientation | None] = mapped_column(
        SQLEnum(
            Orientation,
            name="orientation",
            native_enum=False,
            length=4,
            values_callable=_enum_values,
        )
    )

    status: Mapped[RoomStatus] = mapped_column(
        SQLEnum(
            RoomStatus,
            name="room_status",
            native_enum=False,
            length=20,
            values_callable=_enum_values,
        ),
        nullable=False,
        default=RoomStatus.VACANT,
    )

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

    room_type: Mapped[RoomType] = relationship(back_populates="rooms")
    heating_zones: Mapped[list[HeatingZone]] = relationship(
        back_populates="room", cascade="all, delete-orphan"
    )
    occupancies: Mapped[list[Occupancy]] = relationship(
        back_populates="room", cascade="all, delete-orphan"
    )
    rule_configs: Mapped[list[RuleConfig]] = relationship(
        back_populates="room", cascade="all, delete-orphan"
    )
    scenario_assignments: Mapped[list[ScenarioAssignment]] = relationship(
        back_populates="room", cascade="all, delete-orphan"
    )
    manual_setpoint_events: Mapped[list[ManualSetpointEvent]] = relationship(
        back_populates="room", cascade="all, delete-orphan"
    )

    __table_args__ = (Index("ix_room_status", "status"),)
