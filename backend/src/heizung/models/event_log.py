"""Audit-Log der Engine-Pipeline pro Schicht (AE-08, AE-31).

TimescaleDB-Hypertable. Pro Engine-Evaluation entsteht ein Eintrag pro
durchlaufener Schicht — auch bei unveraenderten Setpoints (KI-Vorbereitung).

PRIMARY KEY enthaelt zwingend die Partition-Spalte ``time`` (TimescaleDB-
Constraint). ``evaluation_id`` (UUID) verbindet alle Schicht-Eintraege einer
Evaluation. ``details`` JSONB haelt vollstaendigen Kontext-Snapshot
(Belegung, Wetter, vorheriger Setpoint usw.).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    func,
)
from sqlalchemy import (
    Enum as SQLEnum,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from heizung.db import Base
from heizung.models.enums import CommandReason, EventLogLayer, _enum_values


class EventLog(Base):
    __tablename__ = "event_log"

    # PK Teil 1 (Partition): time
    time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        primary_key=True,
        server_default=func.now(),
        nullable=False,
    )

    # PK Teil 2: room (kann nicht NULL sein — jeder Evaluation gehoert einem Raum)
    room_id: Mapped[int] = mapped_column(
        ForeignKey("room.id", ondelete="CASCADE", name="fk_event_log_room"),
        primary_key=True,
        nullable=False,
    )

    # PK Teil 3: evaluation-UUID (verbindet alle Layer-Eintraege einer Eval)
    evaluation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        nullable=False,
    )

    # PK Teil 4: Schicht (eine Evaluation = bis zu N Schicht-Eintraege)
    layer: Mapped[EventLogLayer] = mapped_column(
        SQLEnum(
            EventLogLayer,
            name="event_log_layer",
            native_enum=False,
            length=30,
            values_callable=_enum_values,
        ),
        primary_key=True,
        nullable=False,
    )

    # Optional: Geraet, das letztlich angesteuert wird (mehrere pro Raum moeglich)
    device_id: Mapped[int | None] = mapped_column(
        ForeignKey("device.id", ondelete="SET NULL", name="fk_event_log_device")
    )

    setpoint_in: Mapped[Decimal | None] = mapped_column(Numeric(4, 1))
    setpoint_out: Mapped[Decimal | None] = mapped_column(Numeric(4, 1))

    # Reason ist das spezifische "warum" — wir teilen die CommandReason-Enum
    # mit control_command (eine Quelle der Wahrheit fuer alle moeglichen
    # Engine-Ergebnisse). Per Design auch fuer Layer-Audit nutzbar.
    reason: Mapped[CommandReason | None] = mapped_column(
        SQLEnum(
            CommandReason,
            name="event_log_reason",
            native_enum=False,
            length=30,
            values_callable=_enum_values,
        )
    )

    # Vollstaendiger Kontext-Snapshot fuer KI-Training (AE-08)
    details: Mapped[dict | None] = mapped_column(JSONB)

    __table_args__ = (
        # Index fuer Lookup "alle Eintraege fuer Raum X im Zeitraum"
        Index("ix_event_log_room_time", "room_id", "time"),
        # Index fuer Lookup "alle Eintraege einer Evaluation"
        Index("ix_event_log_evaluation", "evaluation_id"),
    )
