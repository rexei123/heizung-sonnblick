"""Die Gast-Sperre endet mit der Abreise (Sprint 23 T4-A / T4-A2).

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

**Nachtrag T4-A2: es gibt zwei Wege, die Sperre zu setzen, und sie tun
nicht dasselbe.** Der Knopf in der Kopfzeile beginnt die Sperre mit einem
Widerruf aller Uebersteuerungen; der Haken im Uebersteuerungs-Dialog
nicht, weil er eine Uebersteuerung gerade **anlegt**. Der Unterschied ist
kein Detail, sondern der ganze Befund des Betreibers zu #340 — er steht
im Docstring von ``setze_bis_checkout``.
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


#: Marker im Audit, wenn die Sperre **mit** einer Uebersteuerung gesetzt
#: wurde (T4-A2). Dieselbe Action wie beim Knopf in der Kopfzeile, damit
#: die Frage „wer hat gesperrt" eine Abfrage bleibt und nicht zwei; das
#: ``via`` sagt, auf welchem Weg.
VIA_UEBERSTEUERUNG = "uebersteuerung"


async def setze_bis_checkout(
    session: AsyncSession,
    *,
    room_id: int,
    user_id: int | None,
    request_ip: str | None = None,
) -> bool:
    """Setzt die Sperre „bis Check-out", **ohne** Overrides zu widerrufen.

    Das ist der Unterschied zum Knopf in der Kopfzeile
    (``PATCH /rooms/{id}/override-block-state``), und er ist der Grund,
    warum es diese Funktion gibt. Dort beginnt die Sperre mit einem
    Widerruf aller aktiven Uebersteuerungen — richtig, wenn jemand sagt
    „ab jetzt soll hier niemand mehr drehen", denn der zuletzt gedrehte
    Wert ist dann Teil des Problems.

    Hier ist es umgekehrt: die Rezeption setzt **einen bestimmten Wert**
    und sperrt ihn fest. Ein Widerruf wuerde genau die Uebersteuerung
    treffen, die gerade angelegt wurde — das Zimmer fiele auf den Plan
    zurueck, und der eingetragene Wunsch waere weg. **Genau das war der
    Befund des Betreibers zu #340:** der Weg ueber den Sperr-Knopf deckt
    diesen Fall nicht ab, er hebt ihn auf.

    **Ein Zustand, nicht zwei.** Beide Felder werden zusammen gesetzt.
    Ein ``guest_block_bis_checkout`` ohne ``guest_override_blocked`` ist
    kein Zustand, sondern eine Sperre, die endet, ohne begonnen zu haben
    (dieselbe Begruendung wie beim 422 des Knopf-Endpunkts).

    Idempotent (Paragraph S2): steht die Sperre schon in dieser Form, wird
    nichts geschrieben und **kein** Audit erzeugt — ein Protokoll voller
    Nicht-Ereignisse verdeckt die echten.

    Die Pruefung, ob das Zimmer ueberhaupt eine Abreise hat, gehoert
    **nicht** hierher, sondern vor den Schreibvorgang in die API: dort
    liegt der Satz, den der Nutzer liest. Diese Funktion setzt voraus,
    dass sie bestanden ist.

    Die Transaktion committet der Aufrufer (Paragraph 5.61).

    Returns ``True``, wenn geschrieben wurde.
    """
    room = await session.get(Room, room_id)
    if room is None:
        return False

    alt_blocked = room.guest_override_blocked
    alt_bis_checkout = room.guest_block_bis_checkout
    if alt_blocked and alt_bis_checkout:
        return False

    room.guest_override_blocked = True
    room.guest_block_bis_checkout = True

    await record_business_action(
        session,
        user_id=user_id,
        action="ROOM_OVERRIDE_BLOCK_TOGGLED",
        target_type="room",
        target_id=room_id,
        old_value={"blocked": alt_blocked, "bis_checkout": alt_bis_checkout},
        new_value={
            "blocked": True,
            "bis_checkout": True,
            # Kein ``revoked_overrides_count`` wie beim Knopf — hier wird
            # bewusst nichts widerrufen. Die fehlende Zahl ist die Aussage.
            "via": VIA_UEBERSTEUERUNG,
        },
        request_ip=request_ip,
    )
    logger.info(
        "Gast-Sperre bis Check-out fuer room_id=%s mit der Uebersteuerung gesetzt",
        room_id,
    )
    return True
