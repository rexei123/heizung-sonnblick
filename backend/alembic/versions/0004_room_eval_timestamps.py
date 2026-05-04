"""Sprint 9.7: Engine-Scheduler braucht room.last_evaluated_at + next_transition_at.

Sprint 9.7 Walking-Skeleton: ``evaluate_due_rooms`` (Celery-Beat alle 60 s)
selektiert Raeume mit ``next_transition_at <= now`` oder ``last_evaluated_at
IS NULL`` und triggert ``evaluate_room.delay(id)`` pro Treffer.

In 9.8 (Layer 2 Temporal) tragen die Layers selbst ihren naechsten Schaltpunkt
in ``next_transition_at`` ein (z.B. Vorheiz-Beginn 60 Min vor Check-in).
Sprint 9.7 setzt next_transition_at einfach auf now+60s nach jedem Eval als
Heartbeat.

Revision ID: 0004_room_eval_ts
Revises: 0003b_event_log_hypertable
Create Date: 2026-05-04
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0004_room_eval_ts"
down_revision: str | None = "0003b_event_log"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Beide Spalten nullable: bestehende 45 Zimmer haben weder Eval-History
    # noch geplanten naechsten Schaltpunkt. Erste Beat-Runde fuellt beides.
    op.add_column(
        "room",
        sa.Column("last_evaluated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "room",
        sa.Column("next_transition_at", sa.DateTime(timezone=True), nullable=True),
    )
    # Index fuer Beat-Lookup: Raeume mit faelliger Eval finden.
    op.create_index(
        "ix_room_next_transition_at",
        "room",
        ["next_transition_at"],
        postgresql_where=sa.text("next_transition_at IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_room_next_transition_at", table_name="room")
    op.drop_column("room", "next_transition_at")
    op.drop_column("room", "last_evaluated_at")
