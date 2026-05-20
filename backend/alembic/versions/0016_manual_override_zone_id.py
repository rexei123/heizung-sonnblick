"""manual_override.heating_zone_id (Sprint 12a T1, AE-58).

Erweitert ``manual_override`` um optionale Zone-Granularitaet. Bestehende
Rows bleiben ``heating_zone_id = NULL`` (Room-Scope-Override als
Backward-Compat-Pfad bis zur naechsten Override-Erneuerung). Engine
Layer 3 (T5) priorisiert Zone-Match vor Room-Match.

FK ``heating_zone(id) ON DELETE SET NULL``: wenn eine Zone geloescht
wird, faellt der Override automatisch auf Room-Scope zurueck statt
einen Foreign-Key-Crash auszuloesen. CASCADE waere zu aggressiv —
Override-Audit bleibt erhalten, Engine ignoriert ihn dann als
Room-Scope-Override.

Zusaetzlicher Partial Index ``ix_manual_override_active_zone`` deckt
den Zone-Lookup-Pfad ab (Sprint 12a T2 ``get_active`` mit
``heating_zone_id`` Argument). Bestehender Index
``ix_manual_override_active`` bleibt fuer Room-Scope-Lookups
unveraendert.

Revision ID: 0016_manual_override_zone_id
Revises: 0015_health_state
Create Date: 2026-05-20
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0016_manual_override_zone_id"
down_revision: str | None = "0015_health_state"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "manual_override",
        sa.Column("heating_zone_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_manual_override_heating_zone",
        "manual_override",
        "heating_zone",
        ["heating_zone_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_manual_override_active_zone",
        "manual_override",
        ["room_id", "heating_zone_id", sa.text("created_at DESC")],
        postgresql_where=sa.text("revoked_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_manual_override_active_zone", table_name="manual_override")
    op.drop_constraint(
        "fk_manual_override_heating_zone",
        "manual_override",
        type_="foreignkey",
    )
    op.drop_column("manual_override", "heating_zone_id")
