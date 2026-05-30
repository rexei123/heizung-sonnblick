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

from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Path, Request, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from heizung.auth.dependencies import require_admin, require_user
from heizung.db import get_session
from heizung.models.heating_zone import HeatingZone
from heizung.models.room import Room
from heizung.models.user import User
from heizung.schemas.heating_zone import (
    HeatingZoneCreate,
    HeatingZoneRead,
    HeatingZoneUpdate,
    ZoneActiveOverrideRead,
)
from heizung.services import override_service
from heizung.services.business_audit_service import record_business_action
from heizung.services.event_log import latest_hard_clamp_setpoint_per_room
from heizung.services.zone_aggregates import latest_mean_temp_per_zone


async def _build_zone_read(
    session: AsyncSession,
    zone: HeatingZone,
    *,
    mean_temps: dict[int, Decimal | None] | None = None,
    engine_setpoints: dict[int, Decimal | None] | None = None,
) -> HeatingZoneRead:
    """Sprint 14d FU-5 + 14e FU-1/FU-2: HeatingZoneRead + Anreicherungen.

    Override (Sprint 14d FU-5): per-Zone-Lookup via
    ``override_service.get_active`` (Zone-Match + Room-Scope-Fallback).

    Mean Temp (Sprint 14e FU-1) und Engine-Setpoint (FU-2) sind als optionale
    Pre-Fetch-Dicts uebergebbar — der List-Endpoint befuellt sie via Batch-
    Helpers (R-D, ein Query pro Aggregat). Der Single-Get-Endpoint laesst sie
    leer und die per-Zone-Calls in dieser Funktion erledigen das (kein N+1,
    Detail = ein Zimmer = wenige Zonen).
    """
    read = HeatingZoneRead.model_validate(zone)
    update: dict[str, Any] = {}

    active = await override_service.get_active(session, zone.room_id, heating_zone_id=zone.id)
    if active is not None:
        update["active_override"] = ZoneActiveOverrideRead(
            source=active.source,
            setpoint_celsius=active.setpoint,
            started_at=active.created_at,
            expires_at=active.expires_at,
        )

    if mean_temps is None:
        mean_temps = await latest_mean_temp_per_zone(session, [zone.id])
    update["mean_temperature_c"] = mean_temps.get(zone.id)

    if engine_setpoints is None:
        engine_setpoints = await latest_hard_clamp_setpoint_per_room(session, [zone.room_id])
    update["engine_setpoint_c"] = engine_setpoints.get(zone.room_id)

    return read.model_copy(update=update)


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
    _user: User = Depends(require_user),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> list[HeatingZoneRead]:
    await _ensure_room_exists(session, room_id)
    stmt = select(HeatingZone).where(HeatingZone.room_id == room_id).order_by(HeatingZone.id)
    zones = list((await session.execute(stmt)).scalars().all())
    if not zones:
        return []
    # Sprint 14e FU-1/FU-2 (R-D): Aggregat-Batches einmal pro Liste, nicht
    # pro Zone. ``engine_setpoint`` ist per Room und damit fuer alle Zonen
    # desselben Zimmers identisch (AE-51 §4.2).
    mean_temps = await latest_mean_temp_per_zone(session, [z.id for z in zones])
    engine_setpoints = await latest_hard_clamp_setpoint_per_room(session, [room_id])
    return [
        await _build_zone_read(
            session, zone, mean_temps=mean_temps, engine_setpoints=engine_setpoints
        )
        for zone in zones
    ]


@router.post(
    "",
    response_model=HeatingZoneRead,
    status_code=status.HTTP_201_CREATED,
    summary="Heizzone anlegen",
)
async def create_heating_zone(
    payload: HeatingZoneCreate,
    room_id: int = RoomIdPath,
    _admin: User = Depends(require_admin),  # noqa: B008
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
    _user: User = Depends(require_user),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> HeatingZoneRead:
    zone = await _get_zone_or_404(session, room_id, zone_id)
    return await _build_zone_read(session, zone)


@router.patch(
    "/{zone_id}",
    response_model=HeatingZoneRead,
    summary="Heizzone partiell aktualisieren",
)
async def update_heating_zone(
    request: Request,
    payload: HeatingZoneUpdate,
    room_id: int = RoomIdPath,
    zone_id: int = ZoneIdPath,
    user: User = Depends(require_admin),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> HeatingZoneRead:
    zone = await _get_zone_or_404(session, room_id, zone_id)
    updates = payload.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Mindestens ein Feld zur Aktualisierung erforderlich",
        )
    # Sprint 14e T4 (R4): Audit nur fuer ``name`` — die anderen PATCH-Felder
    # (kind, is_towel_warmer) sind bewusste 14e-Scope-Eingrenzung.
    old_name = zone.name
    name_changed = "name" in updates and updates["name"] != old_name
    for field, value in updates.items():
        setattr(zone, field, value)
    if name_changed:
        await record_business_action(
            session,
            user_id=user.id,
            action="HEATING_ZONE_NAME_CHANGED",
            target_type="heating_zone",
            target_id=zone_id,
            old_value={"name": old_name},
            new_value={"name": updates["name"]},
            request_ip=request.client.host if request.client else None,
        )
    try:
        await session.commit()
    except IntegrityError as e:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Eindeutigkeitsverletzung (Name?)",
        ) from e
    await session.refresh(zone)
    return await _build_zone_read(session, zone)


@router.delete(
    "/{zone_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Heizzone loeschen (Geraete bleiben mit zone=NULL)",
)
async def delete_heating_zone(
    room_id: int = RoomIdPath,
    zone_id: int = ZoneIdPath,
    _admin: User = Depends(require_admin),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> None:
    zone = await _get_zone_or_404(session, room_id, zone_id)
    # Geraete bleiben — FK ist ON DELETE SET NULL.
    await session.delete(zone)
    await session.commit()
