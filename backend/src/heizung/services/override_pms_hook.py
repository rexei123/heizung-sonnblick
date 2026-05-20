"""Sprint 9.9 T6 (Sprint 12a T2/T6 konsolidiert): PMS-Hook Auto-Revoke bei Check-Out.

Wird vom Belegungs-Service nach jedem Status-Wechsel aufgerufen
(``occupancy_service.sync_room_status``). Wenn ein Raum von ``OCCUPIED``
auf ``VACANT`` wechselt UND keine neue Reservation in den naechsten
4 Stunden ansteht, werden ALLE aktiven Overrides fuer den Raum revokiert
(``override_service.revoke_all_active_overrides`` — Sprint 12a T2 hat
das von „nur device" auf „alle Quellen" erweitert, AE-58).

Begruendung (AE-58): Neue Belegung startet sauber auf globalen
Einstellungen, ohne Override-Erblast aus der vorigen Belegung — weder
Gast-Drehring (DEVICE) noch Mitarbeiter-Eingaben (FRONTEND_*) tragen
ueber den Check-out hinaus.

Heute kein eigener PMS-Polling-Service: Status-Wechsel entstehen via
Occupancy-API (POST/PATCH ``/api/v1/occupancies``). Bei Einfuehrung
eines Casablanca-Polling-Jobs (Sprint 10+) genuegt es, den gleichen
Hook dort zusaetzlich aufzurufen.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from heizung.models.enums import RoomStatus
from heizung.services import override_service
from heizung.services.occupancy_service import next_active_checkin

logger = logging.getLogger(__name__)

CHECKOUT_GRACE_WINDOW = timedelta(hours=4)


async def auto_revoke_on_checkout(
    session: AsyncSession,
    room_id: int,
    previous_status: RoomStatus,
    new_status: RoomStatus,
    now: datetime,
) -> int:
    """Revokes alle aktiven ``device``-Overrides, wenn der Raum gerade
    auf ``VACANT`` wechselt und kein Folgegast innerhalb von 4 Stunden
    erwartet wird.

    Returns Anzahl der revokierten Overrides (0, wenn der Trigger nicht
    greift oder kein aktiver device-Override existiert).
    """
    if previous_status != RoomStatus.OCCUPIED or new_status != RoomStatus.VACANT:
        return 0

    has_followup = await next_active_checkin(
        session,
        room_id,
        within=CHECKOUT_GRACE_WINDOW,
        now=now,
    )
    if has_followup:
        return 0

    revoked = await override_service.revoke_all_active_overrides(
        session,
        room_id,
        reason="auto: guest checked out",
    )
    if revoked > 0:
        logger.info(
            "auto-revoked %d active overrides for room_id=%s (post-checkout)",
            revoked,
            room_id,
        )
    return revoked
