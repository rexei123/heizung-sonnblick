"""sensor_reading.open_window (Sprint 9.10 T1, Window-Detection Layer 4).

Vicki-Codec liefert pro Uplink ``openWindow: bool``. Layer 4 der Engine
faellt zurueck auf ``MIN_SETPOINT_C``, wenn ein Reading mit
``open_window = true`` jung genug ist (siehe ``WINDOW_STALE_THRESHOLD_MIN``
in ``engine.py``).

NULL = "Feld war im Payload nicht vorhanden" (alter Codec-Stand,
Recovery-Daten, etc.) und ist NICHT identisch mit ``False``. Layer 4
behandelt NULL und False als "Fenster nicht offen".

Revision ID: 0009_sensor_reading_open_window
Revises: 0008_manual_override
Create Date: 2026-05-07
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0009_sensor_reading_open_window"
down_revision: str | None = "0008_manual_override"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "sensor_reading",
        sa.Column("open_window", sa.Boolean(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("sensor_reading", "open_window")
