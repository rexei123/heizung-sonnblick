"""device.health_state + heating_zone.health_state (Sprint 11, AE-53).

Additive Schema-Vorbereitung fuer das Health-State-Modell aus
STRATEGIE-THERMOSTAT-ZUORDNUNG.md §4. Beide Spalten werden initial
mit ``silent`` befuellt — der periodische Compute-Task aus Sprint 11
T5 hebt sie nach Deploy auf ``healthy``, sobald frische Uplinks
vorliegen (Defensive nach S5).

Wertebereiche:

- ``device.health_state`` ∈ {healthy, degraded, silent, suspicious}
- ``heating_zone.health_state`` ∈ {healthy, degraded, silent, no_device}

CHECK-Constraints sichern die Werte auf DB-Ebene; der Engine- und
Compute-Task-Code in Sprint 11 darf sich darauf verlassen, dass
keine Fremdwerte durchrutschen.

``server_default='silent'`` macht den Backfill aller bestehenden
Rows atomar mit dem ADD COLUMN — Postgres setzt fuer neu angelegte
NOT-NULL-Spalten mit DEFAULT den Wert automatisch.

Revision ID: 0015_health_state
Revises: 0014_auth_and_business_audit
Create Date: 2026-05-17
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0015_health_state"
down_revision: str | None = "0014_auth_and_business_audit"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "device",
        sa.Column(
            "health_state",
            sa.String(length=16),
            nullable=False,
            server_default="silent",
        ),
    )
    op.create_check_constraint(
        "ck_device_health_state",
        "device",
        "health_state IN ('healthy', 'degraded', 'silent', 'suspicious')",
    )
    op.add_column(
        "heating_zone",
        sa.Column(
            "health_state",
            sa.String(length=16),
            nullable=False,
            server_default="silent",
        ),
    )
    op.create_check_constraint(
        "ck_heating_zone_health_state",
        "heating_zone",
        "health_state IN ('healthy', 'degraded', 'silent', 'no_device')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_heating_zone_health_state", "heating_zone")
    op.drop_column("heating_zone", "health_state")
    op.drop_constraint("ck_device_health_state", "device")
    op.drop_column("device", "health_state")
