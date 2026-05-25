"""Device-Hardware-Nummer (Sprint 14a, D1).

Additive Erweiterung fuer die Cross-Sicht-UI:

- ``hardware_number VARCHAR(64) NULL`` — hersteller-uebergreifende
  Geraete-Seriennummer (z. B. ``MDC5419731K6UF``). Keine Format-
  Validierung (Strategie-Entscheidung D3 aus Phase 0). NULL = noch
  nicht erfasst.
- Partial-Unique-Index ``ix_device_hardware_number_unique`` mit
  ``WHERE hardware_number IS NOT NULL`` — analog zum DevEUI-Pattern aus
  Migration 0018 (``ix_device_dev_eui_active_unique``). Erlaubt beliebig
  viele Rows mit ``hardware_number IS NULL`` (Bestands-Vickis ohne
  erfasste Nummer), erzwingt Eindeutigkeit nur fuer gesetzte Werte.

Rein additiv: keine bestehende Spalte/Constraint wird angefasst, kein
Backfill noetig (alle bestehenden Rows starten mit NULL).

Down-Revision: ``0018_device_lifecycle`` (echter Migrations-Head — die
Datei-Nummerierung 0018/0019 ist gegenlaeufig zur Revisions-Kette:
0017 -> 0019 -> 0018(head), verifiziert via ``alembic heads``).

Revision ID: 0020_device_hardware_number
Revises: 0018_device_lifecycle
Create Date: 2026-05-25
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0020_device_hardware_number"
down_revision: str | None = "0018_device_lifecycle"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Neue nullable Spalte (kein Backfill noetig, alle Rows starten NULL).
    op.add_column(
        "device",
        sa.Column("hardware_number", sa.String(length=64), nullable=True),
    )

    # 2. Partial-Unique-Index (analog ix_device_dev_eui_active_unique aus
    #    0018): Eindeutigkeit nur fuer gesetzte Werte, NULL beliebig oft.
    op.create_index(
        "ix_device_hardware_number_unique",
        "device",
        ["hardware_number"],
        unique=True,
        postgresql_where=sa.text("hardware_number IS NOT NULL"),
    )


def downgrade() -> None:
    # Reihenfolge umgekehrt: Index vor Column.
    op.drop_index("ix_device_hardware_number_unique", table_name="device")
    op.drop_column("device", "hardware_number")
