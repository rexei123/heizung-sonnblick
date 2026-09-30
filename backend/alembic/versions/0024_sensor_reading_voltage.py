"""``sensor_reading.battery_voltage`` — die Groesse, aus der die Stufe wird.

Der Codec liefert die Geraete-Spannung seit je her:

``infra/chirpstack/codecs/mclimate-vicki.js:119-121``
    ``var batteryNibble = (bytes[7] >> 4) & 0x0f;``
    ``var batteryVoltage = 2 + batteryNibble * 0.1;``
    Ausgabe als ``data.battery_voltage`` (Zeile 142).

Persistiert wurde daraus bisher **nur** der abgeleitete Prozentwert:
``services/mqtt_subscriber._map_to_reading`` rechnet ueber
``BATTERY_CURVE_2XAA`` in ``battery_percent`` und verwirft die Spannung.
Die Umkehrung ist zwar rechnerisch eindeutig (das 0.1-V-Raster erzeugt nur
die Prozentwerte 0/10/30/50/65/80/87/93/100), aber sie gilt **nicht** fuer
Zeilen von vor dem 02.06.2026 — davor stand die lineare LiPo-Skala im
Subscriber (AE-64). Ein Backfill braeuchte also einen Stichtag und traegt
sein Ergebnis als Behauptung; er entfaellt (siehe unten).

Warum jetzt (Sprint 20, AE-69): Die drei Stufen der Oberflaeche
(OK/schwach/kritisch) rechnen heute ueber Prozent, und Prozent ist an
dieser Stelle Scheinpraezision — der Codec saettigt oberhalb ~3.4 V am
4-Bit-Anschlag, es gibt effektiv neun unterscheidbare Werte (AE-64,
CLAUDE.md §5.72). Die Schwellen wandern deshalb auf die Spannung selbst:

    OK >= 3.0 V  ·  schwach 2.9 V  ·  kritisch <= 2.8 V

Damit ist die Bewertung unabhaengig vom Batterietyp — Lithium ab Werk,
Alkaline beim spaeteren Tausch durch den Hausmeister — und die
Kritisch-Grenze deckt sich mit der Hersteller-Wechselempfehlung
(< 2.8 V, ``docs/ARCHITEKTUR-ENTSCHEIDUNGEN.md:2539``).

``Numeric(3, 1)`` statt ``Numeric(2, 1)``: der Betriebsbereich der Spec
reicht bis 3.6 VDC (Lithium-AA), das Raster ist 0.1 V. Drei Stellen
lassen Luft nach oben, ohne dass eine spaetere Hardware-Generation eine
zweite Migration braucht. Decimal, nicht Float — der Schwellen-Vergleich
laeuft exakt auf dem 0.1-V-Raster, IEEE-754 hat fuer 2.9 keine exakte
Darstellung (dieselbe Begruendung wie fuer ``BATTERY_CURVE_2XAA``).

``nullable=True`` ohne ``server_default``: ``NULL`` heisst **kein
Spannungswert fuer diese Zeile** und ist nicht dasselbe wie 0.0 V. Alle
Bestandszeilen bleiben ``NULL``; die Bewertung zaehlt sie nicht mit und
liefert "unbekannt", solange die Mindest-Stichprobe im 24-h-Fenster nicht
erreicht ist. Das ist der ehrliche Zustand — nicht "Batterie leer".

Kein Backfill, drei Gruende: die Umkehrung gilt nur ab dem 15b-Deploy
(Stichtag noetig), das Bewertungs-Fenster ist 24 h und fuellt sich von
selbst, und die Geraete im Montage-Bestand sind neu bestueckt. Ein
Backfill haette also fuer genau einen Tag Wirkung und dafuer eine
Datenmigration auf einer Hypertable gekostet. Gleiche Entscheidung wie
in AE-64 Punkt 3 und in 0023.

``battery_percent`` bleibt bestehen und wird weiter geschrieben: es ist
der Rueckfallpfad, falls die Stufen-Umstellung zurueckgedreht werden muss.
Nach Sprint 20 liest es kein Konsument mehr — der Vermerk dazu steht im
Docstring von ``_battery_pct_from_volts``, damit er nicht zum stillen
Schalter wird (CLAUDE.md §5.77).

Revision-ID unter 32 Zeichen (``alembic_version.version_num`` ist
``VARCHAR(32)``, siehe 0022/0023). Gemessen, nicht gezaehlt:

    revision      = '0024_sensor_reading_voltage'  -> 27 Zeichen
    down_revision = '0023_sensor_reading_broken'   -> 26 Zeichen
    Reserve: 5 Zeichen

Revision ID: 0024_sensor_reading_voltage
Revises: 0023_sensor_reading_broken
Create Date: 2026-09-30
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0024_sensor_reading_voltage"
down_revision: str | None = "0023_sensor_reading_broken"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "sensor_reading",
        sa.Column("battery_voltage", sa.Numeric(3, 1), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("sensor_reading", "battery_voltage")
