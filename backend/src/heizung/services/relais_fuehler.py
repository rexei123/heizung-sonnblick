"""Meldung, wenn der Fuehler einer Relais-Zone schweigt (13.11.2026).

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
from heizung.models.room import Room
from heizung.models.sensor_reading import SensorReading
from heizung.services import relay_service
from heizung.services.device_service import get_active_devices_for_zone

logger = logging.getLogger(__name__)

Grund = Literal["stumm", "kein_fuehler"]

#: Die beiden Gruende. snake_case-Marken wie die ``detail``-Token der
#: Engine-Schichten (Paragraph 5.23).
#:
#: **Mit Typ, nicht nur als Zeichenkette.** Ohne die Annotation sind sie
#: fuer mypy ein ``str``, und dann nimmt ``ZonenBefund.grund`` jeden
#: Tippfehler an — eine Marke, die nirgends vorkommt, waere ein Befund,
#: den niemand bemerkt.
GRUND_STUMM: Grund = "stumm"
GRUND_KEIN_FUEHLER: Grund = "kein_fuehler"


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
    #: Wie viele Relais dieser Zone schalten duerfen. Steht in der Mail,
    #: damit „die Zone heizt nicht" belegt ist und nicht behauptet.
    relais_in_betrieb: int
    #: ``None`` heisst in Ordnung. Das Urteil wird in ``beurteile``
    #: gefaellt und **mitgefuehrt**, nicht in einer Eigenschaft
    #: nachgerechnet: die Grenze kommt aus den Settings, und ein Befund,
    #: der sie noch braucht, waere ohne sie nicht lesbar.
    grund: Grund | None

    @property
    def stumm(self) -> bool:
        """Ob diese Zone gemeldet werden muss."""
        return self.grund is not None


def beurteile(
    *,
    zone_id: int,
    zone_name: str,
    ort: str | None,
    fuehler: tuple[str, ...],
    letzte_meldung: datetime | None,
    relais_in_betrieb: int,
    now: datetime,
    grenze_min: int,
) -> ZonenBefund:
    """Urteil fuer **eine** Zone — ohne Datenbank, ohne Wanduhr.

    Reihenfolge verbindlich:

    1. **Kein Fuehler** schlaegt alles. Ohne Fuehler gibt es keine
       Stille, die man messen koennte, und der Mangel ist der schwerere.
    2. **Nie gehoert** zaehlt wie stumm. Ein Fuehler, der noch nie
       gemeldet hat, ist fuer die Zone genau so wertlos wie einer, der
       aufgehoert hat — und anders als beim Totalausfall ist das hier
       **kein** frisch aufgesetztes Haus, sondern ein Relais, das jemand
       ausdruecklich in Betrieb genommen hat.
    3. **Grenze** auf dem Alter, inklusiv: „seit mehr als 30 Minuten"
       meldet bei 30:00 noch nicht und bei 30:01 schon.
    """
    if not fuehler:
        return ZonenBefund(
            zone_id=zone_id,
            zone_name=zone_name,
            ort=ort,
            fuehler=(),
            letzte_meldung=None,
            alter_min=None,
            relais_in_betrieb=relais_in_betrieb,
            grund=GRUND_KEIN_FUEHLER,
        )

    if letzte_meldung is None:
        return ZonenBefund(
            zone_id=zone_id,
            zone_name=zone_name,
            ort=ort,
            fuehler=fuehler,
            letzte_meldung=None,
            alter_min=None,
            relais_in_betrieb=relais_in_betrieb,
            grund=GRUND_STUMM,
        )

    alter = now - letzte_meldung
    alter_min = max(0, int(alter.total_seconds() // 60))
    return ZonenBefund(
        zone_id=zone_id,
        zone_name=zone_name,
        ort=ort,
        fuehler=fuehler,
        letzte_meldung=letzte_meldung,
        alter_min=alter_min,
        relais_in_betrieb=relais_in_betrieb,
        grund=GRUND_STUMM if alter > timedelta(minutes=grenze_min) else None,
    )


async def lies_relais_zonen(
    session: AsyncSession,
    *,
    grenze_min: int,
    now: datetime | None = None,
) -> list[ZonenBefund]:
    """Alle Zonen mit mindestens einem Relais in Betrieb, mit Urteil.

    Drei Abfragen, unabhaengig von der Zahl der Zonen: die Relais, die
    Geraete der betroffenen Zonen, die juengste Meldung je Geraet. Die
    Kachel haengt an jedem Seitenaufruf des Dashboards (Paragraph 5.73 —
    read-time abgeleitet, aber **gehoben**, nicht je Zeile).
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
    zonen_ids: dict[int, int] = {}
    for geraet in relais:
        if not relay_service.darf_schalten(geraet):
            continue
        assert geraet.heating_zone_id is not None  # vom WHERE oben
        zonen_ids[geraet.heating_zone_id] = zonen_ids.get(geraet.heating_zone_id, 0) + 1

    if not zonen_ids:
        return []

    # 2. Zone samt Ort.
    zeilen = (
        await session.execute(
            select(HeatingZone.id, HeatingZone.name, Room.number)
            .join(Room, Room.id == HeatingZone.room_id, isouter=True)
            .where(HeatingZone.id.in_(zonen_ids.keys()))
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

        befunde.append(
            beurteile(
                zone_id=zone_id,
                zone_name=zone_name,
                ort=ort,
                fuehler=etiketten,
                letzte_meldung=letzte,
                relais_in_betrieb=zonen_ids[zone_id],
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


def betreff_alarm(befund: ZonenBefund) -> str:
    if befund.grund == GRUND_KEIN_FUEHLER:
        return f"Heizung Sonnblick: {_ortsname(befund)} hat kein Thermostat zugeordnet"
    return (
        f"Heizung Sonnblick: {_ortsname(befund)} ohne Fuehlerwert seit {befund.alter_min} Minuten"
    )


def betreff_entwarnung(befund: ZonenBefund) -> str:
    return f"Heizung Sonnblick: {_ortsname(befund)} meldet wieder"


def nachricht_alarm(befund: ZonenBefund, *, zeitzone: str) -> str:
    """Die Folge zuerst, die Zahlen danach.

    Der erste Satz muss sagen, was es bedeutet — **die Zone heizt
    nicht** —, nicht welches Geraet schweigt. Wer die Mail nachts liest,
    braucht die Folge, nicht die Diagnose.
    """
    kopf = (
        f"{_ortsname(befund)} wird gerade nicht geheizt.\n\n"
        f"Das Relais dieser Zone ({befund.relais_in_betrieb} in Betrieb) "
        f"hat keinen eigenen Fuehler. Ohne aktuellen Zonenwert schaltet "
        f"die Steuerung bewusst AUS — das ist der sichere Zustand und "
        f"kein Fehler, aber die Zone bleibt damit kalt, solange der Wert "
        f"fehlt.\n\n"
    )

    if befund.grund == GRUND_KEIN_FUEHLER:
        return (
            kopf + "DER GRUND\n"
            "Dieser Zone ist **kein Thermostat** zugeordnet. Das ist "
            "keine Funkstoerung, sondern eine fehlende Zuordnung — und "
            "sie laesst sich nicht aussitzen: ohne Fuehler heizt die "
            "Zone nie.\n\n"
            "WAS ZU TUN IST\n"
            "Ein Thermostat dieser Zone zuordnen (Seite Zimmer, Abschnitt "
            "Heizzonen). Bis dahin bleibt das Relais aus.\n"
        )

    letzte = (
        befund.letzte_meldung.astimezone(ZoneInfo(zeitzone)).strftime("%d.%m.%Y %H:%M")
        if befund.letzte_meldung
        else "noch nie"
    )
    return (
        kopf + f"DER STAND\n"
        f"Fuehler: {', '.join(befund.fuehler)}\n"
        f"Letzte Meldung: {letzte} (vor {befund.alter_min} Minuten)\n\n"
        f"WAS ZU TUN IST — in dieser Reihenfolge\n"
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
        f"und trotzdem hier auftauchen — gemessen wird, was **ankommt**.\n"
    )


def nachricht_entwarnung(befund: ZonenBefund, *, zeitzone: str) -> str:
    """Die Entwarnung ist Pflicht, nicht Hoeflichkeit (Paragraph 5.79)."""
    jetzt = datetime.now(tz=ZoneInfo(zeitzone)).strftime("%d.%m.%Y %H:%M")
    return (
        f"{_ortsname(befund)} liefert wieder Fuehlerwerte ({jetzt}).\n\n"
        f"Die Zone wird damit wieder geregelt. Ob sie in der Zwischenzeit "
        f"ausgekuehlt ist, sagt diese Meldung nicht — der Verlauf steht "
        f"auf der Seite Temperaturverlauf.\n"
    )
