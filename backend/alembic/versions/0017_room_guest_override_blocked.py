"""room.guest_override_blocked (Sprint 12c, AE-58).

Erweitert ``room`` um die Uebersteuerungs-Sperre: ist das Feld ``true``,
weisen Service- und Adapter-Layer jede Override-Anlage ab (Single-
Source-of-Truth: ``override_service.create``). Sprint 12a hatte AE-58
auf Zone-Granularitaet erweitert; Sprint 12c ergaenzt den Block-Schalter
pro Zimmer, der den gesamten Override-Stack des Raums sperrt.

Backward-Compat: bestehende Rows bekommen ``false`` via Server-Default
beim ``add_column``. Direkt danach wird der Server-Default wieder
entfernt — der Default lebt von da an im ORM-Modell (``default=False``).
Pattern identisch zu Sprint 8.7-Aufstockungen: NOT NULL + Backfill in
einem Migration-Schritt ohne separaten Backfill-Job, weil das Feld
ein neues Flag mit klarer Default-Semantik ist.

Begriffstrennung (AE-58 Sprint 12c, siehe ARCHITEKTUR-ENTSCHEIDUNGEN):
``RoomStatus.BLOCKED`` ist „Zimmer gesperrt" als Operations-Zustand
(blockt die Engine komplett heraus). ``guest_override_blocked`` ist
„Uebersteuerung gesperrt" — Engine laeuft normal, aber Override-Anlage
ist abgewiesen.

Revision ID: 0017_room_guest_override_blocked
Revises: 0016_manual_override_zone_id
Create Date: 2026-05-20
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0017_room_guest_override_blocked"
down_revision: str | None = "0016_manual_override_zone_id"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "room",
        sa.Column(
            "guest_override_blocked",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    # Server-Default nach Backfill entfernen — Default lebt im ORM-Modell.
    op.alter_column("room", "guest_override_blocked", server_default=None)


def downgrade() -> None:
    op.drop_column("room", "guest_override_blocked")
