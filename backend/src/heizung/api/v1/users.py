"""User-Verwaltung-API (Sprint 9.17, AE-50). Admin-only.

    GET    /api/v1/users
    POST   /api/v1/users
    PATCH  /api/v1/users/{id}
    POST   /api/v1/users/{id}/reset-password
    DELETE /api/v1/users/{id}

Bricked-System-Schutz:
- Admin kann eigene Rolle nicht auf ``mitarbeiter`` aendern.
- Letzter aktiver Admin kann sich nicht selbst deaktivieren / sein
  Admin-Recht entziehen.
- Letzter aktiver Admin kann nicht geloescht werden.

Audit:
- CREATE / PATCH / DELETE schreiben ``config_audit`` (table='user',
  source='api') mit dem aktuellen User-Id als handelnde Person.
- ``reset-password`` schreibt ``business_audit`` mit
  ``action='PASSWORD_RESET_BY_ADMIN'``.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Path, Request, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from heizung.auth.dependencies import require_admin
from heizung.auth.password import hash_password
from heizung.db import get_session
from heizung.models.enums import UserRole
from heizung.models.user import User
from heizung.schemas.user import UserCreate, UserPasswordReset, UserRead, UserUpdate
from heizung.services.business_audit_service import record_business_action
from heizung.services.config_audit_service import record_config_change

router = APIRouter(prefix="/users", tags=["users"])

UserIdPath = Path(..., gt=0, description="User-ID")  # noqa: B008


async def _count_active_admins(session: AsyncSession, exclude_user_id: int | None = None) -> int:
    stmt = (
        select(func.count())
        .select_from(User)
        .where(User.role == UserRole.ADMIN)
        .where(User.is_active.is_(True))
    )
    if exclude_user_id is not None:
        stmt = stmt.where(User.id != exclude_user_id)
    return int((await session.execute(stmt)).scalar_one())


async def _get_or_404(session: AsyncSession, user_id: int) -> User:
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User {user_id} nicht gefunden",
        )
    return user


@router.get(
    "",
    response_model=list[UserRead],
    summary="Liste aller User (admin-only)",
)
async def list_users(
    _admin: User = Depends(require_admin),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> list[User]:
    stmt = select(User).order_by(User.id)
    return list((await session.execute(stmt)).scalars().all())


@router.post(
    "",
    response_model=UserRead,
    status_code=status.HTTP_201_CREATED,
    summary="User anlegen (admin-only)",
)
async def create_user(
    payload: UserCreate,
    request: Request,
    admin: User = Depends(require_admin),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> User:
    user = User(
        email=payload.email.lower(),
        password_hash=hash_password(payload.initial_password),
        role=payload.role,
        is_active=True,
        must_change_password=True,
    )
    session.add(user)
    try:
        await session.flush()
    except IntegrityError as e:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"E-Mail '{payload.email}' existiert bereits",
        ) from e

    await record_config_change(
        session,
        source="api",
        table_name="user",
        scope_qualifier=f"user:{user.id}",
        column_name="created",
        old_value=None,
        new_value={"email": user.email, "role": user.role.value},
        user_id=admin.id,
        request_ip=request.client.host if request.client else None,
    )
    await session.commit()
    await session.refresh(user)
    return user


@router.patch(
    "/{user_id}",
    response_model=UserRead,
    summary="User-Rolle oder Aktiv-Status aendern (admin-only)",
)
async def update_user(
    payload: UserUpdate,
    request: Request,
    user_id: int = UserIdPath,
    admin: User = Depends(require_admin),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> User:
    user = await _get_or_404(session, user_id)
    updates = payload.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Mindestens ein Feld zur Aktualisierung erforderlich",
        )

    # Bricked-System-Schutz: Admin darf eigene Rolle nicht aendern.
    if admin.id == user.id and "role" in updates and updates["role"] != UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Admin darf eigene Rolle nicht auf 'mitarbeiter' aendern.",
        )

    # Letzter aktiver Admin: weder Rolle-Wechsel weg von admin noch
    # Deaktivierung erlaubt.
    if user.role == UserRole.ADMIN and user.is_active:
        will_lose_admin = ("role" in updates and updates["role"] != UserRole.ADMIN) or (
            "is_active" in updates and updates["is_active"] is False
        )
        if will_lose_admin:
            active_admins = await _count_active_admins(session, exclude_user_id=user.id)
            if active_admins == 0:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        "Letzter aktiver Admin kann sich nicht selbst entziehen / deaktivieren."
                    ),
                )

    old_snapshot = {
        "role": user.role.value,
        "is_active": user.is_active,
    }
    for field, value in updates.items():
        setattr(user, field, value)
    await session.flush()

    await record_config_change(
        session,
        source="api",
        table_name="user",
        scope_qualifier=f"user:{user.id}",
        column_name="updated",
        old_value=old_snapshot,
        new_value={"role": user.role.value, "is_active": user.is_active},
        user_id=admin.id,
        request_ip=request.client.host if request.client else None,
    )
    await session.commit()
    await session.refresh(user)
    return user


@router.post(
    "/{user_id}/reset-password",
    response_model=UserRead,
    summary="User-Passwort durch Admin zuruecksetzen",
)
async def reset_user_password(
    payload: UserPasswordReset,
    request: Request,
    user_id: int = UserIdPath,
    admin: User = Depends(require_admin),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> User:
    user = await _get_or_404(session, user_id)
    user.password_hash = hash_password(payload.new_password)
    user.must_change_password = True
    await record_business_action(
        session,
        user_id=admin.id,
        action="PASSWORD_RESET_BY_ADMIN",
        target_type="user",
        target_id=user.id,
        old_value={"must_change_password": False},
        new_value={"must_change_password": True},
        request_ip=request.client.host if request.client else None,
    )
    await session.commit()
    await session.refresh(user)
    return user


@router.delete(
    "/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="User loeschen (admin-only)",
)
async def delete_user(
    request: Request,
    user_id: int = UserIdPath,
    admin: User = Depends(require_admin),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> None:
    user = await _get_or_404(session, user_id)
    if user.role == UserRole.ADMIN and user.is_active:
        active_admins = await _count_active_admins(session, exclude_user_id=user.id)
        if active_admins == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Letzter aktiver Admin kann nicht geloescht werden.",
            )

    snapshot = {"email": user.email, "role": user.role.value}
    await session.delete(user)
    await record_config_change(
        session,
        source="api",
        table_name="user",
        scope_qualifier=f"user:{user_id}",
        column_name="deleted",
        old_value=snapshot,
        new_value={"deleted": True},
        user_id=admin.id,
        request_ip=request.client.host if request.client else None,
    )
    await session.commit()
