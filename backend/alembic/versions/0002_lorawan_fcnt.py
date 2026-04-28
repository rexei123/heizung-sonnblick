"""LoRaWAN-Foundation: fcnt-Spalte fuer sensor_reading.

Sprint 5 (LoRaWAN-Foundation):
- ChirpStack-Uplinks landen ueber den FastAPI-MQTT-Subscriber in sensor_reading.
- ``fcnt`` (Frame Counter) wird mitgespeichert fuer Lueckenerkennung
  und spaetere Replay-Diagnose.
- Idempotenz: kein zusaetzliches UNIQUE noetig - der bestehende
  Composite-PK (time, device_id) faengt MQTT-Reconnect-Replays ab,
  da Vicki-Uplinks immer einen unique time-stamp haben. Subscriber nutzt
  ON CONFLICT (time, device_id) DO NOTHING.
- Hypertable-Constraint: jeder UNIQUE-Index muss die Partition-Spalte
  ``time`` enthalten - daher kein partial UNIQUE auf (device_id, fcnt).

Revision ID: 0002_lorawan
Revises: 0001_initial
Create Date: 2026-04-28
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_lorawan"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "sensor_reading",
        sa.Column("fcnt", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("sensor_reading", "fcnt")
