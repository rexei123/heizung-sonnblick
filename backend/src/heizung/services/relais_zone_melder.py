"""Meldung, wenn eine Relais-Zone schweigt (13.11.2026, erweitert 14.11.).

**Der Anlass, 12./13.11.2026.** Fuehler 056 (Zone Eingang, Rezeption) hat
von 14:41 bis 04:44 **keine einzige** Meldung geschickt — vierzehn
Stunden, 83 verlorene Frames. Die Zone hat in dieser Zeit ein Relais
gefuehrt, das in Betrieb ist.

**Die Steuerung hat richtig gehandelt und niemand hat es erfahren.** Der
Zweipunktregler kennt den Zwangs-AUS: fehlender Istwert schaltet ab und
bricht dafuer sogar die Mindestlaufzeit (``rules/zweipunkt.py``, S5). Im
Protokoll stand in jedem Durchlauf

    {'zone_id': 299, 'soll': '17.0', 'ist': None,
     'regler': 'unveraendert', 'regler_grund': 'kein_istwert'}

Das Panel blieb aus, und das war richtig. Gemeldet wurde es nicht:

* Die Health-Stufe ``silent`` verlangt **mehr als 24 Stunden** offline
  (AE-53). Vierzehn Stunden sind Stufe 1 — ``degraded``, und die ist
  ausdruecklich stumm.
* Der hausweite Totalausfall-Waechter hat korrekt geschwiegen: 103
  Geraete waren online, 605 Messwerte je Stunde.
* Sichtbar war genau eine Zahl: die Kachel „Geraete online" stand auf
  102 von 103. Dass damit die Rezeption blind ist, liest dort niemand
  heraus.

Das ist Paragraph 5.76 woertlich: die **Wirkung** war beherrscht, die
**Mitteilung** fehlte vollstaendig.

Warum nur Zonen mit einem Relais in Betrieb
-------------------------------------------

Ein stummer Fuehler ist ueberall ein Mangel. In einer Zone mit Vickis
regelt jedes Geraet aber zusaetzlich nach seinem **eigenen** internen
Fuehler weiter — der Raum wird nicht kalt, nur ungenau. Ein Relais hat
keinen eigenen Fuehler: faellt der Zonen-Fuehler aus, **heizt die Zone
gar nicht mehr**. Das ist ein anderer Vorgang, und nur er rechtfertigt
eine Mail.

„In Betrieb" wird dabei nicht hier entschieden, sondern mit
``relay_service.darf_schalten`` — derselbe Posten, den Waechter und
Regler fragen. Eine zweite Bedingung mit denselben vier Pruefungen waere
beim ersten Nachjustieren falsch (Paragraph 5.53). Insbesondere faellt
ein Relais mit stehender Schutz-Sperre damit heraus: es kann ohnehin
nicht schalten, der stumme Fuehler aendert daran nichts.

Warum 30 Minuten und nicht die Grenze des Reglers
-------------------------------------------------

Der Regler haelt einen Messwert bis zum **2,5-fachen** des
Keepalive-Fensters fuer brauchbar, mit der Vorgabe
``health_healthy_max_age_h = 2`` also fuenf Stunden. Diese Meldung
schlaegt bei **30 Minuten** an, also drei verpasste Meldungen bei
Zehn-Minuten-Takt.

**Zwei Grenzen fuer zwei Zwecke, und das ist kein Widerspruch.** Die
Grenze des Reglers entscheidet, wann er abschaltet — sie darf nicht
nervoes sein, ein einzelner verlorener Uplink soll keine Zone
stilllegen. Diese Grenze entscheidet, wann jemand hinsieht, und
entscheidet sonst **nichts**. Wer frueher warnt, hat vier Stunden
Vorlauf, bevor die Zone wirklich abschaltet.

Der Validator in den Settings haelt die Reihenfolge fest: die
Warn-Grenze muss **unter** dem Frischefenster des Reglers liegen. Sonst
kaeme die Warnung nach dem Abschalten, und das waere eine Meldung ueber
etwas, das schon passiert ist.

Warum eine Zone ohne Fuehler mitgemeldet wird
---------------------------------------------

Ein in Betrieb genommenes Relais in einer Zone **ohne** Fuehler kann
nie heizen — der Regler meldet dort dauerhaft ``kein_istwert``. Ein
Waechter, der genau in diesem Fall schweigt, weil es keinen Fuehler
gibt, dessen Stille er messen koennte, waere der naechste Melder, der
dann nichts sagt, wenn es am meisten zaehlt (Paragraph 5.79). Der Fall
bekommt deshalb einen **eigenen Grund** und einen eigenen Satz in der
Mail, nicht dieselbe Formulierung mit einer fehlenden Zahl.

Nachtrag 14.11.2026: das Relais selbst wird mitgemessen
------------------------------------------------------

Die erste Fassung hat nur den **Fuehler** beobachtet. Ein Relais, das
schweigt, blieb ungemeldet — und das ist die andere Haelfte derselben
Zone.

**Warum es zaehlt.** Hoert die Zustandsmeldung des Relais auf, weiss
niemand mehr, ob das Panel heizt. Der Waechter faellt dann auf die
Zustandsabfrage zurueck (14.11.2026, Haltbarkeitsdatum des Zustands) und
fragt alle 25 Minuten nach; mehr kann er nicht tun. Bleibt die Antwort
aus, ist der Zustand auf Dauer unbekannt — ein Panel, von dem wir nicht
wissen, ob es an ist, und **das** ist der Fall, fuer den dieses Haus
einen Waechter hat.

**Eine Meldung, nicht zwei.** Beide Geraetearten gehoeren derselben
Zone, und die Folge ist dieselbe: die Zone wird nicht verlaesslich
geregelt. Zwei Melder haetten zwei Episoden, zwei Mails und zwei
Kacheln fuer einen Vorgang — und beim ersten gleichzeitigen Ausfall
beide gleichzeitig (Paragraph 5.79: wer zwei Mails fuer eine Sache
bekommt, liest bald keine mehr). Der Text nennt deshalb, **wer**
schweigt, und nicht zwei Mails sagen es getrennt.

**Dieselbe Grenze fuer beide**, 30 Minuten. Die Meldeintervalle sind
verschieden (Vicki eine Stunde Keepalive, Relais zehn Minuten), die
Frage ist dieselbe: hat sich das Geraet in der letzten halben Stunde
gemeldet. Eine zweite Grenze waere eine zweite Einstellung mit derselben
Begruendung (Paragraph 5.53) — und beim Relais ist 30 Minuten ohnehin
strenger als beim Fuehler, weil es oefter melden soll.

**Gezaehlt wird auch hier „gehoert", nicht „geschaltet".** Jede Zeile in
``relay_reading`` ist ein Lebenszeichen, auch eine ohne Schaltzustand.
Die Frage „was gilt am Relais" ist eine andere und steht im Waechter.

Was dieses Modul nicht tut
--------------------------

* **Kein Eingriff in die Steuerung.** Rein lesend. Der sichere Zustand
  ist gebaut und bleibt unberuehrt; hier entsteht ausschliesslich eine
  Mitteilung.
* **Keine eigene Veraltungs-Regel fuer den Regler.** Die Grenze hier
  gilt fuer die Meldung, nie fuer eine Schaltentscheidung.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from heizung.models.device import Device
from heizung.models.enums import DeviceKind
from heizung.models.heating_zone import HeatingZone
from heizung.models.relay_reading import RelayReading
from heizung.models.room import Room
from heizung.models.sensor_reading import SensorReading
from heizung.services import relay_service
from heizung.services.device_service import get_active_devices_for_zone

logger = logging.getLogger(__name__)

Grund = Literal["stumm", "kein_fuehler", "relais_stumm"]

#: Die beiden Gruende. snake_case-Marken wie die ``detail``-Token der
#: Engine-Schichten (Paragraph 5.23).
#:
#: **Mit Typ, nicht nur als Zeichenkette.** Ohne die Annotation sind sie
#: fuer mypy ein ``str``, und dann nimmt ``ZonenBefund.grund`` jeden
#: Tippfehler an — eine Marke, die nirgends vorkommt, waere ein Befund,
#: den niemand bemerkt.
GRUND_STUMM: Grund = "stumm"
GRUND_KEIN_FUEHLER: Grund = "kein_fuehler"
GRUND_RELAIS_STUMM: Grund = "relais_stumm"


@dataclass(frozen=True, slots=True)
class ZonenBefund:
    """Eine Zone mit Relais in Betrieb und ihr Fuehler-Stand."""

    zone_id: int
    zone_name: str
    #: Zimmernummer bzw. Bereichsname, fuer die Mail. ``None``, wenn die
    #: Zone an keinem Zimmer haengt (dann steht nur der Zonenname da).
    ort: str | None
    #: Etiketten der Fuehler dieser Zone, aufsteigend. Leer heisst: es
    #: gibt keinen.
    fuehler: tuple[str, ...]
    #: Zeitpunkt der **juengsten** Meldung irgendeines Fuehlers der Zone.
    #:
    #: Gezaehlt wird „gehoert", nicht „gemessen" — eine Zeile ohne
    #: Temperatur ist trotzdem ein Lebenszeichen. Das ist dieselbe Lesart,
    #: die ``relay_tasks._ist_und_veraltung`` fuer die Frische benutzt, und
    #: es ist die, nach der der Betreiber gefragt hat („ohne Meldung").
    letzte_meldung: datetime | None
    #: Alter der juengsten Meldung in Minuten, abgerundet.
    alter_min: int | None
    #: Etiketten der Relais dieser Zone, die schalten duerfen —
    #: aufsteigend. Steht in der Mail, damit „die Zone heizt nicht"
    #: belegt ist und nicht behauptet.
    #:
    #: **Etiketten statt einer Zahl** (14.11.2026). Vorher stand hier
    #: ``relais_in_betrieb: int``. Sobald der Text sagen soll, **wer**
    #: schweigt, braucht er die Namen — und eine Zahl **daneben** waere
    #: eine zweite Wahrheit, die beim ersten Fehlgriff nicht mehr zur
    #: Liste passt (Paragraph 5.53). Die Zahl ist jetzt eine
    #: Eigenschaft.
    relais: tuple[str, ...]
    #: Zeitpunkt der juengsten Meldung irgendeines dieser Relais.
    relais_letzte_meldung: datetime | None
    #: Alter dieser Meldung in Minuten, abgerundet.
    relais_alter_min: int | None
    #: Ob die Relais dieser Zone ueber der Grenze schweigen. **Eigenes
    #: Feld, kein Grund**: es kann gleichzeitig mit einem stummen Fuehler
    #: auftreten, und dann muss die Mail beides nennen. Ein Grund kann
    #: nur einen Fall tragen.
    relais_stumm: bool
    #: ``None`` heisst in Ordnung. Das Urteil wird in ``beurteile``
    #: gefaellt und **mitgefuehrt**, nicht in einer Eigenschaft
    #: nachgerechnet: die Grenze kommt aus den Settings, und ein Befund,
    #: der sie noch braucht, waere ohne sie nicht lesbar.
    grund: Grund | None

    @property
    def relais_in_betrieb(self) -> int:
        """Wie viele Relais dieser Zone schalten duerfen."""
        return len(self.relais)

    @property
    def stumm(self) -> bool:
        """Ob diese Zone gemeldet werden muss."""
        return self.grund is not None

    @property
    def schweigende_geraete(self) -> tuple[str, ...]:
        """Die Etiketten, die in der Mail stehen muessen.

        Fuehler zuerst, Relais danach — in der Reihenfolge der Folge: ohne
        Fuehlerwert heizt die Zone nicht, ohne Relais-Meldung ist ihr
        Zustand unbekannt.
        """
        namen: list[str] = []
        if self.grund == GRUND_STUMM:
            namen.extend(self.fuehler)
        if self.relais_stumm:
            namen.extend(self.relais)
        return tuple(namen)


def _alter_min(letzte_meldung: datetime | None, now: datetime) -> int | None:
    """Alter in ganzen Minuten, nie negativ. ``None`` ohne Meldung."""
    if letzte_meldung is None:
        return None
    return max(0, int((now - letzte_meldung).total_seconds() // 60))


def _ist_stumm(letzte_meldung: datetime | None, now: datetime, grenze_min: int) -> bool:
    """Nie gehoert zaehlt wie stumm; die Grenze ist inklusiv.

    „Seit mehr als 30 Minuten" meldet bei 30:00 noch nicht und bei 30:01
    schon. Die Funktion gilt fuer **beide** Geraetearten — eine zweite
    Rechnung fuer dieselbe Frage waere die Stelle, an der sich die zwei
    Seiten der Zone spaeter unterschiedlich verhalten (Paragraph 5.53).
    """
    if letzte_meldung is None:
        return True
    return now - letzte_meldung > timedelta(minutes=grenze_min)


def beurteile(  # noqa: PLR0913 — jedes Argument ist eine eigene Beobachtung
    *,
    zone_id: int,
    zone_name: str,
    ort: str | None,
    fuehler: tuple[str, ...],
    letzte_meldung: datetime | None,
    relais: tuple[str, ...],
    relais_letzte_meldung: datetime | None,
    now: datetime,
    grenze_min: int,
) -> ZonenBefund:
    """Urteil fuer **eine** Zone — ohne Datenbank, ohne Wanduhr.

    Reihenfolge verbindlich:

    1. **Kein Fuehler** schlaegt alles. Ohne Fuehler gibt es keine
       Stille, die man messen koennte, und der Mangel ist der schwerere.
    2. **Fuehler stumm** schlaegt ein stummes Relais. Ohne Fuehlerwert
       heizt die Zone nicht — das ist die haertere Folge als ein
       Zustand, den wir nicht kennen. „Nie gehoert" zaehlt wie stumm:
       ein Fuehler, der noch nie gemeldet hat, ist fuer die Zone genau so
       wertlos wie einer, der aufgehoert hat.
    3. **Relais stumm** (14.11.2026), wenn der Fuehler in Ordnung ist.
       Dann ist der Sollwert da, der Istwert da — und niemand weiss, ob
       das Panel schaltet.

    **``relais_stumm`` wird in jedem Fall mitgefuehrt**, auch wenn schon
    der Fuehler den Grund stellt. Sonst koennte die Mail nicht beides
    nennen, und bei einem Ausfall, der beide Geraete trifft (Gateway,
    Netz), waere genau die Haelfte unsichtbar, die man zur Diagnose
    braucht.
    """
    relais_schweigt = bool(relais) and _ist_stumm(relais_letzte_meldung, now, grenze_min)

    if not fuehler:
        grund: Grund | None = GRUND_KEIN_FUEHLER
    elif _ist_stumm(letzte_meldung, now, grenze_min):
        grund = GRUND_STUMM
    elif relais_schweigt:
        grund = GRUND_RELAIS_STUMM
    else:
        grund = None

    return ZonenBefund(
        zone_id=zone_id,
        zone_name=zone_name,
        ort=ort,
        fuehler=fuehler,
        # Ohne Fuehler gibt es keine Meldung, die man datieren koennte —
        # und eine Zahl, die aus einer leeren Menge stammt, waere eine
        # Behauptung ueber eine Meldung, die es nicht gibt.
        letzte_meldung=letzte_meldung if fuehler else None,
        alter_min=_alter_min(letzte_meldung, now) if fuehler else None,
        relais=relais,
        relais_letzte_meldung=relais_letzte_meldung,
        relais_alter_min=_alter_min(relais_letzte_meldung, now),
        relais_stumm=relais_schweigt,
        grund=grund,
    )


async def lies_relais_zonen(
    session: AsyncSession,
    *,
    grenze_min: int,
    now: datetime | None = None,
) -> list[ZonenBefund]:
    """Alle Zonen mit mindestens einem Relais in Betrieb, mit Urteil.

    Zwei Abfragen vorweg (die Relais, die Zonen samt Ort) und drei je
    Zone (Geraete, juengste Fuehlermeldung, juengste Relaismeldung). Die
    Kachel haengt an jedem Seitenaufruf des Dashboards (Paragraph 5.73 —
    read-time abgeleitet, aber **gehoben**, nicht je Zeile).

    **Drei je Zone und nicht eine**, und das bleibt vertretbar: die Zahl
    der Zonen mit einem Relais in Betrieb ist durch die Hardware
    begrenzt — heute zwei. Die Begruendung steht unten an der Schleife.
    """
    jetzt = now or datetime.now(tz=UTC)

    # 1. Die Relais, die schalten duerfen. Der Lifecycle-Filter steckt in
    #    ``darf_schalten``; hier wird nur vorgefiltert, was ueberhaupt in
    #    einer Zone haengt (Paragraph 5.58).
    relais = (
        (
            await session.execute(
                select(Device).where(
                    Device.kind == DeviceKind.RELAY,
                    Device.heating_zone_id.is_not(None),
                    Device.retired_at.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )
    # Je Zone: die Relais, die schalten duerfen — mit Etikett und Id.
    # **Kein Etikett heisst nicht „kein Relais"**, dieselbe Falle wie
    # unten beim Fuehler: der Platzhalter haelt die Liste vollstaendig.
    je_zone: dict[int, list[tuple[str, int]]] = {}
    for geraet in relais:
        if not relay_service.darf_schalten(geraet):
            continue
        assert geraet.heating_zone_id is not None  # vom WHERE oben
        je_zone.setdefault(geraet.heating_zone_id, []).append(
            (geraet.label or "ohne Etikett", geraet.id)
        )

    if not je_zone:
        return []

    # 2. Zone samt Ort.
    zeilen = (
        await session.execute(
            select(HeatingZone.id, HeatingZone.name, Room.number)
            .join(Room, Room.id == HeatingZone.room_id, isouter=True)
            .where(HeatingZone.id.in_(je_zone.keys()))
        )
    ).all()

    # 3. Je Zone: ihre Geraete und die juengste Meldung ihrer Fuehler.
    #
    # **Zwei Abfragen je Zone, und das ist hier vertretbar.** Die Zahl
    # der Zonen mit einem Relais in Betrieb ist durch die Hardware
    # begrenzt — heute zwei, auf Sicht eine Handvoll. Die Alternative
    # waere eine Abfrage mit Fensterfunktion ueber alle Geraete des
    # Hauses; sie waere eine Abfrage und laese bei hundert Vickis mehr
    # Zeilen als diese Schleife bei zehn Zonen. Wird die Liste laenger,
    # ist das der Punkt, an dem man es dreht.
    befunde: list[ZonenBefund] = []
    for zone_id, zone_name, ort in zeilen:
        geraete = await get_active_devices_for_zone(session, zone_id)
        # **Kein Etikett heisst nicht „kein Fuehler".** Ein Geraet ohne
        # Etikett regelt die Zone trotzdem mit; es darf die Liste also
        # nicht verkuerzen, sonst meldet der Waechter
        # ``kein_fuehler`` fuer eine Zone, die einen hat. Deshalb ein
        # Platzhalter statt eines Filters — die Laenge der Liste **ist**
        # die Zahl der Fuehler.
        fuehler = [d for d in geraete if d.kind != DeviceKind.RELAY]
        etiketten = tuple(sorted(d.label or "ohne Etikett" for d in fuehler))
        ids = [d.id for d in fuehler]

        letzte: datetime | None = None
        if ids:
            letzte = (
                await session.execute(
                    select(func.max(SensorReading.time)).where(SensorReading.device_id.in_(ids))
                )
            ).scalar_one_or_none()

        # Die Relais-Seite (14.11.2026). **Ohne Filter auf ``relay_on``**:
        # gefragt ist, ob sich das Geraet gemeldet hat, nicht was es
        # gemeldet hat. Eine Zeile ohne Schaltzustand — etwa eine reine
        # Befehlsantwort — ist trotzdem ein Lebenszeichen. Die Frage
        # „welcher Zustand gilt" steht im Waechter und filtert dort
        # sehr wohl.
        relais_etiketten = tuple(sorted(etikett for etikett, _ in je_zone[zone_id]))
        relais_ids = [geraet_id for _, geraet_id in je_zone[zone_id]]
        relais_letzte = (
            await session.execute(
                select(func.max(RelayReading.time)).where(RelayReading.device_id.in_(relais_ids))
            )
        ).scalar_one_or_none()

        befunde.append(
            beurteile(
                zone_id=zone_id,
                zone_name=zone_name,
                ort=ort,
                fuehler=etiketten,
                letzte_meldung=letzte,
                relais=relais_etiketten,
                relais_letzte_meldung=relais_letzte,
                now=jetzt,
                grenze_min=grenze_min,
            )
        )

    befunde.sort(key=lambda b: b.zone_id)
    return befunde


# ---------------------------------------------------------------------------
# Mail-Texte
# ---------------------------------------------------------------------------


def _ortsname(befund: ZonenBefund) -> str:
    return f"{befund.ort} / {befund.zone_name}" if befund.ort else befund.zone_name


def _liste(namen: tuple[str, ...]) -> str:
    return ", ".join(namen) if namen else "-"


def betreff_alarm(befund: ZonenBefund) -> str:
    """Die Betreffzeile nennt den Vorgang und das juengste Alter.

    **Sie nennt ab dem 14.11.2026 auch die Geraeteart**, weil es jetzt
    zwei gibt. "Ohne Meldung seit 40 Minuten" allein liesse offen, ob
    der Hausmeister zum Fuehler oder zum Panel gehen muss - und genau das
    ist die Frage, die eine Mail nachts beantworten soll.
    """
    ort = _ortsname(befund)
    if befund.grund == GRUND_KEIN_FUEHLER:
        return f"Heizung Sonnblick: {ort} hat kein Thermostat zugeordnet"
    if befund.grund == GRUND_RELAIS_STUMM:
        return (
            f"Heizung Sonnblick: Relais in {ort} ohne Meldung seit "
            f"{befund.relais_alter_min} Minuten"
        )
    if befund.relais_stumm:
        return (
            f"Heizung Sonnblick: {ort} ohne Meldung seit {befund.alter_min} "
            f"Minuten (Fuehler und Relais)"
        )
    return f"Heizung Sonnblick: {ort} ohne Fuehlerwert seit {befund.alter_min} Minuten"


def betreff_entwarnung(befund: ZonenBefund) -> str:
    return f"Heizung Sonnblick: {_ortsname(befund)} meldet wieder"


def _zeit(wann: datetime | None, *, zeitzone: str) -> str:
    if wann is None:
        return "noch nie"
    return wann.astimezone(ZoneInfo(zeitzone)).strftime("%d.%m.%Y %H:%M")


def _relais_block(befund: ZonenBefund, *, zeitzone: str) -> str:
    """Der Zusatz, wenn auch das Relais schweigt (14.11.2026).

    Er steht **unter** dem Fuehler-Stand und nicht in einer eigenen
    Mail: es ist eine Zone, ein Vorgang, eine Episode. Faellt beides
    zugleich aus - Gateway, Netz, Strom -, steht hier die Haelfte, die
    den Unterschied zwischen "ein Geraet" und "die Verbindung" macht.
    """
    if not befund.relais_stumm:
        return ""
    return (
        f"\nAUCH DAS RELAIS SCHWEIGT\n"
        f"Relais: {_liste(befund.relais)}\n"
        f"Letzte Meldung: {_zeit(befund.relais_letzte_meldung, zeitzone=zeitzone)}"
        f" (vor {befund.relais_alter_min} Minuten)\n"
        f"Damit ist auch der Schaltzustand unbekannt. Die Steuerung fragt "
        f"ihn von selbst nach und schaltet bis zur Antwort nicht ein.\n\n"
        f"Dass **beide** Geraete der Zone gleichzeitig schweigen, spricht "
        f"eher fuer den Weg als fuer die Geraete: Gateway, Netz oder "
        f"Strom. RUNBOOK Paragraph 10ay nennt die Pruefung am Gateway.\n"
    )


def nachricht_alarm(befund: ZonenBefund, *, zeitzone: str) -> str:
    """Die Folge zuerst, die Zahlen danach.

    Der erste Satz muss sagen, was es bedeutet, nicht welches Geraet
    schweigt. Wer die Mail nachts liest, braucht die Folge, nicht die
    Diagnose.

    **Und die Folge ist nicht bei beiden Geraetearten dieselbe**
    (14.11.2026). Ohne Fuehlerwert heizt die Zone **nicht** - das ist
    gebaut und beabsichtigt. Schweigt nur das Relais, ist der Sollwert da
    und der Istwert da, und unbekannt ist allein, ob das Panel schaltet.
    Beides in einen Satz zu fassen hiesse, einen der beiden Faelle falsch
    zu beschreiben.
    """
    ort = _ortsname(befund)

    if befund.grund == GRUND_RELAIS_STUMM:
        return (
            f"Das Relais in {ort} meldet sich nicht mehr.\n\n"
            f"Der Fuehler dieser Zone liefert Werte, die Steuerung regelt "
            f"also weiter. Unbekannt ist der **Schaltzustand**: ob das "
            f"Panel gerade heizt, sagt uns niemand mehr.\n\n"
            f"DER STAND\n"
            f"Relais: {_liste(befund.relais)}\n"
            f"Letzte Meldung: {_zeit(befund.relais_letzte_meldung, zeitzone=zeitzone)}"
            f" (vor {befund.relais_alter_min} Minuten)\n"
            f"Fuehler: {_liste(befund.fuehler)} - meldet "
            f"({_zeit(befund.letzte_meldung, zeitzone=zeitzone)})\n\n"
            f"WAS DIE STEUERUNG TUT\n"
            f"Sie fragt den Zustand von selbst nach und schaltet bis zur "
            f"Antwort **nicht ein**. Ein Panel, das vor dem Ausfall "
            f"eingeschaltet war, geht von selbst aus - eingeschaltet wird "
            f"immer nur mit Zeitbegrenzung.\n\n"
            f"WAS ZU TUN IST - in dieser Reihenfolge\n"
            f"1. Hat das Panel Strom? Ein ausgestecktes oder "
            f"abgeschaltetes Relais ist der haeufigste Fall und von hier "
            f"nicht von einem Funkproblem zu unterscheiden.\n"
            f"2. Kommen hausweit Meldungen an? Wenn nein, ist es nicht "
            f"dieses Relais.\n"
            f"3. Der Handschalter am Gehaeuse: steht er auf AUS, schaltet "
            f"die Steuerung ins Leere.\n"
        )

    kopf = (
        f"{ort} wird gerade nicht geheizt.\n\n"
        f"Das Relais dieser Zone ({befund.relais_in_betrieb} in Betrieb) "
        f"hat keinen eigenen Fuehler. Ohne aktuellen Zonenwert schaltet "
        f"die Steuerung bewusst AUS - das ist der sichere Zustand und "
        f"kein Fehler, aber die Zone bleibt damit kalt, solange der Wert "
        f"fehlt.\n\n"
    )

    if befund.grund == GRUND_KEIN_FUEHLER:
        return (
            kopf + "DER GRUND\n"
            "Dieser Zone ist **kein Thermostat** zugeordnet. Das ist "
            "keine Funkstoerung, sondern eine fehlende Zuordnung - und "
            "sie laesst sich nicht aussitzen: ohne Fuehler heizt die "
            "Zone nie.\n\n"
            "WAS ZU TUN IST\n"
            "Ein Thermostat dieser Zone zuordnen (Seite Zimmer, "
            "Abschnitt Heizzonen). Bis dahin bleibt das Relais aus.\n"
            + _relais_block(befund, zeitzone=zeitzone)
        )

    return (
        kopf + f"DER STAND\n"
        f"Fuehler: {_liste(befund.fuehler)}\n"
        f"Letzte Meldung: {_zeit(befund.letzte_meldung, zeitzone=zeitzone)}"
        f" (vor {befund.alter_min} Minuten)\n\n"
        f"WAS ZU TUN IST - in dieser Reihenfolge\n"
        f"1. Kommen hausweit Meldungen an? Wenn nein, ist es nicht dieser "
        f"Fuehler, und die Totalausfall-Mail sagt mehr. RUNBOOK "
        f"Paragraph 5.0a nennt den Befehl.\n"
        f"2. Steht der Fuehler noch da, wo er hingehoert, und ist nichts "
        f"davorgestellt worden?\n"
        f"3. Am 12.11.2026 lag es an keinem von beidem: ChirpStack hatte "
        f"dem Fuehler die Sendeleistung auf das Minimum gestellt (etwa 2 "
        f"statt 16 dBm), und damit kam 14 Stunden lang nichts an. Das "
        f"steht in RUNBOOK Paragraph 10av.\n\n"
        f"WAS DIESE MELDUNG NICHT IST\n"
        f"Kein Geraetefehler. Der Fuehler kann senden und gehoert werden "
        f"und trotzdem hier auftauchen - gemessen wird, was **ankommt**.\n"
        + _relais_block(befund, zeitzone=zeitzone)
    )


def nachricht_entwarnung(befund: ZonenBefund, *, zeitzone: str) -> str:
    """Die Entwarnung ist Pflicht, nicht Hoeflichkeit (Paragraph 5.79)."""
    jetzt = datetime.now(tz=ZoneInfo(zeitzone)).strftime("%d.%m.%Y %H:%M")
    return (
        f"{_ortsname(befund)} meldet wieder ({jetzt}).\n\n"
        f"Fuehler und Relais der Zone sind beide zu hoeren, die Zone wird "
        f"damit wieder geregelt und ihr Schaltzustand ist bekannt. Ob sie "
        f"in der Zwischenzeit ausgekuehlt ist, sagt diese Meldung nicht - "
        f"der Verlauf steht auf der Seite Temperaturverlauf.\n"
    )
