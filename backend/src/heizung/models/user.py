"""User-Tabelle fuer FastAPI-native Authentifizierung (Sprint 9.17, AE-50).

Zwei Rollen via ``UserRole``-Enum (``admin``, ``mitarbeiter``).
Passwoerter werden als bcrypt-Hash persistiert; Klartext nie in DB,
Logs oder Audit-Trail. ``must_change_password=True`` zwingt den User
beim naechsten Login zum Wechsel — gesetzt nach Bootstrap-Admin-
Anlage und Admin-Reset.

Postgres-Reserved-Word ``user`` wird in SQLAlchemy implizit gequotet;
in handgeschriebenem SQL (Migrations, raw queries) IMMER ``"user"``
verwenden.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Index, String, func
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column

from heizung.db import Base
from heizung.models.enums import UserRole, _enum_values


class User(Base):
    __tablename__ = "user"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(
        SQLEnum(
            UserRole,
            name="user_role",
            native_enum=False,
            length=32,
            values_callable=_enum_values,
        ),
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    must_change_password: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (Index("idx_user_email", "email"),)
