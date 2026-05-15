"""Belegungs-Endpoints (Sprint 8.5).

CRUD:
    POST    /api/v1/occupancies
    GET     /api/v1/occupancies?from=&to=&room_id=&active=true
    GET     /api/v1/occupancies/{occupancy_id}
    PATCH   /api/v1/occupancies/{occupancy_id}    -> nur Storno (cancel=true)
    DELETE  /api/v1/occupancies/{occupancy_id}    -> 405 (Storno via PATCH)

Storno-Pattern: setzt ``is_active=False``, ``cancelled_at=NOW``. Daten bleiben
fuer Audit-/PMS-Sync-Reproduzierbarkeit.

room.status wird automatisch synchronisiert (occupancy_service).
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from heizung.auth.dependencies import require_mitarbeiter, require_user
from heizung.db import get_session
from heizung.models.occupancy import Occupancy
from heizung.models.room import Room
from heizung.models.user import User
from heizung.schemas.occupancy import OccupancyCancel, OccupancyCreate, OccupancyRead
from heizung.services.business_audit_service import record_business_action
from heizung.services.occupancy_service import has_overlap, sync_room_status
from heizung.tasks.engine_tasks import evaluate_room as _evaluate_room_task

INT4_MAX = 2_147_483_647

OccupancyIdPath = Path(  # noqa: B008
    ...,
    gt=0,
    le=INT4_MAX,
    description="Belegungs-ID",
)

router = APIRouter(prefix="/occupancies", tags=["occupancies"])


async def _get_or_404(session: AsyncSession, occupancy_id: int) -> Occupancy:
    occ = await session.get(Occupancy, occupancy_id)
    if occ is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Belegung {occupancy_id} nicht gefunden",
        )
    return occ


async def _ensure_room_exists(session: AsyncSession, room_id: int) -> None:
    room = await session.get(Room, room_id)
    if room is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"room_id={room_id} existiert nicht",
        )


@router.post(
    "",
    response_model=OccupancyRead,
    status_code=status.HTTP_201_CREATED,
    summary="Belegung anlegen",
)
async def create_occupancy(
    payload: OccupancyCreate,
    request: Request,
    user: User = Depends(require_mitarbeiter),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> Occupancy:
    await _ensure_room_exists(session, payload.room_id)

    if await has_overlap(session, payload.room_id, payload.check_in, payload.check_out):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Zimmer {payload.room_id} hat bereits eine aktive Belegung "
                f"im Zeitraum {payload.check_in.isoformat()} - {payload.check_out.isoformat()}"
            ),
        )

    occ = Occupancy(**payload.model_dump())
    session.add(occ)
    await session.flush()  # ID generieren
    await sync_room_status(session, payload.room_id)
    await record_business_action(
        session,
        user_id=user.id,
        action="OCCUPANCY_CREATE",
        target_type="room",
        target_id=payload.room_id,
        old_value=None,
        new_value={
            "occupancy_id": occ.id,
            "check_in": payload.check_in,
            "check_out": payload.check_out,
        },
        request_ip=request.client.host if request.client else None,
    )
    await session.commit()
    await session.refresh(occ)
    # Sprint 9.4 Trigger: Engine-Re-Eval anstossen, sobald Belegung feststeht.
    _evaluate_room_task.delay(payload.room_id)
    return occ


@router.get(
    "",
    response_model=list[OccupancyRead],
    summary="Belegungs-Liste mit Filtern",
)
async def list_occupancies(
    from_: datetime | None = Query(  # noqa: B008
        default=None,
        alias="from",
        description="Untergrenze auf check_out — Belegungen, die nach diesem Zeitpunkt enden.",
    ),
    to: datetime | None = Query(  # noqa: B008
        default=None,
        description="Obergrenze auf check_in — Belegungen, die vor diesem Zeitpunkt beginnen.",
    ),
    room_id: int | None = Query(default=None, gt=0),  # noqa: B008
    active: bool | None = Query(  # noqa: B008
        default=None, description="Nur aktive (true) oder nur stornierte (false) Belegungen."
    ),
    limit: int = Query(default=100, ge=1, le=1000),  # noqa: B008
    offset: int = Query(default=0, ge=0),  # noqa: B008
    _user: User = Depends(require_user),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> list[Occupancy]:
    stmt = select(Occupancy)
    if from_ is not None:
        stmt = stmt.where(Occupancy.check_out >= from_)
    if to is not None:
        stmt = stmt.where(Occupancy.check_in <= to)
    if room_id is not None:
        stmt = stmt.where(Occupancy.room_id == room_id)
    if active is not None:
        stmt = stmt.where(Occupancy.is_active.is_(active))
    stmt = stmt.order_by(Occupancy.check_in).offset(offset).limit(limit)
    result = await session.execute(stmt)
    return list(result.scalars().all())


@router.get(
    "/{occupancy_id}",
    response_model=OccupancyRead,
    summary="Einzelne Belegung",
)
async def get_occupancy(
    occupancy_id: int = OccupancyIdPath,
    _user: User = Depends(require_user),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> Occupancy:
    return await _get_or_404(session, occupancy_id)


@router.patch(
    "/{occupancy_id}",
    response_model=OccupancyRead,
    summary="Belegung stornieren (cancel=true)",
)
async def cancel_occupancy(
    payload: OccupancyCancel,
    request: Request,
    occupancy_id: int = OccupancyIdPath,
    user: User = Depends(require_mitarbeiter),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> Occupancy:
    if not payload.cancel:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="cancel muss true sein. Daten-Aenderungen sind in Sprint 8 nicht erlaubt.",
        )

    occ = await _get_or_404(session, occupancy_id)
    if not occ.is_active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Belegung {occupancy_id} ist bereits storniert",
        )

    occ.is_active = False
    occ.cancelled_at = datetime.now(tz=UTC)
    await sync_room_status(session, occ.room_id)
    await record_business_action(
        session,
        user_id=user.id,
        action="OCCUPANCY_CANCEL",
        target_type="room",
        target_id=occ.room_id,
        old_value={"occupancy_id": occ.id, "is_active": True},
        new_value={
            "occupancy_id": occ.id,
            "is_active": False,
            "cancelled_at": occ.cancelled_at,
        },
        request_ip=request.client.host if request.client else None,
    )
    await session.commit()
    await session.refresh(occ)
    # Sprint 9.4 Trigger: bei Storno auch re-evaluieren (Setpoint geht zurueck).
    _evaluate_room_task.delay(occ.room_id)
    return occ


@router.delete(
    "/{occupancy_id}",
    status_code=status.HTTP_405_METHOD_NOT_ALLOWED,
    summary="DELETE nicht erlaubt — Storno via PATCH",
)
async def delete_occupancy(
    occupancy_id: int = OccupancyIdPath,
    _user: User = Depends(require_mitarbeiter),  # noqa: B008
) -> None:
    raise HTTPException(
        status_code=status.HTTP_405_METHOD_NOT_ALLOWED,
        detail=(
            "Belegungen werden nicht geloescht. Bitte via PATCH stornieren "
            "(Audit-/PMS-Sync-Reproduzierbarkeit)."
        ),
    )
