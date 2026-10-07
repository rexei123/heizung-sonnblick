"""``device.mounted_confirmed_at`` — der Montage-Nachweis als Lebenszyklus-Tatsache.

**Sprint 20e, T1.** Bis hierher war der Montage-Status eines Geraets ein
**Zustand**: Layer 4 der Engine liest ``sensor_reading.attached_backplate``
des letzten Frames und urteilt daraus "abgenommen" oder nicht. Das ist der
Melder, dem im Haus niemand mehr glaubt (§5.79) — der Taster meldet
``false``, obwohl das Geraet sitzt, und die Engine schaltet in den
Frostschutz.

Der Sprint dreht die Frage um: statt zu fragen "sitzt es **jetzt**?" fragen
wir "**war** es je belegt montiert?". Dafuer reicht eine Richtung — wir
brauchen einmal einen Beleg, keinen Dauerzustand.

**Warum eine Spalte und nicht read-time abgeleitet (§5.73):**

1. Das Praedikat ist monoton ueber die ganze Historie. Read-time waere es
   ein ``EXISTS`` ohne Zeitgrenze: billig, solange es **wahr** ist (erster
   Treffer, Index ``ix_sensor_reading_device_time``), und teuer, wenn es
   **falsch** ist — dann liest es die ganze Historie des Geraets. Falsch ist
   es genau bei den interessanten Geraeten: Pool und defekt. Bei 45 Zimmern
   waeren das 45 solche Abfragen je Minute, dauerhaft.
2. ``sensor_reading`` ist eine Hypertable, und Retention ist vorgesehen
   (B-17-2). Ein Nachweis, der aus Daten abgeleitet wird, die geloescht
   werden duerfen, ist kein Nachweis.

**Vorbild AE-57** (``retired_at``): eine Lebenszyklus-Tatsache des Geraets,
``TIMESTAMPTZ NULL``, geschrieben von genau den Service-Pfaden, die den
Vorgang abbilden — kein direkter Schreibweg aus Schema oder API.

**Kein Backfill im Schema.** Der Nachweis urteilt fachlich ("beide
Bedingungen in einem Frame"), und ein fachliches Urteil gehoert nicht in
eine Migration, die nicht wiederholbar ist. Er liegt als Skript in
``scripts/backfill_mounted_confirmed.py`` (T2, §5.61: committet selbst, mit
Bericht). Ohne Backfill bleibt die Spalte fuer die heute montierten Geraete
``NULL``, bis der naechste Frame mit geoeffnetem Ventil kommt — und das
waere bei einem fertig montierten Geraet im Winterbetrieb erst die naechste
Heizanforderung.

Revision-ID unter 32 Zeichen (``alembic_version.version_num`` ist
``VARCHAR(32)``): ``0027_device_mounted_conf`` = 24 Zeichen (CLAUDE.md
§5.80, dritter Fall).
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0027_device_mounted_conf"
down_revision: str | None = "0026_override_device_manual"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "device",
        sa.Column("mounted_confirmed_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("device", "mounted_confirmed_at")
