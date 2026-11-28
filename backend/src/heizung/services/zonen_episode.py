"""Eine Episode je Vorfall: ein Alarm, eine Entwarnung (27.11.2026).

**Der Anlass, Nacht vom 26. auf den 27.11.2026.** Die Zone Barbereich hat
sechs Mails erzeugt:

====== ========================================
22:40  Zonen-Melder: Zone stumm
23:00  Entwarnung
01:10  Zonen-Melder: Zone stumm
03:40  Geraet offline: 109 Panel
03:50  Geraet offline: 027 Bar
06:30  Entwarnung
====== ========================================

**Drei davon sind dieselbe Nachricht in anderer Schrift.** Die beiden
Geraete-Mails um 03:40 und 03:50 nennen genau die zwei Geraete, die in
der Zonen-Mail von 01:10 schon mit ihrem letzten Kontakt stehen -- sie
sagen nichts Neues und wecken zweimal. Und wer um 23:00 eine Entwarnung
liest, haelt den Vorgang fuer abgeschlossen; um 01:10 war er es nicht.

Was dieses Modul regelt, ist die **Episode**: der Zeitraum von „die Zone
schweigt" bis „sie meldet wieder, und zwar verlaesslich". Darin gibt es
genau eine Alarm-Mail und genau eine Entwarnung.

Warum eine Rueckkehr erst nach einer Wartezeit zaehlt
-----------------------------------------------------

Eine einzelne Meldung nach vierzig Minuten Stille beweist nichts. Faellt
die Zone zehn Minuten spaeter wieder aus, waere die Entwarnung von vorhin
**falsch gewesen** -- und niemand hat sie zurueckgenommen. Der Empfaenger
hat dann die letzte Nachricht „alles in Ordnung" im Postfach, waehrend die
Zone kalt ist. Das ist schlimmer als keine Entwarnung (Paragraph 5.79).

Deshalb wird die Entwarnung **zurueckgehalten**, bis die Rueckkehr
``relais_zone_rueckkehr_stabil_min`` Minuten gehalten hat (Vorgabe 30,
also drei Meldungen im Zehn-Minuten-Takt). Schweigt die Zone in dieser
Zeit erneut, laeuft dieselbe Episode weiter: keine zweite Alarm-Mail,
keine Entwarnung, kein Hin und Her.

**Die Wartezeit verzoegert die Entwarnung, nie den Alarm.** Der Alarm geht
unverzueglich hinaus -- er ist die Nachricht, auf die jemand handeln muss.

Warum der Zustand im Audit steht und nicht in Redis
---------------------------------------------------

``business_audit`` fuehrt den Verlauf ohnehin, und zwar dauerhaft: nach
einem Neustart ist er noch da, und er ist nachlesbar (Paragraph 0 S3).
Ein Redis-Schluessel waere schneller und wuerde beim ersten Neustart eine
Episode doppelt melden. Die Kosten sind eine Abfrage je Zone und Lauf,
alle fuenf Minuten -- das ist nichts gegen eine Mail zuviel um drei Uhr
nachts.

Die vier Tokens
---------------

====================== ===================================================
``RELAIS_ZONE_STUMM``  Alarm **versandt**. Beginn der Episode, oder eine
                       Wiederholung nach ``relais_zone_wiederholung_h``.
``..._STUMM_ERNEUT``   Die Zone schweigt wieder, bevor die Rueckkehr
                       stabil war. **Keine Mail.** Eigenes Token, damit
                       die Wiederholungsbremse weiter am letzten
                       *versandten* Alarm haengt und nicht bei jedem
                       Flackern neu beginnt.
``..._RUECKKEHR``      Die Zone meldet wieder, die Entwarnung steht aus.
                       **Keine Mail.**
``..._STUMM_ENDE``     Entwarnung **versandt**. Episode geschlossen.
====================== ===================================================

``business_audit.action`` ist ``String(64)``; der laengste Token hat 27
Zeichen. Kein CHECK, keine Migration (Paragraph 5.45 war der Fall, in dem
genau das nicht galt).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from heizung.models.business_audit import BusinessAudit

#: Alarm versandt (Beginn oder Wiederholung).
AKTION_STUMM = "RELAIS_ZONE_STUMM"
#: Wieder stumm, ohne Mail -- die Rueckkehr war nicht stabil.
AKTION_STUMM_ERNEUT = "RELAIS_ZONE_STUMM_ERNEUT"
#: Meldet wieder, Entwarnung steht aus. Ohne Mail.
AKTION_RUECKKEHR = "RELAIS_ZONE_RUECKKEHR"
#: Entwarnung versandt, Episode geschlossen.
AKTION_ENDE = "RELAIS_ZONE_STUMM_ENDE"

#: Zustaende, in denen eine Episode laeuft.
OFFEN: tuple[str, ...] = (AKTION_STUMM, AKTION_STUMM_ERNEUT, AKTION_RUECKKEHR)
#: Alle Tokens dieser Zustandsmaschine, in der Reihenfolge der Abfrage.
ALLE: tuple[str, ...] = (*OFFEN, AKTION_ENDE)

#: Was ein Lauf mit einer Zone tun soll.
Schritt = Literal[
    "alarm",
    "wiederholung",
    "erneut_stumm",
    "gebremst",
    "rueckkehr_vermerken",
    "entwarnung",
    "warten",
    "nichts",
]

#: Die Schritte, die eine Zeile ins Audit schreiben, und mit welchem Token.
TOKEN_JE_SCHRITT: dict[str, str] = {
    "alarm": AKTION_STUMM,
    "wiederholung": AKTION_STUMM,
    "erneut_stumm": AKTION_STUMM_ERNEUT,
    "rueckkehr_vermerken": AKTION_RUECKKEHR,
    "entwarnung": AKTION_ENDE,
}

#: Die Schritte, bei denen eine Mail hinausgeht.
MIT_MAIL: frozenset[str] = frozenset({"alarm", "wiederholung", "entwarnung"})


@dataclass(frozen=True, slots=True)
class Stand:
    """Der Zustand einer Zone, wie das Audit ihn hergibt.

    ``letzter_alarm`` ist bewusst getrennt von ``seit``: die
    Wiederholungsbremse haengt am letzten **versandten** Alarm, der
    Zustandswechsel am letzten Eintrag ueberhaupt. Faellt beides
    zusammen, ist es derselbe Zeitpunkt -- und bei einem flackernden Link
    eben nicht.
    """

    aktion: str | None = None
    seit: datetime | None = None
    letzter_alarm: datetime | None = None

    @property
    def episode_offen(self) -> bool:
        return self.aktion in OFFEN


def naechster_schritt(
    stand: Stand,
    *,
    stumm: bool,
    jetzt: datetime,
    wiederholung_h: int,
    stabil_min: int,
) -> Schritt:
    """Was mit dieser Zone zu tun ist -- eine reine Funktion.

    Keine Datenbank, keine Uhr, kein Versand: alles Beobachtete kommt als
    Argument. Das ist der Grund, warum der Ablauf der Nacht vom
    26./27.11.2026 Zeile fuer Zeile nachgespielt werden kann, ohne eine
    Zone zu bauen (Paragraph 5.14 ist die Schwesterlehre: die Naht, an der
    man ohne Ereignis-Schleife pruefen kann).

    :param stumm: Urteil dieses Laufs ueber die Zone.
    :param wiederholung_h: Abstand, nach dem eine laufende Episode erneut
        gemeldet wird.
    :param stabil_min: Wie lange eine Rueckkehr halten muss, bevor die
        Entwarnung hinausgeht.
    """
    if stumm:
        if not stand.episode_offen:
            return "alarm"
        if stand.aktion == AKTION_RUECKKEHR:
            # Die Rueckkehr war nicht stabil. Dieselbe Episode laeuft
            # weiter -- und zwar ohne Mail, denn der Alarm von vorhin ist
            # noch gueltig und wurde nie entwarnt.
            return "erneut_stumm"
        if stand.letzter_alarm is None:
            # Kein versandter Alarm in der Historie, aber eine offene
            # Episode: das ist kein Zustand, den diese Maschine erzeugt.
            # Dann lieber melden als schweigen (dieselbe Richtung wie
            # ``_ist_pool``: ein fehlender Wert darf keinen Melder
            # abschalten).
            return "wiederholung"
        if jetzt - stand.letzter_alarm < timedelta(hours=wiederholung_h):
            return "gebremst"
        return "wiederholung"

    if not stand.episode_offen:
        return "nichts"
    if stand.aktion in (AKTION_STUMM, AKTION_STUMM_ERNEUT):
        return "rueckkehr_vermerken"
    # AKTION_RUECKKEHR: die Wartezeit laeuft.
    if stand.seit is not None and jetzt - stand.seit >= timedelta(minutes=stabil_min):
        return "entwarnung"
    return "warten"


async def lies_stand(session: AsyncSession, *, zone_id: int) -> Stand:
    """Der juengste Eintrag und der juengste **versandte** Alarm.

    Zwei Zeilen aus derselben Abfrage: die Reihenfolge ist absteigend
    nach ``ts``, der erste Treffer ist der Zustand, und der erste
    ``RELAIS_ZONE_STUMM`` darin ist der Anker der Bremse. Mehr als die
    jungen Zeilen braucht es nicht -- ``LIMIT`` bleibt deshalb klein.
    """
    stmt = (
        select(BusinessAudit.action, BusinessAudit.ts)
        .where(
            BusinessAudit.action.in_(ALLE),
            BusinessAudit.target_type == "heating_zone",
            BusinessAudit.target_id == zone_id,
        )
        .order_by(BusinessAudit.ts.desc(), BusinessAudit.id.desc())
        .limit(50)
    )
    zeilen = (await session.execute(stmt)).all()
    if not zeilen:
        return Stand()

    aktion, seit = zeilen[0]
    letzter_alarm = next((ts for a, ts in zeilen if a == AKTION_STUMM), None)
    return Stand(aktion=aktion, seit=seit, letzter_alarm=letzter_alarm)


async def offene_zonen(session: AsyncSession) -> frozenset[int]:
    """Die Zonen, deren Episode gerade laeuft.

    Eine Abfrage fuer alle Zonen, nicht eine je Zone: der Aufrufer ist
    der Health-Beat, und der hat 109 Geraete in der Hand. ``DISTINCT ON``
    liefert je Zone die jungste Zeile; welche Tokens „offen" heissen,
    entscheidet danach Python -- das haelt die Bedeutung an **einer**
    Stelle (Paragraph 5.53).
    """
    stmt = (
        select(BusinessAudit.target_id, BusinessAudit.action)
        .distinct(BusinessAudit.target_id)
        .where(
            BusinessAudit.action.in_(ALLE),
            BusinessAudit.target_type == "heating_zone",
            BusinessAudit.target_id.is_not(None),
        )
        .order_by(BusinessAudit.target_id, BusinessAudit.ts.desc(), BusinessAudit.id.desc())
    )
    zeilen = (await session.execute(stmt)).all()
    return frozenset(
        zone_id for zone_id, aktion in zeilen if zone_id is not None and aktion in OFFEN
    )
