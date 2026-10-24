"""Betriebszeit eines Allgemeinbereichs (Sprint 24d).

**Die Idee in einem Satz:** ausserhalb der Betriebszeit ist bei einem
Bereich genau das, was bei einem Gaestezimmer die Nacht ist.

Die Engine hat seit Sprint 9.8 ein Zeitfenster je Zimmer
(``rule_config.night_start`` / ``night_end``) und senkt darin auf
``t_night`` ab. Fuer eine Bar, die von 15:00 bis 24:00 offen ist, ist das
dieselbe Rechnung mit anderen Worten: Betrieb bis 24:00, danach
Absenkung bis 15:00.

Deshalb **kein eigenes Feld und kein eigener Engine-Zweig**, sondern eine
Umbenennung an der Oberflaeche:

===================  ==========================
Betriebszeit         ``rule_config``
===================  ==========================
von (Beginn)         ``night_end``
bis (Ende)           ``night_start``
===================  ==========================

Die Zuordnung sieht verdreht aus und ist es nicht: ``night_start`` ist der
Beginn der **Absenkung**, und die beginnt, wenn der Betrieb endet.

**Warum am Zimmer und nicht am Raumtyp.** Bar und Rezeption haben
denselben Charakter und verschiedene Zeiten; der Raumtyp „Raum intern"
kann morgen eine zweite Bar bekommen. Die Zeit gehoert zum Ort, nicht zur
Art. Fehlt sie am Zimmer, greift die Kette weiter (Raumtyp, dann
hausweit) — wie bei jedem anderen Feld.

**„24:00" ist erlaubt.** Ein Betrieb „bis 24:00" ist die natuerliche
Schreibweise fuer „bis Mitternacht"; ``time`` kennt sie nicht. Die
Eingabe wird auf ``00:00`` abgebildet, und die Fensterpruefung der Engine
rechnet damit richtig: ``night_start = 00:00``, ``night_end = 15:00``
ergibt ein Fenster ``[00:00, 15:00)`` — Absenkung nach Mitternacht,
Betrieb ab 15:00 bis Mitternacht. Wer stattdessen „00:00" eingibt, meint
dasselbe und bekommt dasselbe.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import time

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from heizung.models.enums import RuleConfigScope
from heizung.models.rule_config import RuleConfig

#: ``HH:MM`` mit 24:00 als erlaubtem Sonderfall.
_MUSTER = re.compile(r"^(?:([01]\d|2[0-3]):([0-5]\d)|24:00)$")


class BetriebszeitError(ValueError):
    """Eingabe, die keine Uhrzeit ist."""


@dataclass(frozen=True, slots=True)
class Betriebszeit:
    """Was die Oberflaeche zeigt. ``None`` heisst „nicht festgelegt"."""

    von: time | None
    bis: time | None


def parse_uhrzeit(wert: str) -> time:
    """``"15:00"`` oder ``"24:00"`` zu ``time``.

    ``24:00`` wird auf ``00:00`` abgebildet — dieselbe Minute, andere
    Schreibweise. Die Engine unterscheidet sie nicht, und ein Mensch, der
    „bis 24:00" eingibt, meint Mitternacht.
    """
    treffer = _MUSTER.match(wert.strip())
    if treffer is None:
        raise BetriebszeitError(
            f"'{wert}' ist keine Uhrzeit. Erwartet HH:MM, zum Beispiel 15:00 "
            "(24:00 ist erlaubt und bedeutet Mitternacht)."
        )
    if treffer.group(1) is None:
        return time(0, 0)
    return time(int(treffer.group(1)), int(treffer.group(2)))


async def lade_zimmer_zeile(session: AsyncSession, room_id: int) -> RuleConfig | None:
    """Die saisonlose ROOM-Zeile dieses Zimmers, falls es sie gibt."""
    stmt = (
        select(RuleConfig)
        .where(RuleConfig.scope == RuleConfigScope.ROOM)
        .where(RuleConfig.room_id == room_id)
        .where(RuleConfig.season_id.is_(None))
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def lade(session: AsyncSession, room_id: int) -> Betriebszeit:
    """Die Betriebszeit, wie sie **am Zimmer** steht.

    Bewusst **ohne** Kette: die Oberflaeche zeigt hier, was an diesem
    Zimmer eingestellt ist, und leer heisst leer. Ein geerbter Wert an
    dieser Stelle waere eine Zahl, die man nicht wegbekommt — wer sie
    loescht, saehe sie wieder dastehen.
    """
    zeile = await lade_zimmer_zeile(session, room_id)
    if zeile is None:
        return Betriebszeit(von=None, bis=None)
    return Betriebszeit(von=zeile.night_end, bis=zeile.night_start)


async def setze(
    session: AsyncSession, room_id: int, *, von: time | None, bis: time | None
) -> Betriebszeit:
    """Schreibt die Betriebszeit an das Zimmer.

    Beide ``None`` loescht sie — dann greift wieder, was Raumtyp oder
    Haus vorgeben. Die uebrige Zeile bleibt stehen: in ihr koennen
    Sollwerte oder Fenster-Schwellen fuer dieses Zimmer stehen, und die
    gehoeren nicht zur Betriebszeit.

    Nur eine der beiden Grenzen ist kein gueltiger Zustand — ein Fenster
    mit einem Ende und ohne Anfang ist keins. Die Engine wuerde es
    stillschweigend ignorieren (``if night_start is not None and night_end
    is not None``), und damit stuende in der Oberflaeche eine Zeit, die
    nichts tut (§5.77).

    ``flush``, kein ``commit``: die Transaktion gehoert dem Aufrufer
    (§5.61).
    """
    if (von is None) != (bis is None):
        raise BetriebszeitError(
            "Betriebszeit braucht Beginn **und** Ende — oder beides leer. "
            "Eine halbe Angabe wuerde nicht wirken."
        )

    zeile = await lade_zimmer_zeile(session, room_id)
    if zeile is None:
        if von is None:
            return Betriebszeit(von=None, bis=None)
        zeile = RuleConfig(scope=RuleConfigScope.ROOM, room_id=room_id)
        session.add(zeile)

    zeile.night_end = von
    zeile.night_start = bis
    await session.flush()
    return Betriebszeit(von=von, bis=bis)
