"""Auth + business_audit fuer Sprint 9.17 (AE-50).

Drei Schemas in einer atomaren Migration:

1. ``user``-Tabelle (Postgres-Reserved-Word, IMMER mit Quotes in
   handgeschriebenem SQL). Spalten gemaess AE-50 / Phase-0-Befund A1.
2. ``business_audit``-Tabelle (operative Mitarbeiter-Aktionen).
   FK auf ``user.id``, nullable solange ``AUTH_ENABLED=false``.
3. ``config_audit.user_id`` FK auf ``user.id`` (Sprint-9.14-Vorbereitung
   wird endlich verknuepft).

Bootstrap-Admin: wenn die ENV-Variablen ``INITIAL_ADMIN_EMAIL`` und
``INITIAL_ADMIN_PASSWORD_HASH`` gesetzt sind UND die ``user``-Tabelle
leer ist, wird ein erster Admin-Account mit
``must_change_password=true`` angelegt. Ohne ENV-Variablen: kein
Bootstrap (Tests / CI-Setup, kein automatischer Default-Admin).

Revision ID: 0014_auth_and_business_audit
Revises: 0013_fix_summer_mode_encoding
Create Date: 2026-05-14
"""

from __future__ import annotations

import os
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0014_auth_and_business_audit"
down_revision: str | None = "0013_fix_summer_mode_encoding"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. user-Tabelle
    op.create_table(
        "user",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("email", sa.String(length=255), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "must_change_password",
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
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "role IN ('admin', 'mitarbeiter')",
            name="ck_user_role",
        ),
    )
    op.create_index("idx_user_email", "user", ["email"])

    # 2. business_audit-Tabelle
    op.create_table(
        "business_audit",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "ts",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("user.id", name="fk_business_audit_user"),
            nullable=True,
        ),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("target_type", sa.String(length=64), nullable=False),
        sa.Column("target_id", sa.Integer(), nullable=True),
        sa.Column("old_value", postgresql.JSONB(), nullable=True),
        sa.Column("new_value", postgresql.JSONB(), nullable=False),
        sa.Column("request_ip", postgresql.INET(), nullable=True),
    )
    op.create_index(
        "idx_business_audit_target_ts",
        "business_audit",
        ["target_type", "target_id", sa.text("ts DESC")],
    )
    op.create_index(
        "idx_business_audit_user_ts",
        "business_audit",
        ["user_id", sa.text("ts DESC")],
    )

    # 3. config_audit.user_id FK auf user
    op.create_foreign_key(
        "fk_config_audit_user",
        "config_audit",
        "user",
        ["user_id"],
        ["id"],
    )

    # 4. Bootstrap-Admin (idempotent + ENV-abhaengig)
    admin_email = os.environ.get("INITIAL_ADMIN_EMAIL")
    admin_hash = os.environ.get("INITIAL_ADMIN_PASSWORD_HASH")
    if admin_email and admin_hash:
        conn = op.get_bind()
        result = conn.execute(sa.text('SELECT COUNT(*) FROM "user"'))
        count = result.scalar() or 0
        if count == 0:
            conn.execute(
                sa.text(
                    'INSERT INTO "user" '
                    "(email, password_hash, role, is_active, must_change_password, "
                    "created_at, updated_at) "
                    "VALUES (:email, :hash, 'admin', true, true, now(), now())"
                ),
                {"email": admin_email, "hash": admin_hash},
            )


def downgrade() -> None:
    op.drop_constraint("fk_config_audit_user", "config_audit", type_="foreignkey")
    op.drop_index("idx_business_audit_user_ts", table_name="business_audit")
    op.drop_index("idx_business_audit_target_ts", table_name="business_audit")
    op.drop_table("business_audit")
    op.drop_index("idx_user_email", table_name="user")
    op.drop_table("user")
