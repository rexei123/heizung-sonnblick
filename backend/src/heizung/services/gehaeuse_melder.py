"""Meldung, wenn ein Relais warm wird (18.11.2026).

**Der Anlass, 18.11.2026.** Relais „109 Panel" (``device.id`` 110) stand
unter Last bei **45** in der Einheit des Keepalive-Bytes, waehrend „108"
(``device.id`` 109) bei nahezu gleicher Last **37** meldete. Die Schwelle
in den Settings liegt bei 40 (``relay_gehaeusetemperatur_alarm``).

**Gesehen hat das der Betreiber, nicht die Steuerung.** Die Zahl stand
auf der Geraeteseite, und dort steht sie nur, solange jemand hinsieht:
der naechste Uplink ersetzt sie, und ``relay_reading`` behaelt die Reihe,
ohne dass sie jemand liest. Der Alarm an der Schwelle war **nicht**
verdrahtet — ``relay_gehaeusetemperatur_alarm`` hatte bis heute genau
einen Verbraucher, das Kennzeichen ``gehaeusetemperatur_alarm`` auf der
Karte (``api/v1/relays.py``). Das ist Paragraph 5.76 woertlich: die
Mechanik war gebaut, die **Mitteilung** fehlte.

Dasselbe gilt eine Stufe hoeher, und das ist der eigentliche Befund: auch
die **Schutzausloesung** schickt keine Mail.
``health_alerts.emit_relay_protection_alert`` schreibt einen Logeintrag,
die Sperre sitzt daneben in ``device.protection_tripped_at`` — mehr
nicht. Wer also nicht hinsieht, erfaehrt vom Ueberhitzen erst daran, dass
eine Zone nicht mehr heizt.

Warum drei Meldungen und nicht eine
-----------------------------------

Ein einzelner Wert kann ein Ausschlag unter Last sein — dieselbe
Erfahrung wie bei der Batterie, wo ein einzelner Frame am 29.09.2026 zu
einem Fehlbefund gefuehrt hat (``BATTERY_MIN_SAMPLES``, Paragraph 5.73).
Ein Relais meldet alle zehn Minuten (gemessen,
``relay_meldeintervall_s``), drei Meldungen in Folge sind also
**mindestens zwanzig Minuten** ueber der Schwelle. Das ist die
Entprellung, und sie ist eine Eigenschaft der Messung und keine
Abwaegung — deshalb eine Konstante und keine Einstellung.

**Keine zweite Schwelle, kein Totband.** Entwarnt wird nach derselben
Regel in die andere Richtung: drei Meldungen in Folge **unter** der
Schwelle. Wer genau auf der Grenze pendelt, braucht damit drei Meldungen
auf der anderen Seite, bevor sich etwas aendert. Ein eigener
Entwarnungs-Wert waere eine zweite Zahl mit derselben Herleitung
(Paragraph 5.53).

**Der Zustand wird nicht gespeichert.** Die drei Werte kommen bei jedem
Lauf aus ``relay_reading``; einen Zaehler, der mitlaeuft, gaebe es nur,
damit er beim Ausfall des Taktgebers plausibel einfriert (Paragraph
5.73). Was gespeichert wird, ist allein die **Episode** — und die steht
im ``business_audit``, nicht in Redis, aus demselben Grund wie beim
Zonen-Melder und bei der Platte.

Warum ohne ``darf_schalten``
----------------------------

Der Zonen-Melder prueft nur Zonen mit einem Relais **in Betrieb**; hier
waere dieselbe Bedingung falsch. Ein warmes Gehaeuse ist ein warmes
Gehaeuse, auch wenn das Relais gesperrt ist — und nach einer
Schutzausloesung ist es **genau dann** warm. Was hier filtert, ist
ausschliesslich der Lebenszyklus (Paragraph 5.58): Relais, nicht
ausgemustert.

Die Einheit
-----------

``internal_temperature_raw`` ist das Byte aus dem Keepalive. Die
Hersteller-Doku nennt die Einheit **dieses Feldes** nicht ausdruecklich —
sie nennt sie aber ueberall sonst, und zwar belegt (abgerufen
18.11.2026):

* Geraeteseite, Abschnitt „Sensors": „Internal temperature sensor —
  Resolution: 1 Grad C, Accuracy: +/- 1 Grad C".
* Abschnitt „Protections": die Ausloese- und Erholungsschwellen stehen in
  Grad Celsius, zulaessiger Bereich 30 bis 100 bei 1 Grad Aufloesung, und
  das Ueberhitzungs-Ereignis (``0x60``) meldet „Temperature in Celsius".

Damit ist Grad Celsius **gestuetzt** und nicht geraten. Dieses Modul
rechnet trotzdem **nicht** um und nennt die Zahl in der Mail als Zahl:
umrechnen waere hier ohnehin die Identitaet, und eine Einheit, die die
Doku fuer dieses eine Feld nicht ausspricht, soll im Text als Hinweis
stehen statt in einer Formel zu verschwinden (AE-78,
Pflicht-Pruefung am Geraet).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from heizung.models.device import Device
from heizung.models.enums import DeviceKind
from heizung.models.heating_zone import HeatingZone
from heizung.models.relay_reading import RelayReading
from heizung.models.room import Room

#: Wie viele gemeldete Werte in Folge auf derselben Seite der Schwelle
#: liegen muessen. **Konstante, keine Einstellung** — siehe Modulkopf: das
#: ist die Entprellung der Messung und nicht die Abwaegung, die die
#: Schwelle selbst traegt.
MIN_MELDUNGEN = 3


@dataclass(frozen=True, slots=True)
class GehaeuseBefund:
    """Ein Relais und der Stand seiner Gehaeusetemperatur."""

    device_id: int
    dev_eui: str
    #: Etikett des Geraets. ``None`` heisst: keines hinterlegt — dann
    #: nennt die Mail die DevEUI, nicht die Id.
    label: str | None
    #: Zimmernummer bzw. Bereichsname. ``None``, wenn das Relais an
    #: keinem Zimmer haengt.
    ort: str | None
    zone_name: str | None
    #: Die juengsten gemeldeten Werte, **juengster zuerst**, hoechstens
    #: ``MIN_MELDUNGEN`` viele und nur aus dem Lesefenster. Weniger
    #: heisst: es gibt kein Urteil.
    werte: tuple[int, ...]
    #: Zeitpunkt der juengsten dieser Meldungen.
    letzte_meldung: datetime | None
    #: Alter der juengsten Meldung in Minuten, abgerundet.
    alter_min: int | None
    #: Schaltzustand und Leistung aus derselben Zeile. Stehen in der Mail,
    #: damit „warm unter Last" von „warm ohne Last" zu unterscheiden ist —
    #: das zweite ist der schwerere Fall.
    relay_on: bool | None
    power_w: int | None
    #: Die Schwelle, gegen die geurteilt wurde. **Mitgefuehrt**, nicht
    #: nachgerechnet: sie kommt aus den Settings, und ein Befund ohne sie
    #: waere nicht lesbar (dieselbe Entscheidung wie bei ``ZonenBefund``).
    schwelle: int
    #: Ob die juengste Meldung im Frischefenster liegt.
    frisch: bool

    @property
    def wert(self) -> int | None:
        """Der juengste gemeldete Wert."""
        return self.werte[0] if self.werte else None

    @property
    def vollstaendig(self) -> bool:
        """Liegen genug frische Werte fuer ein Urteil vor?"""
        return self.frisch and len(self.werte) >= MIN_MELDUNGEN

    @property
    def heiss(self) -> bool:
        """Ob gemeldet werden muss: alle Werte **auf oder ueber** der Schwelle."""
        return self.vollstaendig and all(w >= self.schwelle for w in self.werte)

    @property
    def kuehl(self) -> bool:
        """Ob entwarnt werden darf: alle Werte **unter** der Schwelle.

        **Nicht das Gegenteil von** ``heiss``. Dazwischen liegt der Fall
        „gemischt, zu wenige Werte oder nichts Frisches", und der ist
        weder Alarm noch Entwarnung: eine laufende Episode bleibt dann
        stehen. Ein Relais, das waehrend eines Alarms verstummt, wird
        dadurch **nicht** entwarnt — eine Entwarnung ohne Messwert waere
        eine Behauptung (Paragraph 5.68).
        """
        return self.vollstaendig and all(w < self.schwelle for w in self.werte)

    @property
    def name(self) -> str:
        """Wie das Geraet in der Mail heisst."""
        return self.label or self.dev_eui


def _alter_min(letzte_meldung: datetime | None, now: datetime) -> int | None:
    if letzte_meldung is None:
        return None
    return max(0, math.floor((now - letzte_meldung).total_seconds() / 60))


def beurteile(  # noqa: PLR0913 — jedes Argument ist eine eigene Beobachtung
    *,
    device_id: int,
    dev_eui: str,
    label: str | None,
    ort: str | None,
    zone_name: str | None,
    werte: tuple[int, ...],
    letzte_meldung: datetime | None,
    relay_on: bool | None,
    power_w: int | None,
    schwelle: int,
    frische_fenster: timedelta,
    now: datetime | None = None,
) -> GehaeuseBefund:
    """Baut den Befund. Reine Funktion, ohne Datenbank.

    ``frische_fenster`` ist **Pflicht** und kommt von
    ``relay_tasks.zustand_veraltungs_fenster`` — dieselbe Frist, die der
    Waechter benutzt, um einem gemeldeten Schaltzustand nicht mehr zu
    glauben. Eine eigene Zahl hier waere eine zweite Wahrheit mit
    derselben Herleitung (Paragraph 5.53).
    """
    jetzt = now or datetime.now(tz=UTC)
    frisch = letzte_meldung is not None and jetzt - letzte_meldung <= frische_fenster
    return GehaeuseBefund(
        device_id=device_id,
        dev_eui=dev_eui,
        label=label,
        ort=ort,
        zone_name=zone_name,
        werte=werte[:MIN_MELDUNGEN],
        letzte_meldung=letzte_meldung,
        alter_min=_alter_min(letzte_meldung, jetzt),
        relay_on=relay_on,
        power_w=power_w,
        schwelle=schwelle,
        frisch=frisch,
    )


async def lies_gehaeusetemperaturen(
    session: AsyncSession,
    *,
    schwelle: int,
    frische_fenster: timedelta,
    now: datetime | None = None,
) -> list[GehaeuseBefund]:
    """Je Relais die ``MIN_MELDUNGEN`` juengsten gemeldeten Werte.

    **Eine Abfrage fuer alle Relais**, nicht eine je Zeile (Paragraph
    5.73): ein Fensterausdruck nummeriert die Meldungen je Geraet, und
    genommen werden die ersten ``MIN_MELDUNGEN``.

    **Das Lesefenster ist** ``MIN_MELDUNGEN * frische_fenster``, mit den
    Vorgaben also 75 Minuten. Ohne diese Grenze koennte eine Reihe aus
    drei Tagen die Entprellung fuellen: drei heisse Werte mit
    stundenlangen Luecken dazwischen sind keine drei Meldungen in Folge.
    Wer in diesem Fenster weniger als drei Meldungen hat, bekommt kein
    Urteil — ``vollstaendig`` ist dann ``False``.

    Zeilen **ohne** Temperatur bleiben aussen vor. Sie sind ein
    Lebenszeichen, aber kein Messwert.

    Ein Relais ohne jede Meldung im Fenster kommt trotzdem in die Liste —
    mit leeren ``werte``. Das ist Absicht: der Aufrufer soll sehen, dass
    es das Geraet gibt und dass es nichts gesagt hat, statt es gar nicht
    zu finden.
    """
    jetzt = now or datetime.now(tz=UTC)
    fenster_start = jetzt - MIN_MELDUNGEN * frische_fenster

    nummeriert = (
        select(
            RelayReading.device_id.label("device_id"),
            RelayReading.time.label("time"),
            RelayReading.internal_temperature_raw.label("temperatur"),
            RelayReading.relay_on.label("relay_on"),
            RelayReading.power_w.label("power_w"),
            func.row_number()
            .over(
                partition_by=RelayReading.device_id,
                order_by=RelayReading.time.desc(),
            )
            .label("rang"),
        )
        .where(
            RelayReading.internal_temperature_raw.is_not(None),
            RelayReading.time >= fenster_start,
        )
        .subquery()
    )

    stmt = (
        select(
            Device.id,
            Device.dev_eui,
            Device.label,
            HeatingZone.name,
            Room.number,
            nummeriert.c.time,
            nummeriert.c.temperatur,
            nummeriert.c.relay_on,
            nummeriert.c.power_w,
            nummeriert.c.rang,
        )
        .select_from(Device)
        .outerjoin(HeatingZone, HeatingZone.id == Device.heating_zone_id)
        .outerjoin(Room, Room.id == HeatingZone.room_id)
        .outerjoin(
            nummeriert,
            (nummeriert.c.device_id == Device.id) & (nummeriert.c.rang <= MIN_MELDUNGEN),
        )
        .where(
            Device.kind == DeviceKind.RELAY,
            Device.retired_at.is_(None),
        )
        .order_by(Device.id, nummeriert.c.rang.asc().nulls_last())
    )

    je_geraet: dict[int, dict[str, Any]] = {}
    for zeile in (await session.execute(stmt)).all():
        (
            device_id,
            dev_eui,
            label,
            zone_name,
            room_number,
            zeit,
            temperatur,
            relay_on,
            power_w,
            rang,
        ) = zeile
        eintrag = je_geraet.setdefault(
            device_id,
            {
                "dev_eui": dev_eui,
                "label": label,
                "zone_name": zone_name,
                "ort": room_number,
                "werte": [],
                "letzte_meldung": None,
                "relay_on": None,
                "power_w": None,
            },
        )
        if rang is None or temperatur is None:
            continue
        if not eintrag["werte"]:
            # Die erste Zeile je Geraet ist die juengste (``rang`` 1), und
            # aus ihr kommen Zeit, Schaltzustand und Leistung. Ein
            # Schaltzustand aus einer aelteren Zeile waere falsch
            # einsortiert.
            eintrag["letzte_meldung"] = zeit
            eintrag["relay_on"] = relay_on
            eintrag["power_w"] = power_w
        eintrag["werte"].append(int(temperatur))

    return [
        beurteile(
            device_id=device_id,
            dev_eui=eintrag["dev_eui"],
            label=eintrag["label"],
            ort=eintrag["ort"],
            zone_name=eintrag["zone_name"],
            werte=tuple(eintrag["werte"]),
            letzte_meldung=eintrag["letzte_meldung"],
            relay_on=eintrag["relay_on"],
            power_w=eintrag["power_w"],
            schwelle=schwelle,
            frische_fenster=frische_fenster,
            now=jetzt,
        )
        for device_id, eintrag in sorted(je_geraet.items())
    ]


def _ortsname(befund: GehaeuseBefund) -> str:
    """„Zone (Ort)", soweit vorhanden. Namen statt Ids."""
    teile = [t for t in (befund.zone_name, befund.ort) if t]
    if not teile:
        return "ohne Zone"
    if len(teile) == 1:
        return teile[0]
    return f"{teile[0]} ({teile[1]})"


def _last(befund: GehaeuseBefund) -> str:
    if befund.relay_on is None:
        return "Schaltzustand unbekannt"
    if not befund.relay_on:
        return "Relais aus, keine Last"
    if befund.power_w is None:
        return "Relais ein, Leistung unbekannt"
    return f"Relais ein, {befund.power_w} W"


def betreff_alarm(befund: GehaeuseBefund) -> str:
    return (
        f"Heizung Sonnblick: Relais {befund.name} wird warm "
        f"({befund.wert} ueber Schwelle {befund.schwelle})"
    )


def betreff_entwarnung(befund: GehaeuseBefund) -> str:
    return f"Heizung Sonnblick: Relais {befund.name} wieder unter der Schwelle ({befund.wert})"


def nachricht_alarm(befund: GehaeuseBefund) -> str:
    """Die Folge zuerst, die Zahlen danach, der Handgriff zuletzt."""
    reihe = " / ".join(str(w) for w in befund.werte)
    return (
        f"Das Relais {befund.name} ({_ortsname(befund)}) meldet eine "
        f"Gehaeusetemperatur von {befund.wert}. Die Warnschwelle ist "
        f"{befund.schwelle}.\n\n"
        f"WAS DAS BEDEUTET\n"
        f"Die Hersteller-Anleitung nennt eine Betriebstemperatur von "
        f"0-40 Grad. Der eigene Ueberhitzungsschutz des Geraets loest erst "
        f"bei 85 Grad aus (Vorgabe ab Firmware 1.4) und schaltet dann "
        f"selbst ab; danach sperrt die Steuerung das Relais, bis ein "
        f"Administrator die Sperre aufhebt. Diese Mail kommt VORHER — "
        f"damit niemand erst durch das Abschalten erfaehrt, dass es heiss "
        f"wird.\n\n"
        f"DER STAND\n"
        f"Letzte drei Meldungen (juengste zuerst): {reihe}\n"
        f"Zuletzt gemeldet: vor {befund.alter_min} Minuten\n"
        f"Zustand:          {_last(befund)}\n"
        f"Schwelle:         {befund.schwelle}\n\n"
        f"WAS ZU TUN IST — in dieser Reihenfolge\n"
        f"1. Auf der Geraeteseite nachsehen, ob der Wert weiter steigt.\n"
        f"2. Den Einbauort pruefen: die Dose gehoert nicht direkt neben "
        f"oder ueber das Panel (RUNBOOK Paragraph 10aj Schritt 0). Ein "
        f"Relais, das darueber sitzt, arbeitet im Dauerbetrieb am oberen "
        f"Rand seines Bereichs.\n"
        f"3. Meldet das Geraet den Wert ohne Last, ist das der schwerere "
        f"Fall: dann kommt die Waerme nicht vom Schalten.\n"
        f"4. Loest der Schutz aus, steht der Rueckweg im RUNBOOK "
        f"Paragraph 10aj Schritt d.\n\n"
        f"ZUR ZAHL SELBST\n"
        f"Der Hersteller gibt fuer den internen Fuehler 1 Grad Aufloesung "
        f"an und nennt alle Schutz-Temperaturen in Grad Celsius; fuer "
        f"genau dieses Keepalive-Feld spricht er die Einheit nicht aus "
        f"(AE-78). Gelesen wird sie als Grad Celsius.\n\n"
        f"WAS DIESE MELDUNG NICHT IST\n"
        f"Keine Abschaltung. Die Steuerung hat nichts veraendert, das "
        f"Relais schaltet weiter nach dem Regler.\n"
    )


def nachricht_entwarnung(befund: GehaeuseBefund) -> str:
    """Die Entwarnung ist Pflicht, nicht Hoeflichkeit (Paragraph 5.79)."""
    reihe = " / ".join(str(w) for w in befund.werte)
    return (
        f"Das Relais {befund.name} ({_ortsname(befund)}) liegt wieder "
        f"unter der Schwelle {befund.schwelle}.\n\n"
        f"Letzte drei Meldungen (juengste zuerst): {reihe}\n"
        f"Zustand: {_last(befund)}\n\n"
        f"Woran es liegt, sagt diese Meldung nicht — ein kuehleres "
        f"Gehaeuse kann vom Einbauort kommen, von weniger Schaltzeit oder "
        f"davon, dass gerade nichts heizt.\n"
    )
