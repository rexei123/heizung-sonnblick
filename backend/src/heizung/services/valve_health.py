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

from sqlalchemy import (
    CTE,
    ColumnElement,
    Numeric,
    and_,
    case,
    cast,
    distinct,
    func,
    literal,
    select,
    true,
)
from sqlalchemy.ext.asyncio import AsyncSession

from heizung.config import get_settings
from heizung.models.device import Device
from heizung.models.enums import RoomStatus
from heizung.models.heating_zone import HeatingZone
from heizung.models.room import Room
from heizung.models.sensor_reading import SensorReading

ValveState = Literal["ok", "ventil_klemmt_zu", "zimmer_zu_warm", "unbekannt"]

# Worauf das relative Urteil von Regel 3b fusst (Sprint 20e-b).
#
# ``keine`` ist kein Fehler, sondern eine Aussage: die Referenzmenge war zu
# klein, also gibt es **kein** 3b-Urteil. Benannt und nicht impliziert, damit
# die Oberflaeche "warum kein Hinweis" beantworten kann.
ValveReferenz = Literal["unbelegt", "alle", "keine"]

# Der Median wird auf ``Numeric`` gegossen, nicht als ``double precision``
# gelassen. ``percentile_cont`` nimmt in Postgres ``double precision``, und
# verglichen wird gegen ``Numeric(5,2)`` aus ``sensor_reading`` — ohne Cast
# mischt die Abfrage Gleitkomma und Festkomma, und der Vergleich an der
# Schwelle entscheidet sich im letzten Bit. Dieselbe Begruendung wie bei den
# ``Decimal``-Schwellen in den Settings.
#
# Drei Nachkommastellen, weil ``percentile_cont`` bei gerader Anzahl
# interpoliert: der Median von 21,7 und 21,8 ist 21,75.
_MEDIAN_TYP = Numeric(6, 3)

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
    rel_delta_k: Decimal
    rel_delta_all_k: Decimal
    ref_min_rooms: int


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
        rel_delta_k=settings.room_rel_delta_k,
        rel_delta_all_k=settings.room_rel_delta_all_k,
        ref_min_rooms=settings.ref_min_rooms,
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

    ``referenz`` und ``referenz_median_c`` sagen, **gegen was** Regel 3b
    verglichen hat — die Rueckfallkette aus Sprint 20e-b waehlt die
    Referenzmenge je nach Belegung, und ohne diese Angabe muesste ein
    Hausmeister raten. ``referenz_delta_k`` ist der knappste gemessene
    Abstand zu diesem Median, dieselbe Lesart wie ``delta_k``.

    Diese drei Felder sind bei **jedem** Urteil gefuellt, nicht nur bei
    ``zimmer_zu_warm``: wer wissen will, warum ein offensichtlich warmes
    Zimmer *keinen* Hinweis traegt, braucht die Referenz gerade dann.
    """

    state: ValveState
    samples: int
    delta_k: Decimal | None = None
    referenz: ValveReferenz = "keine"
    referenz_median_c: Decimal | None = None
    referenz_delta_k: Decimal | None = None


UNBEKANNT = ValveVerdict(state="unbekannt", samples=0)


def _referenz_cte(seit: datetime, schwellen: ValveSchwellen) -> CTE:
    """Die Rueckfallkette als **ein** CTE: Median, Delta und Name der Referenz.

    **Was gemessen wird, und warum genau das.** Der Median laeuft ueber die
    einzelnen **Messwerte** des Fensters, nicht ueber Zimmer-Mittelwerte. Das
    ist nicht die elegantere, sondern die kalibrierte Groesse: die
    T0-Messung vom 08.10.2026 (Brief §5) hat ``percentile_cont(0.5) WITHIN
    GROUP (ORDER BY temperature)`` ueber dieselbe Menge gerechnet, und die
    Vorgabe 3,5 K stammt aus ihrer Spalte ``ueber_median``. Eine andere
    Aggregation waere eine andere Zahl — und das Delta waere wieder geraten.

    Die **Zimmer** werden getrennt gezaehlt (``count(distinct room_id)``),
    weil die Mindestzahl eine Aussage ueber die Stichprobe macht: zwoelf
    Messwerte aus zwei Zimmern sind zwei Zimmer.

    **Die Kette (drei Stufen, Brief §3):**

    1. Nicht belegte Zimmer, wenn mindestens ``ref_min_rooms`` davon da
       sind -> ``rel_delta_k``
    2. **Alle** Zimmer, wenn Stufe 1 nicht reicht -> ``rel_delta_all_k``
    3. Sonst: Median ``NULL``, Name ``keine`` -> **kein** 3b-Urteil

    Stufe 3 fuehrt deshalb zu keinem Hinweis, weil ein Vergleich gegen
    ``NULL`` in SQL ``NULL`` ergibt und ``bool_and`` darueber ebenfalls
    ``NULL`` — der ``is True``-Vergleich im Aufrufer behandelt das schon
    richtig. Das ist kein glueklicher Zufall, sondern dieselbe
    NULL-Disziplin, die Regel 3 fuer fehlende Ventilwerte braucht.

    **Nicht** auf den absoluten Hinweis zurueckfallen, wenn die Referenz
    fehlt: das waere der Zustand vom 07.10. mit 14 Falsch-Alarmen, nur
    seltener und damit unberechenbar. Lieber eine Luecke, die man kennt.

    **``status <> 'occupied'`` und nicht ``== 'vacant'``.** Ein reserviertes
    oder gerade gereinigtes Zimmer ist thermisch kein belegtes, und die
    T0-Messung hat genau so gefiltert. Belegte Zimmer sind eine andere
    Population (Brief §2 G5): Gaeste stellen 22-24 °C ein, ein Median
    darueber hebt die Huerde genau dann, wenn ohnehin niemand nachsieht.

    **Annahme, ausgesprochen (Brief §2 G4):** Der Median traegt bis zu 50 %
    Verunreinigung. Sitzen nach einer Reinigungsrunde mehrere Koepfe ab, sind
    diese Zimmer heiss und heben den Median — er verdeckt dann genau den
    Fehler, den er finden soll. Bei mehr als der Haelfte betroffener Zimmer
    ist dieses Kriterium blind, und kein Code hier aendert das. Ein Test
    haelt die Grenze fest, damit sie eine Aussage bleibt und nicht ein
    Nebeneffekt.
    """
    # Das Fenster, einmal, mit Zimmer-Bezug. ``retired_at IS NULL``, weil ein
    # abgemeldetes Geraet keine Aussage ueber ein Zimmer mehr macht (§5.58).
    # Pool-Geraete fallen ueber den Join heraus — sie haengen an keinem
    # Zimmer und koennen daher keine Referenz bilden.
    fenster = (
        select(
            SensorReading.temperature.label("temperature"),
            Room.id.label("room_id"),
            Room.status.label("status"),
        )
        .join(Device, Device.id == SensorReading.device_id)
        .join(HeatingZone, HeatingZone.id == Device.heating_zone_id)
        .join(Room, Room.id == HeatingZone.room_id)
        .where(Device.retired_at.is_(None))
        .where(SensorReading.time >= seit)
        .where(SensorReading.temperature.is_not(None))
        # Dieselbe Bedingung wie in der Hauptabfrage: eine Zeile ohne
        # Sollwert ist fuer diese Bewertung kein Messwert, auch nicht in der
        # Referenz. Sonst waere die Referenz ueber einer anderen Menge
        # gebildet als das Urteil.
        .where(SensorReading.setpoint.is_not(None))
        .cte("fenster")
    )

    def _referenz(name: str, *bedingungen: ColumnElement[bool]) -> CTE:
        stmt = select(
            cast(func.percentile_cont(0.5).within_group(fenster.c.temperature), _MEDIAN_TYP).label(
                "median"
            ),
            func.count(distinct(fenster.c.room_id)).label("zimmer"),
        )
        for bedingung in bedingungen:
            stmt = stmt.where(bedingung)
        return stmt.cte(name)

    # Eine Aggregat-Abfrage ohne GROUP BY liefert **immer** genau eine Zeile,
    # bei leerer Menge mit ``median = NULL`` und ``zimmer = 0``. Der
    # Cross-Join unten hat damit nie null Zeilen, und Stufe 3 greift von
    # selbst — ohne Sonderfall im Python-Code.
    ref_unbelegt = _referenz("ref_unbelegt", fenster.c.status != RoomStatus.OCCUPIED)
    ref_alle = _referenz("ref_alle")

    genug_unbelegt = ref_unbelegt.c.zimmer >= schwellen.ref_min_rooms
    genug_alle = ref_alle.c.zimmer >= schwellen.ref_min_rooms

    return (
        select(
            case(
                (genug_unbelegt, ref_unbelegt.c.median),
                (genug_alle, ref_alle.c.median),
                else_=literal(None, _MEDIAN_TYP),
            ).label("median"),
            case(
                (genug_unbelegt, literal(schwellen.rel_delta_k, _MEDIAN_TYP)),
                (genug_alle, literal(schwellen.rel_delta_all_k, _MEDIAN_TYP)),
                else_=literal(None, _MEDIAN_TYP),
            ).label("delta"),
            case(
                (genug_unbelegt, literal("unbelegt")),
                (genug_alle, literal("alle")),
                else_=literal("keine"),
            ).label("referenz"),
        )
        .select_from(ref_unbelegt)
        .join(ref_alle, true())
        .cte("gewaehlt")
    )


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

    gewaehlt = _referenz_cte(seit, schwellen)

    # Regel 3: Sollwert deutlich ueber Ist UND Ventil zu — ueber jeden
    # einzelnen Messwert des Fensters.
    klemmt_zu = and_(
        SensorReading.setpoint >= SensorReading.temperature + schwellen.stuck_delta_k,
        SensorReading.valve_position <= schwellen.stuck_openness_max,
    )
    # Regel 3b, erste Bedingung: Ist deutlich ueber Sollwert. **Ohne**
    # Ventil-Bedingung, siehe Modul-Docstring — sie haette den Hauptfall
    # verloren.
    zu_warm = SensorReading.temperature >= SensorReading.setpoint + schwellen.too_warm_delta_k
    # Regel 3b, zweite Bedingung (20e-b): auch ueber vergleichbaren Zimmern.
    # Gegen ``NULL`` (Stufe 3 der Kette) ergibt der Vergleich ``NULL``, und
    # ``bool_and`` darueber ebenfalls — also kein Urteil, kein Hinweis.
    ueber_referenz = SensorReading.temperature >= gewaehlt.c.median + gewaehlt.c.delta

    stmt = (
        select(
            SensorReading.device_id,
            func.count().label("samples"),
            func.bool_and(klemmt_zu).label("klemmt_zu"),
            func.bool_and(zu_warm).label("zu_warm"),
            func.bool_and(ueber_referenz).label("ueber_referenz"),
            # Die knappsten gemessenen Abstaende, fuer die Diagnose-Zahl.
            # Im selben Durchgang, kein zweiter Roundtrip.
            func.min(SensorReading.setpoint - SensorReading.temperature).label(
                "min_soll_minus_ist"
            ),
            func.min(SensorReading.temperature - SensorReading.setpoint).label(
                "min_ist_minus_soll"
            ),
            func.min(SensorReading.temperature - gewaehlt.c.median).label("min_ueber_median"),
            gewaehlt.c.median.label("referenz_median"),
            gewaehlt.c.referenz.label("referenz"),
        )
        .select_from(SensorReading)
        # Cross-Join auf eine Ein-Zeilen-CTE: die Referenz gilt fuer alle
        # Geraete gleich. Kein Unterabfrage-je-Zeile, der Planer liest die
        # CTE einmal.
        #
        # Die Referenz steht ausserdem bewusst **nicht** unter
        # ``device_ids``: sie ist hausweit. Ein Request, der nur ein Geraet
        # bewertet, muss gegen dasselbe Haus vergleichen wie die
        # Geraeteliste, sonst haengt das Urteil davon ab, wo man hinsieht.
        .join(gewaehlt, true())
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
        #
        # Median und Referenz-Name stehen mit im GROUP BY, nicht in einem
        # ``max()``: sie sind je Lauf konstant, und ``max()`` ueber eine
        # Konstante waere ein Trick, den ein Leser erst entschluesseln muss.
        .group_by(SensorReading.device_id, gewaehlt.c.median, gewaehlt.c.referenz)
    )

    ergebnis: dict[int, ValveVerdict] = dict.fromkeys(ids, UNBEKANNT)

    for row in (await session.execute(stmt)).all():
        device_id = int(row.device_id)
        samples = int(row.samples)
        # Bei jedem Urteil mitgegeben, auch bei "ok" und "unbekannt" — wer
        # wissen will, warum ein warmes Zimmer *keinen* Hinweis traegt,
        # braucht die Referenz gerade dann.
        referenz: ValveReferenz = row.referenz
        median = row.referenz_median

        if samples < VALVE_MIN_SAMPLES:
            ergebnis[device_id] = ValveVerdict(
                state="unbekannt",
                samples=samples,
                referenz=referenz,
                referenz_median_c=median,
            )
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
                referenz=referenz,
                referenz_median_c=median,
            )
        # Regel 3b ab 20e-b: **beide** Bedingungen, mit UND. Die zweite
        # fehlt, wenn die Referenzmenge zu klein war — dann ist
        # ``ueber_referenz`` NULL und das Urteil faellt auf "ok", nicht auf
        # den alten absoluten Hinweis. Siehe ``_referenz_cte``.
        elif row.zu_warm is True and row.ueber_referenz is True:
            ergebnis[device_id] = ValveVerdict(
                state="zimmer_zu_warm",
                samples=samples,
                delta_k=row.min_ist_minus_soll,
                referenz=referenz,
                referenz_median_c=median,
                referenz_delta_k=row.min_ueber_median,
            )
        else:
            ergebnis[device_id] = ValveVerdict(
                state="ok",
                samples=samples,
                referenz=referenz,
                referenz_median_c=median,
                # Auch im "ok"-Fall: ist das Zimmer absolut zu warm, aber
                # nicht relativ, ist dieser Abstand die Zahl, die den
                # Unterschied erklaert. Ohne sie saehe die Lage aus wie
                # "nichts gemessen".
                referenz_delta_k=row.min_ueber_median if row.zu_warm is True else None,
            )

    return ergebnis
