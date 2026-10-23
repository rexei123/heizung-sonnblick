"""Zweipunktregler fuer Relais-Zonen (Sprint 24, Paket D).

**Wo er sitzt.** Hinter Layer 5, nicht als Layer. Er bekommt den
**fertigen** Sollwert der Pipeline und den gemessenen Istwert der Zone
und entscheidet daraus einen Schaltzustand. Das ist dieselbe Stellung wie
die Hysterese, und die ist bewusst kein Layer (§5.23): ein Layer
veraendert einen Sollwert, dieser Regler veraendert nichts am Sollwert,
sondern setzt ihn um.

**Warum er nicht ``hysteresis_decision`` erweitert.** Die beiden sehen
sich aehnlich und messen Verschiedenes:

| | ``hysteresis_decision`` (AE-32) | dieser Regler |
|---|---|---|
| Vergleicht | gesendeten Sollwert gegen letzten gesendeten | **Ist** gegen **Soll** |
| Zweck | Sendesperre, Batterie sparen | Regelung, Temperatur halten |
| Einheit der Schwelle | ganze Grad Sollwert-Differenz | Kelvin Regelabweichung |
| Zeitbezug | Heartbeat 6 h | Mindestlauf/-pause 10 min |
| Gilt fuer | Vicki (batteriebetrieben) | Relais (netzbetrieben) |

Ein netzbetriebenes Relais hat keinen Batteriegrund fuer eine
Sendesperre, und ein Vicki hat keine Mindestpause. In eine Funktion
gefaltet waere jede Aenderung an einer der beiden Groessen ein Risiko fuer
die andere. ``HYSTERESIS_C`` bleibt unberuehrt.

**Zwei Zeiten gegen zwei Temperaturen.** Die Schwellen sagen, was
*erwuenscht* ist; die Mindestzeiten sagen, was *erlaubt* ist. Bei
Widerspruch gewinnen die Zeiten — ausser bei einem Zwangs-AUS (siehe
unten). Ohne diesen Vorrang taktet ein Relais an einer Zone mit traegem
Istwert im Minutenabstand, und das ist mechanischer Verschleiss und
Kessel-Takten in einem (§0 S4).

**Der Zwangs-AUS bricht die Mindestlaufzeit.** Wenn der Istwert fehlt
oder veraltet ist (S5), muss das Relais aus — sofort, nicht nach Ablauf
einer Mindestlaufzeit. Sonst waere S5 eine Zusicherung, die neun Minuten
lang nicht gilt, und genau an so einer Lücke scheitert eine
Sicherheitsaussage. Deshalb ist ``ist`` hier ``Decimal | None`` und
``None`` ein eigener, dokumentierter Pfad.

**Entscheidung bei fehlendem Istwert: AUS.** Der Brief liess das offen;
nach der Entscheidungsregel die sicherere und kleinere Antwort. Die
Gegenvariante — letzten Zustand halten — heizt bei ausgefallenem Fuehler
**dauerhaft** weiter, und zwar unbemerkt, weil nichts sich mehr aendert.
Ein kaltes Zimmer ist ein Beschwerdefall, ein Panel, das ohne
Rueckmeldung durchheizt, ist ein Sicherheitsfall. Festgehalten in AE-78.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal


class Schaltbefehl(enum.StrEnum):
    """Was der Regler will. ``UNVERAENDERT`` ist ein Ergebnis, kein Fehler."""

    EIN = "ein"
    AUS = "aus"
    UNVERAENDERT = "unveraendert"


@dataclass(frozen=True, slots=True)
class ZweipunktSchwellen:
    """Die vier Parameter des Reglers.

    **Pflicht-Argument, kein Default.** Dieselbe Begruendung wie bei
    ``battery_stage_from_volts`` (§5.73): ein Default waere eine zweite
    Wahrheit neben der Konfiguration und liefe beim ersten Nachjustieren
    stumm auseinander. Gelesen wird einmal je Bewertung, nicht je Zone.
    """

    #: EIN, sobald ``ist <= soll - ein_delta_k``. Vorgabe 0,5 K.
    ein_delta_k: Decimal
    #: AUS, sobald ``ist >= soll + aus_delta_k``. Vorgabe 0,3 K.
    aus_delta_k: Decimal
    #: Mindestlaufzeit nach einem Einschalten.
    min_lauf: timedelta
    #: Mindestpause nach einem Ausschalten.
    min_pause: timedelta


@dataclass(frozen=True, slots=True)
class Zonenzustand:
    """Der Schaltzustand einer Zone, wie er zuletzt bestaetigt wurde.

    ``seit`` ist der Zeitpunkt, zu dem dieser Zustand **begonnen** hat —
    nicht der Zeitpunkt des letzten Befehls. Der Unterschied zaehlt: ein
    Waechter, der denselben Zustand auffrischt, verlaengert ihn, setzt
    ihn aber nicht neu, und die Mindestlaufzeit darf dadurch nicht von
    vorn beginnen.

    ``seit = None`` heisst „noch nie geschaltet" — dann greift keine
    Mindestzeit, weil es keine gibt.
    """

    ein: bool
    seit: datetime | None


@dataclass(frozen=True, slots=True)
class Entscheidung:
    """Ergebnis einer Bewertung.

    ``grund`` ist eine snake_case-Marke und landet im Audit. Sie ist
    bewusst maschinenlesbar und nicht als Satz formuliert: die
    Oberflaeche uebersetzt, das Audit vergleicht.
    """

    befehl: Schaltbefehl
    grund: str


def entscheide(
    *,
    ist: Decimal | None,
    soll: Decimal,
    zustand: Zonenzustand,
    schwellen: ZweipunktSchwellen,
    now: datetime,
    fuehler_veraltet: bool = False,
) -> Entscheidung:
    """Ein Schritt des Reglers fuer **eine** Zone.

    Reine Funktion: kein Datenbankzugriff, keine Wanduhr. ``now`` ist
    Pflicht, damit der Regler gegen feste Zeiten pruefbar ist, ohne die
    Zeit einzufrieren (§5.59 — ``freeze_time`` greift nicht in
    Fixtures).

    Reihenfolge der Pruefungen, und sie ist verbindlich:

    1. **Zwangs-AUS** — Istwert fehlt oder Fuehler veraltet. Bricht die
       Mindestlaufzeit (S5).
    2. **Mindestzeit** — laeuft noch, also kein Wechsel.
    3. **Schwellen** — EIN bei ``ist <= soll - ein_delta``, AUS bei
       ``ist >= soll + aus_delta``.
    4. Sonst: unveraendert. Das ist das **Totband** zwischen den
       Schwellen, und es ist der Normalfall.
    """
    # 1. Zwangs-AUS. Vor allem anderen, einschliesslich der Mindestzeit.
    if ist is None:
        return _aus_oder_unveraendert(zustand, "kein_istwert")
    if fuehler_veraltet:
        return _aus_oder_unveraendert(zustand, "fuehler_veraltet")

    # 2. Mindestzeiten. Sie gelten nur, wenn es einen Vorzustand gibt.
    if zustand.seit is not None:
        gehalten = now - zustand.seit
        if zustand.ein and gehalten < schwellen.min_lauf:
            return Entscheidung(
                Schaltbefehl.UNVERAENDERT,
                f"min_lauf_{int(schwellen.min_lauf.total_seconds())}s",
            )
        if not zustand.ein and gehalten < schwellen.min_pause:
            return Entscheidung(
                Schaltbefehl.UNVERAENDERT,
                f"min_pause_{int(schwellen.min_pause.total_seconds())}s",
            )

    # 3. Schwellen.
    ein_schwelle = soll - schwellen.ein_delta_k
    aus_schwelle = soll + schwellen.aus_delta_k

    if ist <= ein_schwelle:
        if zustand.ein:
            return Entscheidung(Schaltbefehl.UNVERAENDERT, "bereits_ein")
        return Entscheidung(Schaltbefehl.EIN, "unter_ein_schwelle")

    if ist >= aus_schwelle:
        if not zustand.ein:
            return Entscheidung(Schaltbefehl.UNVERAENDERT, "bereits_aus")
        return Entscheidung(Schaltbefehl.AUS, "ueber_aus_schwelle")

    # 4. Totband.
    return Entscheidung(Schaltbefehl.UNVERAENDERT, "im_totband")


def _aus_oder_unveraendert(zustand: Zonenzustand, grund: str) -> Entscheidung:
    """AUS, wenn es etwas abzuschalten gibt — sonst unveraendert.

    Ein ``AUS`` auf ein bereits ausgeschaltetes Relais waere ein
    Downlink ohne Wirkung, und jeder Downlink ist Sendezeit (§0 S4). Der
    **Grund** bleibt in beiden Faellen derselbe, damit das Audit die Lage
    beschreibt und nicht die Reaktion.
    """
    if zustand.ein:
        return Entscheidung(Schaltbefehl.AUS, grund)
    return Entscheidung(Schaltbefehl.UNVERAENDERT, grund)


def einschalt_versatz(index: int, versatz: timedelta) -> timedelta:
    """Wie lange das ``index``-te Relais einer Zone mit dem EIN wartet.

    **Nur beim Einschalten, nicht beim Ausschalten.** Der Versatz
    (Vorgabe 2 min) soll den Einschaltstrom mehrerer 1600-W-Panels
    auseinanderziehen. Beim Ausschalten gibt es keinen Grund zu warten —
    im Gegenteil: ein gestaffeltes AUS wuerde bei einem Zwangs-AUS (S5)
    die Zusicherung um Minuten verzoegern.

    Das erste Relais (``index = 0``) wartet nicht.
    """
    if index < 0:
        raise ValueError(f"index muss >= 0 sein, ist {index}")
    return versatz * index
