"""Initiales Domain-Model: Zimmer, Zonen, Geräte, Belegung, Regeln, Telemetrie.

Erzeugt alle Kern-Tabellen für Sprint 2 und konvertiert ``sensor_reading``
in eine TimescaleDB-Hypertable.

Revision ID: 0001_initial
Revises:
Create Date: 2026-04-20
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # TimescaleDB-Extension sicherstellen. Im Docker-Image vorhanden.
    op.execute("CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE")

    # -----------------------------------------------------------------
    # room_type
    # -----------------------------------------------------------------
    op.create_table(
        "room_type",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("description", sa.String(length=500)),
        sa.Column("is_bookable", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("default_t_occupied", sa.Numeric(4, 1), nullable=False, server_default="21.0"),
        sa.Column("default_t_vacant", sa.Numeric(4, 1), nullable=False, server_default="18.0"),
        sa.Column("default_t_night", sa.Numeric(4, 1), nullable=False, server_default="19.0"),
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
        sa.UniqueConstraint("name", name="uq_room_type_name"),
    )

    # -----------------------------------------------------------------
    # room
    # -----------------------------------------------------------------
    op.create_table(
        "room",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("number", sa.String(length=20), nullable=False),
        sa.Column("display_name", sa.String(length=100)),
        sa.Column(
            "room_type_id",
            sa.Integer(),
            sa.ForeignKey("room_type.id", ondelete="RESTRICT", name="fk_room_room_type"),
            nullable=False,
        ),
        sa.Column("floor", sa.Integer()),
        sa.Column("orientation", sa.String(length=4)),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default="vacant",
        ),
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
        sa.UniqueConstraint("number", name="uq_room_number"),
    )
    op.create_index("ix_room_status", "room", ["status"])

    # -----------------------------------------------------------------
    # heating_zone
    # -----------------------------------------------------------------
    op.create_table(
        "heating_zone",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "room_id",
            sa.Integer(),
            sa.ForeignKey("room.id", ondelete="CASCADE", name="fk_heating_zone_room"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column(
            "is_towel_warmer",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
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
        sa.UniqueConstraint("room_id", "name", name="uq_heating_zone_room_name"),
    )

    # -----------------------------------------------------------------
    # device
    # -----------------------------------------------------------------
    op.create_table(
        "device",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("dev_eui", sa.String(length=16), nullable=False),
        sa.Column("app_eui", sa.String(length=16)),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("vendor", sa.String(length=20), nullable=False),
        sa.Column("model", sa.String(length=50), nullable=False),
        sa.Column(
            "heating_zone_id",
            sa.Integer(),
            sa.ForeignKey("heating_zone.id", ondelete="SET NULL", name="fk_device_heating_zone"),
        ),
        sa.Column("label", sa.String(length=200)),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("last_seen_at", sa.DateTime(timezone=True)),
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
        sa.UniqueConstraint("dev_eui", name="uq_device_dev_eui"),
    )

    # -----------------------------------------------------------------
    # occupancy
    # -----------------------------------------------------------------
    op.create_table(
        "occupancy",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "room_id",
            sa.Integer(),
            sa.ForeignKey("room.id", ondelete="CASCADE", name="fk_occupancy_room"),
            nullable=False,
        ),
        sa.Column("check_in", sa.DateTime(timezone=True), nullable=False),
        sa.Column("check_out", sa.DateTime(timezone=True), nullable=False),
        sa.Column("guest_count", sa.Integer()),
        sa.Column(
            "source",
            sa.String(length=20),
            nullable=False,
            server_default="manual",
        ),
        sa.Column("external_id", sa.String(length=100)),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("cancelled_at", sa.DateTime(timezone=True)),
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
    )
    op.create_index("ix_occupancy_room_checkin", "occupancy", ["room_id", "check_in"])
    op.create_index("ix_occupancy_checkin_checkout", "occupancy", ["check_in", "check_out"])

    # -----------------------------------------------------------------
    # rule_config
    # -----------------------------------------------------------------
    op.create_table(
        "rule_config",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("scope", sa.String(length=20), nullable=False),
        sa.Column(
            "room_type_id",
            sa.Integer(),
            sa.ForeignKey("room_type.id", ondelete="CASCADE", name="fk_rule_config_room_type"),
        ),
        sa.Column(
            "room_id",
            sa.Integer(),
            sa.ForeignKey("room.id", ondelete="CASCADE", name="fk_rule_config_room"),
        ),
        sa.Column("t_occupied", sa.Numeric(4, 1)),
        sa.Column("t_vacant", sa.Numeric(4, 1)),
        sa.Column("t_night", sa.Numeric(4, 1)),
        sa.Column("night_start", sa.Time()),
        sa.Column("night_end", sa.Time()),
        sa.Column("preheat_minutes_before_checkin", sa.Integer()),
        sa.Column("setback_minutes_after_checkout", sa.Integer()),
        sa.Column("long_vacant_hours", sa.Integer()),
        sa.Column("t_long_vacant", sa.Numeric(4, 1)),
        sa.Column("guest_override_min", sa.Numeric(4, 1)),
        sa.Column("guest_override_max", sa.Numeric(4, 1)),
        sa.Column("guest_override_duration_minutes", sa.Integer()),
        sa.Column("window_open_drop_celsius", sa.Numeric(4, 1)),
        sa.Column("window_open_window_minutes", sa.Integer()),
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
            name="ck_rule_config_scope_consistency",
        ),
        sa.UniqueConstraint(
            "scope",
            "room_type_id",
            "room_id",
            name="uq_rule_config_scope_target",
        ),
    )

    # -----------------------------------------------------------------
    # sensor_reading — Hypertable
    # -----------------------------------------------------------------
    op.create_table(
        "sensor_reading",
        sa.Column("time", sa.DateTime(timezone=True), primary_key=True, nullable=False),
        sa.Column(
            "device_id",
            sa.Integer(),
            sa.ForeignKey("device.id", ondelete="CASCADE", name="fk_sensor_reading_device"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("temperature", sa.Numeric(5, 2)),
        sa.Column("setpoint", sa.Numeric(5, 2)),
        sa.Column("valve_position", sa.SmallInteger()),
        sa.Column("battery_percent", sa.SmallInteger()),
        sa.Column("rssi_dbm", sa.SmallInteger()),
        sa.Column("snr_db", sa.Numeric(4, 1)),
        sa.Column("raw_payload", sa.String()),
    )
    op.create_index("ix_sensor_reading_device_time", "sensor_reading", ["device_id", "time"])
    # Hypertable-Konvertierung. 1 Tag Chunk-Intervall ist für 45 Zimmer × 2
    # Thermostate × Messungen/15 min ausreichend dimensioniert.
    op.execute(
        "SELECT create_hypertable("
        "'sensor_reading', 'time',"
        " chunk_time_interval => INTERVAL '1 day',"
        " if_not_exists => TRUE"
        ")"
    )

    # -----------------------------------------------------------------
    # control_command
    # -----------------------------------------------------------------
    op.create_table(
        "control_command",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "issued_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "device_id",
            sa.Integer(),
            sa.ForeignKey("device.id", ondelete="CASCADE", name="fk_control_command_device"),
            nullable=False,
        ),
        sa.Column("target_setpoint", sa.Numeric(5, 2), nullable=False),
        sa.Column("reason", sa.String(length=30), nullable=False),
        sa.Column("rule_context", sa.String()),
        sa.Column("sent_to_gateway_at", sa.DateTime(timezone=True)),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True)),
    )
    op.create_index(
        "ix_control_command_device_issued",
        "control_command",
        ["device_id", "issued_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_control_command_device_issued", table_name="control_command")
    op.drop_table("control_command")

    op.drop_index("ix_sensor_reading_device_time", table_name="sensor_reading")
    op.drop_table("sensor_reading")

    op.drop_table("rule_config")

    op.drop_index("ix_occupancy_checkin_checkout", table_name="occupancy")
    op.drop_index("ix_occupancy_room_checkin", table_name="occupancy")
    op.drop_table("occupancy")

    op.drop_table("device")
    op.drop_table("heating_zone")

    op.drop_index("ix_room_status", table_name="room")
    op.drop_table("room")
    op.drop_table("room_type")
