"""FastAPI-Dependencies fuer Auth (Sprint 9.17, AE-50).

- ``get_current_user``      laedt den eingeloggten User aus dem
                            HttpOnly-Cookie und der DB.
- ``require_admin``         403 fuer Mitarbeiter / Anonyme.
- ``require_mitarbeiter``   akzeptiert ``admin`` UND ``mitarbeiter``.

Feature-Flag ``AUTH_ENABLED`` (AE-6): bei ``false`` werden alle
Dependencies auf den System-User (id=1) abgebildet — vorausgesetzt
der Bootstrap-Admin existiert. Andernfalls 503 (System-Setup
unvollstaendig).
"""

from __future__ import annotations

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from heizung.auth.jwt import decode_access_token
from heizung.config import get_settings
from heizung.db import get_session
from heizung.models.enums import UserRole
from heizung.models.user import User

_UNAUTHORIZED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Authentifizierung erforderlich",
)
_FORBIDDEN = HTTPException(
    status_code=status.HTTP_403_FORBIDDEN,
    detail="Keine Berechtigung fuer diese Aktion",
)


async def _load_user(session: AsyncSession, user_id: int) -> User | None:
    stmt = select(User).where(User.id == user_id).where(User.is_active.is_(True))
    return (await session.execute(stmt)).scalar_one_or_none()


async def _system_user(session: AsyncSession) -> User:
    """Fallback fuer ``AUTH_ENABLED=false``: erster aktiver Admin
    (vermutlich Bootstrap-Admin id=1). Wenn keiner: 503 — System-Setup
    unvollstaendig.
    """
    stmt = (
        select(User)
        .where(User.role == UserRole.ADMIN)
        .where(User.is_active.is_(True))
        .order_by(User.id)
        .limit(1)
    )
    user = (await session.execute(stmt)).scalar_one_or_none()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "AUTH_ENABLED=false und kein Bootstrap-Admin gefunden. "
                "INITIAL_ADMIN_EMAIL + INITIAL_ADMIN_PASSWORD_HASH setzen "
                "und alembic upgrade head ausfuehren."
            ),
        )
    return user


async def get_current_user(
    request: Request,
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> User:
    """Liefert den eingeloggten User. Pflicht-Dependency fuer alle
    geschuetzten Endpoints.

    Bei ``AUTH_ENABLED=false``: System-User-Fallback (kein Cookie-Check).
    Bei ``AUTH_ENABLED=true``: Cookie ``auth_cookie_name`` decodieren,
    User aus DB laden. Bei Fehler 401.
    """
    settings = get_settings()
    if not settings.auth_enabled:
        return await _system_user(session)

    token = request.cookies.get(settings.auth_cookie_name)
    if not token:
        raise _UNAUTHORIZED

    payload = decode_access_token(token)
    if payload is None:
        raise _UNAUTHORIZED

    sub = payload.get("sub")
    if sub is None:
        raise _UNAUTHORIZED

    try:
        user_id = int(sub)
    except (TypeError, ValueError):
        raise _UNAUTHORIZED from None

    user = await _load_user(session, user_id)
    if user is None:
        raise _UNAUTHORIZED
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:  # noqa: B008
    if user.role != UserRole.ADMIN:
        raise _FORBIDDEN
    return user


def require_mitarbeiter(user: User = Depends(get_current_user)) -> User:  # noqa: B008
    """Admin oder Mitarbeiter — beide duerfen Belegungen + Overrides."""
    if user.role not in {UserRole.ADMIN, UserRole.MITARBEITER}:
        raise _FORBIDDEN
    return user
