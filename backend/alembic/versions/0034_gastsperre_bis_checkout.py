"""room.guest_block_bis_checkout (Sprint 23 T4-A).

Die Uebersteuerungs-Sperre aus Sprint 12c (``guest_override_blocked``,
Migration 0017) gilt **dauerhaft**: wer sie fuer einen Gast setzt, muss
sie nach der Abreise von Hand zuruecknehmen. Tut es niemand, hat der
naechste Gast ein Rad, das nichts bewirkt — und niemand weiss, warum.

Diese Spalte sagt, dass die Sperre **mit der Abreise endet**. Der
Belegungsabgleich loest sie dann selbst
(``services/gast_sperre.loese_bei_checkout``), in derselben Kette, die
schon die Overrides widerruft
(``occupancy_service.sync_room_status -> auto_revoke_on_checkout``).

**Zwei Spalten statt eines Moduswerts, mit Grund.** Ein einziges Feld
(``aus`` / ``dauerhaft`` / ``bis_checkout``) waere schoener zu lesen,
haette aber ``guest_override_blocked`` ersetzt — und das Feld liest die
Engine, der Geraete-Adapter und der Override-Dienst. Ein ``DROP COLUMN``
bricht den Rueckfall (Goldene Regel 10), fuer einen Gewinn, der nur die
Form betrifft.

Die unsinnige Kombination ``blocked=false`` mit ``bis_checkout=true``
wird in der API abgewiesen; die Invariante steht im Modell-Kommentar.
Ein CHECK waere der dichtere Ort, verengt aber die Tabelle und ist damit
nicht additiv.

Migration additiv: ja — nur ``add_column``, Bestandszeilen bekommen
``false`` ueber den Server-Default.

Revision ID: 0034_gastsperre_bis_checkout
Revises: 0033_kindersicherung_befehl
Create Date: 2026-10-25
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0034_gastsperre_bis_checkout"
down_revision: str | None = "0033_kindersicherung_befehl"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "room",
        sa.Column(
            "guest_block_bis_checkout",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    # Server-Default nach dem Backfill entfernen — der Default lebt von
    # hier an im ORM-Modell (``default=False``), wie bei 0017. Folge:
    # Raw-SQL-INSERTs in Tests muessen die Spalte setzen, wenn sie am
    # HEAD-Stand inserten (CLAUDE.md Paragraph 5.56).
    op.alter_column("room", "guest_block_bis_checkout", server_default=None)


def downgrade() -> None:
    op.drop_column("room", "guest_block_bis_checkout")
