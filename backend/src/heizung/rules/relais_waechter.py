"""Waechter fuer Relais-Aktoren (Sprint 24, Paket C, S1/S2).

**Was der Waechter leistet, und warum er nicht weglassbar ist.** Ein
Relais, das dauerhaft EIN gesetzt wird, bleibt EIN — auch wenn der Server
stirbt, das Netz ausfaellt oder der Regler haengt. Bei einem 1600-W-Panel
in einer Allgemeinflaeche ist das der Fall, den niemand bemerkt, bis
jemand den Raum betritt.

Deshalb wird **nie** dauerhaft eingeschaltet (S1). EIN geht
ausschliesslich ueber den Relais-Timer ``0x57``, und der laeuft von
selbst ab. Ein stummer Server fuehrt damit nicht zu einem heizenden
Panel, sondern zu einem kalten Raum — der teure Fehler wird gegen den
billigen getauscht.

**Zwei Strategien, und die Vorgabe ist die vorsichtigere.**

``EXPIRE_AND_RESEND`` (Vorgabe): ``0x57`` geht **nur** heraus, wenn der
zuletzt **bestaetigte** Zustand AUS ist. Laeuft der Timer ab, meldet das
Geraet den Wechsel, und erst danach wird bei Bedarf neu gesetzt. Der
Raum kuehlt zwischen Ablauf und Neusetzen etwas ab; dafuer haengt die
Sicherheit an keiner Doku-Luecke.

``REFRESH``: der Timer wird nachgesetzt, waehrend das Relais EIN ist.
Kuerzere Abschaltzeit, gleichmaessigere Temperatur — **aber** die Doku
sagt nicht, was „previous state" bedeutet, wenn ein Timer-Befehl
waehrend eines laufenden Timers eintrifft (AE-78 §4). Bedeutet es „der
Zustand vor diesem Befehl", schreibt das Nachsetzen **EIN** als
Rueckfallzustand fest, und das Relais bleibt dauerhaft EIN — der
Waechter erzeugte dann genau den Zustand, den er verhindern soll.
Deshalb ist diese Strategie gebaut, je Geraet waehlbar und
**standardmaessig aus**; freigegeben wird sie erst, wenn die Messung
T3.0 am Geraet ergeben hat, dass „previous state" der dauerhafte Zustand
ist.

**Bestaetigung ist Pflicht.** Ein Befehl gilt erst als ausgefuehrt, wenn
ein Uplink den Zustand bestaetigt — nicht, wenn der Downlink abgesetzt
wurde. Das ist dieselbe Trennung, die Sprint 20f zugrunde liegt: was wir
gesendet haben, steht in ``control_command``; was am Geraet gilt, steht
im Uplink. Bei Class C ist die Antwort schnell, aber nicht garantiert.

Diese Datei entscheidet nur. Senden, Speichern und Alarmieren macht der
Aufrufer — so bleiben S1 und S2 ohne Datenbank pruefbar.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from datetime import datetime, timedelta

from heizung.models.enums import WatchdogStrategy


class WaechterAktion(enum.StrEnum):
    """Was der Aufrufer tun soll."""

    #: ``0x57`` mit ``sekunden`` senden. Der **einzige** Weg zu EIN (S1).
    SENDE_EIN = "sende_ein"
    #: ``0xC1 00`` senden.
    SENDE_AUS = "sende_aus"
    #: Es laeuft ein Befehl, auf dessen Bestaetigung noch gewartet wird.
    WARTE = "warte"
    #: Nach ``max_versuche`` ohne Bestaetigung: melden, nicht weiter senden.
    ALARM = "alarm"
    #: Nichts zu tun — der bestaetigte Zustand ist der gewuenschte.
    NICHTS = "nichts"


@dataclass(frozen=True, slots=True)
class Offen:
    """Ein abgesetzter Befehl, dessen Bestaetigung aussteht."""

    #: Was der Befehl erreichen wollte.
    ziel_ein: bool
    #: Wann er abgesetzt wurde.
    seit: datetime
    #: Wie oft er bisher abgesetzt wurde, einschliesslich des ersten Mals.
    versuche: int


@dataclass(frozen=True, slots=True)
class WaechterSchwellen:
    """Die Parameter des Waechters. Pflicht-Argument, kein Default (§5.73)."""

    #: Laufzeit des Timers bei ``EXPIRE_AND_RESEND``.
    timer_expire: timedelta
    #: Laufzeit des Timers bei ``REFRESH``.
    timer_refresh: timedelta
    #: Abstand zwischen zwei Auffrischungen bei ``REFRESH``.
    refresh_abstand: timedelta
    #: Wie lange auf eine Bestaetigung gewartet wird, bevor neu gesendet wird.
    bestaetigungs_frist: timedelta
    #: Nach so vielen erfolglosen Versuchen kommt der Alarm.
    max_versuche: int


@dataclass(frozen=True, slots=True)
class Waechterbefehl:
    """Ergebnis einer Bewertung. ``sekunden`` nur bei ``SENDE_EIN``."""

    aktion: WaechterAktion
    grund: str
    sekunden: int | None = None


def naechste_aktion(
    *,
    strategie: WatchdogStrategy,
    gewuenscht_ein: bool,
    bestaetigt_ein: bool | None,
    offen: Offen | None,
    letzter_ein_befehl: datetime | None,
    schwellen: WaechterSchwellen,
    now: datetime,
) -> Waechterbefehl:
    """Ein Schritt des Waechters fuer **ein** Relais.

    ``bestaetigt_ein`` ist der vom **Geraet gemeldete** Zustand.
    ``None`` heisst „noch nie etwas gehoert" — dann ist der Zustand
    unbekannt, und der Waechter schaltet **nicht ein**. Ein unbekannter
    Zustand als AUS zu lesen waere die naheliegende und falsche
    Vereinfachung: der erste Befehl wuerde dann ein Relais einschalten,
    von dem wir nicht wissen, ob es schon heizt.

    Reihenfolge, verbindlich:

    1. **Offener Befehl** — erst die Bestaetigung, dann Neues.
    2. **AUS gewuenscht** — Sicherheit vor Komfort, und AUS braucht
       keine Bedingung.
    3. **Zustand unbekannt** — kein EIN.
    4. **EIN gewuenscht** nach Strategie.
    """
    # 1. Ein abgesetzter Befehl wartet auf seine Bestaetigung.
    if offen is not None:
        if bestaetigt_ein is offen.ziel_ein:
            # Bestaetigt. Der Aufrufer loescht ``offen`` und zaehlt bei
            # einem EIN einen Schaltzyklus. Wir sagen hier nur, dass
            # nichts mehr zu senden ist.
            return Waechterbefehl(WaechterAktion.NICHTS, "bestaetigt")

        if now - offen.seit < schwellen.bestaetigungs_frist:
            return Waechterbefehl(WaechterAktion.WARTE, "frist_laeuft")

        if offen.versuche >= schwellen.max_versuche:
            return Waechterbefehl(
                WaechterAktion.ALARM,
                f"keine_bestaetigung_nach_{offen.versuche}_versuchen",
            )

        # Frist abgelaufen, Versuche noch offen: denselben Befehl erneut.
        if offen.ziel_ein:
            return Waechterbefehl(
                WaechterAktion.SENDE_EIN,
                f"wiederholung_{offen.versuche + 1}",
                sekunden=int(_timer(strategie, schwellen).total_seconds()),
            )
        return Waechterbefehl(WaechterAktion.SENDE_AUS, f"wiederholung_{offen.versuche + 1}")

    # 2. AUS gewuenscht.
    if not gewuenscht_ein:
        if bestaetigt_ein is True:
            return Waechterbefehl(WaechterAktion.SENDE_AUS, "aus_gewuenscht")
        # Auch bei unbekanntem Zustand nichts senden: ein ``0xC1 00`` auf
        # ein Relais, das ohnehin aus ist, waere Sendezeit ohne Wirkung
        # (§0 S4). Wer sicher ausschalten will, tut das ueber den
        # Zwangs-AUS des Reglers, der einen bekannten Zustand sieht.
        return Waechterbefehl(WaechterAktion.NICHTS, "bereits_aus")

    # 3. EIN gewuenscht, aber der Zustand ist unbekannt.
    if bestaetigt_ein is None:
        return Waechterbefehl(WaechterAktion.NICHTS, "zustand_unbekannt")

    # 4. EIN gewuenscht.
    if not bestaetigt_ein:
        return Waechterbefehl(
            WaechterAktion.SENDE_EIN,
            "ein_gewuenscht",
            sekunden=int(_timer(strategie, schwellen).total_seconds()),
        )

    # Bestaetigt EIN und EIN gewuenscht.
    if strategie is WatchdogStrategy.EXPIRE_AND_RESEND:
        # **Der Kern von S2.** Kein ``0x57`` auf ein laufendes EIN. Der
        # Timer laeuft ab, das Geraet meldet AUS, und dann greift
        # Zweig 4 oben. Das ist die Stelle, die Mutationsprobe M2
        # angreift.
        return Waechterbefehl(WaechterAktion.NICHTS, "laeuft_ab_von_selbst")

    # REFRESH: nachsetzen, wenn der Abstand erreicht ist.
    if letzter_ein_befehl is None:
        return Waechterbefehl(
            WaechterAktion.SENDE_EIN,
            "auffrischung_ohne_vorbefehl",
            sekunden=int(schwellen.timer_refresh.total_seconds()),
        )
    if now - letzter_ein_befehl >= schwellen.refresh_abstand:
        return Waechterbefehl(
            WaechterAktion.SENDE_EIN,
            "auffrischung",
            sekunden=int(schwellen.timer_refresh.total_seconds()),
        )
    return Waechterbefehl(WaechterAktion.NICHTS, "auffrischung_noch_nicht_faellig")


def _timer(strategie: WatchdogStrategy, schwellen: WaechterSchwellen) -> timedelta:
    """Die Timer-Laufzeit der Strategie.

    ``EXPIRE_AND_RESEND`` nimmt die laengere Zeit (Vorgabe 30 min): das
    Relais soll nicht unnoetig oft abfallen, weil jeder Abfall eine
    Abkuehlphase und einen Schaltzyklus bedeutet. ``REFRESH`` nimmt die
    kuerzere (15 min), weil dort ohnehin nachgesetzt wird und die kurze
    Zeit der Sinn der Strategie ist — sie ist die Obergrenze fuer die
    Zeit, die ein Panel nach einem Serverausfall noch heizt.
    """
    if strategie is WatchdogStrategy.REFRESH:
        return schwellen.timer_refresh
    return schwellen.timer_expire
