"""device.firmware_version + sensor_reading.attached_backplate (Sprint 9.11x).

Vicki-Codec (FW >= 4.1) liefert pro Uplink ``attachedBackplate: bool`` —
True, wenn der Vicki an seine Wandhalterung angeflanscht ist; False bei
Demontage durch Housekeeping/Defekt. Layer 4 Engine nutzt das fuer den
zweiten Frostschutz-Trigger ``device_detached`` mit AND-Semantik ueber
alle Devices einer Heizzone (siehe ``rules/engine.py``).

``firmware_version`` ist Schema-Vorbereitung fuer Sprint 9.11x.b
(Codec-Drift-Schutz). In 9.11x ungenutzt, additiv, kein Cleanup-Bedarf
falls 9.11x.b verschoben wird.

NULL = "Feld war im Payload nicht vorhanden" (alter Codec, Recovery-
Daten) und ist NICHT identisch mit ``False``. Layer 4 behandelt NULL
als "Device unklar" (nicht detached).

``sensor_reading`` ist Hypertable — ``add_column`` mit ``nullable=True``
ohne Default ist sicher (kein Rewrite, kein Lock auf Bestandsdaten).

Revision ID: 0010_attached_backplate_and_fw
Revises: 0009_sensor_reading_open_window
Create Date: 2026-05-09

Hinweis zum Namen: ``alembic_version.version_num`` ist ``VARCHAR(32)``.
Der Brief-Originalname (67 Zeichen) schlaegt beim Upgrade fehl. Gekuerzt
auf 29 Zeichen — beide neuen Spalten weiterhin im Namen lesbar
(``0009_sensor_reading_open_window`` ist 31 Zeichen, gleicher Constraint).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0010_attached_backplate_and_fw"
down_revision: str | None = "0009_sensor_reading_open_window"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "device",
        sa.Column("firmware_version", sa.String(length=8), nullable=True),
    )
    op.add_column(
        "sensor_reading",
        sa.Column("attached_backplate", sa.Boolean(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("sensor_reading", "attached_backplate")
    op.drop_column("device", "firmware_version")
