"""Auth-API (Sprint 9.17, AE-50).

    POST  /api/v1/auth/login            Body LoginRequest -> HttpOnly-Cookie
    POST  /api/v1/auth/logout           Cookie loeschen
    GET   /api/v1/auth/me               Aktueller User
    POST  /api/v1/auth/change-password  Eigenes Passwort wechseln

Generische Fehlermeldung bei Login-Fehler (kein User-Enumeration).
Rate-Limit auf /login via slowapi (siehe ``main.py``-Limiter).
Login-Versuche werden NICHT in business_audit gelogt (Hochfrequenz);
nur Python-Logging mit Ergebnis + IP.

Owner / Audit-Hinweis: ``change-password`` schreibt einen Eintrag in
``business_audit`` mit ``action='PASSWORD_CHANGE'``.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from heizung.auth.dependencies import require_real_user
from heizung.auth.jwt import create_access_token
from heizung.auth.password import hash_password, verify_password
from heizung.auth.rate_limit import limiter
from heizung.config import get_settings
from heizung.db import get_session
from heizung.models.user import User
from heizung.schemas.auth import ChangePasswordRequest, LoginRequest, LoginResponse
from heizung.schemas.user import UserRead
from heizung.services.business_audit_service import record_business_action

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

_LOGIN_FAILED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="E-Mail oder Passwort falsch",
)


def _set_auth_cookie(response: Response, token: str) -> None:
    settings = get_settings()
    response.set_cookie(
        key=settings.auth_cookie_name,
        value=token,
        max_age=settings.access_token_expire_hours * 3600,
        httponly=True,
        secure=settings.auth_cookie_secure,
        samesite="lax",
        path="/",
    )


def _clear_auth_cookie(response: Response) -> None:
    settings = get_settings()
    response.delete_cookie(
        key=settings.auth_cookie_name,
        path="/",
        httponly=True,
        secure=settings.auth_cookie_secure,
        samesite="lax",
    )


@router.post(
    "/login",
    response_model=LoginResponse,
    summary="Login via E-Mail + Passwort (setzt HttpOnly-Cookie)",
)
@limiter.limit(get_settings().auth_login_rate_limit)
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> LoginResponse:
    client_ip = request.client.host if request.client else "unknown"
    stmt = select(User).where(User.email == payload.email.lower())
    user = (await session.execute(stmt)).scalar_one_or_none()

    if user is None or not verify_password(payload.password, user.password_hash):
        logger.info("login_failed", extra={"email": payload.email, "ip": client_ip})
        raise _LOGIN_FAILED

    if not user.is_active:
        logger.info("login_inactive", extra={"user_id": user.id, "ip": client_ip})
        raise _LOGIN_FAILED

    user.last_login_at = datetime.now(UTC)
    await session.commit()
    await session.refresh(user)

    token = create_access_token(user_id=user.id, role=user.role.value)
    _set_auth_cookie(response, token)
    logger.info("login_success", extra={"user_id": user.id, "ip": client_ip})
    return LoginResponse(user=UserRead.model_validate(user))


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Logout (loescht HttpOnly-Cookie)",
)
async def logout() -> Response:
    # Sprint 9.17b B-9.17a-1: NICHT den injizierten response-Parameter
    # mutieren und dann ein neues Response zurueckgeben — FastAPI verwirft
    # dann die delete_cookie-Header-Aenderung. Eigenes Response-Objekt
    # erzeugen, Cookie darauf loeschen, dieses zurueckgeben.
    # Siehe CLAUDE.md §5.31.
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    _clear_auth_cookie(response)
    return response


@router.get(
    "/me",
    response_model=UserRead,
    summary="Aktueller User (eingelogt)",
)
async def me(user: User = Depends(require_real_user)) -> User:  # noqa: B008
    return user


@router.post(
    "/change-password",
    response_model=UserRead,
    summary="Eigenes Passwort wechseln (eingelogt)",
)
async def change_password(
    payload: ChangePasswordRequest,
    request: Request,
    user: User = Depends(require_real_user),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> User:
    if not verify_password(payload.current_password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Aktuelles Passwort falsch",
        )
    user.password_hash = hash_password(payload.new_password)
    user.must_change_password = False
    await record_business_action(
        session,
        user_id=user.id,
        action="PASSWORD_CHANGE",
        target_type="user",
        target_id=user.id,
        old_value={"must_change_password": True},
        new_value={"must_change_password": False},
        request_ip=request.client.host if request.client else None,
    )
    await session.commit()
    await session.refresh(user)
    return user
