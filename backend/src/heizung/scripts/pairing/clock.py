"""Uhr und Warten als **ein** injizierbares Paar (Sprint 19 / PR B, T14).

Warum das ein eigenes Objekt ist und nicht zwei Modul-Funktionen
-----------------------------------------------------------------

Bis PR A hatten die Warte-Schleifen zwei getrennte Einhaengepunkte,
``_now()`` und ``_sleep()``. Tests ersetzten sie per ``monkeypatch`` — und
konnten dabei **eines von beiden vergessen**. Genau das ist passiert:
``mock_downlinks_ok`` in ``test_pairing_inbound_test.py`` ersetzte ``_sleep``
durch eine Attrappe, die sofort zurueckkehrt, liess ``_now`` aber auf der
echten Wanduhr.

Damit verliert die Schleife ihre Bremse: sie fragt die Datenbank so schnell,
wie diese antwortet, bis das Zeitfenster in *echter* Zeit abgelaufen ist.
Gemessen am 30.09.2026: **900 000 Durchlaeufe** statt der vorgesehenen 30,
Faktor 30 000 — und 15 Minuten Wanduhrzeit in einem einzigen Test. Der
CI-Job ``lint-and-test`` sprang dadurch von rund 3 auf 18 Minuten.

Eine halb gefaelschte Zeitquelle ist schlimmer als keine: sie sieht aus wie
eine Attrappe und verhaelt sich wie die Wirklichkeit. Deshalb sind Uhr und
Warten hier **ein** Wert. Wer ihn ersetzt, ersetzt beides; die Haelfte gibt
es nicht mehr.

Verwendung
----------

Produktionspfad nimmt den Default::

    await run_batch_inbound_test(session, devices)          # REAL_CLOCK

Tests nehmen die virtuelle Uhr — kein echtes Warten, die Zeit springt::

    clock = virtual_clock(T0)
    await run_batch_inbound_test(session, devices, clock=clock)

``virtual_clock`` steht bewusst hier neben ``REAL_CLOCK`` und nicht in den
Tests: die Attrappe ist Teil des Vertrags, nicht Zubehoer. Wer eine eigene
baut, baut sich den Leerlauf von oben nach.

Querverweise: CLAUDE.md §5.81 (Laufzeit als Diagnose-Signal), §5.59
(freezegun greift nicht in Fixtures — dieselbe Familie: Zeit, die nur
teilweise kontrolliert ist).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

__all__ = ["REAL_CLOCK", "Clock", "virtual_clock"]


@dataclass(frozen=True, slots=True)
class Clock:
    """Zeitquelle einer Warte-Schleife: Jetzt-Zeit **und** Warten.

    :param now: liefert den aktuellen Zeitpunkt (timezone-aware, UTC).
    :param sleep: wartet die angegebene Anzahl Sekunden.
    """

    now: Callable[[], datetime]
    sleep: Callable[[float], Awaitable[None]]


async def _real_sleep(seconds: float) -> None:
    await asyncio.sleep(seconds)


def _real_now() -> datetime:
    return datetime.now(tz=UTC)


REAL_CLOCK = Clock(now=_real_now, sleep=_real_sleep)
"""Der Produktions-Default: echte Uhr, echtes Warten."""


def virtual_clock(start: datetime) -> Clock:
    """Virtuelle Uhr fuer Tests: ``sleep`` laesst die Zeit springen.

    Kein echtes Warten, und — das ist der Punkt — ``now`` folgt denselben
    Spruengen. Eine Schleife, die alle 10 s fragt und 600 s Fenster hat,
    laeuft damit genau 60 Mal und nicht 600 000 Mal.

    ``sleep`` gibt trotzdem einmal an den Event-Loop ab
    (``asyncio.sleep(0)``): ohne das kann eine Schleife, deren restliche
    Aufrufe alle synchron sind, den Loop aushungern und andere Tasks nie
    laufen lassen.
    """
    stand = {"jetzt": start}

    def now() -> datetime:
        return stand["jetzt"]

    async def sleep(seconds: float) -> None:
        stand["jetzt"] += timedelta(seconds=seconds)
        await asyncio.sleep(0)

    return Clock(now=now, sleep=sleep)
