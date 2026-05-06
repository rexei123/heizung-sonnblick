"""manual_override (Sprint 9.9 T1, Engine Layer 3).

Manual-Override-Tabelle: pro Raum wird ein Setpoint mit Quelle
(``device``/``frontend_4h``/``frontend_midnight``/``frontend_checkout``)
und Ablaufzeitpunkt persistiert. Engine-Layer 3 nutzt den juengsten
nicht-revokierten Eintrag mit ``expires_at > now``.

Index ``ix_manual_override_active`` ist partial: ``WHERE revoked_at IS NULL``.
``expires_at > NOW()`` ist hier bewusst nicht im Predicate, weil ``NOW()``
in PostgreSQL ``STABLE`` (nicht ``IMMUTABLE``) ist und im Index-Predicate
einen Migration-Crash ausloesen wuerde — der Filter passiert query-seitig.

Revision ID: 0008_manual_override
Revises: 0004_room_eval_ts
Create Date: 2026-05-06
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0008_manual_override"
down_revision: str | None = "0004_room_eval_ts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "manual_override",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("room_id", sa.Integer(), nullable=False),
        sa.Column("setpoint", sa.Numeric(4, 1), nullable=False),
        sa.Column("source", sa.String(length=30), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("created_by", sa.String(length=255), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_reason", sa.String(length=500), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_manual_override"),
        sa.ForeignKeyConstraint(
            ["room_id"],
            ["room.id"],
            ondelete="CASCADE",
            name="fk_manual_override_room",
        ),
        sa.CheckConstraint(
            "source IN ('device', 'frontend_4h', 'frontend_midnight', 'frontend_checkout')",
            name="ck_manual_override_source",
        ),
        sa.CheckConstraint(
            "setpoint >= 5.0 AND setpoint <= 30.0",
            name="ck_manual_override_setpoint_range",
        ),
    )
    op.create_index(
        "ix_manual_override_active",
        "manual_override",
        ["room_id", sa.text("created_at DESC")],
        postgresql_where=sa.text("revoked_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_manual_override_active", table_name="manual_override")
    op.drop_table("manual_override")
