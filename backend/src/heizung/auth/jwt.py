"""JWT-Signing / Decoding (Sprint 9.17, AE-50).

HS256 mit ``settings.jwt_secret_key`` (Fallback auf ``settings.secret_key``).
Token-Lifetime: ``settings.access_token_expire_hours`` (Default 12h).

Token-Payload:
  - ``sub``  User-ID als String
  - ``role`` ``UserRole``-Value (``admin``/``mitarbeiter``)
  - ``exp``  Unix-Timestamp (auto durch ``jose.jwt``)
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from jose import JWTError, jwt

from heizung.config import get_settings


def _get_secret() -> str:
    settings = get_settings()
    return settings.jwt_secret_key or settings.secret_key


def create_access_token(*, user_id: int, role: str) -> str:
    """Erzeugt JWT mit ``sub``, ``role``, ``exp``."""
    settings = get_settings()
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "role": role,
        "exp": now + timedelta(hours=settings.access_token_expire_hours),
        "iat": now,
    }
    token: str = jwt.encode(payload, _get_secret(), algorithm=settings.jwt_algorithm)
    return token


def decode_access_token(token: str) -> dict[str, Any] | None:
    """Validiert + dekodiert JWT. ``None`` bei Manipulation oder Ablauf."""
    settings = get_settings()
    try:
        payload: dict[str, Any] = jwt.decode(
            token, _get_secret(), algorithms=[settings.jwt_algorithm]
        )
        return payload
    except JWTError:
        return None
