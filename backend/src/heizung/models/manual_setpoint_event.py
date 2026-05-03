"""Einmalige manuelle Setpoint-Aktion mit Zeitbegrenzung (AE-29).

Hotelier-Aktion "Temperatur jetzt setzen" — z.B. fuer Wartung Fenster oder
Spezialgast vor regulaerer Belegung. Wirkt fuer Raumtyp (alle Raeume) oder
einzelnen Raum, gilt zwischen ``starts_at`` und ``ends_at``.

Engine-Layer 3a (manual_override) prueft pro Evaluation: existiert ein
aktiver Eintrag fuer den Raum? Wenn ja, ueberschreibt er R1-R7. R8
(Frostschutz) bleibt unangetastet.

Audit-faehig: ``reason`` ist Pflicht (gegen anonymes "warum heizt das jetzt
24 Grad"-Reverse-Engineering nach 4 Wochen).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    func,
)
from sqlalchemy import (
    Enum as SQLEnum,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from heizung.db import Base
from heizung.models.enums import ManualOverrideScope, _enum_values

if TYPE_CHECKING:
    from heizung.models.room import Room
    from heizung.models.room_type import RoomType


class ManualSetpointEvent(Base):
    __tablename__ = "manual_setpoint_event"

    id: Mapped[int] = mapped_column(primary_key=True)

    scope: Mapped[ManualOverrideScope] = mapped_column(
        SQLEnum(
            ManualOverrideScope,
            name="manual_override_scope",
            native_enum=False,
            length=20,
            values_callable=_enum_values,
        ),
        nullable=False,
    )
    room_type_id: Mapped[int | None] = mapped_column(ForeignKey("room_type.id", ondelete="CASCADE"))
    room_id: Mapped[int | None] = mapped_column(ForeignKey("room.id", ondelete="CASCADE"))

    target_setpoint_celsius: Mapped[Decimal] = mapped_column(Numeric(4, 1), nullable=False)

    starts_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # Pflicht — wer warum
    reason: Mapped[str] = mapped_column(String(500), nullable=False)

    # Kann manuell beendet werden vor ends_at
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    room_type: Mapped[RoomType | None] = relationship(back_populates="manual_setpoint_events")
    room: Mapped[Room | None] = relationship(back_populates="manual_setpoint_events")

    __table_args__ = (
        # Scope-Konsistenz (kein GLOBAL — bewusst, siehe Doku)
        CheckConstraint(
            "(scope = 'room_type' AND room_type_id IS NOT NULL AND room_id IS NULL)"
            " OR (scope = 'room' AND room_id IS NOT NULL AND room_type_id IS NULL)",
            name="ck_manual_setpoint_event_scope_consistency",
        ),
        # Zeitfenster-Konsistenz
        CheckConstraint("starts_at < ends_at", name="ck_manual_setpoint_event_time_ordered"),
        # Setpoint im sinnvollen Bereich (Frostschutz bis HotelMax). Engine clampt
        # zusaetzlich, aber DB-Schutz gegen ueble Tippfehler.
        CheckConstraint(
            "target_setpoint_celsius >= 5.0 AND target_setpoint_celsius <= 30.0",
            name="ck_manual_setpoint_event_temp_range",
        ),
        # Index fuer Engine-Lookup "welche Events sind jetzt aktiv fuer Raum X"
        Index(
            "ix_manual_setpoint_event_active_window",
            "is_active",
            "starts_at",
            "ends_at",
        ),
    )
