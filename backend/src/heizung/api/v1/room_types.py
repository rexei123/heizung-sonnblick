"""Raumtypen-Endpoints (Sprint 8.4).

CRUD:
    POST    /api/v1/room-types
    GET     /api/v1/room-types
    GET     /api/v1/room-types/{room_type_id}
    PATCH   /api/v1/room-types/{room_type_id}
    DELETE  /api/v1/room-types/{room_type_id}   — 409 wenn Raeume verknuepft
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from heizung.auth.dependencies import require_admin, require_user
from heizung.db import get_session
from heizung.models.room import Room
from heizung.models.room_type import RoomType
from heizung.models.user import User
from heizung.schemas.room_type import RoomTypeCreate, RoomTypeRead, RoomTypeUpdate

# Postgres int4-Range. IDs > 2^31-1 wuerden DataError werfen → 500.
INT4_MAX = 2_147_483_647

RoomTypeIdPath = Path(  # noqa: B008
    ...,
    gt=0,
    le=INT4_MAX,
    description="Raumtyp-ID (positive Integer, Postgres int4-Range)",
)

router = APIRouter(prefix="/room-types", tags=["room-types"])


async def _get_or_404(session: AsyncSession, room_type_id: int) -> RoomType:
    rt = await session.get(RoomType, room_type_id)
    if rt is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Raumtyp {room_type_id} nicht gefunden",
        )
    return rt


@router.post(
    "",
    response_model=RoomTypeRead,
    status_code=status.HTTP_201_CREATED,
    summary="Raumtyp anlegen",
)
async def create_room_type(
    payload: RoomTypeCreate,
    _admin: User = Depends(require_admin),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> RoomType:
    rt = RoomType(**payload.model_dump())
    session.add(rt)
    try:
        await session.commit()
    except IntegrityError as e:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Raumtyp-Name '{payload.name}' existiert bereits",
        ) from e
    await session.refresh(rt)
    return rt


@router.get(
    "",
    response_model=list[RoomTypeRead],
    summary="Raumtypen-Liste",
)
async def list_room_types(
    is_bookable: bool | None = Query(default=None),  # noqa: B008
    limit: int = Query(default=100, ge=1, le=1000),  # noqa: B008
    offset: int = Query(default=0, ge=0),  # noqa: B008
    _user: User = Depends(require_user),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> list[RoomType]:
    stmt = select(RoomType)
    if is_bookable is not None:
        stmt = stmt.where(RoomType.is_bookable == is_bookable)
    stmt = stmt.order_by(RoomType.id).offset(offset).limit(limit)
    result = await session.execute(stmt)
    return list(result.scalars().all())


@router.get(
    "/{room_type_id}",
    response_model=RoomTypeRead,
    summary="Einzelnen Raumtyp",
)
async def get_room_type(
    room_type_id: int = RoomTypeIdPath,
    _user: User = Depends(require_user),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> RoomType:
    return await _get_or_404(session, room_type_id)


@router.patch(
    "/{room_type_id}",
    response_model=RoomTypeRead,
    summary="Raumtyp partiell aktualisieren",
)
async def update_room_type(
    payload: RoomTypeUpdate,
    room_type_id: int = RoomTypeIdPath,
    _admin: User = Depends(require_admin),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> RoomType:
    rt = await _get_or_404(session, room_type_id)
    updates = payload.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Mindestens ein Feld zur Aktualisierung erforderlich",
        )
    for field, value in updates.items():
        setattr(rt, field, value)
    try:
        await session.commit()
    except IntegrityError as e:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Eindeutigkeitsverletzung (Name?)",
        ) from e
    await session.refresh(rt)
    return rt


@router.delete(
    "/{room_type_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Raumtyp loeschen (nur ohne verknuepfte Raeume)",
)
async def delete_room_type(
    room_type_id: int = RoomTypeIdPath,
    _admin: User = Depends(require_admin),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> None:
    rt = await _get_or_404(session, room_type_id)

    room_count = await session.scalar(
        select(func.count()).select_from(Room).where(Room.room_type_id == room_type_id)
    )
    if room_count and room_count > 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Raumtyp ist mit {room_count} Zimmern verknuepft. "
                "Zuerst Zimmer umverknuepfen oder loeschen."
            ),
        )

    await session.delete(rt)
    await session.commit()
