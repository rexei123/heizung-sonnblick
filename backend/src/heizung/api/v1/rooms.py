"""Zimmer-Endpoints (Sprint 8.4).

CRUD:
    POST    /api/v1/rooms
    GET     /api/v1/rooms
    GET     /api/v1/rooms/{room_id}
    PATCH   /api/v1/rooms/{room_id}
    DELETE  /api/v1/rooms/{room_id}    — 409 wenn aktive Belegungen
"""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, status
from sqlalchemy import Integer, cast, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from heizung.auth.dependencies import require_admin, require_mitarbeiter, require_user
from heizung.db import get_session
from heizung.models.enums import RoomStatus
from heizung.models.event_log import EventLog
from heizung.models.occupancy import Occupancy
from heizung.models.room import Room
from heizung.models.room_type import RoomType
from heizung.models.user import User
from heizung.schemas.event_log import EventLogRead
from heizung.schemas.room import (
    BetriebszeitUpdate,
    RoomCreate,
    RoomOverrideBlockUpdate,
    RoomRead,
    RoomUpdate,
)
from heizung.schemas.room_history import (
    HistoryPunkt,
    HistoryZone,
    NachtBand,
    NachtFenster,
    RoomHistoryRead,
)
from heizung.services import betriebszeit, override_service, raumtyp_regel
from heizung.services.business_audit_service import record_business_action
from heizung.services.event_log import (
    latest_hard_clamp_setpoint_per_room,
    latest_hard_clamp_zone_setpoints,
)
from heizung.services.referenzzone import referenzzonen_pro_zimmer
from heizung.services.room_history import lade_verlauf
from heizung.services.zone_aggregates import latest_mean_temp_per_zone

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


async def _als_read(session: AsyncSession, room: Room) -> RoomRead:
    """Ein Zimmer mit der Bereichs-Marke (Sprint 24d).

    Eine Abfrage auf den Raumtyp statt der Beziehung: ein Lazy-Load auf
    ``room.room_type`` endet unter asyncpg in ``MissingGreenlet``, und die
    Liste loest das ohnehin gebuendelt (§5.38).
    """
    buchbar = await session.scalar(
        select(RoomType.is_bookable).where(RoomType.id == room.room_type_id)
    )
    ist_bereich = buchbar is False
    # Die Betriebszeit nur fuer einen Bereich lesen: bei einem
    # Gaestezimmer waere dieselbe Zeile das Nacht-Fenster, und sie unter
    # dem Namen „Betriebszeit" auszuliefern hiesse, zwei Dinge gleich zu
    # nennen, die verschieden gemeint sind.
    zeit = (
        await betriebszeit.lade(session, room.id)
        if ist_bereich
        else betriebszeit.Betriebszeit(von=None, bis=None)
    )
    return RoomRead.model_validate(room).model_copy(
        update={
            "ist_allgemeinbereich": ist_bereich,
            "betriebszeit_von": zeit.von,
            "betriebszeit_bis": zeit.bis,
        }
    )


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
    _admin: User = Depends(require_admin),  # noqa: B008
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
    _user: User = Depends(require_user),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> list[RoomRead]:
    stmt = select(Room)
    if room_type_id is not None:
        stmt = stmt.where(Room.room_type_id == room_type_id)
    if status_filter is not None:
        stmt = stmt.where(Room.status == status_filter)
    if floor is not None:
        stmt = stmt.where(Room.floor == floor)
    # Sortierung: primaer floor ASC (Etage 0 zuerst; Integer, kein String-
    # Vergleich), sekundaer number numerisch aufsteigend. number ist VARCHAR
    # ("101A" moeglich), daher numerischer Prefix via regexp statt String-Sort
    # (sonst "101" vor "99"). Nicht-numerische Nummern -> NULL -> NULLS LAST,
    # number als Tiebreak ("101" vor "101A"). floor NULL ebenfalls ans Ende.
    numeric_prefix = cast(
        func.nullif(func.regexp_replace(Room.number, "[^0-9].*$", ""), ""),
        Integer,
    )
    stmt = (
        stmt.order_by(
            Room.floor.asc().nullslast(),
            numeric_prefix.asc().nullslast(),
            Room.number.asc(),
        )
        .offset(offset)
        .limit(limit)
    )
    rooms = list((await session.execute(stmt)).scalars().all())

    # Sprint 14d (R-A/R-D): EIN Batch-Aggregat fuer den Override-Indikator,
    # KEIN per-room-Lookup (kein N+1 wie devices._build_device_read).
    rooms_with_override = await override_service.get_rooms_with_active_override(session)

    # Sprint 24d: welche Raumtypen Allgemeinbereiche sind — eine Abfrage
    # fuer die ganze Seite, nicht eine je Zeile.
    bereich_typen = await raumtyp_regel.nicht_buchbare_typ_ids(session)

    # Ist und Soll der Referenzzone (15.10.2026). Drei Aggregate fuer die
    # ganze Seite, keine Abfrage je Zimmer — dieselbe Regel wie oben.
    room_ids = [room.id for room in rooms]
    referenzzonen = await referenzzonen_pro_zimmer(session, room_ids)
    ist_pro_zone = await latest_mean_temp_per_zone(session, referenzzonen.values())
    soll_pro_zimmer = await latest_hard_clamp_setpoint_per_room(session, room_ids)
    # Befund des Betreibers, 31.10.2026: der Soll der **Referenzzone**, nicht
    # der des Zimmers. Begruendung in ``_mit_ist_und_soll``.
    soll_pro_zone = await latest_hard_clamp_zone_setpoints(session, room_ids)

    def _mit_ist_und_soll(room: Room) -> RoomRead:
        zone_id = referenzzonen.get(room.id)
        # Zimmer ohne Referenzzone: kein Ist. Der Soll bleibt trotzdem, er
        # haengt am Zimmer und nicht an der Zone — die Oberflaeche zeigt dann
        # „–" nur in der Ist-Spalte.
        zonen_ist = ist_pro_zone.get(zone_id) if zone_id is not None else None
        ist = zonen_ist.mittel if zonen_ist is not None else None
        # **Ist und Soll muessen dieselbe Zone meinen** (Befund des
        # Betreibers aus dem Rad-Test, 31.10.2026). Das Ist war seit dem
        # 15.10. das der Referenzzone, der Soll der des **Zimmers** — und
        # bei einer Zonen-Uebersteuerung sind das verschiedene Zahlen. In
        # Zimmer 107 stand „Soll 21,0 °C" neben einer aktiven
        # Uebersteuerung auf 23; die Spalte sprach vom Zimmer, die
        # daneben von der Zone, und niemand konnte das sehen.
        #
        # Der Rueckfall auf den Zimmerwert bleibt fuer zwei Faelle: ein
        # Zimmer ohne Referenzzone (dann gibt es keinen Zonenwert, der
        # gemeint sein koennte) und die erste Minute nach einem Deploy,
        # bevor der Engine-Lauf den Zonenwert geschrieben hat.
        soll = soll_pro_zimmer.get(room.id)
        if zone_id is not None:
            zonen_soll = soll_pro_zone.get(room.id, {}).get(zone_id)
            if zonen_soll is not None:
                soll = Decimal(zonen_soll)
        return RoomRead.model_validate(room).model_copy(
            update={
                "has_active_override": room.id in rooms_with_override,
                "reference_zone_id": zone_id,
                "mean_temperature_c": ist,
                "engine_setpoint_c": soll,
                "ist_allgemeinbereich": room.room_type_id in bereich_typen,
            }
        )

    return [_mit_ist_und_soll(room) for room in rooms]


@router.get(
    "/{room_id}",
    response_model=RoomRead,
    summary="Einzelnes Zimmer",
)
async def get_room(
    room_id: int = RoomIdPath,
    _user: User = Depends(require_user),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> RoomRead:
    return await _als_read(session, await _get_or_404(session, room_id))


@router.patch(
    "/{room_id}",
    response_model=RoomRead,
    summary="Zimmer partiell aktualisieren",
)
async def update_room(
    request: Request,
    payload: RoomUpdate,
    room_id: int = RoomIdPath,
    user: User = Depends(require_admin),  # noqa: B008
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
    # Sprint 14e T4 (R4): Audit nur fuer ``room_type_id`` — Engine-Wirkung via
    # RuleConfig-Scope (engine.py:856) macht den Wechsel zur fachlich
    # heizverhaltens-relevanten Aktion. Andere PATCH-Felder (number,
    # display_name, floor, orientation, status, notes) bleiben Audit-frei
    # (bewusste 14e-Scope-Eingrenzung, Phase-0 R4).
    old_room_type_id = room.room_type_id
    room_type_changed = "room_type_id" in updates and updates["room_type_id"] != old_room_type_id
    for field, value in updates.items():
        setattr(room, field, value)
    if room_type_changed:
        await record_business_action(
            session,
            user_id=user.id,
            action="ROOM_TYPE_CHANGED",
            target_type="room",
            target_id=room_id,
            old_value={"room_type_id": old_room_type_id},
            new_value={
                "room_type_id": updates["room_type_id"],
                # Engine-Wirkungs-Hinweis: naechster Tick (~60s) zieht die
                # RuleConfigs des neuen room_type.
                "engine_effect": "rule_config_scope_room_type",
            },
            request_ip=request.client.host if request.client else None,
        )
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


@router.patch(
    "/{room_id}/betriebszeit",
    response_model=RoomRead,
    summary="Betriebszeit eines Allgemeinbereichs setzen (Admin, mit Audit)",
)
async def set_betriebszeit(
    payload: BetriebszeitUpdate,
    room_id: int = RoomIdPath,
    admin: User = Depends(require_admin),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> RoomRead:
    """Setzt oder loescht die Betriebszeit — nur bei einem Bereich.

    **Warum der Endpunkt auf einen nicht buchbaren Raumtyp besteht.**
    Intern sind es die Grenzen des Nacht-Fensters. An einem Gaestezimmer
    wuerde dieselbe Eingabe die Nachtabsenkung dieses Zimmers umstellen —
    unter einem Namen, der etwas anderes sagt. Das waere ein Schalter, der
    etwas anderes tut, als auf ihm steht.

    ``require_admin``, weil die Betriebszeit zu den Stammdaten gehoert
    (dieselbe Rolle wie Zimmer, Raumtypen und Heizzonen; `rechte.ts`
    spiegelt das als ``darfStammdatenAendern``).
    """
    room = await _get_or_404(session, room_id)
    buchbar = await session.scalar(
        select(RoomType.is_bookable).where(RoomType.id == room.room_type_id)
    )
    if buchbar is not False:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "Betriebszeiten gibt es nur fuer Allgemeinbereiche "
                "(Raumtyp nicht buchbar). Ein Gaestezimmer folgt dem "
                "Nachtfenster seines Raumtyps."
            ),
        )

    try:
        von = betriebszeit.parse_uhrzeit(payload.von) if payload.von is not None else None
        bis = betriebszeit.parse_uhrzeit(payload.bis) if payload.bis is not None else None
        vorher = await betriebszeit.lade(session, room_id)
        neu = await betriebszeit.setze(session, room_id, von=von, bis=bis)
    except betriebszeit.BetriebszeitError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e)) from e

    await record_business_action(
        session,
        user_id=admin.id,
        action="ROOM_OPERATING_HOURS_SET",
        target_type="room",
        target_id=room_id,
        old_value={
            "von": vorher.von.isoformat() if vorher.von else None,
            "bis": vorher.bis.isoformat() if vorher.bis else None,
        },
        new_value={
            "von": neu.von.isoformat() if neu.von else None,
            "bis": neu.bis.isoformat() if neu.bis else None,
        },
    )
    await session.commit()
    await session.refresh(room)
    return await _als_read(session, room)


@router.patch(
    "/{room_id}/override-block-state",
    response_model=RoomRead,
    summary="Uebersteuerungs-Sperre togglen (Sprint 12c, AE-58)",
)
async def set_override_block_state(
    request: Request,
    payload: RoomOverrideBlockUpdate,
    room_id: int = RoomIdPath,
    user: User = Depends(require_mitarbeiter),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> Room:
    """Setzt ``room.guest_override_blocked`` auf den Ziel-Wert.

    Sprint 12c (AE-58): Toggle-On (False -> True) revoked **alle** aktiven
    Overrides des Raums (source-agnostic) via
    ``override_service.revoke_all_active_overrides`` mit
    ``reason="room_override_blocked"``. Toggle-Off (True -> False) laesst
    die Override-Tabelle unangetastet — bestehende Overrides bleiben
    revoked, neue koennen wieder angelegt werden.

    Idempotenz (§S2): wenn ``old == new``, kein Audit, kein Revoke, 200
    mit aktuellem Room-Stand.

    Audit: BusinessAudit-Action ``ROOM_OVERRIDE_BLOCK_TOGGLED`` mit
    ``new_value.revoked_overrides_count``. Override-IDs werden NICHT im
    Audit gefuehrt — rekonstruierbar via
    ``revoked_reason='room_override_blocked'``-Filter auf
    ``manual_override``.

    Begriffstrennung: ``guest_override_blocked`` ist **nicht** identisch
    mit ``RoomStatus.BLOCKED`` (das ist „Zimmer aus Engine genommen").
    Hier laeuft die Engine normal, nur die Override-Eingabe ist gesperrt.

    **Sprint 23 T4-A: ``bis_checkout``.** Mit ``true`` endet die Sperre
    beim Uebergang OCCUPIED -> VACANT von selbst
    (``services/gast_sperre``). Das ist der Regelfall fuer einen Gast, der
    die Einstellung verstellt: eine dauerhafte Sperre, die niemand
    zuruecknimmt, hinterlaesst dem **naechsten** Gast ein Rad, das nichts
    bewirkt — und an der Rezeption keine Erklaerung dafuer.

    Der Standard bleibt ``false`` und damit das bisherige Verhalten. Zwei
    Faelle werden mit 422 abgewiesen: ``bis_checkout`` ohne ``blocked``,
    und ``bis_checkout`` fuer einen Allgemeinbereich (der hat keine
    Abreise, die Sperre wuerde nie enden). Begruendungen stehen im Code
    daneben.
    """
    room = await _get_or_404(session, room_id)

    # Sprint 23 T4-A: zwei Abweisungen, bevor irgendetwas geschrieben wird.
    #
    # 1. ``bis_checkout`` ohne ``blocked`` ist kein Zustand. Es waere eine
    #    Sperre, die endet, ohne begonnen zu haben — und sie wuerde beim
    #    naechsten Setzen eine Absicht vorspiegeln, die niemand geaeussert
    #    hat.
    if payload.bis_checkout and not payload.blocked:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                '„Bis Check-out" setzt eine Sperre voraus. Entweder sperren '
                "und bis Check-out, oder aufheben."
            ),
        )

    # 2. Ein Allgemeinbereich hat keinen Check-out. ``sync_room_status``
    #    laesst den Status eines nicht buchbaren Raumtyps stehen (Sprint
    #    24d), der Uebergang OCCUPIED -> VACANT tritt dort nie ein — eine
    #    Sperre „bis Check-out" wuerde also **nie** enden. Dass der
    #    Loese-Dienst sie nie zu sehen bekaeme, ist kein Ersatz fuer diese
    #    Abweisung, sondern der Grund dafuer: ein Versprechen, das niemand
    #    einloest, darf nicht annehmbar sein (Paragraph 5.77).
    if payload.bis_checkout:
        buchbar = await session.scalar(
            select(RoomType.is_bookable).where(RoomType.id == room.room_type_id)
        )
        if buchbar is False:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    "Ein Allgemeinbereich hat keine Abreise — eine Sperre „bis "
                    'Check-out" wuerde dort nie enden. Hier gilt nur die '
                    "dauerhafte Sperre."
                ),
            )

    old_blocked = room.guest_override_blocked
    old_bis_checkout = room.guest_block_bis_checkout
    # Idempotenz (Paragraph S2) vergleicht **beide** Felder. Vorher stand
    # hier nur ``blocked``; damit haette ein Wechsel von „dauerhaft" auf
    # „bis Check-out" nichts getan und 200 gemeldet.
    if old_blocked == payload.blocked and old_bis_checkout == payload.bis_checkout:
        return room

    revoked_count = 0
    # Widerrufen wird beim **Beginn** der Sperre, nicht bei jeder
    # Aenderung: wer von „dauerhaft" auf „bis Check-out" umstellt, hat
    # schon gesperrt, und ein zweiter Widerruf traefe nichts.
    if payload.blocked and not old_blocked:
        revoked_count = await override_service.revoke_all_active_overrides(
            session,
            room_id=room_id,
            reason=override_service.REVOKE_REASON_ROOM_BLOCKED,
        )

    room.guest_override_blocked = payload.blocked
    # Beim Aufheben faellt die Absicht mit — sonst stuende sie beim
    # naechsten Setzen noch da (dieselbe Regel wie im Loese-Dienst).
    room.guest_block_bis_checkout = payload.bis_checkout if payload.blocked else False

    await record_business_action(
        session,
        user_id=user.id,
        action="ROOM_OVERRIDE_BLOCK_TOGGLED",
        target_type="room",
        target_id=room_id,
        old_value={"blocked": old_blocked, "bis_checkout": old_bis_checkout},
        new_value={
            "blocked": payload.blocked,
            "bis_checkout": room.guest_block_bis_checkout,
            "revoked_overrides_count": revoked_count,
        },
        request_ip=request.client.host if request.client else None,
    )
    await session.commit()
    await session.refresh(room)
    return room


@router.get(
    "/{room_id}/engine-trace",
    response_model=list[EventLogRead],
    summary="Engine-Pipeline-Trace fuer einen Raum (Sprint 9.5)",
)
async def engine_trace(
    room_id: int = RoomIdPath,
    limit: int = Query(default=50, ge=1, le=500),  # noqa: B008
    _user: User = Depends(require_user),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> list[EventLog]:
    """Liest die letzten N event_log-Eintraege fuer einen Raum.

    Sortierung: neueste zuerst. Im Frontend (Sprint 9.10) gruppiert das
    Engine-Decision-Panel die Eintraege per ``evaluation_id`` zu einem
    Layer-Trace pro Engine-Run.
    """
    await _get_or_404(session, room_id)
    stmt = (
        select(EventLog)
        .where(EventLog.room_id == room_id)
        .order_by(EventLog.time.desc())
        .limit(limit)
    )
    return list((await session.execute(stmt)).scalars().all())


@router.get(
    "/{room_id}/history",
    response_model=RoomHistoryRead,
    summary="Verlauf eines Zimmers je Heizzone (Sprint 21 A1)",
)
async def room_history(
    room_id: int = RoomIdPath,
    bereich: Literal["24h", "7d"] = Query(default="24h", alias="range"),  # noqa: B008
    _user: User = Depends(require_user),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> RoomHistoryRead:
    """Ist-Temperatur und Sollwert je Heizzone, serverseitig zusammengefasst.

    ``range=24h`` liefert Zehn-Minuten-Eimer (144 Punkte je Zone),
    ``range=7d`` Stunden-Eimer (168). Die Zusammenfassung liegt hier und
    nicht im Diagramm: eine Woche rohe Messwerte sind bei vier Geraeten
    rund 4000 Zeilen je Zimmer.

    Die Antwort traegt ``range_from``/``range_to`` (UTC, halboffen),
    ``timezone`` und das aufgeloeste ``night_window`` in Ortszeit mit — die
    Oberflaeche rechnet nichts davon selbst nach. Das Nachtfenster kommt
    durch dieselbe Kette wie bei der Engine (``rules/config_resolve``),
    sonst zeichnete die Anzeige ein Band, nach dem gar nicht geregelt wird.

    Belegungs-Baender holt die Oberflaeche aus
    ``GET /occupancies?room_id=&from=&to=`` — der Endpunkt existiert, und
    ein zweiter Weg zu denselben Zeilen waere eine zweite Wahrheit fuer
    nichts.
    """
    room = await _get_or_404(session, room_id)
    verlauf = await lade_verlauf(session, room=room, bereich=bereich)
    fenster = (
        NachtFenster(start=verlauf.night_start, end=verlauf.night_end)
        if verlauf.night_start is not None and verlauf.night_end is not None
        else None
    )
    return RoomHistoryRead(
        room_id=verlauf.room_id,
        range=verlauf.bereich,
        bucket_minutes=verlauf.bucket_minutes,
        range_from=verlauf.von,
        range_to=verlauf.bis,
        timezone=verlauf.timezone,
        night_window=fenster,
        night_bands=[NachtBand(start=b.start, end=b.end) for b in verlauf.night_bands],
        zones=[
            HistoryZone(
                zone_id=z.zone_id,
                name=z.name,
                kind=z.kind,
                points=[
                    HistoryPunkt(t=pt.t, temperature=pt.temperature, setpoint=pt.setpoint)
                    for pt in z.points
                ],
            )
            for z in verlauf.zones
        ],
    )


@router.delete(
    "/{room_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Zimmer loeschen (nur ohne aktive Belegungen)",
)
async def delete_room(
    room_id: int = RoomIdPath,
    _admin: User = Depends(require_admin),  # noqa: B008
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
