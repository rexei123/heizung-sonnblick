"""PMS-Hook Auto-Revoke bei Check-Out.

Sprint 9.9 T6, Sprint 12a T2/T6 (AE-58), Sprint 13 Hygiene (B-12c-AuditGap).

Wird vom Belegungs-Service nach jedem Status-Wechsel aufgerufen
(``occupancy_service.sync_room_status``). Wechselt ein Raum von
``OCCUPIED`` auf ``VACANT``, werden ALLE aktiven Overrides fuer den Raum
revokiert (``override_service.revoke_all_active_overrides`` — Sprint 12a T2
hat das von „nur device" auf „alle Quellen" erweitert, AE-58).

**Sprint 20f (T5): das Gnaden-Fenster ist entfallen.** Bis hierher
unterblieb der Widerruf, wenn innerhalb von vier Stunden ein Folgegast
erwartet wurde (``CHECKOUT_GRACE_WINDOW``). Die fachliche Regel des Hotels
ist eindeutig: **ein Override endet mit jeder Abreise, ohne Ausnahme.**

Die Begruendung des Hoteliers trifft den Kern: der Override gehoert dem
Gast, der gegangen ist. Ob der naechste in zwei oder in zwanzig Stunden
kommt, aendert daran nichts — er bekommt ein Zimmer auf den globalen
Einstellungen, nicht die Wunschtemperatur seines Vorgaengers.

Ueberlappende Buchungen bleiben unberuehrt: dort bleibt das Zimmer
``OCCUPIED``, der Statuswechsel tritt gar nicht ein, und dieser Hook wird
nicht wirksam. Das Fenster hat also nie den Fall geschuetzt, fuer den man
es vermuten wuerde.

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
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from heizung.models.enums import RoomStatus
from heizung.services import override_service
from heizung.services.business_audit_service import record_business_action

logger = logging.getLogger(__name__)

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
    """Revokes alle aktiven Overrides, wenn der Raum auf ``VACANT`` wechselt.

    Schreibt bei effektiver Revokation einen
    ``OVERRIDES_AUTO_REVOKED_ON_CHECKOUT`` BusinessAudit-Eintrag in
    derselben Transaktion (Sprint 13 Hygiene B-12c-AuditGap).

    **Sprint 20f (T5): ohne Gnaden-Fenster.** Vorher unterblieb der
    Widerruf, wenn innerhalb von vier Stunden ein Folgegast erwartet wurde.
    Jetzt endet jeder Override mit jeder Abreise — siehe Modul-Kopf.

    ``now`` bleibt in der Signatur, obwohl die Funktion den Wert nicht mehr
    selbst braucht: sie reicht ihn an ``revoke_all_active_overrides`` weiter,
    und dort ist er der Bezugspunkt fuer den ``expires_at``-Vergleich **und**
    fuer den ``revoked_at``-Stempel. Die Kette
    ``sync_active_rooms -> sync_room_status -> auto_revoke_on_checkout``
    reicht ihn seit Sprint 15g durch; wer ihn hier entfernt, laesst die
    letzte Stufe wieder auf die Wanduhr zurueckfallen (§5.59-Familie).

    Returns Anzahl der revokierten Overrides (0, wenn der Trigger nicht
    greift oder kein aktiver Override existiert). Bei Returncount 0 wird
    KEIN Audit geschrieben (Idempotenz-Pfad analog 12c).
    """
    if previous_status != RoomStatus.OCCUPIED or new_status != RoomStatus.VACANT:
        return 0

    revoked = await override_service.revoke_all_active_overrides(
        session,
        room_id,
        reason=REVOKE_REASON_CHECKOUT,
        now=now,
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
