"""Manual-Override-API (Sprint 9.9 T4; Sprint 9.17 auth-secured).

REST-Schicht ueber ``override_service``. Bewusst zwei Pfade:

- ``GET/POST  /api/v1/rooms/{room_id}/overrides``  (raumbezogen, Listen + Anlage)
- ``DELETE    /api/v1/overrides/{override_id}``    (id-basiert, Revoke)

Auth (Sprint 9.17, AE-50 / AE-8): ``require_mitarbeiter``.
``X-User-Email``-Header aus 9.9-Vorbereitung ist entfernt — der
authentifizierte User-Account ist die Quelle der Wahrheit. ``created_by``
in ``manual_override`` wird mit ``user.email`` gefuellt; ``business_audit``
trackt die operative Aktion separat.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from heizung.auth.dependencies import require_mitarbeiter
from heizung.db import get_session
from heizung.models.enums import OverrideSource
from heizung.models.global_config import GlobalConfig
from heizung.models.manual_override import ManualOverride
from heizung.models.room import Room
from heizung.models.user import User
from heizung.schemas.manual_override import (
    ManualOverrideCreate,
    ManualOverrideResponse,
    ManualOverrideRevoke,
)
from heizung.services import override_service
from heizung.services.business_audit_service import record_business_action
from heizung.services.occupancy_service import next_active_checkout
from heizung.tasks.engine_tasks import evaluate_room as _evaluate_room_task

INT4_MAX = 2_147_483_647

OverrideIdPath = Path(  # noqa: B008
    ...,
    gt=0,
    le=INT4_MAX,
    description="Manual-Override-ID",
)
RoomIdPath = Path(  # noqa: B008
    ...,
    gt=0,
    le=INT4_MAX,
    description="Raum-ID",
)

router = APIRouter(tags=["overrides"])


async def _ensure_room_exists(session: AsyncSession, room_id: int) -> None:
    room = await session.get(Room, room_id)
    if room is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"room_id={room_id} existiert nicht",
        )


@router.get(
    "/rooms/{room_id}/overrides",
    response_model=list[ManualOverrideResponse],
    summary="Override-Historie eines Raums",
)
async def list_room_overrides(
    room_id: int = RoomIdPath,
    limit: int = Query(default=50, ge=1, le=200),  # noqa: B008
    include_expired: bool = Query(default=True),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> list[ManualOverride]:
    await _ensure_room_exists(session, room_id)
    return await override_service.get_history(
        session,
        room_id,
        limit=limit,
        include_expired=include_expired,
    )


@router.post(
    "/rooms/{room_id}/overrides",
    response_model=ManualOverrideResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Manuellen Override anlegen",
)
async def create_room_override(
    payload: ManualOverrideCreate,
    request: Request,
    room_id: int = RoomIdPath,
    user: User = Depends(require_mitarbeiter),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> ManualOverride:
    await _ensure_room_exists(session, room_id)

    # Sprint 9.9a Hotfix A2: Engine quantisiert auf ganze Grad (rules.engine._quantize),
    # daher API-seitig nur ganze Werte akzeptieren - sonst sieht der User
    # 22.5 in der DB, aber 23 im Engine-Trace.
    if payload.setpoint != payload.setpoint.quantize(Decimal("1"), rounding=ROUND_HALF_UP):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Setpoint muss in ganzen °C-Schritten angegeben werden.",
        )

    source = OverrideSource(payload.source)

    next_checkout: datetime | None = None
    if source == OverrideSource.FRONTEND_CHECKOUT:
        next_checkout = await next_active_checkout(session, room_id)
        if next_checkout is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail='„Bis Check-Out" funktioniert nur bei einem belegten Zimmer.',
            )

    hotel_config = await session.get(GlobalConfig, 1)
    now = datetime.now(tz=UTC)
    expires_at = override_service.compute_expires_at(
        source,
        now,
        next_checkout_at=next_checkout,
        hotel_config=hotel_config,
    )

    try:
        override = await override_service.create(
            session,
            room_id=room_id,
            setpoint=payload.setpoint,
            source=source,
            expires_at=expires_at,
            reason=payload.reason,
            created_by=user.email,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e),
        ) from e

    await record_business_action(
        session,
        user_id=user.id,
        action="MANUAL_OVERRIDE_SET",
        target_type="room",
        target_id=room_id,
        old_value=None,
        new_value={
            "override_id": override.id,
            "setpoint": payload.setpoint,
            "source": source.value,
            "expires_at": expires_at,
        },
        request_ip=request.client.host if request.client else None,
    )
    await session.commit()
    await session.refresh(override)
    # Sprint 9.9a Hotfix A1: Engine-Re-Eval anstossen, damit Layer 3 sofort
    # greift (analog zu occupancies.py - AE-07).
    _evaluate_room_task.delay(room_id)
    return override


@router.delete(
    "/overrides/{override_id}",
    response_model=ManualOverrideResponse,
    summary="Override revoken (kein Hard-Delete)",
)
async def revoke_override(
    request: Request,
    payload: ManualOverrideRevoke | None = None,
    override_id: int = OverrideIdPath,
    user: User = Depends(require_mitarbeiter),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> ManualOverride:
    existing = await session.get(ManualOverride, override_id)
    if existing is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"override_id={override_id} existiert nicht",
        )

    revoked_reason = payload.revoked_reason if payload else None

    try:
        override = await override_service.revoke(
            session,
            override_id,
            reason=revoked_reason,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e),
        ) from e

    await record_business_action(
        session,
        user_id=user.id,
        action="MANUAL_OVERRIDE_CLEAR",
        target_type="room",
        target_id=override.room_id,
        old_value={"override_id": override.id, "is_active": True},
        new_value={"override_id": override.id, "revoked_reason": revoked_reason},
        request_ip=request.client.host if request.client else None,
    )
    await session.commit()
    await session.refresh(override)
    # Sprint 9.9a Hotfix A1: Engine-Re-Eval nach Revoke - Setpoint faellt
    # auf den regulaeren Layer-1/2-Wert zurueck.
    _evaluate_room_task.delay(override.room_id)
    return override
