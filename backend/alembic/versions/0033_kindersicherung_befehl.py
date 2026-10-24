"""``device.child_lock_commanded_at`` — wann die Sperre gesendet wurde (24d).

**Der Befund aus dem Realbetrieb (Betreiber, 24.10.2026).** Direkt nach
dem Umschalten auf „nur messen" zeigte die Geraeteseite
**„Kindersicherung nicht gesetzt"** in Rot — statt „ausstehend". Der
Downlink war gerade hinausgegangen, eine Antwort konnte es noch nicht
geben.

Die Ursache ist eine fehlende Zeit. ``child_lock_state`` las die
**juengste** Meldung mit dem Feld und verglich sie mit dem gewollten
Zustand. Nach dem Umschalten ist die juengste Meldung aber die vom
Keepalive **davor** — sie sagt „Rad frei", und das war bis zur Sekunde
vorher auch richtig. Ohne den Zeitpunkt des Befehls ist eine alte
Antwort nicht von einer Ablehnung zu unterscheiden.

Das ist der Fehler aus §5.79 in seiner lauten Form: ein Melder, der im
Normalfall rot zeigt, wird nach einer Woche nicht mehr gelesen — und dann
auch nicht in dem einen Fall, in dem die Sperre wirklich nicht sitzt.

**Warum eine Spalte und nicht der Audit-Eintrag.** Die Zeit stand
bereits im ``business_audit`` (``DEVICE_MEASURE_ONLY_TOGGLED``). Sie von
dort zu lesen haette eine Anzeige an eine Protokoll-Tabelle gehaengt,
die man loeschen oder umbauen darf, ohne an die Geraeteseite zu denken —
und die Abfrage waere je Geraet eine Suche im Protokoll geworden, in
einer Liste mit 104 Zeilen. Die Zeit gehoert zum Geraet.

**Additiv:** eine neue, ``NULL``-bare Spalte. Bestandszeilen tragen
``NULL``, und das ist der richtige Wert — fuer die Geraete, die vor
dieser Migration umgeschaltet wurden, ist der Zeitpunkt nicht bekannt.
Die Ableitung behandelt ``NULL`` wie „kein Befehl bekannt" und urteilt
dann wie vorher.

Migration additiv: **ja**.

Revision-ID unter 32 Zeichen (§5.80 dritter Fall):
``0033_kindersicherung_befehl`` = 26.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0033_kindersicherung_befehl"
down_revision: str | None = "0032_override_bereich"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "device",
        sa.Column("child_lock_commanded_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("device", "child_lock_commanded_at")
