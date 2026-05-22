"""Drop manual_setpoint_event (B-12a-1, AE-29 abgeloest durch AE-58).

Sprint 13-Hygiene-Cleanup. Sprint 12a (AE-58) hat das Override-Modell
konsolidiert und ``manual_setpoint_event`` (AE-29) als abgeloest markiert.
Wartungs-Anwendungsfaelle laufen seither ueber fiktive Belegung
(RUNBOOK §10d.7). Cleanup wurde als B-12a-1 zurueckgestellt — diese
Migration loescht die ungenutzte Tabelle (DB-seitig leer in heizung-test
+ heizung-main) inkl. Index.

Downgrade-Pfad reproduziert das Original-Schema aus Migration
``0003a_stammdaten_schema`` 1:1 (Spalten, Constraints, server_defaults,
FK-Optionen, Index) — Pflicht fuer Roundtrip-Tests (CLAUDE.md §5.56).

Down-Revision: ``0017_room_guest_override_blocked``. Der Slot
``0018_*`` ist fuer Sprint 13b (Device-Lifecycle aus AE-57) reserviert
und wird dort die Felder ``retired_at`` / ``retired_reason`` /
``replaced_by_device_id`` einfuehren.

Revision ID: 0019_drop_manual_setpoint_event
Revises: 0017_room_guest_override_blocked
Create Date: 2026-05-21
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0019_drop_manual_setpoint_event"
down_revision: str | None = "0017_room_guest_override_blocked"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Reihenfolge analog 0003a-downgrade (388-393): Index zuerst, dann
    # Table — kein FK-Eingang von anderen Tabellen, kein CASCADE-Risiko.
    op.drop_index(
        "ix_manual_setpoint_event_active_window",
        table_name="manual_setpoint_event",
    )
    op.drop_table("manual_setpoint_event")


def downgrade() -> None:
    # 1:1-Reproduktion aus 0003a:271-330 (create_table) + 326-330 (create_index).
    # ``scope`` ist VARCHAR(20), kein Postgres-Enum-Typ (im Modell als
    # SQLEnum(..., native_enum=False) gefuehrt). FK-Optionen mit
    # ON DELETE CASCADE wie im Original.
    op.create_table(
        "manual_setpoint_event",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("scope", sa.String(length=20), nullable=False),
        sa.Column(
            "room_type_id",
            sa.Integer(),
            sa.ForeignKey(
                "room_type.id",
                ondelete="CASCADE",
                name="fk_manual_setpoint_event_room_type",
            ),
        ),
        sa.Column(
            "room_id",
            sa.Integer(),
            sa.ForeignKey(
                "room.id",
                ondelete="CASCADE",
                name="fk_manual_setpoint_event_room",
            ),
        ),
        sa.Column("target_setpoint_celsius", sa.Numeric(4, 1), nullable=False),
        sa.Column(
            "starts_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=False),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column("cancelled_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(scope = 'room_type' AND room_type_id IS NOT NULL AND room_id IS NULL)"
            " OR (scope = 'room' AND room_id IS NOT NULL AND room_type_id IS NULL)",
            name="ck_manual_setpoint_event_scope_consistency",
        ),
        sa.CheckConstraint("starts_at < ends_at", name="ck_manual_setpoint_event_time_ordered"),
        sa.CheckConstraint(
            "target_setpoint_celsius >= 5.0 AND target_setpoint_celsius <= 30.0",
            name="ck_manual_setpoint_event_temp_range",
        ),
    )
    op.create_index(
        "ix_manual_setpoint_event_active_window",
        "manual_setpoint_event",
        ["is_active", "starts_at", "ends_at"],
    )
