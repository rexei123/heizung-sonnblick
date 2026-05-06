"""Manueller Setpoint-Override pro Raum (Sprint 9.9, Engine Layer 3).

Vier Quellen (siehe :class:`heizung.models.enums.OverrideSource`):
``device`` (Drehring), ``frontend_4h``, ``frontend_midnight``,
``frontend_checkout``. Engine-Layer 3 nimmt pro Raum den juengsten
nicht-revokierten Eintrag mit ``expires_at > now``; Layer 5 (Hard-Clamp)
greift danach.

Abgrenzung zu :class:`heizung.models.manual_setpoint_event.ManualSetpointEvent`:
``ManualSetpointEvent`` (Sprint 8) ist die Hotelleitungs-Aktion "fuer X Tage
auf Raumtyp/Raum manuell setzen". ``ManualOverride`` (Sprint 9.9) ist die
operative Override-Erkennung pro Raum mit auto-revoke beim PMS-Status-Wechsel
"belegt -> frei". Beide leben parallel und triggern jeweils eigene Engine-
Layer; eine Konsolidierung ist Sprint-10+-Backlog.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    func,
    text,
)
from sqlalchemy import (
    Enum as SQLEnum,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from heizung.db import Base
from heizung.models.enums import OverrideSource, _enum_values

if TYPE_CHECKING:
    from heizung.models.room import Room


class ManualOverride(Base):
    __tablename__ = "manual_override"

    id: Mapped[int] = mapped_column(primary_key=True)
    room_id: Mapped[int] = mapped_column(ForeignKey("room.id", ondelete="CASCADE"), nullable=False)

    setpoint: Mapped[Decimal] = mapped_column(Numeric(4, 1), nullable=False)
    source: Mapped[OverrideSource] = mapped_column(
        SQLEnum(
            OverrideSource,
            name="override_source",
            native_enum=False,
            length=30,
            values_callable=_enum_values,
        ),
        nullable=False,
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(500))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_by: Mapped[str | None] = mapped_column(String(255))

    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_reason: Mapped[str | None] = mapped_column(String(500))

    room: Mapped[Room] = relationship(back_populates="manual_overrides")

    __table_args__ = (
        # Setpoint im sinnvollen Bereich (Frostschutz bis Hotel-Max). Layer 5
        # clampt zusaetzlich, aber DB-Schutz gegen Tippfehler im API-Body.
        CheckConstraint(
            "setpoint >= 5.0 AND setpoint <= 30.0",
            name="ck_manual_override_setpoint_range",
        ),
        # Layer-3-Lookup: aktive (= nicht-revokierte) Overrides pro Raum,
        # juengster zuerst. Partial Index laesst alte revokierte Records
        # ausserhalb des Index - die brauchen wir nur fuer Audit-Queries.
        # Hinweis: kein ``expires_at > NOW()`` im Predicate, weil NOW()
        # in PostgreSQL STABLE statt IMMUTABLE ist und im Index-Predicate
        # nicht erlaubt waere; ``expires_at``-Filter passiert query-seitig.
        Index(
            "ix_manual_override_active",
            "room_id",
            "created_at",
            postgresql_where=text("revoked_at IS NULL"),
        ),
    )

    def __repr__(self) -> str:
        return (
            f"ManualOverride(id={self.id}, room_id={self.room_id}, "
            f"source={self.source.value}, expires_at={self.expires_at.isoformat()})"
        )
