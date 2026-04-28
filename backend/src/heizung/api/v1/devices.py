"""Devices-Endpoints (Sprint 5.8).

GET /api/v1/devices/{device_id}/sensor-readings
    Paginierte Zeitreihen-Readings, Default-Sort time DESC, max 1000 Eintraege.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from heizung.db import get_session
from heizung.models.device import Device
from heizung.models.sensor_reading import SensorReading
from heizung.schemas.sensor_reading import SensorReadingRead

router = APIRouter(prefix="/devices", tags=["devices"])


@router.get(
    "/{device_id}/sensor-readings",
    response_model=list[SensorReadingRead],
    summary="Zeitreihen-Readings eines Geraets",
)
async def list_sensor_readings(
    device_id: int,
    from_: datetime | None = Query(  # noqa: B008  (FastAPI-Idiom: Query in default)
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
    session: AsyncSession = Depends(get_session),  # noqa: B008  (FastAPI-Idiom: Depends in default)
) -> list[SensorReading]:
    # Device-Existenz pruefen, damit 404 statt leerem Array fuer falsche IDs.
    device = await session.get(Device, device_id)
    if device is None:
        raise HTTPException(status_code=404, detail=f"Device {device_id} nicht gefunden")

    stmt = select(SensorReading).where(SensorReading.device_id == device_id)
    if from_ is not None:
        stmt = stmt.where(SensorReading.time >= from_)
    if to is not None:
        stmt = stmt.where(SensorReading.time < to)
    stmt = stmt.order_by(SensorReading.time.desc()).limit(limit)

    result = await session.execute(stmt)
    return list(result.scalars().all())
