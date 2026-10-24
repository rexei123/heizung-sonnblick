"""``manual_override.source`` erlaubt ``frontend_bereich`` (Sprint 24d).

Die Spalte traegt eine DB-CHECK-Beschraenkung mit den erlaubten Werten als
**Literale**; ein neuer Wert ist ohne Migration nicht einfuegbar (§5.45,
zuletzt belegt in ``0029``). Derselbe Handgriff wie dort, mit demselben
Grund.

**Warum ein eigener Wert und nicht ``frontend_24h`` mitbenutzt.** Eine
Uebersteuerung in einem Allgemeinbereich ist eine andere Aussage als eine
in einem Gaestezimmer:

* Sie braucht **keine Belegung** — ein Bereich hat keine. Das Gate, das
  sie erlaubt, ist der nicht buchbare Raumtyp (AE-58 bleibt fuer
  Gaestezimmer unveraendert).
* Ihre **Dauer ist frei waehlbar** bis 24 Stunden, nicht an den Namen der
  Quelle gebunden. Bei ``frontend_24h`` steckt die Dauer im Wert; hier
  steht sie in ``expires_at`` und sonst nirgends.

Haette die Rezeption fuer die Bar ``frontend_24h`` geschrieben, truege
jede Zeile in Historie und Audit eine Dauer, die nicht stimmt — und zwar
dauerhaft und unbemerkt. Vier Zeichen Ersparnis gegen eine Luege in jeder
Zeile, genau die Abwaegung aus ``0029``.

``frontend_bereich`` hat 17 Zeichen, die Spalte ist ``String(30)``
(``SQLEnum(..., native_enum=False, length=30)``,
``models/manual_override.py``). Es ist also **nur** der CHECK neu zu
schreiben, keine Spaltenaenderung. Vor der Aenderung nachgesehen, nicht
aus ``0029`` uebernommen.

**Bestandszeilen bleiben unberuehrt.** Kein Backfill, keine Umdeutung.

Der ``downgrade`` stellt den alten CHECK her und **loescht vorher alle
``frontend_bereich``-Zeilen** — sonst schlaegt das Anlegen fehl. Das ist
Datenverlust, aber der einzige Weg zurueck: ein Umschreiben auf eine
andere Quelle waere eine andere Aussage (eine Belegung behaupten, die es
nie gab).

Migration additiv: **ja** — eine CHECK-Bedingung zu erweitern ist additiv
(Goldene Regel 10).

Revision-ID unter 32 Zeichen (``alembic_version.version_num`` ist
``VARCHAR(32)``, §5.80 dritter Fall): ``0032_override_bereich`` = 21.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0032_override_bereich"
down_revision: str | None = "0031_relais_offener_befehl"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CONSTRAINT = "ck_manual_override_source"
TABLE = "manual_override"

ALT = (
    "source IN ('device', 'device_manual', 'frontend_4h', 'frontend_24h', "
    "'frontend_midnight', 'frontend_checkout')"
)
NEU = (
    "source IN ('device', 'device_manual', 'frontend_4h', 'frontend_24h', "
    "'frontend_midnight', 'frontend_checkout', 'frontend_bereich')"
)


def upgrade() -> None:
    op.drop_constraint(CONSTRAINT, TABLE, type_="check")
    op.create_check_constraint(CONSTRAINT, TABLE, sa.text(NEU))


def downgrade() -> None:
    # Pflicht vor dem alten CHECK: Zeilen entfernen, die er nicht erlaubt.
    op.execute(sa.text("DELETE FROM manual_override WHERE source = 'frontend_bereich'"))
    op.drop_constraint(CONSTRAINT, TABLE, type_="check")
    op.create_check_constraint(CONSTRAINT, TABLE, sa.text(ALT))
