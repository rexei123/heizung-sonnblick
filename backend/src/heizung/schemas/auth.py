"""Pydantic-Schemas fuer Auth-Endpoints (Sprint 9.17, AE-50)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from heizung.schemas.user import UserRead


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    password: str = Field(..., min_length=1, max_length=128)


class LoginResponse(BaseModel):
    """Antwort auf /auth/login. JWT landet als HttpOnly-Cookie,
    nicht im Body. Body traegt User-Daten + must_change_password-
    Flag fuer das Frontend-Routing nach Login."""

    user: UserRead


class ChangePasswordRequest(BaseModel):
    """Eigenes Passwort wechseln (eingeloggter User)."""

    model_config = ConfigDict(extra="forbid")

    current_password: str = Field(..., min_length=1, max_length=128)
    new_password: str = Field(..., min_length=12, max_length=128)
