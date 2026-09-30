"""Batterie als additive Health-Dimension (AE-65, ab Sprint 20 AE-72).

Zwei Teile in einer Datei, weil es ein Begriff ist:

1. **Reine Schwellen-Logik** — Konstanten plus ``battery_stage_from_volts``
   (AE-72). Kein I/O, direkt testbar.
2. **Die Bewertung ueber das Fenster** — ``battery_verdicts`` liest
   ``sensor_reading.battery_voltage`` der letzten 24 h und bildet den
   Median. Session-gebunden, eine Aggregat-Query fuer alle Geraete.

Read-time abgeleitet, nicht persistiert: kein Beat-Task, keine zweite
Wahrheit, kein Zustand der bei Ausfall des Taktgebers plausibel einfriert
(§5.73 — "wenn ein Wert deterministisch aus vorhandenen Daten ableitbar
ist, read-time im Schema-Assembler ableiten statt persistieren").

Eine **orthogonale dritte Achse** neben dem persistierten ``device.health_state``
(offline/implausible, AE-53): ``battery_state`` wird NICHT in ``health_state``
gefaltet, sondern als eigenes Read-Feld in ``DeviceRead`` exponiert
(``api/v1/devices.py``) und vom Dashboard-Aggregat ``battery_low_count``
(``services/dashboard_aggregates.py``) konsumiert. Die offline/implausible-
Pfade in ``tasks/health_tasks.py`` bleiben unangetastet.

Schwellen (AE-72), Eingangsgroesse ist der 24-h-Median der Spannung:
  ok        : >= BATTERY_OK_MIN_V (3.0 V)
  warn      : dazwischen — genau ein Rasterschritt (2.9 V)
  kritisch  : <= BATTERY_CRITICAL_MAX_V (2.8 V)
  unbekannt : Mindest-Stichprobe im Fenster nicht erreicht

**Was Sprint 20 entfernt hat:** ``battery_health_state`` (Prozent) und mit
ihm die konfigurierbare Schwelle ``global_config.alert_battery_warn_percent``
samt der fixen ``BATTERY_CRITICAL_PCT``-Grenze. Die Prozent-Achse war aus
einem 0.1-V-Raster interpoliert und im oberen Bereich vom Codec gesaettigt
(AE-64, §5.72) — die Schwellen liegen jetzt dort, wo die Messgroesse ist.

Die Spalte ``sensor_reading.battery_percent`` wird weiter geschrieben
(Rueckfallpfad fuer ein Rollback), hat aber keinen Lesepfad mehr; der
Vermerk dazu steht im Docstring von ``mqtt_subscriber._battery_pct_from_volts``.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import aggregate_order_by
from sqlalchemy.ext.asyncio import AsyncSession

from heizung.models.sensor_reading import SensorReading

# ---------------------------------------------------------------------------
# Sprint 20 (AE-72): die Stufen rechnen auf der Spannung, nicht auf Prozent
# ---------------------------------------------------------------------------
#
# Warum die Umstellung: Der Codec liefert die Geraete-Spannung in einem
# 4-Bit-Nibble, also in 0.1-V-Schritten von 2.0 bis 3.5 V
# (``mclimate-vicki.js:119-121``). Die Kennlinie ``BATTERY_CURVE_2XAA``
# uebersetzt das in Prozent — aus neun moeglichen Eingaben werden neun
# moegliche Ausgaben (0/10/30/50/65/80/87/93/100). Eine zweistellige
# Prozentzahl sieht nach Aufloesung aus, die es nicht gibt (AE-64,
# CLAUDE.md §5.72), und oberhalb ~3.4 V saettigt der Codec ohnehin.
#
# Die Schwellen in Volt sind ausserdem **unabhaengig vom Batterietyp**:
# Lithium ab Werk, Alkaline beim spaeteren Tausch durch den Hausmeister.
# Eine Prozent-Kennlinie ist immer fuer genau einen Zelltyp kalibriert —
# die unsere fuer 2xAA-Alkaline.
#
# Herleitung der Werte (Anforderung Hotel: volle Batterie nie als leer,
# haeufigerer Tausch akzeptiert):
#
#   OK        >= 3.0 V   frische Alkaline liegt bei 3.1 V, frische Lithium
#                        am Codec-Anschlag 3.5 V — beide mit Reserve
#   schwach    = 2.9 V   genau EIN Rasterschritt breit; mehr gibt das
#                        0.1-V-Raster zwischen den beiden Grenzen nicht her
#   kritisch  <= 2.8 V   Hersteller-Wechselempfehlung ist "< 2.8 V"
#                        (docs/ARCHITEKTUR-ENTSCHEIDUNGEN.md:2539); wir
#                        warnen eine Quantisierungsstufe frueher
#
# Der Betriebsbereich der Spec ist 2.7-3.6 VDC. Die Kritisch-Grenze liegt
# also 0.1 V ueber dem Geraete-Minimum: wer bei "kritisch" wechselt, kommt
# dem Ausfall zuvor statt ihn zu bestaetigen.
#
# Verworfen wurde OK >= 3.1 / schwach 3.0 / kritisch <= 2.9 (erster
# Vorschlag): 3.1 V **ist** der frische Alkaline-Zustand. Eine Grenze
# genau dort laesst jedes Alkaline-Geraet ab dem ersten Rasterschritt
# dauerhaft "schwach" melden — und ein Melder, dem niemand mehr glaubt,
# ueberwacht nichts (CLAUDE.md §5.79). Der 24-h-Median filtert zudem den
# Lastabfall heraus, gegen den die hoehere Grenze schuetzen sollte.
#
# ``Decimal``, nicht ``float``: 2.9 hat in IEEE-754 keine exakte
# Darstellung, und der Vergleich laeuft genau auf diesem Rasterpunkt.
# Gleiche Begruendung wie bei ``BATTERY_CURVE_2XAA``.
BATTERY_OK_MIN_V = Decimal("3.0")
BATTERY_CRITICAL_MAX_V = Decimal("2.8")

# Mindest-Stichprobe im Bewertungs-Fenster. Unter drei Messwerten gibt es
# keinen belastbaren Median — ein einzelner Frame kann ein Lastabfall waehrend
# einer Motorbewegung sein (Geraet 001 am 29.09.: klemmendes Ventil,
# ``lowMotorConsumption``, Einbruch unter den Kritisch-Wert). Weniger als drei
# Werte ergeben "unbekannt", nicht "kritisch".
BATTERY_MIN_SAMPLES = 3

# Sprung nach oben, ab dem ein Batteriewechsel angenommen wird. Zwei
# Rasterschritte plus einer: 0.2 V waere noch als Messrauschen zwischen zwei
# Nibble-Stufen erklaerbar, 0.3 V nicht mehr. Entladung geht nie so schnell
# nach oben — nur ein Wechsel tut das.
BATTERY_JUMP_V = Decimal("0.3")

BatteryHealthState = Literal["ok", "warn", "kritisch", "unbekannt"]


def battery_stage_from_volts(volts: Decimal | None) -> BatteryHealthState:
    """Reine Abbildung Geraete-Spannung -> Batterie-Stufe (AE-72).

    Die Reihenfolge ist verbindlich: ``unbekannt`` vor ``kritisch`` vor
    ``warn`` vor ``ok``. Beide Grenzen sind **inklusiv auf ihrer Seite** —
    2.8 V ist kritisch, 3.0 V ist ok. Dazwischen liegt genau ein
    Rasterschritt (2.9 V) und der ist ``warn``.

    Die vier Zustaende sind dieselben wie in AE-65; nur die Eingangsgroesse
    wechselt von Prozent auf Volt (die Prozent-Variante ist mit Sprint 20
    entfallen). Das Frontend-Spiegelbild
    (``BatteryHealthState`` in ``lib/api/types.ts``) bleibt damit
    unveraendert.

    Args:
        volts: Median der Geraete-Spannung im Bewertungs-Fenster, oder
            ``None`` wenn die Mindest-Stichprobe nicht erreicht ist.

    Returns:
        ``"unbekannt"`` bei ``None``, sonst ``"kritisch"``/``"warn"``/``"ok"``.
    """
    if volts is None:
        return "unbekannt"
    if volts <= BATTERY_CRITICAL_MAX_V:
        return "kritisch"
    if volts < BATTERY_OK_MIN_V:
        return "warn"
    return "ok"


# ---------------------------------------------------------------------------
# Bewertungs-Fenster (AE-72)
# ---------------------------------------------------------------------------
#
# 24 Stunden. Der regulaere Vicki-Uplink kommt alle ~10 min, das Fenster
# haelt also rund 144 Messwerte je Geraet. Es geht nicht um Statistik,
# sondern um EINEN Effekt: die Spannung eines Alkaline-Paars bricht unter
# Motorlast ein, und die Anzeige stammte bisher aus dem letzten Frame. Ein
# Median ueber einen Tag laesst den Einbruch nicht durch.
BATTERY_WINDOW_H = 24


@dataclass(frozen=True, slots=True)
class BatteryVerdict:
    """Ergebnis der Fenster-Bewertung fuer ein Geraet.

    ``median_v`` ist die Zahl, die zur Stufe gehoert — **nicht** der letzte
    Messwert. Wer in der Oberflaeche die Stufe neben eine Spannung stellt,
    nimmt diese hier, sonst widerspricht der Badge sich selbst (Stufe aus
    dem Median, Zahl aus einem Ausreisser).

    ``jump_at`` ist gesetzt, wenn ein Batteriewechsel erkannt wurde: dann
    zaehlt nur das Fenster ab diesem Messwert, und ``samples`` ist
    entsprechend klein. Solange die Mindest-Stichprobe darin nicht erreicht
    ist, steht die Stufe auf ``unbekannt`` — mit ``jump_at`` kann die
    Oberflaeche den Grund nennen statt einen Fehler zu suggerieren.
    """

    stage: BatteryHealthState
    median_v: Decimal | None
    samples: int
    jump_at: datetime | None = None


UNBEKANNT = BatteryVerdict(stage="unbekannt", median_v=None, samples=0)


def oberer_median(werte: Sequence[Decimal]) -> Decimal:
    """Median; bei gerader Stichprobe der **hoehere** der beiden Mittelwerte.

    Die Vorgabe lautet "volle Batterie nie als leer" — das gilt auch an der
    Rundungskante. Bei vier Werten 2.8/2.9/3.0/3.1 ist der uebliche Median
    2.95, ein Wert, den das 0.1-V-Raster nicht kennt und der zwischen zwei
    Stufen liegt. Statt zu runden wird der obere Mittelwert genommen: 3.0.

    ``sorted(...)[n // 2]`` liefert genau das — bei n=4 den Index 2 (also
    den dritten Wert, den oberen der beiden mittleren), bei n=5 den Index 2
    (den echten Median). Es ist dieselbe Auswahl, die
    ``percentile_disc(0.5) WITHIN GROUP (ORDER BY ... DESC)`` in Postgres
    trifft; ein DB-Test haelt beide Wege gegeneinander.

    Raises:
        IndexError: bei leerer Eingabe. Aufrufer pruefen die Stichprobe
            vorher gegen ``BATTERY_MIN_SAMPLES``.
    """
    return sorted(werte)[len(werte) // 2]


async def battery_verdicts(
    session: AsyncSession,
    device_ids: Sequence[int],
    *,
    now: datetime | None = None,
) -> dict[int, BatteryVerdict]:
    """Batterie-Stufe je Geraet aus dem 24-h-Median (AE-72).

    Eine Aggregat-Query fuer **alle** uebergebenen Geraete, nicht eine pro
    Geraet: die Geraeteliste rendert 104 Zeilen, und ``_build_device_read``
    laeuft dort in einer Schleife (die dortigen zwei Queries pro Geraet sind
    als N+1 bewusst akzeptiert — ein dritter kaeme auf 312 Roundtrips).

    Ein zweiter, kleiner Durchgang folgt nur fuer die Geraete, bei denen ein
    Batteriewechsel erkannt wurde. Im Normalbetrieb ist das die leere Menge.

    Zeitquelle ist ein einfacher ``now``-Parameter und nicht die
    ``Clock``-Struktur aus ``scripts/pairing/clock.py``: hier wird nichts
    abgewartet, es gibt also keine Schleife, die man halb faelschen koennte
    (§5.82 betrifft Warte-Schleifen, nicht Zeitpunkt-Vergleiche).

    Args:
        session: Aktive Session. Nur lesend, kein Commit (§5.61).
        device_ids: Die zu bewertenden Geraete. Leer -> keine Query.
        now: Fenster-Ende. Default ``datetime.now(UTC)``.

    Returns:
        Ein Eintrag **je uebergebener ID**, auch wenn das Geraet keine
        Messwerte hat (dann ``UNBEKANNT``). Damit kann kein fehlender
        Schluessel beim Aufrufer still zu "ok" werden.
    """
    if not device_ids:
        return {}

    jetzt = now or datetime.now(tz=UTC)
    seit = jetzt - timedelta(hours=BATTERY_WINDOW_H)
    ids = list(device_ids)

    # percentile_disc(0.5) mit ABSTEIGENDER Ordnung ist der obere Median:
    # die Funktion nimmt den ersten Wert, dessen kumulierter Anteil >= 0.5
    # erreicht. Bei vier Werten ist das der zweite von oben — also der
    # hoehere der beiden mittleren. Genau die Vorgabe, in einer Zeile.
    median_ausdruck = func.percentile_disc(0.5).within_group(SensorReading.battery_voltage.desc())
    # Der juengste Messwert im selben Durchgang: array_agg nach Zeit
    # absteigend, davon das erste Element. Kein zweiter Roundtrip, und der
    # Wert wird ausschliesslich fuer die Sprung-Erkennung gebraucht.
    letzter_ausdruck = func.array_agg(
        aggregate_order_by(SensorReading.battery_voltage, SensorReading.time.desc())
    )[1]

    stmt = (
        select(
            SensorReading.device_id,
            median_ausdruck.label("median_v"),
            func.count().label("samples"),
            letzter_ausdruck.label("letzter_v"),
        )
        .where(SensorReading.device_id.in_(ids))
        .where(SensorReading.time >= seit)
        .where(SensorReading.battery_voltage.is_not(None))
        .group_by(SensorReading.device_id)
    )

    ergebnis: dict[int, BatteryVerdict] = dict.fromkeys(ids, UNBEKANNT)
    sprung_kandidaten: dict[int, Decimal] = {}

    for row in (await session.execute(stmt)).all():
        device_id = int(row.device_id)
        median_v = row.median_v
        samples = int(row.samples)
        letzter_v = row.letzter_v
        if median_v is None:
            continue

        # Sprung nach oben = Batteriewechsel. Verglichen wird der juengste
        # Messwert gegen den Median, NICHT Median gegen Median: ein 24-h-
        # Median bewegt sich nach einem Wechsel erst, wenn die neuen Werte
        # in der Mehrheit sind — das dauert einen halben Tag, und "sofort"
        # waere dann eine Behauptung.
        if letzter_v is not None and letzter_v - median_v >= BATTERY_JUMP_V:
            sprung_kandidaten[device_id] = median_v
            continue

        ergebnis[device_id] = BatteryVerdict(
            stage=(
                battery_stage_from_volts(median_v)
                if samples >= BATTERY_MIN_SAMPLES
                else "unbekannt"
            ),
            median_v=median_v,
            samples=samples,
        )

    for device_id, alter_median in sprung_kandidaten.items():
        ergebnis[device_id] = await _verdict_nach_sprung(
            session, device_id, seit=seit, alter_median=alter_median
        )

    return ergebnis


async def _verdict_nach_sprung(
    session: AsyncSession,
    device_id: int,
    *,
    seit: datetime,
    alter_median: Decimal,
) -> BatteryVerdict:
    """Bewertung nur ueber die Messwerte ab dem Sprung.

    Der Sprung ist der aelteste Messwert einer **zusammenhaengenden** Reihe
    am oberen Ende, die den alten Median um mindestens ``BATTERY_JUMP_V``
    uebersteigt. Rueckwaerts gelesen: von jetzt nach hinten, bis der erste
    Wert kommt, der das nicht mehr tut — dort war die alte Batterie.

    Die Reihe kann nie das ganze Fenster umfassen: der Median ist selbst
    einer der Werte und liegt damit unter der Schwelle. Es bleibt also immer
    ein Rest, an dem die Schleife endet.

    Sind es weniger als ``BATTERY_MIN_SAMPLES`` Werte, bleibt die Stufe
    ``unbekannt`` — mit gesetztem ``jump_at``, damit die Oberflaeche
    "Batteriewechsel erkannt" sagen kann statt zu schweigen. Bei einem
    Uplink alle 10 Minuten ist das eine halbe Stunde.
    """
    schwelle = alter_median + BATTERY_JUMP_V
    stmt = (
        select(SensorReading.time, SensorReading.battery_voltage)
        .where(SensorReading.device_id == device_id)
        .where(SensorReading.time >= seit)
        .where(SensorReading.battery_voltage.is_not(None))
        .order_by(SensorReading.time.desc())
    )

    werte: list[Decimal] = []
    jump_at: datetime | None = None
    for row in (await session.execute(stmt)).all():
        volts = row.battery_voltage
        if volts is None or volts < schwelle:
            break
        werte.append(volts)
        jump_at = row.time

    if not werte:
        # Nur moeglich, wenn zwischen den beiden Queries ein Frame
        # dazugekommen ist. Kein Grund fuer eine Ausnahme — der naechste
        # Request bewertet neu.
        return UNBEKANNT

    median = oberer_median(werte)
    return BatteryVerdict(
        stage=(
            battery_stage_from_volts(median) if len(werte) >= BATTERY_MIN_SAMPLES else "unbekannt"
        ),
        median_v=median,
        samples=len(werte),
        jump_at=jump_at,
    )
