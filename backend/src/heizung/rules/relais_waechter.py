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

**Und weil sie nicht garantiert ist, braucht die Wiederholung eine
Bremse** (02.11.2026). Die Frist verdoppelt sich je Versuch und ist bei
einer halben Stunde gekappt; nach ``max_versuche`` kommt **einmal** ein
Alarm, danach laeuft die gedrosselte Wiederholung weiter. Endgueltig
aufzugeben waere die naheliegende und falschere Variante: ein Geraet an
der Funkgrenze verliert irgendwann drei Bestaetigungen in Folge, und der
Waechter haette es damit dauerhaft stillgelegt — ohne dass am Geraet
etwas kaputt ist. Einzelheiten in ``_frist``.

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
    #: Nach ``max_versuche`` ohne Bestaetigung: **einmal** melden. Danach
    #: wird weiter versucht, aber nur noch im Abstand ``backoff_max``.
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
    #: Wie lange auf eine Bestaetigung gewartet wird, bevor neu gesendet
    #: wird — fuer den **ersten** Versuch. Danach verdoppelt sie sich.
    bestaetigungs_frist: timedelta
    #: Nach so vielen erfolglosen Versuchen kommt der Alarm. Danach wird
    #: weiter versucht, aber nur noch im Abstand ``backoff_max``.
    max_versuche: int
    #: Obergrenze der Verdopplung. Mehr dazu in ``_frist``.
    backoff_max: timedelta


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

    1. **Bestaetigung** — ein offener Befehl, den das Geraet gemeldet
       hat, ist erledigt.
    2. **Ein offener Befehl, der dem jetzigen Wunsch widerspricht, wird
       nicht wiederholt** (02.11.2026, Punkt 3 der Freigabe). Er wird
       uebergangen; die Wunsch-Regeln entscheiden, und der Aufrufer
       ersetzt oder loescht den offenen Stand.
    3. **Offener Befehl**, der zum Wunsch passt: Frist mit Backoff,
       Alarm, Wiederholung.
    4. **AUS gewuenscht** — Sicherheit vor Komfort, und AUS braucht
       keine Bedingung.
    5. **Zustand unbekannt** — kein EIN.
    6. **EIN gewuenscht** nach Strategie.
    """
    # 1. Ein abgesetzter Befehl wartet auf seine Bestaetigung.
    if offen is not None and bestaetigt_ein is offen.ziel_ein:
        # Bestaetigt. Der Aufrufer loescht ``offen`` und zaehlt bei einem
        # EIN einen Schaltzyklus. Wir sagen hier nur, dass nichts mehr zu
        # senden ist.
        return Waechterbefehl(WaechterAktion.NICHTS, "bestaetigt")

    # 2./3. Ein offener Befehl bremst nur, solange er noch gewollt ist.
    #
    # **Der Fall, der diese Bedingung noetig macht.** Ein EIN geht
    # hinaus, das Geraet schaltet, der bestaetigende Uplink geht
    # verloren (am Relais 109 gemessen: rund 30 % Verlust). Fuer uns ist
    # das Relais damit AUS, waehrend es heizt — der Raum wird warm, der
    # Zweipunktregler will AUS. Ohne diese Bedingung sieht der Waechter
    # nur den offenen Befehl und **wiederholt das EIN**, also genau das,
    # was niemand mehr will.
    #
    # Die Sorge, die in der ersten Fassung hinter dem Vorrang stand —
    # zwei unbestaetigte Befehle koennten sich ueberlagern — bleibt
    # unbegruendet: es gibt genau **einen** offenen Stand je Geraet, und
    # er wird ersetzt, nicht ergaenzt. Die Versuchszaehlung beginnt beim
    # Ersetzen von vorn, weil es ein anderer Befehl ist.
    if offen is not None and offen.ziel_ein == gewuenscht_ein:
        if now - offen.seit < _frist(offen.versuche, schwellen):
            return Waechterbefehl(WaechterAktion.WARTE, "frist_laeuft")

        if offen.versuche == schwellen.max_versuche:
            # **Einmal** melden. Der Aufrufer zaehlt den Versuch hoch,
            # ohne zu senden; der naechste Durchlauf landet unten in der
            # gedrosselten Wiederholung und meldet nicht erneut.
            return Waechterbefehl(
                WaechterAktion.ALARM,
                f"keine_bestaetigung_nach_{offen.versuche}_versuchen",
            )

        # Frist abgelaufen: denselben Befehl erneut. Jenseits von
        # ``max_versuche`` ist das die gedrosselte Wiederholung — die
        # Frist steht dann auf ``backoff_max``.
        gedrosselt = "_gedrosselt" if offen.versuche > schwellen.max_versuche else ""
        if offen.ziel_ein:
            return Waechterbefehl(
                WaechterAktion.SENDE_EIN,
                f"wiederholung{gedrosselt}_{offen.versuche + 1}",
                sekunden=int(_timer(strategie, schwellen).total_seconds()),
            )
        return Waechterbefehl(
            WaechterAktion.SENDE_AUS,
            f"wiederholung{gedrosselt}_{offen.versuche + 1}",
        )

    # 4. AUS gewuenscht.
    if not gewuenscht_ein:
        if bestaetigt_ein is True:
            return Waechterbefehl(WaechterAktion.SENDE_AUS, "aus_gewuenscht")
        # Auch bei unbekanntem Zustand nichts senden: ein ``0xC1 00`` auf
        # ein Relais, das ohnehin aus ist, waere Sendezeit ohne Wirkung
        # (§0 S4). Wer sicher ausschalten will, tut das ueber den
        # Zwangs-AUS des Reglers, der einen bekannten Zustand sieht.
        return Waechterbefehl(WaechterAktion.NICHTS, "bereits_aus")

    # 5. EIN gewuenscht, aber der Zustand ist unbekannt.
    if bestaetigt_ein is None:
        return Waechterbefehl(WaechterAktion.NICHTS, "zustand_unbekannt")

    # 6. EIN gewuenscht.
    if not bestaetigt_ein:
        return Waechterbefehl(
            WaechterAktion.SENDE_EIN,
            "ein_gewuenscht",
            sekunden=int(_timer(strategie, schwellen).total_seconds()),
        )

    # Bestaetigt EIN und EIN gewuenscht.
    if strategie == WatchdogStrategy.EXPIRE_AND_RESEND:
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


def _frist(versuche: int, schwellen: WaechterSchwellen) -> timedelta:
    """Wie lange nach dem ``versuche``-ten Versuch gewartet wird.

    Verdopplung je Versuch, gekappt bei ``backoff_max``:

    ======== ======
    Versuche Frist
    ======== ======
    1        60 s
    2        120 s
    3        240 s
    4        480 s
    5        960 s
    6+       1800 s (Kappung)
    ======== ======

    **Der Anlass ist eine Messung des Betreibers am 01.11.2026.** Zwischen
    11:22 und 11:28 ging **jede Minute** ein Downlink an Relais 109 —
    sieben Stueck, jeder bei SF12 ueber RX2 mit 1,32 Sekunden Sendezeit,
    also rund neun Sekunden Sendezeit des Gateways in sieben Minuten. Die
    feste Frist von 60 Sekunden lag damit genau auf dem Tick-Intervall:
    jeder Durchlauf erzeugte einen Versuch.

    **Dass ``max_versuche`` das nicht begrenzt hat, war der eigentliche
    Befund.** Der Alarm loeschte den offenen Stand, und der naechste
    Durchlauf begann die Zaehlung von vorn — ``max_versuche`` hat also nur
    getaktet, wie oft ein Alarm kommt, und nichts begrenzt. Ein Melder,
    der sich selbst zurueckstellt, ueberwacht nichts (§5.79).

    Mit der Kappung bei einer halben Stunde bleibt ein unerreichbares
    Geraet bei **einem** Downlink je 30 Minuten — 1,3 Sekunden Sendezeit,
    statt 79 Sekunden wie bisher. In der ersten Stunde sind es sechs
    Downlinks statt sechzig.
    """
    # **Der Exponent wird gekappt, nicht nur das Ergebnis.** Ein offener
    # Stand lebt jetzt beliebig lange (der Alarm loescht ihn nicht mehr),
    # und ``versuche`` waechst entsprechend. ``timedelta * 2**98``
    # ueberlaeuft mit ``OverflowError: Python int too large to convert to
    # C int`` — mitten im Schaltpfad, und das ``min`` danach kommt zu
    # spaet. Gefunden hat das der Test mit 99 Versuchen; bei einem
    # Downlink je halbe Stunde ist das nach zwei Tagen Funkstille
    # erreicht. 20 ist weit jenseits jeder Kappung und sicher.
    faktor: int = 2 ** min(max(0, versuche - 1), 20)
    return min(schwellen.bestaetigungs_frist * faktor, schwellen.backoff_max)


def _timer(strategie: WatchdogStrategy, schwellen: WaechterSchwellen) -> timedelta:
    """Die Timer-Laufzeit der Strategie.

    **Verglichen wird mit ``==``, nicht mit ``is``.** ``WatchdogStrategy``
    ist ein ``StrEnum``, und die Strategie kommt aus einer
    ``String(20)``-Spalte. Ein roher String ist **nicht** identisch mit
    dem Enum-Mitglied, aber gleich — mit ``is`` waere er still in den
    ``else``-Zweig gefallen, also in die riskantere Strategie, ohne dass
    jemand sie gewaehlt hat. Gefunden hat das der Ende-zu-Ende-Test;
    ``==`` ist in der sicheren Richtung nachgiebig.

    ``EXPIRE_AND_RESEND`` nimmt die laengere Zeit (Vorgabe 30 min): das
    Relais soll nicht unnoetig oft abfallen, weil jeder Abfall eine
    Abkuehlphase und einen Schaltzyklus bedeutet. ``REFRESH`` nimmt die
    kuerzere (15 min), weil dort ohnehin nachgesetzt wird und die kurze
    Zeit der Sinn der Strategie ist — sie ist die Obergrenze fuer die
    Zeit, die ein Panel nach einem Serverausfall noch heizt.
    """
    if strategie == WatchdogStrategy.REFRESH:
        return schwellen.timer_refresh
    return schwellen.timer_expire
