"""Der hausweite Boost-Wert wird auf 23,0 gesetzt, wenn er leer ist.

**Reine Daten-Migration, Entscheidung des Betreibers vom 02.11.2026.**

``0036`` hat die Spalte ``rule_config.boost_temperature`` angelegt, und sie
ist danach ueberall ``NULL``. Der erste Entwurf fiel in diesem Fall auf
``guest_override_max`` derselben Kette zurueck — den hoechsten Wert, den
die Rezeption eingeben darf.

**Das war fachlich falsch, und der Betreiber hat widersprochen.**
``guest_override_max`` ist die **Gast-Obergrenze**; sie kann 25 sein,
waehrend der festgelegte Boost-Wert **23** ist. Ein Rueckfall auf eine
Grenze, die eine andere Frage beantwortet, macht aus einem Boost
stillschweigend das Maximum — und zwar genau dort, wo niemand hinsieht,
weil beides eine plausible Zahl ist.

Deshalb: der Wert steht ausdruecklich in den Daten. Steht er trotzdem
nirgends, wird ein Boost **abgewiesen** mit dem Grund „Boost-Temperatur
nicht eingestellt" (``services/boost``). Kein Rueckfall auf eine andere
Spalte.

**Nur ein UPDATE, kein INSERT.** Gibt es keine hausweite Zeile, legt diese
Migration auch keine an: eine Zeile zu erfinden, um einen Vorgabewert
unterzubringen, waere eine Entscheidung ueber die Konfiguration des
Hauses. Fehlt sie, greift die Abweisung oben, und die nennt den Grund. Im
Haus existiert die Zeile (sie traegt heute ``t_night``); in einer frischen
Datenbank nicht, und dort ist „nicht eingestellt" die richtige Antwort.

**``WHERE boost_temperature IS NULL``** — ein bereits gesetzter Wert wird
nicht ueberschrieben. Diese Migration laeuft auf Datenbanken, in denen
jemand den Wert schon von Hand gesetzt haben kann (``0036`` ist seit
heute in ``develop``), und ihn zurueck auf 23 zu ziehen waere eine
stille Aenderung an einer wirksamen Einstellung.

Der ``downgrade`` setzt den Wert **nicht** zurueck. Er kann nicht
unterscheiden, ob die 23,0 von dieser Migration kommt oder von einem
Menschen — und ein Rueckweg, der eine Einstellung loescht, die jemand
bewusst gesetzt hat, ist schlimmer als keiner. ``0036`` entfernt die
Spalte ohnehin vollstaendig, wenn man so weit zurueckgeht.

Migration additiv: **ja** — kein Schema-Eingriff, nur ein Wert in einer
Spalte, die vorher leer war.

Revision-ID unter 32 Zeichen (Paragraph 5.80 dritter Fall):
``0037_boost_temperatur`` = 20.
"""

from collections.abc import Sequence
from decimal import Decimal

import sqlalchemy as sa

from alembic import op

revision: str = "0037_boost_temperatur"
down_revision: str | None = "0036_boost"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Festlegung des Betreibers vom 02.11.2026.
BOOST_C = Decimal("23.0")


def upgrade() -> None:
    # **Der Typ am Bindparameter ist Pflicht.** Ohne ihn schickt asyncpg
    # den Wert als ``character varying``, und Postgres weist das ab:
    # „column is of type numeric but expression is of type character
    # varying". Ein Literal in der SQL-Zeichenkette waere die andere
    # Loesung und die schlechtere — dann stuende die Zahl zweimal da.
    op.execute(
        sa.text(
            "UPDATE rule_config SET boost_temperature = :wert "
            "WHERE scope = 'global' AND boost_temperature IS NULL"
        ).bindparams(sa.bindparam("wert", value=BOOST_C, type_=sa.Numeric(4, 1)))
    )


def downgrade() -> None:
    """Absichtlich leer. Die Begruendung steht im Docstring."""
