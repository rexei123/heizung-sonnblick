"""``manual_override.source`` erlaubt ``frontend_24h`` (Fix A, 20.10.2026).

Die Spalte traegt eine DB-CHECK-Beschraenkung mit den erlaubten Werten als
**Literale** — angelegt in ``0008_manual_override.py``, zuletzt umgeschrieben
in ``0026_override_device_manual.py``. Ein neuer Wert ist damit ohne Migration
nicht einfuegbar: der erste Insert scheitert mit ``CheckViolation``. Das ist
dieselbe Falle wie bei ``CommandReason`` in Sprint 12 T3 (CLAUDE.md §5.45),
und sie gilt hier nachweislich — gegen ``0026`` geprueft, nicht aus der
Lesson uebernommen.

**Warum ein neuer Wert und nicht ``frontend_4h`` umgedeutet.** Die
Betreiber-Entscheidung vom 19.10.2026 ersetzt die Auswahl der Rezeption
durch zwei Moeglichkeiten: **24 Stunden** oder **bis Check-out**. Der
naheliegende Weg waere, ``frontend_4h`` einfach auf 24 Stunden zu rechnen —
dann hiesse der Wert in Datenbank, Audit und Historie etwas anderes als er
tut, und zwar dauerhaft und unbemerkt (§5.77 in Reinform: ein Name, der
mehr behauptet, als er haelt). Vier Zeichen Ersparnis gegen eine Luege in
jeder alten Zeile.

``frontend_4h`` und ``frontend_midnight`` **bleiben erlaubt**. Sie
verschwinden nur aus der Auswahl in der Oberflaeche; die Historie braucht
ihre Etiketten weiter, und Bestandszeilen bleiben lesbar. Wer sie spaeter
wirklich entfernen will, braucht eine eigene Migration **und** eine
Entscheidung darueber, was mit den alten Zeilen passiert.

Geprueft vor der Aenderung: ``frontend_24h`` hat 12 Zeichen, die Spalte ist
``String(30)`` (``SQLEnum(..., native_enum=False, length=30)``,
``models/manual_override.py:56-65``). Es ist also **nur** der CHECK neu zu
schreiben, keine Spaltenaenderung.

**Bestandszeilen bleiben unberuehrt.** Kein Backfill, keine Umdeutung: ein
vorhandener ``frontend_4h``-Eintrag war eine Vier-Stunden-Entscheidung und
bleibt eine. Die Betreiber-Vorgabe lautet ausdruecklich, bestehende aktive
Overrides nicht rueckwirkend zu aendern.

Der ``downgrade`` stellt den alten CHECK wieder her und **loescht vorher
alle ``frontend_24h``-Zeilen**, sonst schlaegt das Anlegen des alten CHECK
fehl. Das ist Datenverlust, aber der einzige Weg zurueck; ein Umschreiben
auf ``frontend_4h`` waere stillschweigend eine andere Aussage (vier Stunden
statt vierundzwanzig) und koennte einen laufenden Override verkuerzen.

Migration additiv: **ja** — eine CHECK-Bedingung zu erweitern ist additiv
(CLAUDE.md Goldene Regel 10). Ein Rueckfall per ``PIN_SHA`` auf einen Stand
vor dieser Migration ist damit zulaessig, solange keine
``frontend_24h``-Zeile existiert; danach kostet er sie.

Revision-ID unter 32 Zeichen (``alembic_version.version_num`` ist
``VARCHAR(32)``, §5.80 dritter Fall): ``0029_override_frontend_24h`` = 26.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0029_override_frontend_24h"
down_revision: str | None = "0028_global_config_pin_seen"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CONSTRAINT = "ck_manual_override_source"
TABLE = "manual_override"

ALT = (
    "source IN ('device', 'device_manual', 'frontend_4h', 'frontend_midnight', 'frontend_checkout')"
)
NEU = (
    "source IN ('device', 'device_manual', 'frontend_4h', 'frontend_24h', "
    "'frontend_midnight', 'frontend_checkout')"
)


def upgrade() -> None:
    op.drop_constraint(CONSTRAINT, TABLE, type_="check")
    op.create_check_constraint(CONSTRAINT, TABLE, sa.text(NEU))


def downgrade() -> None:
    # Pflicht vor dem alten CHECK: Zeilen entfernen, die er nicht erlaubt.
    op.execute(sa.text(f"DELETE FROM {TABLE} WHERE source = 'frontend_24h'"))
    op.drop_constraint(CONSTRAINT, TABLE, type_="check")
    op.create_check_constraint(CONSTRAINT, TABLE, sa.text(ALT))
