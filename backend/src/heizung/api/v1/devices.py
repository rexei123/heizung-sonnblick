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

from heizung.auth.dependencies import require_admin, require_user
from heizung.db import get_session
from heizung.models.device import Device
from heizung.models.heating_zone import HeatingZone
from heizung.models.sensor_reading import SensorReading
from heizung.models.user import User
from heizung.rules.constants import WINDOW_STALE_THRESHOLD_MIN
from heizung.schemas.device import (
    DeviceActiveOverrideRead,
    DeviceAssignZoneRequest,
    DeviceAssignZoneResponse,
    DeviceCreate,
    DeviceLatestReadingRead,
    DeviceRead,
    DeviceReplaceFromPoolRequest,
    DeviceRetireRequest,
    DeviceUpdate,
    HardwareStatusResponse,
)
from heizung.schemas.sensor_reading import SensorReadingRead
from heizung.services import override_service
from heizung.services.device_service import (
    get_device_with_relations,
    get_latest_reading,
    get_pool_devices,
    list_devices_with_relations,
    replace_device,
    retire_device,
)
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


async def _build_device_read(session: AsyncSession, device: Device) -> DeviceRead:
    """Assembliert ein ``DeviceRead`` inkl. Nested-Zuordnung + active_override
    + latest_reading (Sprint 14a, D2).

    Erwartet ein Device mit eager-geladener ``heating_zone``-Kette (via
    ``list_devices_with_relations`` / ``get_device_with_relations``), sonst
    Lazy-Load-Fehler im async-Pfad. ``heating_zone`` (Nested),
    ``hardware_number`` und die Basis-Felder kommen via ``model_validate``
    (from_attributes); ``active_override`` + ``latest_reading`` werden
    nachgesetzt, weil sie keine ORM-Attribute sind.

    Hinweis (D3): pro Device je eine Override- + eine Reading-Query (N+1).
    Bewusst akzeptiert bei < 200 Geraeten; Optimierung im Backlog falls noetig.
    """
    read = DeviceRead.model_validate(device)

    override_read: DeviceActiveOverrideRead | None = None
    if device.heating_zone is not None:
        active = await override_service.get_active(
            session,
            device.heating_zone.room_id,
            heating_zone_id=device.heating_zone_id,
        )
        if active is not None:
            override_read = DeviceActiveOverrideRead(
                source=active.source,
                setpoint_celsius=active.setpoint,
                started_at=active.created_at,
                expires_at=active.expires_at,
            )

    reading = await get_latest_reading(session, device.id)
    reading_read: DeviceLatestReadingRead | None = None
    if reading is not None:
        reading_read = DeviceLatestReadingRead(
            valve_position=reading.valve_position,
            open_window=reading.open_window,
            attached_backplate=reading.attached_backplate,
            temperature=reading.temperature,
            battery_percent=reading.battery_percent,
            recorded_at=reading.time,
        )

    return read.model_copy(
        update={"active_override": override_read, "latest_reading": reading_read}
    )


async def _reload_device_read(session: AsyncSession, device_id: int) -> DeviceRead:
    """Laedt ein Geraet mit Relations frisch und baut das ``DeviceRead``.

    Fuer Mutations-Endpoints, deren Response ``DeviceRead`` ist: nach
    ``commit``/``refresh`` ist ``device.heating_zone`` nicht eager-geladen,
    ein direktes ``model_validate`` wuerde im async-Pfad einen Lazy-Load
    (MissingGreenlet) ausloesen. Daher Reload via ``get_device_with_relations``.
    """
    device = await get_device_with_relations(session, device_id)
    if device is None:  # pragma: no cover — direkt nach erfolgreichem commit
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Device {device_id} nicht gefunden",
        )
    return await _build_device_read(session, device)


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
    _admin: User = Depends(require_admin),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> DeviceRead:
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
    # Sprint 14a (D2): enriched DeviceRead inkl. Nested-Zuordnung (reload
    # mit Eager-Load, weil refresh die Relation nicht laedt).
    return await _reload_device_read(session, device.id)


@router.get(
    "",
    response_model=list[DeviceRead],
    summary="Geraete-Liste (paginiert)",
)
async def list_devices(
    include_retired: bool = Query(  # noqa: B008
        default=False,
        description=(
            "Wenn False (Default): nur aktive Geraete (retired_at IS NULL). "
            "True liefert retired Devices mit (Audit-Sicht)."
        ),
    ),
    vendor: str | None = Query(default=None),  # noqa: B008
    limit: int = Query(default=100, ge=1, le=1000),  # noqa: B008
    offset: int = Query(default=0, ge=0),  # noqa: B008
    _user: User = Depends(require_user),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> list[DeviceRead]:
    # Sprint 14a (D2/D3): Eager-Load der Zuordnungs-Kette + Nested-Response
    # (heating_zone.name/health_state, room.number, room_type.name) plus
    # active_override + latest_reading. Lifecycle-Filter AE-57 unveraendert
    # (retired_at IS NULL per Default, include_retired fuer Audit-Sicht).
    devices = await list_devices_with_relations(
        session,
        include_retired=include_retired,
        vendor=vendor,
        limit=limit,
        offset=offset,
    )
    return [await _build_device_read(session, d) for d in devices]


@router.get(
    "/pool",
    response_model=list[DeviceRead],
    summary="Reserve-Pool-Devices (heating_zone_id IS NULL, retired_at IS NULL)",
)
async def list_pool_devices(
    _user: User = Depends(require_user),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> list[DeviceRead]:
    """Liefert alle aktiven Reserve-Vickis sortiert ``created_at DESC``
    (neueste zuerst). Frontend nutzt das fuer den Pool-Dropdown beim
    Tausch (13b.2).

    Sprint 13b.1 (AE-57): MUSS vor ``GET /{device_id}`` registriert sein,
    sonst matched FastAPI ``/{device_id}`` mit ``device_id="pool"`` -> 422.

    Sprint 14a (D2): Response ist jetzt das enriched ``DeviceRead``. Pool-
    Geraete haben ``heating_zone IS NULL`` -> ``heating_zone``/
    ``active_override`` sind null; ``latest_reading`` kann gesetzt sein.
    """
    pool = await get_pool_devices(session)
    return [await _build_device_read(session, d) for d in pool]


@router.get(
    "/{device_id}",
    response_model=DeviceRead,
    summary="Einzelnes Geraet",
)
async def get_device(
    device_id: int = DeviceIdPath,
    _user: User = Depends(require_user),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> DeviceRead:
    # Sprint 14a (D2): Detail-Response mit Nested-Zuordnung + active_override
    # + latest_reading (Quelle fuer Karten + Diagnose-Kacheln der Detail-Seite).
    device = await get_device_with_relations(session, device_id)
    if device is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Device {device_id} nicht gefunden",
        )
    return await _build_device_read(session, device)


@router.patch(
    "/{device_id}",
    response_model=DeviceRead,
    summary="Geraet partiell aktualisieren",
)
async def update_device(
    payload: DeviceUpdate,
    device_id: int = DeviceIdPath,
    _admin: User = Depends(require_admin),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> DeviceRead:
    device = await _get_or_404(session, device_id)
    updates = payload.model_dump(exclude_unset=True)

    if "heating_zone_id" in updates:
        await _ensure_zone_exists(session, updates["heating_zone_id"])

    for field, value in updates.items():
        setattr(device, field, value)

    try:
        await session.commit()
    except IntegrityError as e:
        await session.rollback()
        # Sprint 14a (D1): Partial-Unique-Index auf hardware_number — bei
        # Inline-Edit-Kollision (zwei Geraete, gleiche Nummer) sauberes 409
        # statt 500.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Hardware-Nummer '{updates.get('hardware_number')}' ist bereits vergeben",
        ) from e
    await session.refresh(device)
    # Sprint 14a (D2): enriched DeviceRead (reload mit Eager-Load).
    return await _reload_device_read(session, device.id)


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
    _admin: User = Depends(require_admin),  # noqa: B008
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
    _admin: User = Depends(require_admin),  # noqa: B008
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
    _user: User = Depends(require_user),  # noqa: B008
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
    _user: User = Depends(require_user),  # noqa: B008
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


# ---------------------------------------------------------------------------
# Lifecycle: Pool-Reassign-Tausch + Retire + Pool-Liste (Sprint 13b.1, AE-57)
# ---------------------------------------------------------------------------
#
# Hinweis: ``GET /pool`` ist weiter oben (vor ``/{device_id}``) registriert
# — sonst matched FastAPI ``/{device_id}`` mit ``device_id="pool"`` und
# liefert 422 statt 200.


@router.post(
    "/{device_id}/replace/from-pool",
    response_model=DeviceRead,
    status_code=status.HTTP_200_OK,
    summary="Vicki via Pool-Device ersetzen (atomarer Tausch)",
)
async def replace_device_from_pool(
    payload: DeviceReplaceFromPoolRequest,
    device_id: int = DeviceIdPath,
    user: User = Depends(require_admin),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> DeviceRead:
    """Atomarer Pool-Reassign-Tausch (AE-57 Entscheidung 6).

    Alt-Vicki bekommt ``retired_at``, ``retired_reason='replaced_by_pool'``,
    ``replaced_by_device_id=new``. Neu-Vicki uebernimmt die Zone. Eine
    ``DEVICE_REPLACED``-BusinessAudit-Row in derselben Transaktion.

    Engine-Tick auf der betroffenen Zone-Room triggert nach Commit
    automatisch (Sprint 9.13a hf2-Pattern), Layer-4 sieht den neuen
    Stand sofort.
    """
    # Engine-Tick-Trigger: alte Zone capturen vor dem Tausch (replace
    # setzt heating_zone_id = NULL).
    old_for_trigger = await session.get(Device, device_id)
    old_zone_id = old_for_trigger.heating_zone_id if old_for_trigger else None

    # B-Sprint13b2-4 (AE-59): LifecycleError-Subklassen propagieren bis
    # zum App-weiten Exception-Handler in heizung.main, der sie als
    # {detail, error_code} mit 404 (DeviceNotFound) oder 409 (sonst)
    # rendert. Kein endpoint-lokales try/except mehr noetig.
    result = await replace_device(
        session,
        old_device_id=device_id,
        new_pool_device_id=payload.new_pool_device_id,
        user_id=user.id,
    )

    await session.commit()
    await session.refresh(result)

    # Engine-Tick triggern, damit Layer 4 + Engine-Decision-Panel den
    # neuen Stand ohne 60-s-Beat-Latenz sehen (Pattern aus Sprint HF-9.13a-2).
    if old_zone_id is not None:
        zone = await session.get(HeatingZone, old_zone_id)
        if zone is not None:
            evaluate_room.delay(zone.room_id)
            logger.info(
                "engine_tick_triggered",
                extra={
                    "device_id": result.id,
                    "room_id": zone.room_id,
                    "trigger": "device_replaced_from_pool",
                },
            )

    # Sprint 14a (D2): enriched DeviceRead des (retired) Alt-Geraets.
    return await _reload_device_read(session, result.id)


@router.post(
    "/{device_id}/retire",
    response_model=DeviceRead,
    status_code=status.HTTP_200_OK,
    summary="Vicki stillsetzen (Retire ohne Ersatz)",
)
async def retire_device_endpoint(
    payload: DeviceRetireRequest,
    device_id: int = DeviceIdPath,
    user: User = Depends(require_admin),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> DeviceRead:
    """Stilllegung ohne Ersatz (AE-57 Entscheidung 6).

    Setzt ``retired_at`` + ``retired_reason``. ``heating_zone_id`` bleibt
    (Historie-Anker fuer sensor_reading-FK). DEVICE_RETIRED-Audit atomar.
    """
    old_for_trigger = await session.get(Device, device_id)
    old_zone_id = old_for_trigger.heating_zone_id if old_for_trigger else None

    # B-Sprint13b2-4 (AE-59): LifecycleError-Propagation (siehe replace-Endpoint).
    result = await retire_device(
        session,
        device_id=device_id,
        reason=payload.reason,
        user_id=user.id,
    )

    await session.commit()
    await session.refresh(result)

    if old_zone_id is not None:
        zone = await session.get(HeatingZone, old_zone_id)
        if zone is not None:
            evaluate_room.delay(zone.room_id)
            logger.info(
                "engine_tick_triggered",
                extra={
                    "device_id": result.id,
                    "room_id": zone.room_id,
                    "trigger": "device_retired",
                },
            )

    # Sprint 14a (D2): enriched DeviceRead des stillgelegten Geraets.
    return await _reload_device_read(session, result.id)
