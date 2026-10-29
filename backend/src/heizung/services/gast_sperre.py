"""Die Gast-Sperre endet mit der Abreise (Sprint 23 T4-A).

**Was vorher fehlte.** Die Uebersteuerungs-Sperre aus Sprint 12c
(``room.guest_override_blocked``) gilt dauerhaft. Sie ist dafuer gebaut,
einem Gast das Drehrad zu nehmen, der die Einstellung verstellt und sich
danach beschwert — und genau deshalb ist sie ein Fall fuer *einen
Aufenthalt*, nicht fuer immer.

Wer sie nicht zuruecknimmt, hinterlaesst dem **naechsten** Gast ein Rad,
das nichts bewirkt. Das Zimmer heizt richtig, die Drehung wird verworfen,
und niemand an der Rezeption kann die Frage „warum reagiert das nicht"
beantworten, weil die Ursache eine Entscheidung von vorletzter Woche ist.
Eine Sperre, an die sich niemand erinnert, ist nicht weniger wirksam —
nur unerklaerlich.

**Die Loesung sitzt dort, wo der Check-out schon Folgen hat.** Der
Belegungsabgleich widerruft beim Uebergang OCCUPIED -> VACANT die
Overrides (``override_pms_hook.auto_revoke_on_checkout``, Sprint 9.9 T6).
Dieselbe Kette loest jetzt die Sperre. Kein zweiter Taktgeber, kein
Ablaufdatum in der Zeile: der Check-out ist das Ereignis, und der
Abgleich ist die Stelle, die ihn sieht.

**Warum kein ``expires_at`` wie beim Override.** Ein Zeitstempel waere
eine Vorhersage: er muesste beim Verschieben der Abreise nachgezogen
werden, und wer es vergisst, hat genau das Problem zurueck, das diese
Datei loest (dieselbe Klasse wie das Gnaden-Fenster, das Sprint 20f
entfernt hat). Der Statuswechsel ist dagegen ein Befund.

**Allgemeinbereiche koennen das nicht haben.** Ein Zimmer mit nicht
buchbarem Raumtyp wechselt nie auf VACANT — ``sync_room_status`` laesst
seinen Status stehen (Sprint 24d). Eine Sperre „bis Check-out" wuerde
dort **nie** enden. Die API weist sie deshalb ab; dass dieser Dienst sie
nie zu sehen bekaeme, ist kein Ersatz fuer die Abweisung, sondern der
Grund dafuer: ein Versprechen, das niemand einloest, darf nicht
annehmbar sein.
"""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from heizung.models.enums import RoomStatus
from heizung.models.room import Room
from heizung.services.business_audit_service import record_business_action

logger = logging.getLogger(__name__)

#: Audit-Action beim automatischen Loesen. Eigene Action und nicht
#: ``ROOM_OVERRIDE_BLOCK_TOGGLED`` mit ``user_id=None``: beim Suchen nach
#: „wer hat die Sperre aufgehoben" ist „der Check-out" eine andere
#: Antwort als „niemand weiss es".
ACTION_GELOEST = "ROOM_GUEST_BLOCK_LIFTED_ON_CHECKOUT"


async def loese_bei_checkout(
    session: AsyncSession,
    room_id: int,
    previous_status: RoomStatus,
    new_status: RoomStatus,
) -> bool:
    """Loest die Sperre, wenn das Zimmer auf ``VACANT`` wechselt.

    Greift nur, wenn **alle drei** Bedingungen stimmen: der Uebergang ist
    OCCUPIED -> VACANT, die Sperre steht, und sie war als „bis Check-out"
    gesetzt. Eine dauerhaft gesetzte Sperre bleibt stehen — sie ist eine
    Entscheidung ueber das Zimmer und nicht ueber den Gast.

    Beide Felder werden zurueckgesetzt, nicht nur eines: ein stehen
    gelassenes ``guest_block_bis_checkout`` wuerde beim naechsten Setzen
    der Sperre eine Absicht vorspiegeln, die niemand geaeussert hat.

    Die Transaktion committet der Aufrufer (``sync_room_status``), wie
    ueberall in ``services/`` (Paragraph 5.61).

    Returns ``True``, wenn geloest wurde. Ohne Wirkung **kein** Audit —
    derselbe Idempotenz-Pfad wie in ``auto_revoke_on_checkout``, denn ein
    Protokoll voller Nicht-Ereignisse verdeckt die echten.
    """
    if previous_status != RoomStatus.OCCUPIED or new_status != RoomStatus.VACANT:
        return False

    room = await session.get(Room, room_id)
    if room is None:
        return False
    if not room.guest_block_bis_checkout:
        return False

    war_gesperrt = room.guest_override_blocked
    room.guest_override_blocked = False
    room.guest_block_bis_checkout = False

    await record_business_action(
        session,
        user_id=None,
        action=ACTION_GELOEST,
        target_type="room",
        target_id=room_id,
        old_value={"blocked": war_gesperrt, "bis_checkout": True},
        new_value={"blocked": False, "bis_checkout": False},
    )
    logger.info("Gast-Sperre fuer room_id=%s mit dem Check-out geloest", room_id)
    return True
