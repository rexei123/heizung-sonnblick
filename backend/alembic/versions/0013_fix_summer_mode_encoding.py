"""Encoding-Fix fuer scenario.description='summer_mode' (Sprint 9.16a).

Migration 0012 hat die Description als ASCII-Replacement-Variante
(``uebernimmt``/``Raeume``) seeded. 0012 wurde nachtraeglich korrigiert,
aber bereits ausgefuehrte DBs (heizung-test) tragen weiter den
Mojibake-Stand. Diese Migration zieht sie auf den korrekten UTF-8-Stand
nach.

Down-Pfad ist absichtlich No-Op: ein Downgrade auf Mojibake zurueck
waere keine sinnvolle Wiederherstellung eines frueheren Zustands;
realistisch wird Downgrade nie ausgefuehrt.

Revision ID: 0013_fix_summer_mode_encoding
Revises: 0012_summer_mode_scenario
Create Date: 2026-05-14
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0013_fix_summer_mode_encoding"
down_revision: str | None = "0012_summer_mode_scenario"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "UPDATE scenario "
        "SET description = 'Heizthermostate funktionslos — Klimaanlage übernimmt. "
        "Alle Räume auf Frostschutz.' "
        "WHERE code = 'summer_mode'"
    )


def downgrade() -> None:
    # Intentional no-op: Downgrade wuerde Mojibake wiederherstellen,
    # was kein sinnvoller frueherer Zustand ist.
    pass
