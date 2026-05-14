"""Audit-Trail-Tabelle fuer Settings-Aenderungen (Sprint 9.14, AE-46).

Jede Aenderung an ``global_config`` oder ``rule_config`` (scope=GLOBAL)
landet hier mit (table, column, old, new, source, request_ip, ts).
Getrennt von ``event_log`` (Engine-Decisions-Domain) — siehe AE-46
in ``docs/ARCHITEKTUR-ENTSCHEIDUNGEN.md``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, func
from sqlalchemy.dialects.postgresql import INET, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from heizung.db import Base


class ConfigAudit(Base):
    __tablename__ = "config_audit"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Sprint 9.17 (AE-50): FK auf user.id, nullable solange
    # AUTH_ENABLED=false. Wenn Feature-Flag scharf: handelnde Person.
    user_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("user.id"), nullable=True)

    # Aktions-Quelle. Heute "api" fuer PATCH-Routen. Spaeter z.B. "seed" / "cli".
    source: Mapped[str] = mapped_column(String(32), nullable=False)

    # Was wurde geaendert: Tabellen-/Spaltenname + ggf. Scope-Qualifier
    # (z.B. "global", "room_type:5", "room:12").
    table_name: Mapped[str] = mapped_column(String(64), nullable=False)
    scope_qualifier: Mapped[str | None] = mapped_column(String(64), nullable=True)
    column_name: Mapped[str] = mapped_column(String(64), nullable=False)

    # Werte als JSONB — typsicher persistieren, ohne pro-Typ-Spalten.
    # ``old_value`` kann NULL sein (z.B. wenn eine bisher leere Spalte
    # erstmals gesetzt wird).
    old_value: Mapped[dict[str, Any] | list[Any] | str | int | float | bool | None] = mapped_column(
        JSONB, nullable=True
    )
    new_value: Mapped[dict[str, Any] | list[Any] | str | int | float | bool] = mapped_column(
        JSONB, nullable=False
    )

    # Bei AUTH_ENABLED=false identifiziert request_ip den Client
    # (Best-Effort). Sobald Feature-Flag scharf, ergaenzt user_id die
    # Person.
    request_ip: Mapped[str | None] = mapped_column(INET, nullable=True)

    __table_args__ = (
        Index(
            "idx_config_audit_table_col_ts",
            "table_name",
            "column_name",
            "ts",
        ),
    )
