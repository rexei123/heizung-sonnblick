"""Audit-Trail fuer operative Hotelier-Aktionen (Sprint 9.17, AE-50).

Getrennt von ``config_audit`` (Konfigurations-/Stammdaten-Mutationen):
``business_audit`` haelt Belegungs-Aenderungen und Manual-Override-
Aktionen — die Domaene, die Mitarbeiter taeglich bedienen. Zwei
Domains, weil unterschiedliche Konsumenten (Compliance vs. Tagessicht)
und unterschiedliche Lebensdauern (Settings selten, Operationen
haeufig).

Schreibt pro Aktion einen Eintrag mit ``user_id`` (FK auf
``user.id``, nullable solange ``AUTH_ENABLED=false``), ``action`` als
Token (z.B. ``OCCUPANCY_CREATE``, ``MANUAL_OVERRIDE_SET``),
``target_type``/``target_id`` zur Aufloesung und JSONB-Wertepaaren.

Atomar mit dem eigentlichen UPDATE in derselben Transaktion (analog
``config_audit_service``, Sprint 9.14 AE-46).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, func
from sqlalchemy.dialects.postgresql import INET, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from heizung.db import Base


class BusinessAudit(Base):
    __tablename__ = "business_audit"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    user_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("user.id"), nullable=True)

    # Aktion als Token. Eingefuehrte Werte:
    #   OCCUPANCY_CREATE, OCCUPANCY_CANCEL,
    #   MANUAL_OVERRIDE_SET, MANUAL_OVERRIDE_CLEAR,
    #   PASSWORD_CHANGE, PASSWORD_RESET_BY_ADMIN
    action: Mapped[str] = mapped_column(String(64), nullable=False)

    # Domaenen-Objekt: target_type='room' / 'user' / 'occupancy' ...
    target_type: Mapped[str] = mapped_column(String(64), nullable=False)
    target_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    old_value: Mapped[dict[str, Any] | list[Any] | str | int | float | bool | None] = mapped_column(
        JSONB, nullable=True
    )
    new_value: Mapped[dict[str, Any] | list[Any] | str | int | float | bool] = mapped_column(
        JSONB, nullable=False
    )

    request_ip: Mapped[str | None] = mapped_column(INET, nullable=True)

    __table_args__ = (
        Index("idx_business_audit_target_ts", "target_type", "target_id", "ts"),
        Index("idx_business_audit_user_ts", "user_id", "ts"),
    )
