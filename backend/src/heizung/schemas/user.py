"""Pydantic-Schemas fuer User-Verwaltung (Sprint 9.17, AE-50)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from heizung.models.enums import UserRole


class UserCreate(BaseModel):
    """Eingabe fuer POST /api/v1/users (admin-only)."""

    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    role: UserRole
    initial_password: str = Field(..., min_length=12, max_length=128)


class UserUpdate(BaseModel):
    """Eingabe fuer PATCH /api/v1/users/{id} (admin-only).

    ``role`` und ``is_active`` aenderbar. ``email`` bewusst nicht
    aenderbar — neue Identitaet bedeutet neuen User-Account.
    """

    model_config = ConfigDict(extra="forbid")

    role: UserRole | None = None
    is_active: bool | None = None


class UserPasswordReset(BaseModel):
    """Eingabe fuer POST /api/v1/users/{id}/reset-password (admin-only)."""

    model_config = ConfigDict(extra="forbid")

    new_password: str = Field(..., min_length=12, max_length=128)


class UserRead(BaseModel):
    """Ausgabe fuer GET /api/v1/users[/{id}] — ohne password_hash."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    role: UserRole
    is_active: bool
    must_change_password: bool
    created_at: datetime
    updated_at: datetime
    last_login_at: datetime | None
