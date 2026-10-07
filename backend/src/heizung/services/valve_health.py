"""Regel 3 und 3b — reagiert das Ventil, und ist das Zimmer zu warm?

**Warum es diese Datei gibt, und warum sie vor dem 01.11. fertig sein muss.**

Bis Sprint 20e war Engine-Layer 4 der Melder fuer ein abgenommenes Geraet:
alle Vickis eines Zimmers melden ``attached_backplate=false`` -> Frostschutz.
Dieser Melder hat im Haus nicht funktioniert — der Taster meldet zu oft
``false``, obwohl das Geraet sitzt —, und 20e T4 hat ihn fuer Geraete mit
Montage-Nachweis stillgelegt.

**Damit ist er fuer genau die Geraete stillgelegt, bei denen er haette
anschlagen sollen.** Ein montiertes, belegt nachgewiesenes Geraet, das
spaeter tatsaechlich abfaellt, erkennt Layer 4 nicht mehr. Das ist der Preis
der Entscheidung vom 07.10.2026, er war bekannt, und diese Datei ist der
Ersatz.

Der Ersatz kann nicht derselbe Mechanismus sein, denn der Taster bleibt
unzuverlaessig. Er misst die **Wirkung** statt der Mechanik (§5.76):

**Regel 3b — Zimmer zu warm.** Ein Ventil ohne Kopf steht **voll offen**:
der Stift wird von der Feder herausgedrueckt, sobald der Thermostatkopf ab
ist. Ein abgenommenes Geraet fuehrt also nicht zu einem kalten, sondern zu
einem **heissen** Zimmer. Das ist messbar, ohne den Backplate-Taster
anzufassen — und es ist der Grund, warum 3b der eigentliche Ersatz fuer
Layer 4 ist und nicht eine Zugabe.

**Regel 3 — Ventil klemmt zu.** Die Gegenrichtung: Sollwert deutlich ueber
Ist, Ventil ueber das ganze Fenster geschlossen. Ein Zimmer, das nicht warm
wird, obwohl die Engine heizt.

Die beiden Bedingungen schliessen sich gegenseitig aus, solange beide Deltas
positiv sind: ``setpoint >= temp + a`` und ``temp >= setpoint + b`` koennen
nicht zugleich gelten. Es braucht deshalb **keine** Vorrangregel, und ein
Test haelt das fest — sonst waere die Reihenfolge der Abfragen im Code eine
stille Entscheidung.

**Zwei Dinge, die man ueber die Messgroessen wissen muss:**

1. ``temperature`` ist der **interne Vicki-Sensor**, nicht die
   Raumtemperatur. Er wird von der Heizkoerperwaerme mitgezogen; der
   Hersteller sagt das selbst (§5.27). Fuer **Regel 3** wirkt die Verzerrung
   in die harmlose Richtung — der gemessene Wert ist zu hoch, die Bedingung
   trifft also seltener zu, der Hinweis kommt eher zu selten als zu oft.
   Fuer **Regel 3b** wirkt sie in die unangenehme Richtung, deshalb steht
   deren Delta hoeher (Vorgabe 5 K statt 3 K) und ist eine **eigene**
   Einstellung.
2. ``valve_position = 0`` ist zweideutig: zu, oder nicht kalibriert. Fuer
   Regel 3 ist das kein Problem — bei ``setpoint >= temp + 3`` soll das
   Ventil offen sein, und beide Ursachen verdienen denselben Satz "Ventil
   pruefen". Der Hinweistext nennt deshalb beide Moeglichkeiten statt zu
   raten.

**Was ausdruecklich NICHT Bedingung von Regel 3b ist: die Ventilstellung.**
Naheliegend waere "Hinweis nur, wenn das Ventil auch offen gemeldet wird" —
das verliert genau den Hauptfall. Ein abgenommener Kopf meldet die
**Motorposition, die er zuletzt angefahren hat**; stand der Sollwert
niedrig, meldet er "geschlossen", waehrend das Ventil mechanisch voll offen
ist. Die Zusatzbedingung haette den Melder gegen seinen eigenen Zweck
abgedichtet.

**Wo gerechnet wird: read-time, kein Beat-Task.** Dasselbe Muster wie die
Batterie-Stufe (AE-72 §3): eine Aggregat-Query ueber das Fenster fuer
**alle** Geraete des Requests, vor der Schleife, Ergebnis als
Pflicht-Argument durchgereicht. Begruendung wie dort — kein persistierter
Zustand, der bei Ausfall des Taktgebers plausibel einfriert (§5.76), und
B-20c-4 ist genau dieser Fall.

**Kein Mailversand.** Gate-Entscheidung, und sie ist richtig: ein Hinweis in
der Oberflaeche, der manchmal zu viel zeigt, kostet einen Blick; eine Mail,
die manchmal zu viel zeigt, kostet die Glaubwuerdigkeit aller Mails (§5.79).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Literal

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from heizung.config import get_settings
from heizung.models.sensor_reading import SensorReading

ValveState = Literal["ok", "ventil_klemmt_zu", "zimmer_zu_warm", "unbekannt"]

# Mindest-Stichprobe im Fenster.
#
# Keine Einstellung, sondern eine Eigenschaft der Messung — dieselbe
# Unterscheidung wie bei ``BATTERY_MIN_SAMPLES``. Der regulaere Vicki-Uplink
# kommt alle ~10 min, ein 2-h-Fenster haelt also rund zwoelf Messwerte. Sechs
# ist die Haelfte davon: genug, dass ein Geraet nicht nach dem ersten Frame
# nach einem Neustart beurteilt wird, und wenig genug, dass ein Geraet mit
# halbem Funkloch noch bewertet wird.
#
# Ohne diese Grenze waere der schlimmste Fall ein Geraet, das genau einmal
# gemeldet hat — und dessen einzelner Frame dann als "das ganze Fenster
# erfuellt die Bedingung" gilt. Das ist formal richtig und fachlich unsinnig.
VALVE_MIN_SAMPLES = 6


@dataclass(frozen=True, slots=True)
class ValveSchwellen:
    """Die Grenzen beider Regeln als ein Wert.

    Zusammen und nicht als vier Argumente, aus demselben Grund wie bei
    ``BatterySchwellen`` und ``HealthSchwellen`` (AE-73): Werte, die
    gemeinsam eine Bewertung bilden, sollen nicht einzeln ersetzbar sein.

    Geprueft werden sie vom Settings-Validator beim Start
    (``config._ventil_schwellen_sind_sinnvoll``), an der einen Stelle, an der
    sie von aussen kommen.
    """

    stuck_delta_k: Decimal
    stuck_openness_max: int
    too_warm_delta_k: Decimal
    window_h: int


def valve_schwellen() -> ValveSchwellen:
    """Die konfigurierten Grenzen aus den Settings (T7/T10, Muster AE-73).

    Einmal pro Bewertung aufrufen, nicht pro Geraet.
    """
    settings = get_settings()
    return ValveSchwellen(
        stuck_delta_k=settings.valve_stuck_delta_k,
        stuck_openness_max=settings.valve_stuck_openness_max,
        too_warm_delta_k=settings.room_too_warm_delta_k,
        window_h=settings.valve_window_h,
    )


@dataclass(frozen=True, slots=True)
class ValveVerdict:
    """Ergebnis der Fenster-Bewertung fuer ein Geraet.

    ``samples`` ist die Zahl brauchbarer Messwerte im Fenster — also solche
    mit Sollwert **und** Ist-Temperatur. Sie steht im Verdict, damit die
    Oberflaeche "unbekannt" begruenden kann ("zu wenige Messwerte") statt
    einen Fehler zu suggerieren.

    ``delta_k`` ist der **gemessene** Abstand, der zum Urteil gehoert: bei
    ``ventil_klemmt_zu`` der kleinste ``setpoint - temperature`` im Fenster,
    bei ``zimmer_zu_warm`` der kleinste ``temperature - setpoint``. Also
    jeweils der knappste Wert, der die Bedingung noch erfuellt hat — nicht
    der Spitzenwert. Wer in der Oberflaeche eine Zahl neben den Hinweis
    stellt, nimmt diese: sie sagt, wie weit die Lage von der Schwelle weg
    ist, und ein Spitzenwert wuerde den Befund dramatischer darstellen, als
    er ist.
    """

    state: ValveState
    samples: int
    delta_k: Decimal | None = None


UNBEKANNT = ValveVerdict(state="unbekannt", samples=0)


async def valve_verdicts(
    session: AsyncSession,
    device_ids: Sequence[int],
    *,
    now: datetime | None = None,
) -> dict[int, ValveVerdict]:
    """Ventil-Urteil je Geraet aus dem Fenster (Regel 3 + 3b).

    **Eine Query, zwei Bedingungen.** Nicht zwei Queries: beide Regeln lesen
    dieselben Zeilen desselben Fensters, und zwei Durchgaenge waeren zwei
    Scans fuer eine Information. Umgesetzt mit zwei ``bool_and``-Aggregaten
    ueber denselben ``GROUP BY``.

    ``bool_and`` ist genau die Formulierung, die der Brief verlangt — "das
    Fenster **vollstaendig**, nicht im Mittel". Ein Durchschnitt haette den
    Aufheiz-Peak nach einer Nachtabsenkung als Befund gelesen; mit
    ``bool_and`` faellt ein einziger Messwert, der die Bedingung nicht
    erfuellt, das ganze Urteil.

    Args:
        session: Aktive Session. Nur lesend, kein Commit (§5.61).
        device_ids: Die zu bewertenden Geraete. Leer -> keine Query.
        now: Fenster-Ende. Default ``datetime.now(UTC)``.

    Returns:
        Ein Eintrag **je uebergebener ID**, auch ohne Messwerte (dann
        ``UNBEKANNT``). Damit kann ein fehlender Schluessel beim Aufrufer
        nicht still zu "ok" werden.
    """
    if not device_ids:
        return {}

    jetzt = now or datetime.now(tz=UTC)
    schwellen = valve_schwellen()
    seit = jetzt - timedelta(hours=schwellen.window_h)
    ids = list(device_ids)

    # Regel 3: Sollwert deutlich ueber Ist UND Ventil zu — ueber jeden
    # einzelnen Messwert des Fensters.
    klemmt_zu = and_(
        SensorReading.setpoint >= SensorReading.temperature + schwellen.stuck_delta_k,
        SensorReading.valve_position <= schwellen.stuck_openness_max,
    )
    # Regel 3b: Ist deutlich ueber Sollwert. **Ohne** Ventil-Bedingung, siehe
    # Modul-Docstring — sie haette den Hauptfall verloren.
    zu_warm = SensorReading.temperature >= SensorReading.setpoint + schwellen.too_warm_delta_k

    stmt = (
        select(
            SensorReading.device_id,
            func.count().label("samples"),
            func.bool_and(klemmt_zu).label("klemmt_zu"),
            func.bool_and(zu_warm).label("zu_warm"),
            # Die knappsten gemessenen Abstaende, fuer die Diagnose-Zahl.
            # Im selben Durchgang, kein zweiter Roundtrip.
            func.min(SensorReading.setpoint - SensorReading.temperature).label(
                "min_soll_minus_ist"
            ),
            func.min(SensorReading.temperature - SensorReading.setpoint).label(
                "min_ist_minus_soll"
            ),
        )
        .where(SensorReading.device_id.in_(ids))
        .where(SensorReading.time >= seit)
        # Beide Groessen muessen da sein, sonst ist die Zeile fuer diese
        # Bewertung kein Messwert. Ein Reply-Frame ohne Ist-Temperatur darf
        # ein Fenster nicht verwaessern — und er darf es auch nicht
        # abwerten, denn ``bool_and`` ueber NULL waere NULL.
        .where(SensorReading.setpoint.is_not(None))
        .where(SensorReading.temperature.is_not(None))
        # Regel 3 braucht ausserdem die Ventilstellung. Sie hier
        # mitzufiltern waere falsch: Regel 3b braucht sie nicht, und ein
        # Geraet ohne Ventilwerte wuerde sonst auch fuer 3b unbewertbar.
        # Stattdessen traegt ``klemmt_zu`` den NULL-Fall selbst — siehe
        # unten.
        .group_by(SensorReading.device_id)
    )

    ergebnis: dict[int, ValveVerdict] = dict.fromkeys(ids, UNBEKANNT)

    for row in (await session.execute(stmt)).all():
        device_id = int(row.device_id)
        samples = int(row.samples)

        if samples < VALVE_MIN_SAMPLES:
            ergebnis[device_id] = ValveVerdict(state="unbekannt", samples=samples)
            continue

        # ``bool_and`` liefert NULL, wenn **jeder** Eingabewert NULL ist —
        # bei Regel 3 also, wenn im ganzen Fenster keine Ventilstellung
        # gemeldet wurde. NULL ist hier "keine Aussage" und nicht "wahr";
        # der ``is True``-Vergleich behandelt beides richtig und ist der
        # Grund, warum hier nicht ``if row.klemmt_zu:`` steht.
        if row.klemmt_zu is True:
            ergebnis[device_id] = ValveVerdict(
                state="ventil_klemmt_zu",
                samples=samples,
                delta_k=row.min_soll_minus_ist,
            )
        elif row.zu_warm is True:
            ergebnis[device_id] = ValveVerdict(
                state="zimmer_zu_warm",
                samples=samples,
                delta_k=row.min_ist_minus_soll,
            )
        else:
            ergebnis[device_id] = ValveVerdict(state="ok", samples=samples)

    return ergebnis
