"""Device-Lifecycle: retired_at + Pool-Reassign-Tausch (Sprint 13b.1, AE-57).

Loest die ``is_active``-Spalte (Migration 0001) durch ein explizites
Lifecycle-Modell ab:

- ``retired_at TIMESTAMPTZ NULL`` — NULL = aktiv, gesetzt = retired
  (unwiderruflich, Audit-Anker).
- ``retired_reason VARCHAR(255) NULL`` — Freitext-Begruendung
  (`replaced_by_pool`, `hardware_swap`, etc.).
- ``replaced_by_device_id INTEGER NULL`` — selbst-referenzielle FK auf
  ``device.id`` mit ``ON DELETE SET NULL``. Cross-Reference Alt -> Neu
  beim Tausch (AE-57 Entscheidung 6).
- Voll-Unique-Constraint ``uq_device_dev_eui`` (Migration 0001) wird
  ersetzt durch Partial-Unique-Index ``ix_device_dev_eui_active_unique``
  mit ``WHERE retired_at IS NULL``. Erlaubt mehrere retired Rows mit
  derselben DevEUI (Hardware-Drift-Forensik + Re-Pair nach Werksreset),
  Eindeutigkeit nur unter aktiven Rows.
- ``is_active``-Spalte wird gedropped (AE-57 Entscheidung 2 Uebergangs-
  Klausel: bis 13b-Merge, danach ``retired_at IS NULL`` Single Source
  of Truth).

Pattern-Mix:
- ADD von 0017 (analog Strukturmuster, hier aber 3 nullable Spalten
  ohne Backfill — kein server_default noetig).
- DROP + 1:1-Downgrade-Reproduktion von 0019 (``is_active`` und
  ``uq_device_dev_eui`` werden im Downgrade exakt wie in 0001
  wiederhergestellt: ``BOOLEAN NOT NULL server_default='true'``,
  ``UniqueConstraint(name='uq_device_dev_eui')``).

Backfill nur im Downgrade-Pfad (``UPDATE device SET is_active = FALSE
WHERE retired_at IS NOT NULL``) — Up-Pfad braucht kein Backfill, weil
alle bestehenden Rows ``is_active=TRUE`` waren und damit ``retired_at
IS NULL`` semantisch gleich sind.

Querverweise: AE-57 (Master-ADR), Phase-0-Bericht
``docs/features/2026-05-21-sprint13-phase0-quellcheck.md`` §H,
Phase-0-Update ``docs/features/2026-05-23-sprint13b-phase0-update.md``
Audit 5.

Revision ID: 0018_device_lifecycle
Revises: 0019_drop_manual_setpoint_event
Create Date: 2026-05-23
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0018_device_lifecycle"
down_revision: str | None = "0019_drop_manual_setpoint_event"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Drei neue Lifecycle-Spalten (alle nullable, kein Backfill noetig).
    op.add_column(
        "device",
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "device",
        sa.Column("retired_reason", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "device",
        sa.Column("replaced_by_device_id", sa.Integer(), nullable=True),
    )

    # 2. Selbst-referenzielle FK fuer Cross-Reference Alt -> Neu.
    op.create_foreign_key(
        "fk_device_replaced_by",
        "device",
        "device",
        ["replaced_by_device_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # 3. Voll-Unique-Constraint aus 0001 entfernen, Partial-Unique-Index
    #    anlegen (AE-57 Entscheidung 1).
    op.drop_constraint("uq_device_dev_eui", "device", type_="unique")
    op.create_index(
        "ix_device_dev_eui_active_unique",
        "device",
        ["dev_eui"],
        unique=True,
        postgresql_where=sa.text("retired_at IS NULL"),
    )

    # 4. is_active droppen (AE-57 Entscheidung 2 Uebergangs-Klausel
    #    abgeschlossen).
    op.drop_column("device", "is_active")


def downgrade() -> None:
    # 1. is_active wiederherstellen — exakt wie 0001 (NOT NULL +
    #    server_default='true'). Alle existing Rows bekommen via
    #    server_default zunaechst TRUE.
    op.add_column(
        "device",
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )

    # 2. Backfill: retired Rows bekommen is_active = FALSE. Muss VOR dem
    #    Drop von retired_at laufen, sonst ist der Filter nicht mehr
    #    auflosbar.
    op.execute(
        "UPDATE device SET is_active = FALSE WHERE retired_at IS NOT NULL"
    )

    # 3. Partial-Unique-Index droppen, Voll-Unique-Constraint
    #    wiederherstellen (1:1 wie in 0001 angelegt).
    op.drop_index("ix_device_dev_eui_active_unique", table_name="device")
    op.create_unique_constraint("uq_device_dev_eui", "device", ["dev_eui"])

    # 4. Selbst-referenzielle FK + Lifecycle-Spalten in umgekehrter
    #    Reihenfolge entfernen (FK vor Column, sonst Drop-Error).
    op.drop_constraint("fk_device_replaced_by", "device", type_="foreignkey")
    op.drop_column("device", "replaced_by_device_id")
    op.drop_column("device", "retired_reason")
    op.drop_column("device", "retired_at")
