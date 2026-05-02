"""Heizzone-Endpoints (Sprint 8.4).

Nested unter Zimmer. Eine Heizzone gehoert immer zu genau einem Zimmer.

CRUD:
    GET     /api/v1/rooms/{room_id}/heating-zones
    POST    /api/v1/rooms/{room_id}/heating-zones
    GET     /api/v1/rooms/{room_id}/heating-zones/{zone_id}
    PATCH   /api/v1/rooms/{room_id}/heating-zones/{zone_id}
    DELETE  /api/v1/rooms/{room_id}/heating-zones/{zone_id}
            -> bei zugewiesenem Geraet wird device.heating_zone_id auf NULL
               gesetzt (FK SET NULL), Geraet bleibt erhalten.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Path, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from heizung.db import get_session
from heizung.models.heating_zone import HeatingZone
from heizung.models.room import Room
from heizung.schemas.heating_zone import (
    HeatingZoneCreate,
    HeatingZoneRead,
    HeatingZoneUpdate,
)

INT4_MAX = 2_147_483_647

RoomIdPath = Path(  # noqa: B008
    ...,
    gt=0,
    le=INT4_MAX,
    description="Zimmer-ID",
)
ZoneIdPath = Path(  # noqa: B008
    ...,
    gt=0,
    le=INT4_MAX,
    description="Heizzone-ID",
)

router = APIRouter(prefix="/rooms/{room_id}/heating-zones", tags=["heating-zones"])


async def _ensure_room_exists(session: AsyncSession, room_id: int) -> None:
    room = await session.get(Room, room_id)
    if room is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Zimmer {room_id} nicht gefunden",
        )


async def _get_zone_or_404(session: AsyncSession, room_id: int, zone_id: int) -> HeatingZone:
    zone = await session.get(HeatingZone, zone_id)
    if zone is None or zone.room_id != room_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Heizzone {zone_id} in Zimmer {room_id} nicht gefunden",
        )
    return zone


@router.get(
    "",
    response_model=list[HeatingZoneRead],
    summary="Heizzonen eines Zimmers",
)
async def list_heating_zones(
    room_id: int = RoomIdPath,
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> list[HeatingZone]:
    await _ensure_room_exists(session, room_id)
    stmt = select(HeatingZone).where(HeatingZone.room_id == room_id).order_by(HeatingZone.id)
    result = await session.execute(stmt)
    return list(result.scalars().all())


@router.post(
    "",
    response_model=HeatingZoneRead,
    status_code=status.HTTP_201_CREATED,
    summary="Heizzone anlegen",
)
async def create_heating_zone(
    payload: HeatingZoneCreate,
    room_id: int = RoomIdPath,
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> HeatingZone:
    await _ensure_room_exists(session, room_id)
    zone = HeatingZone(room_id=room_id, **payload.model_dump())
    session.add(zone)
    try:
        await session.commit()
    except IntegrityError as e:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Heizzone-Name '{payload.name}' existiert bereits in diesem Zimmer",
        ) from e
    await session.refresh(zone)
    return zone


@router.get(
    "/{zone_id}",
    response_model=HeatingZoneRead,
    summary="Einzelne Heizzone",
)
async def get_heating_zone(
    room_id: int = RoomIdPath,
    zone_id: int = ZoneIdPath,
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> HeatingZone:
    return await _get_zone_or_404(session, room_id, zone_id)


@router.patch(
    "/{zone_id}",
    response_model=HeatingZoneRead,
    summary="Heizzone partiell aktualisieren",
)
async def update_heating_zone(
    payload: HeatingZoneUpdate,
    room_id: int = RoomIdPath,
    zone_id: int = ZoneIdPath,
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> HeatingZone:
    zone = await _get_zone_or_404(session, room_id, zone_id)
    updates = payload.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Mindestens ein Feld zur Aktualisierung erforderlich",
        )
    for field, value in updates.items():
        setattr(zone, field, value)
    try:
        await session.commit()
    except IntegrityError as e:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Eindeutigkeitsverletzung (Name?)",
        ) from e
    await session.refresh(zone)
    return zone


@router.delete(
    "/{zone_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Heizzone loeschen (Geraete bleiben mit zone=NULL)",
)
async def delete_heating_zone(
    room_id: int = RoomIdPath,
    zone_id: int = ZoneIdPath,
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> None:
    zone = await _get_zone_or_404(session, room_id, zone_id)
    # Geraete bleiben — FK ist ON DELETE SET NULL.
    await session.delete(zone)
    await session.commit()
