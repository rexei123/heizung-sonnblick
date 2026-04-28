"""Devices-Endpoints.

CRUD (Sprint 6.10):
    POST   /api/v1/devices
    GET    /api/v1/devices
    GET    /api/v1/devices/{device_id}
    PATCH  /api/v1/devices/{device_id}

Zeitreihen (Sprint 5.8):
    GET    /api/v1/devices/{device_id}/sensor-readings
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from heizung.db import get_session
from heizung.models.device import Device
from heizung.models.heating_zone import HeatingZone
from heizung.models.sensor_reading import SensorReading
from heizung.schemas.device import DeviceCreate, DeviceRead, DeviceUpdate
from heizung.schemas.sensor_reading import SensorReadingRead

router = APIRouter(prefix="/devices", tags=["devices"])


# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------


async def _get_or_404(session: AsyncSession, device_id: int) -> Device:
    device = await session.get(Device, device_id)
    if device is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Device {device_id} nicht gefunden",
        )
    return device


async def _ensure_zone_exists(session: AsyncSession, zone_id: int | None) -> None:
    if zone_id is None:
        return
    zone = await session.get(HeatingZone, zone_id)
    if zone is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"heating_zone_id={zone_id} existiert nicht",
        )


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


@router.post(
    "",
    response_model=DeviceRead,
    status_code=status.HTTP_201_CREATED,
    summary="Geraet anlegen",
)
async def create_device(
    payload: DeviceCreate,
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> Device:
    await _ensure_zone_exists(session, payload.heating_zone_id)

    device = Device(**payload.model_dump())
    session.add(device)
    try:
        await session.commit()
    except IntegrityError as e:
        await session.rollback()
        # UNIQUE-Verletzung auf dev_eui ist der haeufige Fall
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"DevEUI '{payload.dev_eui}' existiert bereits",
        ) from e
    await session.refresh(device)
    return device


@router.get(
    "",
    response_model=list[DeviceRead],
    summary="Geraete-Liste (paginiert)",
)
async def list_devices(
    is_active: bool | None = Query(  # noqa: B008
        default=None, description="Nur aktive (True) oder nur deaktivierte (False) Geraete."
    ),
    vendor: str | None = Query(default=None),  # noqa: B008
    limit: int = Query(default=100, ge=1, le=1000),  # noqa: B008
    offset: int = Query(default=0, ge=0),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> list[Device]:
    stmt = select(Device)
    if is_active is not None:
        stmt = stmt.where(Device.is_active == is_active)
    if vendor is not None:
        stmt = stmt.where(Device.vendor == vendor)
    stmt = stmt.order_by(Device.id).offset(offset).limit(limit)
    result = await session.execute(stmt)
    return list(result.scalars().all())


@router.get(
    "/{device_id}",
    response_model=DeviceRead,
    summary="Einzelnes Geraet",
)
async def get_device(
    device_id: int,
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> Device:
    return await _get_or_404(session, device_id)


@router.patch(
    "/{device_id}",
    response_model=DeviceRead,
    summary="Geraet partiell aktualisieren",
)
async def update_device(
    device_id: int,
    payload: DeviceUpdate,
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> Device:
    device = await _get_or_404(session, device_id)
    updates = payload.model_dump(exclude_unset=True)

    if "heating_zone_id" in updates:
        await _ensure_zone_exists(session, updates["heating_zone_id"])

    for field, value in updates.items():
        setattr(device, field, value)

    await session.commit()
    await session.refresh(device)
    return device


# ---------------------------------------------------------------------------
# Zeitreihen-Readings (Sprint 5.8)
# ---------------------------------------------------------------------------


@router.get(
    "/{device_id}/sensor-readings",
    response_model=list[SensorReadingRead],
    summary="Zeitreihen-Readings eines Geraets",
)
async def list_sensor_readings(
    device_id: int,
    from_: datetime | None = Query(  # noqa: B008
        default=None,
        alias="from",
        description="Start-Zeit (inklusive, ISO 8601). Default: keine Untergrenze.",
    ),
    to: datetime | None = Query(  # noqa: B008
        default=None,
        description="End-Zeit (exklusive, ISO 8601). Default: keine Obergrenze.",
    ),
    limit: int = Query(  # noqa: B008
        default=100, ge=1, le=1000, description="Max. Anzahl Eintraege."
    ),
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> list[SensorReading]:
    await _get_or_404(session, device_id)

    stmt = select(SensorReading).where(SensorReading.device_id == device_id)
    if from_ is not None:
        stmt = stmt.where(SensorReading.time >= from_)
    if to is not None:
        stmt = stmt.where(SensorReading.time < to)
    stmt = stmt.order_by(SensorReading.time.desc()).limit(limit)

    result = await session.execute(stmt)
    return list(result.scalars().all())
