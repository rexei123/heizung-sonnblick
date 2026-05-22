"""PMS-Hook Auto-Revoke bei Check-Out.

Sprint 9.9 T6, Sprint 12a T2/T6 (AE-58), Sprint 13 Hygiene (B-12c-AuditGap).

Wird vom Belegungs-Service nach jedem Status-Wechsel aufgerufen
(``occupancy_service.sync_room_status``). Wenn ein Raum von ``OCCUPIED``
auf ``VACANT`` wechselt UND keine neue Reservation in den naechsten
4 Stunden ansteht, werden ALLE aktiven Overrides fuer den Raum revokiert
(``override_service.revoke_all_active_overrides`` — Sprint 12a T2 hat
das von „nur device" auf „alle Quellen" erweitert, AE-58).

Sprint 13 Hygiene (B-12c-AuditGap): zusaetzlich wird pro effektiver
Revokation ein BusinessAudit-Eintrag ``OVERRIDES_AUTO_REVOKED_ON_CHECKOUT``
in derselben Transaktion geschrieben. Override-IDs stehen NICHT im Audit
— Rekonstruktion via ``manual_override.revoked_reason=
'auto_revoke_on_checkout'``-Filter analog zum 12c-Pattern. ``user_id=None``
weil System-Trigger (kein API-Caller); Praezedenzfall fuer kuenftige
System-Audits.

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
from heizung.services.business_audit_service import record_business_action
from heizung.services.occupancy_service import next_active_checkin

logger = logging.getLogger(__name__)

CHECKOUT_GRACE_WINDOW = timedelta(hours=4)

# Sprint 13 Hygiene (B-12c-AuditGap): String wird sowohl als
# ``manual_override.revoked_reason`` als auch als
# ``business_audit.new_value.reason`` verwendet. Identitaet ist
# Pflicht-Voraussetzung fuer die Audit-Rekonstruktion via
# ``revoked_reason``-Filter (kein Override-ID-Tracking im Audit,
# analog 12c-Pattern fuer ``ROOM_OVERRIDE_BLOCK_TOGGLED``).
REVOKE_REASON_CHECKOUT = "auto_revoke_on_checkout"


async def auto_revoke_on_checkout(
    session: AsyncSession,
    room_id: int,
    previous_status: RoomStatus,
    new_status: RoomStatus,
    now: datetime,
) -> int:
    """Revokes alle aktiven Overrides, wenn der Raum gerade auf
    ``VACANT`` wechselt und kein Folgegast innerhalb von 4 Stunden
    erwartet wird. Schreibt bei effektiver Revokation einen
    ``OVERRIDES_AUTO_REVOKED_ON_CHECKOUT`` BusinessAudit-Eintrag in
    derselben Transaktion (Sprint 13 Hygiene B-12c-AuditGap).

    Returns Anzahl der revokierten Overrides (0, wenn der Trigger nicht
    greift oder kein aktiver Override existiert). Bei Returncount 0 wird
    KEIN Audit geschrieben (Idempotenz-Pfad analog 12c).
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
        reason=REVOKE_REASON_CHECKOUT,
    )
    if revoked > 0:
        await record_business_action(
            session,
            user_id=None,
            action="OVERRIDES_AUTO_REVOKED_ON_CHECKOUT",
            target_type="room",
            target_id=room_id,
            old_value=None,
            new_value={
                "room_id": room_id,
                "revoked_overrides_count": revoked,
                "reason": REVOKE_REASON_CHECKOUT,
            },
        )
        logger.info(
            "auto-revoked %d active overrides for room_id=%s (post-checkout)",
            revoked,
            room_id,
        )
    return revoked
