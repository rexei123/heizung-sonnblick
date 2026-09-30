"""``sensor_reading.broken_sensor`` — das Defekt-Bit des Temperatursensors.

Der Vicki-Codec liefert es seit je her, persistiert wurde es nie:

``infra/chirpstack/codecs/mclimate-vicki.js:161``
    ``data.brokenSensor = (status7 & 0x01) !== 0``
    mit ``status7 = bytes[7] & 0x0f`` (Zeile 124)

Also **Bit 0 des Low-Nibbles von Byte 7** — dieselbe Statusgruppe wie
``openWindow`` (0x08), ``highMotorConsumption`` (0x04) und
``lowMotorConsumption`` (0x02). Drei der vier Bits werden gelesen, dieses
eine fiel durch.

Warum jetzt (Sprint 19 / PR B): Der Eingangstest urteilt ueber die
Ventilstellung, und die Regelung der Vicki stuetzt sich auf ihren internen
Temperatursensor. Meldet der einen Defekt, ist jede Aussage ueber das
Ventil wertlos — das Geraet regelt gegen einen Messwert, dem es selbst
nicht traut. Ohne Persistenz kann der Test das Bit nicht sehen; es steht
sonst nur in ``raw_payload`` als Base64.

Das ist genau die Begruendung, mit der ``attached_backplate`` in Sprint
9.11x aufgenommen wurde (CLAUDE.md §5.27: "Das ``attachedBackplate``-Bit
gehoert in ``sensor_reading``. Codec liefert es seit FW 4.1, ohne
Persistenz keine Demontage-Erkennung."). Dieselbe Klasse, dieselbe
Antwort.

``nullable=True`` ohne ``server_default``: ``NULL`` heisst **Feld nicht im
Payload** (alter Codec, Recovery-Daten) und ist **nicht** dasselbe wie
``False``. Nur ``True`` ist ein Defekt-Befund. Dieselbe Drei-Zustands-
Semantik wie ``open_window`` und ``attached_backplate``; Bestandszeilen
bleiben ``NULL`` und werden damit korrekt als "unbekannt" gefuehrt statt
als "Sensor in Ordnung".

Kein Backfill: die Rohbytes liegen in ``raw_payload``, ein Re-Decode waere
moeglich, aber der Wert hat nur fuer **frische** Frames Bedeutung — der
Eingangstest liest den Setzframe, nicht die Historie.

Revision-ID unter 32 Zeichen (``alembic_version.version_num`` ist
``VARCHAR(32)``, siehe 0022). Gemessen, nicht gezaehlt:

    revision      = '0023_sensor_reading_broken'  -> 26 Zeichen
    down_revision = '0022_occupancy_expected_by'  -> 26 Zeichen
    Reserve: 6 Zeichen

Der erste Entwurf von 0022 hiess ``0022_occupancy_import_expected_by`` — 33
Zeichen, eines zu viel. Lokal lief die Migration durch (anderer
Alembic-Stand), in CI scheiterte jeder DB-Test am ``UPDATE
alembic_version``. Die Zahl steht hier, damit sie nicht erneut geschaetzt
wird.

Revision ID: 0023_sensor_reading_broken
Revises: 0022_occupancy_expected_by
Create Date: 2026-09-30
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0023_sensor_reading_broken"
down_revision: str | None = "0022_occupancy_expected_by"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "sensor_reading",
        sa.Column("broken_sensor", sa.Boolean(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("sensor_reading", "broken_sensor")
