"""Den Tagesplan eines Bereichs schreiben (21.11.2026).

**Gelesen wird er woanders** — in ``rules/tagesplan``, weil Engine und
Verlauf dieselben Fenster brauchen und ``rules`` nichts aus ``services``
importieren soll (§5.46). Dieses Modul hat genau eine Aufgabe: den Plan
**austauschen**.

**Austauschen und nicht pflegen.** Ein ``PUT`` mit der ganzen Liste statt
vier Endpunkten fuer anlegen, aendern, loeschen und sortieren. Die
Begruendung steht im Schema (``TagesplanUpdate``); der harte Grund ist der
dritte dort: zwei Fenster zu tauschen verletzt bei jedem einzelnen Schritt
die ``EXCLUDE``-Bedingung, und zwar ganz gleich, mit welchem man anfaengt.
In einer Transaktion zuerst zu loeschen und dann zu schreiben hat dieses
Problem nicht.

**``flush``, kein ``commit``** (§5.61): die Transaktion gehoert dem
Endpunkt, der im selben Zug den Audit-Eintrag schreibt. Ein ``commit``
hier wuerde den Plan speichern und die Spur davon getrennt — und bei einem
Fehler danach stuende die Aenderung ohne Eintrag da.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from heizung.models.tagesplan import TagesplanFenster
from heizung.rules.tagesplan import TagesFenster, lade_fenster
from heizung.uhrzeit import als_text


@dataclass(frozen=True, slots=True)
class NeuesFenster:
    """Ein Fenster, wie es gespeichert werden soll — noch ohne ``id``."""

    von_minute: int
    bis_minute: int
    temperatur: Decimal


async def ersetze(
    session: AsyncSession, room_id: int, fenster: list[NeuesFenster]
) -> list[TagesFenster]:
    """Setzt den Plan dieses Zimmers auf genau diese Fenster.

    Eine **leere** Liste loescht den Plan. Das ist der Aus-Zustand und
    braucht keinen eigenen Schalter: ohne Fenster entscheidet Schicht 2
    wieder am Nachtfenster, also an der Betriebszeit.

    Die Reihenfolge der Eingabe ist gleichgueltig —
    ``rules/tagesplan.lade_fenster`` ordnet nach Beginn, und das ist die
    Reihenfolge, in der Engine und Oberflaeche sie sehen.
    """
    await session.execute(delete(TagesplanFenster).where(TagesplanFenster.room_id == room_id))
    # ``flush`` zwischen Loeschen und Schreiben: sonst kann SQLAlchemy die
    # INSERTs vor das DELETE sortieren, und dann greift die
    # ``EXCLUDE``-Bedingung gegen Zeilen, die gleich verschwinden.
    await session.flush()

    for f in fenster:
        session.add(
            TagesplanFenster(
                room_id=room_id,
                von_minute=f.von_minute,
                bis_minute=f.bis_minute,
                temperatur=f.temperatur,
            )
        )
    await session.flush()
    return await lade_fenster(session, room_id)


def als_audit_wert(fenster: list[TagesFenster]) -> list[dict[str, str]]:
    """Der Plan in der Form, in der er im Audit lesbar ist.

    Uhrzeiten als Text und nicht als Minutenzahl: den Eintrag liest ein
    Mensch, und „360" ist keine Uhrzeit (§5.65 in seiner kleinen Form).
    Die Temperatur ebenfalls als Text, weil ``Decimal`` in JSONB sonst zur
    Gleitkommazahl wird und 22,1 als 22.099999 im Protokoll stuende.
    """
    return [
        {"von": f.von_text, "bis": f.bis_text, "temperatur": f"{f.temperatur:.1f}"} for f in fenster
    ]


def spannen_text(fenster: list[TagesFenster]) -> str:
    """``"06:00-08:00 25.0 | 08:00-21:00 22.0"`` — fuer Meldungen.

    Nicht fuer die Oberflaeche: die zeigt eine Tabelle und eine Tagesleiste.
    """
    if not fenster:
        return "kein Tagesplan"
    return " | ".join(
        f"{als_text(f.von_minute)}-{als_text(f.bis_minute)} {f.temperatur:.1f}" for f in fenster
    )
