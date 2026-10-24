"""Der offene Befehl eines Relais (Sprint 24b, Orchestrator).

**Migration additiv: ja.** Drei neue Spalten auf ``device``, alle
nullable oder mit Server-Vorgabe. Keine Spalte entfernt, umbenannt oder
verengt, keine Bestandszeile angefasst.

**Warum diese drei und nicht mehr.** Der Waechter braucht vier
Angaben, und drei davon sind schon vorhanden oder ableitbar:

| Angabe | Woher |
|---|---|
| bestaetigter Schaltzustand | **abgeleitet** aus ``relay_reading`` |
| seit wann dieser Zustand gilt | **abgeleitet** aus ``relay_reading`` |
| Schaltzyklen | ``device.switch_cycles`` (Migration 0030) |
| **offener Befehl** | hier |

Der bestaetigte Zustand wird **nicht** auf ``device`` gespiegelt, obwohl
das eine Abfrage spart. Er steht in ``relay_reading``, und eine Kopie
daneben waere eine zweite Wahrheit, die beim ersten verpassten Uplink
auseinanderlaeuft — §5.53, und bei einem Schaltzustand ist die falsche
Haelfte der Kopie genau die, auf die sich der Waechter verlassen wuerde.

Der **offene** Befehl hat dagegen kein anderes Zuhause: er beschreibt,
was wir gesendet und noch nicht bestaetigt bekommen haben, und das steht
in keiner Zeitreihe.

**Rueckweg:** ``downgrade`` entfernt die drei Spalten. Ein laufender
offener Befehl geht dabei verloren; die Folge ist, dass der Waechter ihn
beim naechsten Durchlauf neu absetzt — kein Schaden, weil ein ``0x57``
oder ``0xC1 00`` idempotent ist.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0031_relais_offener_befehl"
down_revision = "0030_relais_und_messfuehler"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "device",
        sa.Column("pending_target_on", sa.Boolean(), nullable=True),
    )
    op.add_column(
        "device",
        sa.Column("pending_since", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "device",
        sa.Column(
            "pending_attempts",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )


def downgrade() -> None:
    op.drop_column("device", "pending_attempts")
    op.drop_column("device", "pending_since")
    op.drop_column("device", "pending_target_on")
