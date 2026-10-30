"""Zustand der Kindersicherung je Gerät (Sprint 24c, Sprint 23 T4-B).

**Was dieser Dienst beantwortet.** Die Rolle „nur messen" schickt beim
Umschalten einen Downlink: ``0x07 01`` sperrt das Drehrad, ``0x07 00``
gibt es frei. Ob der Befehl **angekommen** ist, sagt erst ein späterer
Uplink — das Gerät meldet das 0x80-Bit im Keepalive, und der Subscriber
schreibt es seit Sprint 24b nach ``sensor_reading.child_lock``.

Dieser Dienst vergleicht den **gewollten** mit dem **gemeldeten** Zustand
und liefert daraus eine von drei Aussagen. Eine vierte („unbekannt")
gibt es bewusst nicht: wenn kein Messwert vorliegt, ist die Antwort
``ausstehend``, und das ist eine Aussage über den Vorgang, nicht über
das Gerät.

**Der gewollte Zustand folgt der Rolle, in beide Richtungen.** Das ist
die eine Regel, die den Dienst klein hält:

| Rolle | gewollt | gemeldet | Ergebnis |
|---|---|---|---|
| „nur messen" | Rad gesperrt | gesperrt | ``bestaetigt`` |
| „nur messen" | Rad gesperrt | frei | ``fehlgeschlagen`` |
| normal | Rad frei | frei | ``bestaetigt`` |
| normal | Rad frei | gesperrt | ``fehlgeschlagen`` |
| beliebig | — | keine Meldung | ``ausstehend`` |

**Warum ``fehlgeschlagen`` und nicht ``abweichend``.** Beim Setzen der
Rolle ist der Downlink hinausgegangen; meldet das Gerät danach das
Gegenteil, ist der Befehl nicht angekommen oder wurde überschrieben.
Das ist ein Fehlschlag und keine Geschmacksfrage — und er braucht einen
Namen, der zum Handeln auffordert.

**``NULL`` zählt nicht mit.** Ein Uplink ohne das Feld (etwa eine reine
Befehlsantwort) sagt nichts über die Sperre. Die Abfrage nimmt deshalb
die jüngste Zeile, **die das Feld führt** — dieselbe Regel wie bei
``attached_backplate`` in der Geräte-Sicherheit.

## Sprint 23 T4-B: der gewollte Zustand hat jetzt **zwei** Gründe

Die Tabelle oben steht unter „Rolle", und bis Sprint 23 war das die
ganze Wahrheit: ``measure_only`` entschied allein. Mit der Gast-Sperre
kommt ein zweiter Grund dazu, das Rad stillzulegen — und damit die
Gefahr aus Paragraph 5.53: zwei Treiber ohne gemeinsame Quelle.

Die beiden Fehlerbilder, die daraus entstanden wären, sind konkret:

1. **Das Zurücknehmen der Rolle hätte das Rad eines gast-gesperrten
   Zimmers freigegeben.** ``setze_messrolle`` schickte ``0x07 00``,
   sobald ``measure_only`` auf ``False`` ging — ohne zu wissen, dass ein
   zweiter Grund die Sperre noch verlangt.
2. **``child_lock_state`` hätte für ein gast-gesperrtes Normalgerät
   „fehlgeschlagen" gemeldet.** Gewollt wäre ``measure_only=False``, das
   Gerät meldet „gesperrt" — und ein Melder, der im Normalfall rot
   zeigt, wird nach einer Woche nicht mehr gelesen (Paragraph 5.79).

Deshalb **eine** Funktion: ``soll_kindersicherung``. Sie ist die einzige
Stelle, an der aus Gründen ein gewollter Zustand wird, und beide
Schreibpfade sowie der Lesepfad gehen durch sie. ``child_lock_state``
nimmt seither ``gewollt`` statt ``measure_only`` — der alte Parametername
**war** die Falle, weil er einen der beiden Gründe zur Wahrheit erklärte.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from heizung.models.device import Device
from heizung.models.heating_zone import HeatingZone
from heizung.models.room import Room
from heizung.models.sensor_reading import SensorReading

#: Die drei Aussagen. Als ``Literal`` und nicht als Enum: die Werte gehen
#: unverändert in die API-Antwort, und ein Enum wäre eine zweite Liste
#: neben dem Schema.
ChildLockState = Literal["bestaetigt", "ausstehend", "fehlgeschlagen"]


def soll_kindersicherung(*, measure_only: bool, gast_sperre: bool) -> bool:
    """Der gewollte Zustand des Rades, aus **beiden** Gründen.

    Reine Funktion, eine Zeile, und trotzdem die wichtigste in dieser
    Datei: sie ist die einzige Stelle, an der entschieden wird, ob das
    Rad gesperrt sein soll. Wer sie umgeht und einen der beiden Gründe
    direkt an einen Downlink oder an ``child_lock_state`` hängt, baut die
    zweite Wahrheit aus Paragraph 5.53 — und sie fällt nicht auf, weil
    jeder Grund für sich das Richtige tut.

    **Oder, nicht Und.** Jeder Grund allein genügt, und keiner hebt den
    anderen auf:

    | ``measure_only`` | Gast-Sperre | Rad |
    |---|---|---|
    | ja | ja | gesperrt |
    | ja | nein | gesperrt — der Fühler liegt unmontiert im Raum |
    | nein | ja | gesperrt — der Gast soll nicht verstellen |
    | nein | nein | frei |

    Die dritte Zeile ist die neue, und die zweite ist die, die beim
    Zurücknehmen der Rolle nicht verloren gehen darf.

    :param measure_only: die Rolle „nur messen" (Sprint 24c).
    :param gast_sperre: ``room.guest_override_blocked`` des Zimmers, zu
        dem das Gerät gehört — **beide** Formen, dauerhaft und bis
        Check-out. Ein Gerät ohne Zimmer hat keine Gast-Sperre.
    """
    return measure_only or gast_sperre


def child_lock_state(
    *,
    gewollt: bool,
    gemeldet: bool | None,
    gemeldet_um: datetime | None = None,
    befehl_um: datetime | None = None,
) -> ChildLockState:
    """Vergleicht gewollt gegen gemeldet. Reine Funktion.

    ``gemeldet is None`` heißt „keine Zeile, die das Feld führt" — nicht
    „Rad frei". Der Unterschied ist der ganze Grund für ``ausstehend``:
    ein Gerät, von dem wir nichts gehört haben, hat die Sperre nicht
    verweigert.

    **Und eine Meldung, die älter ist als der Befehl, ist keine Antwort
    darauf** (Befund des Betreibers, 24.10.2026). Direkt nach dem
    Umschalten auf „nur messen" ist die jüngste Meldung die vom Keepalive
    **davor**: sie sagt „Rad frei", und das war bis zur Sekunde vorher
    richtig. Ohne den Zeitvergleich stand dort ein roter Befund im
    Normalfall — und ein Melder, der im Normalfall rot zeigt, wird nach
    einer Woche nicht mehr gelesen (§5.79).

    Fehlt eine der beiden Zeiten, wird nicht geraten: dann urteilt die
    Funktion wie vorher. ``befehl_um is None`` heißt „kein Befehl bekannt"
    (Bestandsgeräte vor Migration 0033), ``gemeldet_um is None`` heißt,
    der Aufrufer hat die Zeit nicht mitgegeben.

    **``gewollt`` ist ein Pflicht-Argument und kommt aus
    ``soll_kindersicherung``** (Sprint 23 T4-B). Hier stand bis dahin
    ``measure_only``, und dieser Name war die Falle: er erklärte einen
    der beiden Gründe zur Wahrheit. Ein Default gäbe es aus demselben
    Grund nicht — er würde einen Aufrufer erlauben, der den zweiten Grund
    stillschweigend vergisst.
    """
    if gemeldet is None:
        return "ausstehend"
    if befehl_um is not None and gemeldet_um is not None and gemeldet_um <= befehl_um:
        return "ausstehend"
    return "bestaetigt" if gemeldet == gewollt else "fehlgeschlagen"


@dataclass(frozen=True, slots=True)
class Sperrmeldung:
    """Was das Gerät gemeldet hat — **und wann**.

    Die Zeit war in der ersten Fassung (24c) nicht dabei, und genau sie
    fehlte: ohne sie ist eine Meldung von vor dem Befehl nicht von einer
    Ablehnung zu unterscheiden.
    """

    gesperrt: bool
    gemeldet_um: datetime


async def child_lock_verdicts(
    session: AsyncSession,
    device_ids: Sequence[int],
) -> dict[int, Sperrmeldung | None]:
    """Der jüngste gemeldete Sperr-Zustand je Gerät, in **einer** Abfrage.

    Dieselbe Form wie ``battery_verdicts`` und ``valve_verdicts``: die
    Geräteliste rendert bis zu 104 Zeilen, und eine Abfrage je Zeile wäre
    104 Rundreisen für eine Information (AE-72 §3).

    ``None`` für ein Gerät heißt: keine Zeile mit gesetztem
    ``child_lock``. Jede angefragte ID kommt im Ergebnis vor — ein
    fehlender Schlüssel wäre für den Aufrufer nicht von „keine Meldung"
    zu unterscheiden, und dann müsste er raten.
    """
    ergebnis: dict[int, Sperrmeldung | None] = dict.fromkeys(device_ids)
    if not device_ids:
        return ergebnis

    # ``DISTINCT ON (device_id) … ORDER BY device_id, time DESC`` über den
    # Index ``ix_sensor_reading_device_time``. Der Filter auf
    # ``IS NOT NULL`` steht in der WHERE-Klausel und nicht im Nachhinein:
    # sonst käme für ein Gerät, dessen jüngste Zeile das Feld nicht führt,
    # ``None`` heraus, obwohl die Zeile davor es führt.
    stmt = (
        select(SensorReading.device_id, SensorReading.child_lock, SensorReading.time)
        .where(SensorReading.device_id.in_(list(device_ids)))
        .where(SensorReading.child_lock.is_not(None))
        .order_by(SensorReading.device_id, SensorReading.time.desc())
        .distinct(SensorReading.device_id)
    )
    for device_id, gesperrt, gemeldet_um in (await session.execute(stmt)).tuples().all():
        if gesperrt is None:
            continue
        ergebnis[device_id] = Sperrmeldung(gesperrt=gesperrt, gemeldet_um=gemeldet_um)
    return ergebnis


async def child_lock_verdict(session: AsyncSession, device_id: int) -> Sperrmeldung | None:
    """Einzel-Variante für die Detail-Ansicht.

    Gegenstück zu den ``_verdict_fuer``-Helfern in ``api/v1/devices.py``:
    ``child_lock_verdicts`` liefert garantiert einen Eintrag je
    angefragter ID, der Zugriff ist also sicher.
    """
    return (await child_lock_verdicts(session, [device_id]))[device_id]


async def gast_sperren_je_geraet(
    session: AsyncSession, device_ids: Sequence[int]
) -> dict[int, bool]:
    """``room.guest_override_blocked`` je Gerät, in **einer** Abfrage.

    Die Geräteliste rendert über hundert Zeilen. Eine Abfrage je Zeile
    wäre hundert Abfragen für eine Spalte — dieselbe Regel wie bei den
    Batterie-Stufen (Paragraph 5.73: wenn read-time, dann gehoben, nicht
    je Zeile).

    Jede angefragte ID kommt im Ergebnis vor; ein Gerät ohne Zone oder
    ohne Zimmer steht mit ``False`` darin. Das ist keine Annahme, sondern
    die Lage: wo kein Zimmer ist, ist kein Gast, der etwas verstellen
    könnte.

    **Beide Formen der Sperre zählen.** Gelesen wird
    ``guest_override_blocked`` allein, ohne ``guest_block_bis_checkout``:
    das Rad soll in beiden Formen still sein, die Formen unterscheiden
    sich nur darin, **wann** die Sperre endet.
    """
    ergebnis: dict[int, bool] = dict.fromkeys(device_ids, False)
    if not ergebnis:
        return ergebnis

    stmt = (
        select(Device.id, Room.guest_override_blocked)
        .join(HeatingZone, Device.heating_zone_id == HeatingZone.id)
        .join(Room, HeatingZone.room_id == Room.id)
        .where(Device.id.in_(list(ergebnis)))
    )
    for device_id, gesperrt in (await session.execute(stmt)).all():
        ergebnis[device_id] = bool(gesperrt)
    return ergebnis
