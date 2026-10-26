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

from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from heizung.auth.dependencies import require_mitarbeiter, require_user
from heizung.db import get_session
from heizung.models.enums import OverrideSource
from heizung.models.global_config import GlobalConfig
from heizung.models.heating_zone import HeatingZone
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
from heizung.services.geraetegrenzen import Grenzen, soll_grenzen_je_zone
from heizung.services.occupancy_service import next_active_checkout
from heizung.services.override_service import InvalidZoneError
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


async def _ensure_zone_in_room(
    session: AsyncSession, *, room_id: int, heating_zone_id: int
) -> None:
    """Sprint 12a T3 (AE-58): validiert dass die Zone zum Raum gehoert.

    Wirft ``InvalidZoneError`` (HTTP 404 ``INVALID_ZONE``) falls Zone nicht
    existiert oder zu einem anderen Raum gehoert. Beide Faelle werden
    gleich behandelt — der Client darf keine Zonen-IDs anderer Raeume
    erraten koennen (kein leakendes 403 vs 404).

    B-Sprint13b2-7 (AE-59): app-weiter ``OverrideError``-Handler in
    ``heizung.main`` rendert das Top-Level-``error_code``-Schema.
    """
    stmt = select(HeatingZone.id).where(
        HeatingZone.id == heating_zone_id,
        HeatingZone.room_id == room_id,
    )
    found = await session.scalar(stmt)
    if found is None:
        raise InvalidZoneError(room_id=room_id, zone_id=heating_zone_id)


async def _mit_kappung(
    session: AsyncSession, verlauf: Sequence[ManualOverride]
) -> list[ManualOverrideResponse]:
    """Ergaenzt den **wirksamen** Wert, wo die Kappung greift (T1.7).

    **Nur fuer aktive Zeilen.** Eine Bestandszeile von vorgestern gegen
    die *heutigen* Grenzen zu rechnen wuerde eine Vergangenheit
    behaupten, die so nicht war — abgelaufene und widerrufene Zeilen
    zeigen weiter den gespeicherten Wert.

    Die Grenzen kommen aus ``soll_grenzen_je_zone``, also aus demselben
    Helfer, der sie an das Geraet schickt (T1.3) und der die Bad-Vorlage
    kennt. Eine zweite Rechnung daneben waere die Stelle, an der die
    Anzeige spaeter von der Engine abweicht (Paragraph 5.53).

    Zonenlose Overrides (``heating_zone_id IS NULL``, zimmerweit) nehmen
    die Grenzen des **Zimmertyps**: so rechnet Layer 5 fuer das Zimmer
    auch.
    """
    jetzt = datetime.now(tz=UTC)
    aktiv = [
        o
        for o in verlauf
        if o.revoked_at is None and o.expires_at > jetzt and o.heating_zone_id is not None
    ]
    grenzen_je_zone: dict[int, Grenzen] = {}
    if aktiv:
        grenzen_je_zone = await soll_grenzen_je_zone(
            session, [o.heating_zone_id for o in aktiv if o.heating_zone_id is not None]
        )

    ergebnis: list[ManualOverrideResponse] = []
    for o in verlauf:
        antwort = ManualOverrideResponse.model_validate(o)
        grenzen = (
            grenzen_je_zone.get(o.heating_zone_id)
            if o in aktiv and o.heating_zone_id is not None
            else None
        )
        if grenzen is not None:
            wunsch = int(o.setpoint)
            gekappt = max(grenzen.min_c, min(grenzen.max_c, wunsch))
            if gekappt != wunsch:
                antwort = antwort.model_copy(update={"wirksam_gekappt_c": gekappt})
        ergebnis.append(antwort)
    return ergebnis


@router.get(
    "/rooms/{room_id}/overrides",
    response_model=list[ManualOverrideResponse],
    summary="Override-Historie eines Raums",
)
async def list_room_overrides(
    room_id: int = RoomIdPath,
    limit: int = Query(default=50, ge=1, le=200),  # noqa: B008
    include_expired: bool = Query(default=True),  # noqa: B008
    zone_id: int | None = Query(default=None, gt=0),  # noqa: B008
    _user: User = Depends(require_user),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> list[ManualOverrideResponse]:
    """Override-Historie eines Raums.

    Sprint 12a T3 (AE-58): Optionaler Query-Param ``zone_id`` filtert auf
    Zone-Match (``heating_zone_id == zone_id``) und ergaenzt Room-Scope-
    Overrides (``heating_zone_id IS NULL``) als Fallback. Sortierung:
    Zone-Match zuerst, dann Room-Match, dann ``created_at DESC``. Ohne
    ``zone_id``: alle Overrides des Raums (Backward-Compat).
    """
    await _ensure_room_exists(session, room_id)
    if zone_id is not None:
        await _ensure_zone_in_room(session, room_id=room_id, heating_zone_id=zone_id)
    verlauf = await override_service.get_history(
        session,
        room_id,
        limit=limit,
        include_expired=include_expired,
        heating_zone_id=zone_id,
    )
    return await _mit_kappung(session, verlauf)


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

    # Sprint 12a T3 (AE-58): wenn Body heating_zone_id setzt, muss die Zone
    # zum Pfad-Raum gehoeren — sonst 404 invalid_zone.
    if payload.heating_zone_id is not None:
        await _ensure_zone_in_room(
            session, room_id=room_id, heating_zone_id=payload.heating_zone_id
        )

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
    try:
        expires_at = override_service.compute_expires_at(
            source,
            now,
            next_checkout_at=next_checkout,
            hotel_config=hotel_config,
            dauer_minuten=payload.dauer_minuten,
        )
    except ValueError as e:
        # Sprint 24d: Dauer fehlt oder liegt ueber 24 h. Das Schema weist
        # das schon ab; dieser Zweig ist die Antwort fuer den Fall, dass
        # jemand die Pruefung dort lockert — dann kommt 422 und nicht 500.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e),
        ) from e

    # B-Sprint13b2-7 (AE-59): Override-Domain-Exceptions
    # (RoomOverrideBlockedError, RoomNotOccupiedError,
    # OverrideRejectedWindowOpenError) werden vom app-weiten
    # ``OverrideError``-Handler in ``heizung.main`` gefangen und auf
    # ``{detail, error_code, ...extras}`` mit korrektem HTTP-Status
    # gerendert. ``ValueError`` aus der Schema-/Setpoint-Validierung
    # bleibt 422.
    try:
        override = await override_service.create(
            session,
            room_id=room_id,
            setpoint=payload.setpoint,
            source=source,
            expires_at=expires_at,
            reason=payload.reason,
            created_by=user.email,
            heating_zone_id=payload.heating_zone_id,
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
