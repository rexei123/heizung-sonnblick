"""Sprint 8 Stammdaten-Schema: Saison, Szenarien, GlobalConfig, Manuelle Setpoints.

Erweitert das Domain-Model fuer Sprint 8 (Stammdaten + Belegung) und Sprint 10
(Saison + Szenarien + Sommermodus). Engine-Logik (Sprint 9) und event_log
Hypertable (Migration 0003b) bleiben in eigenen Migrationen.

Revision ID: 0003a_stammdaten
Revises: 0002_lorawan_fcnt
Create Date: 2026-05-02
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import time

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003a_stammdaten"
down_revision: str | None = "0002_lorawan"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # -----------------------------------------------------------------
    # season — Zeitraum-Override (AE-26)
    # -----------------------------------------------------------------
    op.create_table(
        "season",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("starts_on", sa.Date(), nullable=False),
        sa.Column("ends_on", sa.Date(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("notes", sa.String(length=1000)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("name", name="uq_season_name"),
        sa.CheckConstraint("starts_on <= ends_on", name="ck_season_dates_ordered"),
    )
    op.create_index(
        "ix_season_active_range",
        "season",
        ["is_active", "starts_on", "ends_on"],
    )

    # -----------------------------------------------------------------
    # scenario — Szenario-Stammdaten (AE-27)
    # -----------------------------------------------------------------
    op.create_table(
        "scenario",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(length=50), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("description", sa.String(length=1000)),
        sa.Column("is_system", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "default_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("parameter_schema", sa.dialects.postgresql.JSONB()),
        sa.Column("default_parameters", sa.dialects.postgresql.JSONB()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("code", name="uq_scenario_code"),
    )

    # -----------------------------------------------------------------
    # scenario_assignment — Aktivierung pro Scope (AE-27)
    # -----------------------------------------------------------------
    op.create_table(
        "scenario_assignment",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "scenario_id",
            sa.Integer(),
            sa.ForeignKey(
                "scenario.id",
                ondelete="CASCADE",
                name="fk_scenario_assignment_scenario",
            ),
            nullable=False,
        ),
        sa.Column("scope", sa.String(length=20), nullable=False),
        sa.Column(
            "room_type_id",
            sa.Integer(),
            sa.ForeignKey(
                "room_type.id",
                ondelete="CASCADE",
                name="fk_scenario_assignment_room_type",
            ),
        ),
        sa.Column(
            "room_id",
            sa.Integer(),
            sa.ForeignKey(
                "room.id",
                ondelete="CASCADE",
                name="fk_scenario_assignment_room",
            ),
        ),
        sa.Column(
            "season_id",
            sa.Integer(),
            sa.ForeignKey(
                "season.id",
                ondelete="CASCADE",
                name="fk_scenario_assignment_season",
            ),
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column("parameters", sa.dialects.postgresql.JSONB()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(scope = 'global' AND room_type_id IS NULL AND room_id IS NULL)"
            " OR (scope = 'room_type' AND room_type_id IS NOT NULL AND room_id IS NULL)"
            " OR (scope = 'room' AND room_id IS NOT NULL AND room_type_id IS NULL)",
            name="ck_scenario_assignment_scope_consistency",
        ),
        sa.UniqueConstraint(
            "scenario_id",
            "scope",
            "room_type_id",
            "room_id",
            "season_id",
            name="uq_scenario_assignment_scope_target",
        ),
    )
    op.create_index(
        "ix_scenario_assignment_scenario_active",
        "scenario_assignment",
        ["scenario_id", "is_active"],
    )

    # -----------------------------------------------------------------
    # global_config — Singleton (AE-28)
    # -----------------------------------------------------------------
    op.create_table(
        "global_config",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=False),
        sa.Column("hotel_name", sa.String(length=200), nullable=False, server_default="Hotel"),
        sa.Column(
            "timezone",
            sa.String(length=50),
            nullable=False,
            server_default="Europe/Vienna",
        ),
        sa.Column(
            "default_checkin_time",
            sa.Time(),
            nullable=False,
            server_default=sa.text("'14:00:00'"),
        ),
        sa.Column(
            "default_checkout_time",
            sa.Time(),
            nullable=False,
            server_default=sa.text("'11:00:00'"),
        ),
        sa.Column(
            "summer_mode_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("summer_mode_starts_on", sa.Date()),
        sa.Column("summer_mode_ends_on", sa.Date()),
        sa.Column("alert_email", sa.String(length=200)),
        sa.Column(
            "alert_device_offline_minutes",
            sa.Integer(),
            nullable=False,
            server_default="120",
        ),
        sa.Column(
            "alert_battery_warn_percent",
            sa.Integer(),
            nullable=False,
            server_default="20",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("id = 1", name="ck_global_config_singleton"),
        sa.CheckConstraint(
            "(summer_mode_starts_on IS NULL AND summer_mode_ends_on IS NULL)"
            " OR (summer_mode_starts_on IS NOT NULL AND summer_mode_ends_on IS NOT NULL"
            " AND summer_mode_starts_on <= summer_mode_ends_on)",
            name="ck_global_config_summer_dates",
        ),
        sa.CheckConstraint(
            "alert_device_offline_minutes >= 1 AND alert_device_offline_minutes <= 1440",
            name="ck_global_config_alert_offline_minutes",
        ),
        sa.CheckConstraint(
            "alert_battery_warn_percent >= 1 AND alert_battery_warn_percent <= 100",
            name="ck_global_config_alert_battery",
        ),
    )

    # Singleton-Row anlegen mit Defaults aus Sprint-8-Brief.
    # hotelsonnblick@gmail.com aus Strategie / .env-Convention.
    op.execute(
        """
        INSERT INTO global_config (
            id, hotel_name, timezone, default_checkin_time, default_checkout_time,
            summer_mode_active, alert_email, alert_device_offline_minutes,
            alert_battery_warn_percent
        ) VALUES (
            1, 'Hotel Sonnblick', 'Europe/Vienna', '14:00:00', '11:00:00',
            false, 'hotelsonnblick@gmail.com', 120, 20
        )
        ON CONFLICT (id) DO NOTHING
        """
    )

    # -----------------------------------------------------------------
    # manual_setpoint_event — One-Off-Aktion (AE-29)
    # -----------------------------------------------------------------
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
        sa.CheckConstraint(
            "starts_at < ends_at", name="ck_manual_setpoint_event_time_ordered"
        ),
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

    # -----------------------------------------------------------------
    # room_type — Sprint-8-Erweiterungen (AE-30)
    # -----------------------------------------------------------------
    op.add_column(
        "room_type",
        sa.Column("max_temp_celsius", sa.Numeric(4, 1)),
    )
    op.add_column(
        "room_type",
        sa.Column("min_temp_celsius", sa.Numeric(4, 1)),
    )
    op.add_column(
        "room_type",
        sa.Column("treat_unoccupied_as_vacant_after_hours", sa.Integer()),
    )

    # -----------------------------------------------------------------
    # rule_config — Saison-Resolution (AE-26)
    # -----------------------------------------------------------------
    op.add_column(
        "rule_config",
        sa.Column(
            "season_id",
            sa.Integer(),
            sa.ForeignKey(
                "season.id",
                ondelete="CASCADE",
                name="fk_rule_config_season",
            ),
        ),
    )
    # Alten UNIQUE-Constraint ohne season_id durch neuen mit season_id ersetzen.
    op.drop_constraint(
        "uq_rule_config_scope_target", "rule_config", type_="unique"
    )
    op.create_unique_constraint(
        "uq_rule_config_scope_target",
        "rule_config",
        ["scope", "room_type_id", "room_id", "season_id"],
    )


def downgrade() -> None:
    # rule_config — Saison entfernen, alten UNIQUE wiederherstellen
    op.drop_constraint(
        "uq_rule_config_scope_target", "rule_config", type_="unique"
    )
    op.drop_constraint("fk_rule_config_season", "rule_config", type_="foreignkey")
    op.drop_column("rule_config", "season_id")
    op.create_unique_constraint(
        "uq_rule_config_scope_target",
        "rule_config",
        ["scope", "room_type_id", "room_id"],
    )

    # room_type — Sprint-8-Erweiterungen entfernen
    op.drop_column("room_type", "treat_unoccupied_as_vacant_after_hours")
    op.drop_column("room_type", "min_temp_celsius")
    op.drop_column("room_type", "max_temp_celsius")

    # manual_setpoint_event
    op.drop_index(
        "ix_manual_setpoint_event_active_window",
        table_name="manual_setpoint_event",
    )
    op.drop_table("manual_setpoint_event")

    # global_config (Singleton-Row wird mit Tabelle entfernt)
    op.drop_table("global_config")

    # scenario_assignment
    op.drop_index(
        "ix_scenario_assignment_scenario_active",
        table_name="scenario_assignment",
    )
    op.drop_table("scenario_assignment")

    # scenario
    op.drop_table("scenario")

    # season
    op.drop_index("ix_season_active_range", table_name="season")
    op.drop_table("season")
