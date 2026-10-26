"""sensor_reading.temp_range_min / temp_range_max (Sprint 23 T1).

Die Antwort auf ``0x15`` nennt die Grenzen, die **am Geraet** gelten.
Bisher landete sie als ``unknown_reply`` im Protokoll; mit T1 dekodiert
der Codec sie, und diese beiden Spalten nehmen sie auf.

**Warum in ``sensor_reading`` und nicht auf ``device``.** Es ist eine
Meldung des Geraets mit einem Zeitpunkt, kein Stammdatum. Die Anzeige
liest die **juengste Zeile, die die Felder fuehrt**, und deren ``time``
ist der Bestaetigungszeitpunkt — dieselbe Form wie
``battery_voltage_median`` (AE-72): read-time abgeleitet, nichts
zusaetzlich persistiert, keine zweite Wahrheit.

``NULL`` heisst „diese Zeile fuehrt das Feld nicht", nicht „keine
Grenzen". Ein Keepalive ohne ``0x15``-Antwort sagt ueber die Grenzen
nichts, und er darf eine aeltere Antwort nicht ueberschreiben — dieselbe
Drei-Zustands-Regel wie bei ``open_window``, ``attached_backplate`` und
``child_lock``.

Migration additiv: ja — zwei nullable Spalten, kein Backfill, keine
Beschraenkung auf Bestandszeilen. ``sensor_reading`` ist eine
TimescaleDB-Hypertable; ``ADD COLUMN`` mit NULL ist dort eine
Metadaten-Operation und beruehrt die Chunks nicht.

Revision ID: 0035_geraetegrenzen_messwert
Revises: 0034_gastsperre_bis_checkout
Create Date: 2026-10-26
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0035_geraetegrenzen_messwert"
down_revision: str | None = "0034_gastsperre_bis_checkout"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("sensor_reading", sa.Column("temp_range_min", sa.SmallInteger(), nullable=True))
    op.add_column("sensor_reading", sa.Column("temp_range_max", sa.SmallInteger(), nullable=True))


def downgrade() -> None:
    op.drop_column("sensor_reading", "temp_range_max")
    op.drop_column("sensor_reading", "temp_range_min")
