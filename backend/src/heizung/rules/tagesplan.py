"""Der Tagesplan, wie ihn die Steuerung liest (21.11.2026).

**Warum dieses Modul in ``rules`` liegt und nicht in ``services``.**
Dieselbe Lage wie bei ``rules/config_resolve``: die Engine braucht die
Fenster, und der Verlauf-Endpunkt braucht sie auch — er zeichnet das
Absenk-Band, und mit einem Tagesplan sind das die **Luecken zwischen den
Fenstern**. Zwei Nachbauten waeren zwei Wahrheiten, und die teuerste
Form davon: die Oberflaeche zeichnete ein Band, nach dem gar nicht
geregelt wird (§5.53, und genau der Fall, fuer den
``rules/config_resolve`` ausgelagert wurde).

Dieses Modul haengt nur an ``models`` und an ``heizung.uhrzeit``. Es
kennt weder Engine noch Dienste, importiert also nichts, was es
zurueckimportieren koennte (§5.46).

**Die Lesart in einem Satz:** liegt die Ortszeit in einem Fenster, gilt
sein Sollwert; liegt sie in keinem, gilt die Absenkung. Beides
entscheidet die Engine, hier steht nur, **welches** Fenster.

Die Spanne ist halboffen — ``von <= minute < bis``. 08:00 gehoert damit
zum Fenster, das um 08:00 beginnt, und nicht mehr zu dem, das dort endet.
Dieselbe Lesart wie ``_is_in_night_window`` (``start <= t < end``) und
dieselbe wie ``int4range`` in der ``EXCLUDE``-Bedingung; drei Stellen,
eine Grenzauslegung.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from heizung.models.tagesplan import TagesplanFenster
from heizung.uhrzeit import MINUTEN_PRO_TAG, als_text


@dataclass(frozen=True, slots=True)
class TagesFenster:
    """Ein Fenster, losgeloest von der Sitzung.

    Die Engine haelt den Kontext ueber den ganzen Lauf; ein ORM-Objekt
    darin waere an eine Sitzung gebunden, die vielleicht schon zu ist.
    Dieselbe Entscheidung wie bei ``GehaeuseBefund`` und ``SchutzBefund``.
    """

    id: int
    von_minute: int
    bis_minute: int
    temperatur: Decimal

    @property
    def von_text(self) -> str:
        return als_text(self.von_minute)

    @property
    def bis_text(self) -> str:
        return als_text(self.bis_minute)

    @property
    def spanne_text(self) -> str:
        """``"06:00-08:00"`` — fuer Trace und Mail, nicht fuer die Rechnung."""
        return f"{self.von_text}-{self.bis_text}"

    def enthaelt(self, minute: int) -> bool:
        """Halboffen: ``von <= minute < bis``."""
        return self.von_minute <= minute < self.bis_minute


async def lade_fenster(session: AsyncSession, room_id: int) -> list[TagesFenster]:
    """Die Fenster dieses Zimmers, nach Beginn geordnet.

    **Kein Lebenszyklus-Filter und keine Erbkette**: der Plan haengt am
    Zimmer, und es gibt genau einen (``models/tagesplan`` nennt den
    Grund). Eine leere Liste heisst „kein Tagesplan" — und das ist der
    Zustand, in dem sich die Steuerung wie vor dem 21.11.2026 verhaelt.
    """
    zeilen = (
        await session.execute(
            select(
                TagesplanFenster.id,
                TagesplanFenster.von_minute,
                TagesplanFenster.bis_minute,
                TagesplanFenster.temperatur,
            )
            .where(TagesplanFenster.room_id == room_id)
            .order_by(TagesplanFenster.von_minute)
        )
    ).all()
    return [
        TagesFenster(id=zeile[0], von_minute=zeile[1], bis_minute=zeile[2], temperatur=zeile[3])
        for zeile in zeilen
    ]


def minute_des_tages(lokal: datetime) -> int:
    """Die Wanduhrzeit als Minuten seit Mitternacht.

    Erwartet eine **Ortszeit** — die Umrechnung aus UTC macht der
    Aufrufer, weil nur er die Zeitzone des Hauses kennt (§5.65). Sekunden
    fallen weg: ein Fenster beginnt zur Minute.
    """
    return lokal.hour * 60 + lokal.minute


def fenster_bei(fenster: Sequence[TagesFenster], minute: int) -> TagesFenster | None:
    """Das Fenster, das diese Minute enthaelt — oder ``None`` fuer eine Luecke.

    Dass es **hoechstens eines** sein kann, ist keine Annahme dieser
    Funktion, sondern eine Zusicherung der Datenbank
    (``uq_tagesplan_fenster_ohne_ueberschneidung``). Trotzdem wird hier das
    erste genommen und nicht geprueft, ob ein zweites passt: eine
    Steuerentscheidung, die im Fehlerfall eine Ausnahme wirft, liesse die
    Zone unversorgt. Die Reihenfolge ist durch ``lade_fenster`` festgelegt,
    also ist die Wahl auch im unmoeglichen Fall deterministisch (§0 S2).
    """
    for f in fenster:
        if f.enthaelt(minute):
            return f
    return None


def luecken(fenster: Sequence[TagesFenster]) -> list[tuple[int, int]]:
    """Die Zeiten **zwischen** den Fenstern, als Minuten-Spannen.

    Das ist die Absenkung: alles, was kein Fenster abdeckt. Vor dem ersten
    und nach dem letzten Fenster gehoert dazu.

    Ohne Fenster ist das Ergebnis **leer** und nicht „der ganze Tag". Der
    Unterschied ist wichtig: ohne Plan gilt das Nachtfenster der
    Betriebszeit, und ein Band ueber 24 Stunden waere die Behauptung, der
    Bereich sei dauerhaft abgesenkt.
    """
    if not fenster:
        return []
    geordnet = sorted(fenster, key=lambda f: f.von_minute)
    ergebnis: list[tuple[int, int]] = []
    grenze = 0
    for f in geordnet:
        if f.von_minute > grenze:
            ergebnis.append((grenze, f.von_minute))
        grenze = max(grenze, f.bis_minute)
    if grenze < MINUTEN_PRO_TAG:
        ergebnis.append((grenze, MINUTEN_PRO_TAG))
    return ergebnis
