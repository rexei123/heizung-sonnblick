"""Audit-Log der von der Regel-Engine erzeugten Steuerbefehle.

Unveränderlich: jeder Befehl wird als neuer Datensatz geschrieben.
``rule_context`` enthält den auslösenden Regel-Kontext als JSON-String
(z. B. aktueller Setpoint, Belegungsstatus, Uhrzeit-Fenster).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    DateTime,
    Enum as SQLEnum,
    ForeignKey,
    Index,
    Numeric,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from heizung.db import Base
from heizung.models.enums import CommandReason, _enum_values


class ControlCommand(Base):
    __tablename__ = "control_command"

    id: Mapped[int] = mapped_column(primary_key=True)
    issued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    device_id: Mapped[int] = mapped_column(
        ForeignKey("device.id", ondelete="CASCADE"), nullable=False
    )

    target_setpoint: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    reason: Mapped[CommandReason] = mapped_column(
        SQLEnum(
            CommandReason,
            name="command_reason",
            native_enum=False,
            length=30,
            values_callable=_enum_values,
        ),
        nullable=False,
    )
    rule_context: Mapped[str | None] = mapped_column(String)  # JSON

    sent_to_gateway_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index("ix_control_command_device_issued", "device_id", "issued_at"),
    )
