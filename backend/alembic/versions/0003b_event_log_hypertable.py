"""Sprint 8 event_log Hypertable fuer Engine-Audit (AE-08, AE-31).

Pro Engine-Evaluation entsteht ein Eintrag pro durchlaufener Schicht. PRIMARY
KEY enthaelt zwingend die Partition-Spalte ``time`` (TimescaleDB-Constraint).

Chunk-Intervall 7 Tage — bei einer Engine-Evaluation pro Raum alle 60s plus
ca. 6 Schicht-Eintraege ergibt das fuer 45 Raeume ca. 2 Mio Rows pro Woche.
TimescaleDB komprimiert aeltere Chunks automatisch.

Revision ID: 0003b_event_log
Revises: 0003a_stammdaten
Create Date: 2026-05-02
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003b_event_log"
down_revision: str | None = "0003a_stammdaten"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "event_log",
        sa.Column(
            "time",
            sa.DateTime(timezone=True),
            primary_key=True,
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "room_id",
            sa.Integer(),
            sa.ForeignKey("room.id", ondelete="CASCADE", name="fk_event_log_room"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "evaluation_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        # layer als String gespeichert — SQLEnum native_enum=False entspricht
        # in der DB einer VARCHAR-Spalte. Validierung via SQLAlchemy-Layer.
        sa.Column("layer", sa.String(length=30), primary_key=True, nullable=False),
        # Index/Performance-Hinweis: layer ist Teil PK, also automatisch
        # indexiert. Kein zusaetzlicher Index noetig.
        sa.Column(
            "device_id",
            sa.Integer(),
            sa.ForeignKey("device.id", ondelete="SET NULL", name="fk_event_log_device"),
        ),
        sa.Column("setpoint_in", sa.Numeric(4, 1)),
        sa.Column("setpoint_out", sa.Numeric(4, 1)),
        sa.Column("reason", sa.String(length=30)),
        sa.Column("details", sa.dialects.postgresql.JSONB()),
    )

    # Hypertable-Konvertierung: 7 Tage Chunk-Intervall
    op.execute(
        "SELECT create_hypertable("
        "'event_log', 'time',"
        " chunk_time_interval => INTERVAL '7 days',"
        " if_not_exists => TRUE"
        ")"
    )

    op.create_index("ix_event_log_room_time", "event_log", ["room_id", "time"])
    op.create_index("ix_event_log_evaluation", "event_log", ["evaluation_id"])


def downgrade() -> None:
    op.drop_index("ix_event_log_evaluation", table_name="event_log")
    op.drop_index("ix_event_log_room_time", table_name="event_log")
    # Hypertable-Cleanup: drop_table reicht in TimescaleDB, da Hypertable
    # ueber dieselbe Tabelle laeuft. Chunks werden automatisch gedropped.
    op.drop_table("event_log")
