"""Devices-Endpoints.

CRUD (Sprint 6.10):
    POST   /api/v1/devices
    GET    /api/v1/devices
    GET    /api/v1/devices/{device_id}
    PATCH  /api/v1/devices/{device_id}

Zeitreihen (Sprint 5.8):
    GET    /api/v1/devices/{device_id}/sensor-readings

Geraete-Zone-Zuordnung (Sprint 9.11a):
    PUT    /api/v1/devices/{device_id}/heating-zone
    DELETE /api/v1/devices/{device_id}/heating-zone
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from heizung.db import get_session
from heizung.models.device import Device
from heizung.models.heating_zone import HeatingZone
from heizung.models.sensor_reading import SensorReading
from heizung.rules.constants import WINDOW_STALE_THRESHOLD_MIN
from heizung.schemas.device import (
    DeviceAssignZoneRequest,
    DeviceAssignZoneResponse,
    DeviceCreate,
    DeviceRead,
    DeviceUpdate,
    HardwareStatusResponse,
)
from heizung.schemas.sensor_reading import SensorReadingRead
from heizung.tasks.engine_tasks import evaluate_room

logger = logging.getLogger(__name__)

# Postgres int4-Range. IDs > 2^31-1 wuerden DataError werfen → 500.
# Mit Path-Validierung kommt FastAPI sauberer mit 422 zurueck.
INT4_MAX = 2_147_483_647

DeviceIdPath = Path(  # noqa: B008 (FastAPI-Idiom)
    ...,
    gt=0,
    le=INT4_MAX,
    description="Device-ID (positive Integer, Postgres int4-Range)",
)

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
    device_id: int = DeviceIdPath,
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> Device:
    return await _get_or_404(session, device_id)


@router.patch(
    "/{device_id}",
    response_model=DeviceRead,
    summary="Geraet partiell aktualisieren",
)
async def update_device(
    payload: DeviceUpdate,
    device_id: int = DeviceIdPath,
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
# Geraete-Zone-Zuordnung (Sprint 9.11a)
# ---------------------------------------------------------------------------


@router.put(
    "/{device_id}/heating-zone",
    response_model=DeviceAssignZoneResponse,
    status_code=status.HTTP_200_OK,
    summary="Geraet einer Heizzone zuweisen oder neu zuordnen",
)
async def assign_device_to_zone(
    payload: DeviceAssignZoneRequest,
    device_id: int = DeviceIdPath,
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> Device:
    device = await session.get(Device, device_id)
    if device is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="device_not_found",
        )

    zone = await session.get(HeatingZone, payload.heating_zone_id)
    if zone is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="heating_zone_not_found",
        )

    if device.heating_zone_id == payload.heating_zone_id:
        return device

    device.heating_zone_id = payload.heating_zone_id
    await session.commit()
    await session.refresh(device)

    logger.info(
        "device_zone_changed",
        extra={
            "device_id": device.id,
            "dev_eui": device.dev_eui,
            "heating_zone_id_new": device.heating_zone_id,
        },
    )

    # Sprint HF-9.13a-2: Engine-Tick triggern, damit der Layer-4-Detached-
    # Trace und das Engine-Decision-Panel sofort den neuen Stand zeigen
    # (sonst erst beim naechsten 60-s-Beat-Tick). AE-47 Hardware-First
    # bleibt: Engine sieht weiter die sensor_reading-Frame-Historie.
    evaluate_room.delay(zone.room_id)
    logger.info(
        "engine_tick_triggered",
        extra={
            "device_id": device.id,
            "room_id": zone.room_id,
            "trigger": "device_zone_changed",
        },
    )
    return device


@router.delete(
    "/{device_id}/heating-zone",
    response_model=DeviceAssignZoneResponse,
    status_code=status.HTTP_200_OK,
    summary="Geraet von Heizzone trennen (Detach)",
)
async def detach_device_from_zone(
    device_id: int = DeviceIdPath,
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> Device:
    device = await session.get(Device, device_id)
    if device is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="device_not_found",
        )

    if device.heating_zone_id is None:
        return device

    prev = device.heating_zone_id
    device.heating_zone_id = None
    await session.commit()
    await session.refresh(device)

    logger.info(
        "device_zone_detached",
        extra={
            "device_id": device.id,
            "dev_eui": device.dev_eui,
            "heating_zone_id_prev": prev,
        },
    )

    # Sprint HF-9.13a-2: Engine-Tick fuer das ALTE Zimmer triggern. Es hat
    # jetzt ein Geraet weniger; Layer-4-Detached-Aggregation aendert sich
    # (z.B. von "1 von 2 detached" zu "no_devices_in_zone"). Symmetrisch
    # zum PUT-Handler.
    old_zone = await session.get(HeatingZone, prev)
    if old_zone is not None:
        evaluate_room.delay(old_zone.room_id)
        logger.info(
            "engine_tick_triggered",
            extra={
                "device_id": device.id,
                "room_id": old_zone.room_id,
                "trigger": "device_zone_detached",
            },
        )
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
    device_id: int = DeviceIdPath,
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


# ---------------------------------------------------------------------------
# Hardware-Status (Sprint 9.13c, B-LT-2-followup-1)
# ---------------------------------------------------------------------------


@router.get(
    "/{device_id}/hardware-status",
    response_model=HardwareStatusResponse,
    summary="Hardware-Status (attached_backplate) im 30-Min-Fenster",
)
async def get_hardware_status(
    device_id: int = DeviceIdPath,
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> HardwareStatusResponse:
    """Binaerer Hardware-Status fuer das Frontend-Badge.

    Liest ``sensor_reading.attached_backplate`` der letzten
    ``WINDOW_STALE_THRESHOLD_MIN`` Minuten:
      - ``status="active"`` wenn mindestens ein Frame ``attached_backplate=True``
        existiert; ``last_seen`` ist dessen Zeitstempel.
      - ``status="inactive"`` sonst (alle False, alle NULL, oder keine Frames).
      - ``frames_in_window`` zaehlt Frames mit ``attached_backplate IS NOT NULL``
        (NULL-Frames aus FW < 4.1 / Recovery-Daten werden bewusst ausgeschlossen,
        konsistent zu Layer 4 Detached, siehe ``rules/engine.py``).

    Reine Lese-Aggregation, kein Engine-Pfad und kein Cache. AE-47
    Hardware-First bleibt unveraendert.
    """
    await _get_or_404(session, device_id)

    now = datetime.now(UTC)
    threshold = now - timedelta(minutes=WINDOW_STALE_THRESHOLD_MIN)

    frames_stmt = select(func.count()).where(
        SensorReading.device_id == device_id,
        SensorReading.time >= threshold,
        SensorReading.attached_backplate.is_not(None),
    )
    frames_in_window = (await session.execute(frames_stmt)).scalar_one()

    last_seen_stmt = select(func.max(SensorReading.time)).where(
        SensorReading.device_id == device_id,
        SensorReading.time >= threshold,
        SensorReading.attached_backplate.is_(True),
    )
    last_seen = (await session.execute(last_seen_stmt)).scalar_one()

    return HardwareStatusResponse(
        status="active" if last_seen is not None else "inactive",
        last_seen=last_seen,
        frames_in_window=frames_in_window,
        window_minutes=WINDOW_STALE_THRESHOLD_MIN,
    )
