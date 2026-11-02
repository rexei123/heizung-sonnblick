"""Boost: ``rule_config.boost_temperature`` und die Quelle ``frontend_boost``.

Zwei Aenderungen, beide additiv.

**1. ``rule_config.boost_temperature``** (``Numeric(4,1)``, nullable). Der
Wert, auf den ein Boost setzt. Er liegt in ``rule_config`` und **nicht** in
``global_config``, weil er damit derselben Kette folgt wie jeder andere
Sollwert: Zimmer schlaegt Raumtyp schlaegt hausweit
(``rules/config_resolve.resolve_rule_field``). Ein Bad darf einen anderen
Boost haben als ein Zimmer, und ein einzelnes Zimmer einen anderen als sein
Raumtyp — ohne dass dafuer eine zweite Mechanik entsteht.

``NULL`` ueberall ist der Zustand nach dieser Migration, und er ist kein
Fehler: ohne gesetzten Wert nimmt der Dienst ``guest_override_max``
derselben Kette (siehe ``services/boost.py``). Der Boost setzt dann auf den
hoechsten Wert, den die Rezeption ohnehin haette eingeben koennen — und
nicht auf eine Zahl, die sich jemand ausgedacht hat.

**2. ``manual_override.source`` erlaubt ``frontend_boost``.** Die Spalte
traegt eine DB-CHECK-Beschraenkung mit den erlaubten Werten als
**Literale**; ein neuer Wert ist ohne Migration nicht einfuegbar (§5.45,
zuletzt in ``0032``). Derselbe Handgriff, dieselbe Begruendung.

**Warum eine eigene Quelle und nicht ``frontend_24h`` mitbenutzt.** Ein
Boost ist eine andere Aussage:

* Er braucht **keine Belegung**. Die Festlegung des Betreibers vom
  31.10.2026 lautet „eine Regel fuer belegt und frei" — ein freies Zimmer
  darf einen Boost bekommen, eine Uebersteuerung nicht.
* Seine **Dauer kommt vom Nachtfenster des Zimmers** und nicht aus dem
  Namen der Quelle. Bei ``frontend_24h`` steckt die Dauer im Wert; hier
  steht sie in ``expires_at`` und sonst nirgends.
* Die Oberflaeche kennzeichnet ihn eigens (Flammen-Zeichen und
  „Boost bis HH:MM"), und das geht nur, wenn die Zeile ihn von einer
  gewoehnlichen Uebersteuerung unterscheidbar macht.

Haette die Rezeption fuer einen Boost ``frontend_24h`` geschrieben, truege
jede Zeile in Historie und Audit eine Dauer, die nicht stimmt — dieselbe
Abwaegung wie in ``0029`` und ``0032``.

``frontend_boost`` hat 14 Zeichen, die Spalte ist ``String(30)``
(``SQLEnum(..., native_enum=False, length=30)``,
``models/manual_override.py``). Nur der CHECK ist neu zu schreiben, keine
Spaltenaenderung. Vor der Aenderung nachgesehen, nicht uebernommen.

**Bestandszeilen bleiben unberuehrt.** Kein Backfill.

Der ``downgrade`` stellt den alten CHECK her und **loescht vorher alle
``frontend_boost``-Zeilen** — sonst schlaegt das Anlegen fehl. Das ist
Datenverlust, und der einzige Weg zurueck: ein Umschreiben auf eine andere
Quelle waere eine andere Aussage (eine Dauer behaupten, die nie galt).

Migration additiv: **ja** — eine Spalte hinzufuegen und eine
CHECK-Bedingung erweitern sind beides additiv (Goldene Regel 10).

Revision-ID unter 32 Zeichen (§5.80 dritter Fall): ``0036_boost`` = 10.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0036_boost"
down_revision: str | None = "0035_geraetegrenzen_messwert"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CONSTRAINT = "ck_manual_override_source"
TABLE = "manual_override"

ALT = (
    "source IN ('device', 'device_manual', 'frontend_4h', 'frontend_24h', "
    "'frontend_midnight', 'frontend_checkout', 'frontend_bereich')"
)
NEU = (
    "source IN ('device', 'device_manual', 'frontend_4h', 'frontend_24h', "
    "'frontend_midnight', 'frontend_checkout', 'frontend_bereich', "
    "'frontend_boost')"
)


def upgrade() -> None:
    op.add_column(
        "rule_config",
        sa.Column("boost_temperature", sa.Numeric(4, 1), nullable=True),
    )
    op.drop_constraint(CONSTRAINT, TABLE, type_="check")
    op.create_check_constraint(CONSTRAINT, TABLE, sa.text(NEU))


def downgrade() -> None:
    # Pflicht vor dem alten CHECK: Zeilen entfernen, die er nicht erlaubt.
    op.execute(sa.text("DELETE FROM manual_override WHERE source = 'frontend_boost'"))
    op.drop_constraint(CONSTRAINT, TABLE, type_="check")
    op.create_check_constraint(CONSTRAINT, TABLE, sa.text(ALT))
    op.drop_column("rule_config", "boost_temperature")
