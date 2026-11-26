"""Eine Uhrzeit des Tages als Minuten seit Mitternacht (21.11.2026).

**Warum dieses Modul ganz oben liegt und nicht in ``services`` oder
``rules``.** Es ist weder eine Regel noch ein Dienst, sondern eine
**Schreibweise**: ``"06:00"`` zu ``360`` und zurueck. Gebraucht wird sie
an drei Stellen, die einander nicht importieren duerfen — die Schemata
(Eingabepruefung), ``rules/tagesplan`` (der Vergleich in der Engine) und
``services/tagesplan`` (das Schreiben). Ein Modul ohne eigene
Abhaengigkeiten kann von allen dreien gelesen werden, ohne einen Ring zu
bilden (Paragraph 5.46).

**Warum Minuten und nicht ``time``.** ``"bis 24:00"`` ist die natuerliche
Schreibweise fuer „bis Mitternacht", und die Betriebszeit erlaubt sie
seit Sprint 24d ausdruecklich. ``datetime.time`` kennt sie **nicht** —
die hoechste Uhrzeit ist 23:59:59. Ein Zeitfenster „15:00 bis 24:00"
muesste damit entweder auf 23:59 enden (eine Minute Absenkung, die
niemand bestellt hat) oder 00:00 heissen und damit **kleiner** sein als
sein Anfang. Beides ist eine Falle; 1440 ist keine.

``MINUTEN_PRO_TAG`` ist deshalb ein **gueltiger** Wert fuer ein Ende und
nie einer fuer einen Anfang. Die Spanne eines Fensters ist halboffen:
``[von, bis)``. 08:00 gehoert damit zum Fenster, das um 08:00 beginnt,
und nicht mehr zu dem, das dort endet — dieselbe Lesart wie
``_is_in_night_window`` in der Engine (``start <= t < end``).

**Die Betriebszeit rechnet weiter in ``time``** und bleibt dabei: ihre
beiden Werte stehen in ``rule_config.night_start`` / ``night_end``, und
dort ist die Spalte ``Time``. ``services/betriebszeit.parse_uhrzeit``
ruft deshalb ``parse_minuten`` und bildet das Ergebnis auf ``time`` ab —
``24:00`` wird dabei zu ``00:00``, wie vorher. Eine Schreibweise, zwei
Leser.
"""

from __future__ import annotations

import re
from typing import Final

#: Minuten eines Tages. Gueltig als **Ende** eines Fensters (``24:00``),
#: nie als Anfang.
MINUTEN_PRO_TAG: Final[int] = 24 * 60

#: ``HH:MM`` mit ``24:00`` als erlaubtem Sonderfall.
#:
#: Dasselbe Muster stand bis zum 21.11.2026 in ``services/betriebszeit``;
#: es ist hierher gewandert, damit Tagesplan und Betriebszeit dieselbe
#: Schreibweise annehmen (Paragraph 5.53 — eine Eingabe, die an einer
#: Stelle gilt und an der anderen nicht, ist der naechste Fehlerbericht).
MUSTER: Final[str] = r"^(?:(?:[01]\d|2[0-3]):[0-5]\d|24:00)$"

_MUSTER = re.compile(MUSTER)


class UhrzeitError(ValueError):
    """Eine Eingabe, die keine Uhrzeit ist."""


def parse_minuten(wert: str) -> int:
    """``"06:00"`` zu ``360``, ``"24:00"`` zu ``1440``.

    Die ``24:00`` bleibt hier **erhalten** und wird nicht auf Null
    abgebildet: fuer ein Fenster ist sie das Ende des Tages, und das ist
    etwas anderes als sein Anfang. Wer ``time`` braucht, rechnet selbst um
    (``services/betriebszeit``).
    """
    if _MUSTER.match(wert.strip()) is None:
        raise UhrzeitError(
            f"'{wert}' ist keine Uhrzeit. Erwartet HH:MM, zum Beispiel 06:00 "
            "(24:00 ist erlaubt und bedeutet Mitternacht)."
        )
    stunde, minute = wert.strip().split(":")
    return int(stunde) * 60 + int(minute)


def als_text(minuten: int) -> str:
    """``360`` zu ``"06:00"``, ``1440`` zu ``"24:00"``.

    Die Umkehrung von ``parse_minuten`` **einschliesslich** der 1440: wer
    „bis 24:00" eingegeben hat, soll „24:00" wiedersehen und nicht
    „00:00". Ein Wert, der anders zurueckkommt als er hineinging, ist die
    Sorte Kleinigkeit, nach der man zweimal hinsieht.
    """
    if not 0 <= minuten <= MINUTEN_PRO_TAG:
        raise UhrzeitError(f"{minuten} liegt nicht in einem Tag (0 bis {MINUTEN_PRO_TAG}).")
    if minuten == MINUTEN_PRO_TAG:
        return "24:00"
    return f"{minuten // 60:02d}:{minuten % 60:02d}"
