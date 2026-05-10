"""Belegungs-Service: Overlap-Check + room.status-Auto-Update.

Wird von der Occupancy-API (Sprint 8.5) verwendet. Kapselt die Logik die
- pruefen muss, ob ein neuer Eintrag mit aktiven Belegungen kollidiert
- bei POST/Storno den ``room.status`` synchron zur aktuellen Belegung haelt

Engine (Sprint 9) liest spaeter ``room.status`` zur Layer-1-Bestimmung,
deshalb ist die Auto-Aktualisierung kein Komfort sondern Pflicht.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from heizung.models.enums import RoomStatus
from heizung.models.occupancy import Occupancy
from heizung.models.room import Room


def _now() -> datetime:
    return datetime.now(tz=UTC)


async def has_overlap(
    session: AsyncSession,
    room_id: int,
    check_in: datetime,
    check_out: datetime,
    exclude_occupancy_id: int | None = None,
) -> bool:
    """Prueft, ob es eine aktive Belegung im selben Raum gibt, die sich
    mit dem Zeitfenster [check_in, check_out) ueberlappt.

    Overlap-Definition (halboffen am Ende, gleich check_out gilt nicht
    mehr als Konflikt — naechster Gast kann ab check_out anreisen):
        existing.check_in < check_out  AND  existing.check_out > check_in
    """
    stmt = select(Occupancy).where(
        and_(
            Occupancy.room_id == room_id,
            Occupancy.is_active.is_(True),
            Occupancy.check_in < check_out,
            Occupancy.check_out > check_in,
        )
    )
    if exclude_occupancy_id is not None:
        stmt = stmt.where(Occupancy.id != exclude_occupancy_id)
    result = await session.execute(stmt.limit(1))
    return result.scalar_one_or_none() is not None


async def derive_room_status(
    session: AsyncSession, room_id: int, now: datetime | None = None
) -> RoomStatus:
    """Berechnet den korrekten ``room.status`` aus den aktiven Belegungen.

    - OCCUPIED wenn aktive Belegung mit check_in <= jetzt < check_out
    - RESERVED wenn aktive Belegung mit check_in > jetzt (nichts gerade aktiv)
    - VACANT wenn keine aktive Belegung
    - CLEANING / BLOCKED werden hier NICHT veraendert (manueller Status)
    """
    current_time = now or _now()

    # Aktuell laufende Belegung?
    stmt_current = (
        select(Occupancy)
        .where(
            and_(
                Occupancy.room_id == room_id,
                Occupancy.is_active.is_(True),
                Occupancy.check_in <= current_time,
                Occupancy.check_out > current_time,
            )
        )
        .limit(1)
    )
    current = await session.scalar(stmt_current)
    if current is not None:
        return RoomStatus.OCCUPIED

    # Zukuenftige Belegung?
    stmt_future = (
        select(Occupancy)
        .where(
            and_(
                Occupancy.room_id == room_id,
                Occupancy.is_active.is_(True),
                Occupancy.check_in > current_time,
            )
        )
        .limit(1)
    )
    future = await session.scalar(stmt_future)
    if future is not None:
        return RoomStatus.RESERVED

    return RoomStatus.VACANT


async def sync_room_status(
    session: AsyncSession, room_id: int, now: datetime | None = None
) -> None:
    """Setzt ``room.status`` auf den abgeleiteten Wert.

    CLEANING und BLOCKED werden NICHT ueberschrieben — sind manuelle
    Operations-Zustaende, die nichts mit Belegung zu tun haben.
    """
    room = await session.get(Room, room_id)
    if room is None:
        return
    if room.status in (RoomStatus.CLEANING, RoomStatus.BLOCKED):
        return
    new_status = await derive_room_status(session, room_id, now)
    if room.status != new_status:
        room.status = new_status
