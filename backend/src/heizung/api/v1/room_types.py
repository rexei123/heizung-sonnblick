"""Raumtypen-Endpoints (Sprint 8.4).

CRUD:
    POST    /api/v1/room-types
    GET     /api/v1/room-types
    GET     /api/v1/room-types/{room_type_id}
    PATCH   /api/v1/room-types/{room_type_id}
    DELETE  /api/v1/room-types/{room_type_id}   — 409 wenn Raeume verknuepft

Sprint 24d:
    GET     /api/v1/room-types/sollwert-wirksamkeit
    POST    /api/v1/room-types/{room_type_id}/sollwerte-uebernehmen

**Die Reihenfolge der Routen ist nicht beliebig.** ``/{room_type_id}``
traegt ``gt=0``; ein Aufruf von ``/sollwert-wirksamkeit`` wuerde daran mit
422 scheitern, wenn die dynamische Route zuerst registriert ist. Die
statische steht deshalb davor — dieselbe Falle wie bei den
Playwright-Routen in Sprint 24b, nur eine Schicht tiefer.
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
from heizung.schemas.room_type import (
    RoomTypeCreate,
    RoomTypeRead,
    RoomTypeUpdate,
    SollwertUebernahme,
    WirksamkeitFeld,
    WirksamkeitRaumtyp,
)
from heizung.services import raumtyp_regel
from heizung.services.business_audit_service import record_business_action

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


def _betrieb_gleichziehen(rt: RoomType) -> None:
    """Bei einem Allgemeinbereich ist „Betrieb" der Frei-Wert — auch in der Spalte.

    Die Raumtyp-Seite zeigt fuer einen nicht buchbaren Typ nur „Betrieb"
    und „Nacht"; „Belegt" ist ausgeblendet, weil ein Bereich nie belegt
    ist. Die Spalte ``default_t_occupied`` bleibt aber bestehen, und wer
    sie stehenlaesst, haelt einen Wert, den niemand sieht und der bei
    einem von Hand gesetzten Status ``occupied`` ploetzlich gilt.

    Deshalb zieht das Speichern sie gleich. Eine Spalte, ein angezeigter
    Wert, ein wirksamer Wert — sonst waere die Seite nach diesem Sprint
    wieder eine Anzeige, die etwas anderes behauptet als die Engine tut
    (§5.77, der Fehler, aus dem dieser Sprint entstanden ist).
    """
    if not rt.is_bookable:
        rt.default_t_occupied = rt.default_t_vacant


@router.get(
    "/sollwert-wirksamkeit",
    response_model=list[WirksamkeitRaumtyp],
    summary="Vorschau: welcher Sollwert wirkt heute, welcher wuerde wirken",
)
async def sollwert_wirksamkeit(
    _user: User = Depends(require_user),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> list[WirksamkeitRaumtyp]:
    """Die Diff-Tabelle als Abfrage, nicht als Behauptung in einer Doku.

    Welche Werte in diesem Haus stehen, weiss nur dieses Haus. Eine
    Tabelle im Sprint-Bericht waere eine Momentaufnahme meiner
    Test-Datenbank (§5.79); diese Abfrage beantwortet die Frage am
    Datenstand, an dem sie gestellt wird — und sie ist genau die
    Vorschau, die die Admin-Aktion unten anbietet, bevor jemand sie
    ausloest.
    """
    befunde = await raumtyp_regel.wirksamkeit(session)
    return [
        WirksamkeitRaumtyp(
            room_type_id=b.room_type_id,
            name=b.name,
            is_bookable=b.is_bookable,
            zeile_vorhanden=b.zeile_vorhanden,
            wuerde_sich_aendern=b.wuerde_sich_aendern,
            felder=[
                WirksamkeitFeld(
                    feld=f.feld,
                    angezeigt=f.angezeigt,
                    wirksam=f.wirksam,
                    quelle=f.quelle,
                )
                for f in b.felder
            ],
        )
        for b in befunde
    ]


@router.post(
    "/{room_type_id}/sollwerte-uebernehmen",
    response_model=SollwertUebernahme,
    summary="Sollwerte dieses Raumtyps wirksam machen (Admin, mit Audit)",
)
async def sollwerte_uebernehmen(
    room_type_id: int = RoomTypeIdPath,
    admin: User = Depends(require_admin),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> SollwertUebernahme:
    """Die vorbereitete Freigabe-Aktion fuer **buchbare** Raumtypen.

    Beim Speichern eines Gaestezimmer-Raumtyps entsteht bewusst keine
    ``rule_config``-Zeile (Begruendung in ``services/raumtyp_regel``):
    eine Aenderung an der Beschreibung wuerde sonst nebenbei die
    Sollwerte von zwanzig Zimmern umstellen. Diese Aktion ist der
    ausdrueckliche Weg — ein Aufruf je Raumtyp, mit Audit, nach der
    Vorschau oben.

    Fuer einen nicht buchbaren Typ ist sie unnoetig (das Speichern tut es
    schon) und bleibt trotzdem erlaubt: sie ist dann der Weg, eine Zeile
    nachzuziehen, die aus irgendeinem Grund fehlt.
    """
    rt = await _get_or_404(session, room_type_id)
    vorher = await raumtyp_regel.lade_raumtyp_zeile(session, room_type_id)
    altwert = (
        {
            "t_occupied": str(vorher.t_occupied) if vorher.t_occupied is not None else None,
            "t_vacant": str(vorher.t_vacant) if vorher.t_vacant is not None else None,
            "t_night": str(vorher.t_night) if vorher.t_night is not None else None,
        }
        if vorher is not None
        else None
    )

    ergebnis = await raumtyp_regel.synchronisiere_raumtyp(session, rt, anlegen_erlaubt=True)

    await record_business_action(
        session,
        user_id=admin.id,
        action="ROOM_TYPE_SETPOINTS_APPLIED",
        target_type="room_type",
        target_id=room_type_id,
        old_value=altwert,
        new_value={
            "ergebnis": ergebnis.value,
            "t_occupied": str(rt.default_t_occupied),
            "t_vacant": str(rt.default_t_vacant),
            "t_night": str(rt.default_t_night),
        },
    )
    await session.commit()
    return SollwertUebernahme(
        room_type_id=room_type_id,
        ergebnis=ergebnis.value,
        t_occupied=rt.default_t_occupied,
        t_vacant=rt.default_t_vacant,
        t_night=rt.default_t_night,
    )


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
    _betrieb_gleichziehen(rt)
    session.add(rt)
    try:
        # Sprint 24d: **kein** Nachziehen einer rule_config-Zeile hier.
        # Fuer einen Allgemeinbereich hebt die Engine die Spalten ohnehin
        # auf ROOM_TYPE-Rang (``rules.engine.bereichs_kette``); eine Zeile
        # daneben waere eine zweite Wahrheit. Fuer ein Gaestezimmer ist der
        # Vorrang eine Entscheidung des Betreibers und laeuft ueber
        # ``POST /room-types/{id}/sollwerte-uebernehmen``.
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

    # Sprint 24e (PR A): das Echo der bearbeiteten ID gegen den Pfad.
    #
    # Die Oberflaeche hat am 25.10.2026 im Formular einen **fremden**
    # Datensatz gezeigt; ein Speichern haette dessen Werte in den
    # ausgewaehlten Raumtyp geschrieben. Behoben ist das dort, wo es
    # entstanden ist — diese Pruefung ist die zweite Haelfte, damit der
    # Server sich nicht darauf verlaesst, dass die Oberflaeche richtig
    # rechnet.
    #
    # ``id`` wird danach aus ``updates`` entfernt: es ist ein Echo und
    # kein Feld. Bliebe es stehen, wuerde ``setattr`` den Primaerschluessel
    # neu setzen — mit demselben Wert, also wirkungslos, aber eine
    # schreibende Zuweisung auf einen Schluessel ist nichts, was man
    # stehen lassen sollte.
    gesendete_id = updates.pop("id", None)
    if gesendete_id is not None and gesendete_id != room_type_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Die Anfrage gehoert zu Raumtyp {gesendete_id}, der Pfad zu "
                f"{room_type_id}. Nichts gespeichert — bitte die Seite neu laden."
            ),
        )

    if not updates:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Mindestens ein Feld zur Aktualisierung erforderlich",
        )
    for field, value in updates.items():
        setattr(rt, field, value)
    _betrieb_gleichziehen(rt)
    try:
        # Eine **vorhandene** Zeile wird nachgezogen — sie ist wirksam, und
        # ein Formular, das sie stehenlaesst, zeigte danach einen Wert und
        # die Engine naehme einen anderen. Eine neue entsteht hier nicht
        # (Begruendung im POST oben).
        if await raumtyp_regel.lade_raumtyp_zeile(session, rt.id) is not None:
            await raumtyp_regel.synchronisiere_raumtyp(session, rt, anlegen_erlaubt=False)
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
