"""``manual_override.source`` erlaubt ``device_manual`` (Sprint 20f, T2).

Die Spalte traegt eine DB-CHECK-Beschraenkung mit den vier bisherigen Werten
als **Literale**:

``alembic/versions/0008_manual_override.py:57-60``
    ``source IN ('device', 'frontend_4h', 'frontend_midnight',
    'frontend_checkout')``

Ein fuenfter Wert ist damit ohne Migration nicht einfuegbar — der erste
Insert scheitert mit ``CheckViolation``. Das ist dieselbe Falle wie bei
``CommandReason`` in Sprint 12 T3 (CLAUDE.md §5.45): die
Enum-Definition im Python-Code sagt nichts darueber, was die Datenbank
akzeptiert.

Geprueft vor der Aenderung: ``device_manual`` hat 13 Zeichen, die Spalte ist
``String(30)`` (``SQLEnum(..., native_enum=False, length=30)``,
``models/manual_override.py:57-66``). Es ist also **nur** der CHECK neu zu
schreiben, keine Spaltenaenderung.

**Warum der neue Wert und nicht ``device``:** ``device`` ist ein
*abgeleiteter* Befund — der gemeldete Sollwert weicht vom letzten
Engine-Send ab, also hat vermutlich jemand gedreht (AE-45). Das kann aber
auch ein Reboot-Drift oder ein verlorener Downlink sein, und deshalb haelt
dieser Override bis zum Check-out: im Zweifel schuetzt er den Gastwunsch.

``device_manual`` ist eine *Meldung des Geraets*. Seit Sprint 20f T1
dekodiert der Codec den ``0x28``-Frame ("Manual target temp change",
FW >= 3.5) — die Vicki sagt selbst, dass am Rad gedreht wurde. Kein
Rateschritt, und daraus folgt der kuerzere Ablauf von vier Stunden.

Die Unterscheidung ist auch im Audit wertvoll: ein ``device_manual`` im
Verlauf eines Zimmers heisst "ein Gast hat gedreht", ein ``device`` heisst
"die Engine hat eine Abweichung gesehen und sie dem Gast zugeschrieben".
Das sind verschiedene Aussagen, und sie waren bis hierher nicht
unterscheidbar.

**Bestandszeilen bleiben unberuehrt.** Kein Backfill, keine Umdeutung
vorhandener ``device``-Zeilen: welche davon aus einer echten Drehung kamen,
ist nachtraeglich nicht entscheidbar — die Payloads liegen als base64 in
``sensor_reading.raw_payload``, aber die Zuordnung Override zu Frame nicht.
Eine Umdeutung waere eine Behauptung (§5.68).

Der ``downgrade`` stellt den alten CHECK wieder her und **loescht vorher
alle ``device_manual``-Zeilen**, sonst schlaegt das Anlegen des alten CHECK
fehl. Das ist Datenverlust, aber der einzige Weg zurueck; ein Umschreiben
auf ``device`` waere stillschweigend eine andere Aussage.

Revision-ID unter 32 Zeichen (``alembic_version.version_num`` ist
``VARCHAR(32)``): ``0026_override_device_manual`` = 26 Zeichen.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0026_override_device_manual"
down_revision: str | None = "0025_sensor_reading_calib"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CONSTRAINT = "ck_manual_override_source"
TABLE = "manual_override"

ALT = "source IN ('device', 'frontend_4h', 'frontend_midnight', 'frontend_checkout')"
NEU = (
    "source IN ('device', 'device_manual', 'frontend_4h', 'frontend_midnight', 'frontend_checkout')"
)


def upgrade() -> None:
    op.drop_constraint(CONSTRAINT, TABLE, type_="check")
    op.create_check_constraint(CONSTRAINT, TABLE, sa.text(NEU))


def downgrade() -> None:
    # Pflicht vor dem alten CHECK: Zeilen entfernen, die er nicht erlaubt.
    op.execute(sa.text(f"DELETE FROM {TABLE} WHERE source = 'device_manual'"))
    op.drop_constraint(CONSTRAINT, TABLE, type_="check")
    op.create_check_constraint(CONSTRAINT, TABLE, sa.text(ALT))
