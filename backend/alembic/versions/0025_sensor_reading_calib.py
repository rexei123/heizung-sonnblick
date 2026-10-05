"""``sensor_reading.calibration_failed`` — das Bit, das seit Sprint 6.8 ankommt und verworfen wird.

Der Codec setzt es seit der ersten Fassung:

``infra/chirpstack/codecs/mclimate-vicki.js:163``
    ``data.calibrationFailed = (status8 & 0x40) !== 0;``

Es landet also in jedem Periodic-Report im ChirpStack-``object`` — aber
``services/mqtt_subscriber._map_to_reading`` liest es nicht, und
``sensor_reading`` hatte keine Spalte dafuer. Der Wert wurde bei jedem
einzelnen Frame weggeworfen.

**Warum jetzt (Sprint 20f, T7):** Geraet **026** meldete am 05.10.2026
``status8 = 0x70``, also ``calibrationFailed = true`` —

    0x80 childLock           false
    0x40 calibrationFailed   TRUE
    0x20 attachedBackplate   true
    0x10 perceiveAsOnline    true
    0x08 antiFreeze          false

Zum Vergleich die sieben Geraete 038-044 vom selben Tag: ``0x30``, also
identisch **ausser** diesem Bit. 026 ist damit der erste belegte Fall im
Haus.

Und es ist genau die Information, die im Eingangstest fehlt. Ein Geraet mit
fehlgeschlagener Kalibrierung fuehrt das Ventil nicht richtig; der
Eingangstest beurteilt es ueber das Ventilkriterium
(``VALVE_OPEN_MIN_PCT``) und faellt es durch, **ohne den Grund nennen zu
koennen**. Der Pruefer sieht "Ventil oeffnet nicht weit genug" und muss
raten, ob Hardware, Montage oder Raumtemperatur dahinter steckt. Mit dem
Bit heisst derselbe Befund "Kalibrierung fehlgeschlagen" — und das ist ein
Handgriff am Geraet (Recalibrate, Cmd 0x03) statt einer Fehlersuche.

Dieselbe Klasse wie der 0x28-Befund aus T1: die Information kommt an, und
wir werfen sie weg. Dort war es ein ganzer Keep-alive, hier ein Bit.

``nullable=True`` ohne ``server_default``, wie in 0023 und 0024: ``NULL``
heisst **kein Wert fuer diese Zeile** und ist nicht dasselbe wie ``false``.
Nur ``true`` ist ein Befund — ein Bestandszeile ohne Wert behauptet nicht,
die Kalibrierung sei in Ordnung. Dieselbe Drei-Zustands-Regel wie bei
``open_window``, ``attached_backplate`` und ``broken_sensor``.

**Kein Backfill.** Die Rohdaten liegen zwar als base64 in
``raw_payload``, der Wert waere also rekonstruierbar — aber das hiesse eine
Datenmigration mit Payload-Dekodierung auf einer Hypertable, fuer eine
Diagnose-Groesse, die ihren Zweck ab dem naechsten Keep-alive erfuellt
(alle zehn Minuten je Geraet). Gleiche Entscheidung wie in 0023 und 0024.

Revision-ID unter 32 Zeichen (``alembic_version.version_num`` ist
``VARCHAR(32)``): ``0025_sensor_reading_calib`` = 25 Zeichen. Gemessen,
nicht gezaehlt — Alembic 1.20 hat eine 33-Zeichen-ID aus genau diesem
Grund abgewiesen (CLAUDE.md §5.80, dritter Fall).
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0025_sensor_reading_calib"
down_revision: str | None = "0024_sensor_reading_voltage"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "sensor_reading",
        sa.Column("calibration_failed", sa.Boolean(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("sensor_reading", "calibration_failed")
