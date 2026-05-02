"""Zimmer-Endpoints (Sprint 8.4).

CRUD:
    POST    /api/v1/rooms
    GET     /api/v1/rooms
    GET     /api/v1/rooms/{room_id}
    PATCH   /api/v1/rooms/{room_id}
    DELETE  /api/v1/rooms/{room_id}    — 409 wenn aktive Belegungen
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from heizung.db import get_session
from heizung.models.enums import RoomStatus
from heizung.models.occupancy import Occupancy
from heizung.models.room import Room
from heizung.models.room_type import RoomType
from heizung.schemas.room import RoomCreate, RoomRead, RoomUpdate

INT4_MAX = 2_147_483_647

RoomIdPath = Path(  # noqa: B008
    ...,
    gt=0,
    le=INT4_MAX,
    description="Zimmer-ID",
)

router = APIRouter(prefix="/rooms", tags=["rooms"])


async def _get_or_404(session: AsyncSession, room_id: int) -> Room:
    room = await session.get(Room, room_id)
    if room is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Zimmer {room_id} nicht gefunden",
        )
    return room


async def _ensure_room_type_exists(session: AsyncSession, room_type_id: int) -> None:
    rt = await session.get(RoomType, room_type_id)
    if rt is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"room_type_id={room_type_id} existiert nicht",
        )


@router.post(
    "",
    response_model=RoomRead,
    status_code=status.HTTP_201_CREATED,
    summary="Zimmer anlegen",
)
async def create_room(
    payload: RoomCreate,
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> Room:
    await _ensure_room_type_exists(session, payload.room_type_id)
    room = Room(**payload.model_dump())
    session.add(room)
    try:
        await session.commit()
    except IntegrityError as e:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Zimmer-Nummer '{payload.number}' existiert bereits",
        ) from e
    await session.refresh(room)
    return room


@router.get(
    "",
    response_model=list[RoomRead],
    summary="Zimmer-Liste",
)
async def list_rooms(
    room_type_id: int | None = Query(default=None, gt=0),  # noqa: B008
    status_filter: RoomStatus | None = Query(default=None, alias="status"),  # noqa: B008
    floor: int | None = Query(default=None),  # noqa: B008
    limit: int = Query(default=100, ge=1, le=1000),  # noqa: B008
    offset: int = Query(default=0, ge=0),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> list[Room]:
    stmt = select(Room)
    if room_type_id is not None:
        stmt = stmt.where(Room.room_type_id == room_type_id)
    if status_filter is not None:
        stmt = stmt.where(Room.status == status_filter)
    if floor is not None:
        stmt = stmt.where(Room.floor == floor)
    stmt = stmt.order_by(Room.number).offset(offset).limit(limit)
    result = await session.execute(stmt)
    return list(result.scalars().all())


@router.get(
    "/{room_id}",
    response_model=RoomRead,
    summary="Einzelnes Zimmer",
)
async def get_room(
    room_id: int = RoomIdPath,
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> Room:
    return await _get_or_404(session, room_id)


@router.patch(
    "/{room_id}",
    response_model=RoomRead,
    summary="Zimmer partiell aktualisieren",
)
async def update_room(
    payload: RoomUpdate,
    room_id: int = RoomIdPath,
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> Room:
    room = await _get_or_404(session, room_id)
    updates = payload.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Mindestens ein Feld zur Aktualisierung erforderlich",
        )
    if "room_type_id" in updates:
        await _ensure_room_type_exists(session, updates["room_type_id"])
    for field, value in updates.items():
        setattr(room, field, value)
    try:
        await session.commit()
    except IntegrityError as e:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Eindeutigkeitsverletzung (Nummer?)",
        ) from e
    await session.refresh(room)
    return room


@router.delete(
    "/{room_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Zimmer loeschen (nur ohne aktive Belegungen)",
)
async def delete_room(
    room_id: int = RoomIdPath,
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> None:
    room = await _get_or_404(session, room_id)

    active_occupancies = await session.scalar(
        select(func.count())
        .select_from(Occupancy)
        .where(Occupancy.room_id == room_id, Occupancy.is_active.is_(True))
    )
    if active_occupancies and active_occupancies > 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(f"Zimmer hat {active_occupancies} aktive Belegung(en). Zuerst stornieren."),
        )

    await session.delete(room)
    await session.commit()
