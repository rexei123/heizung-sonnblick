"""config_audit-Tabelle fuer Audit-Trail von Settings-Aenderungen
(Sprint 9.14, AE-46).

Jede Aenderung an ``global_config`` und ``rule_config`` (scope=GLOBAL)
schreibt einen Eintrag mit (table, column, old, new, source, request_ip,
ts). Atomar mit dem eigentlichen UPDATE in einer Transaktion (Service
``record_config_change``).

``event_log`` bleibt der Engine-Decisions-Audit; ``config_audit`` ist
die getrennte Hotelier-Aktions-Domain. Reason: zwei orthogonale Zwecke,
unterschiedliche Konsumenten, S6 (Komplexitaet traegt Beweislast)
favorisiert getrennte Tabellen statt eines uebergeordneten event-Pots.

Revision ID: 0011_config_audit
Revises: 0010_attached_backplate_and_fw
Create Date: 2026-05-12
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0011_config_audit"
down_revision: str | None = "0010_attached_backplate_and_fw"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "config_audit",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "ts",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("table_name", sa.String(length=64), nullable=False),
        sa.Column("scope_qualifier", sa.String(length=64), nullable=True),
        sa.Column("column_name", sa.String(length=64), nullable=False),
        sa.Column("old_value", postgresql.JSONB(), nullable=True),
        sa.Column("new_value", postgresql.JSONB(), nullable=False),
        sa.Column("request_ip", postgresql.INET(), nullable=True),
    )
    op.create_index(
        "idx_config_audit_table_col_ts",
        "config_audit",
        ["table_name", "column_name", sa.text("ts DESC")],
    )


def downgrade() -> None:
    op.drop_index("idx_config_audit_table_col_ts", table_name="config_audit")
    op.drop_table("config_audit")
