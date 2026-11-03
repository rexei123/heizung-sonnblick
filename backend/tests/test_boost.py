"""Boost: das Ende, der Wert und die sechs Gruende (02.11.2026).

Der Teil, der ohne Datenbank pruefbar ist, steht hier:
``naechster_nachtfenster_wechsel``. Reine Funktion, Ortszeit hinein,
Ortszeit heraus, ``jetzt`` als Argument — also keine Zeitbombe (§5.59).

Die Lage je Zimmer braucht die Regelkette und steht in
``test_api_boost.py`` am echten Endpunkt.
"""

from __future__ import annotations

from datetime import datetime, time
from zoneinfo import ZoneInfo

from heizung.services.boost import naechster_nachtfenster_wechsel

WIEN = ZoneInfo("Europe/Vienna")


def _lokal(tag: int, stunde: int, minute: int = 0) -> datetime:
    return datetime(2026, 11, tag, stunde, minute, tzinfo=WIEN)


# ---------------------------------------------------------------------------
# Nachtfenster ueber Mitternacht — der Fall im Haus (22:00 bis 06:00)
# ---------------------------------------------------------------------------

UEBER_MITTERNACHT = (time(22, 0), time(6, 0))


def test_am_tag_endet_der_boost_bei_nachtbeginn() -> None:
    """**Festlegung 2 des Betreibers**, woertlich: Ende = ``night_start``."""
    ende = naechster_nachtfenster_wechsel(_lokal(2, 15, 30), *UEBER_MITTERNACHT)
    assert ende == _lokal(2, 22, 0)


def test_kein_mindestmass() -> None:
    """**Festlegung 4.** Ein Boost um 21:55 endet um 22:00.

    Fuenf Minuten sind wenig und das ist in Ordnung: der Knopf zeigt die
    Endzeit vorher, und wer um 21:55 noch boostet, weiss, was er bekommt.
    """
    ende = naechster_nachtfenster_wechsel(_lokal(2, 21, 55), *UEBER_MITTERNACHT)
    assert ende == _lokal(2, 22, 0)


def test_in_der_nacht_endet_der_boost_am_morgen() -> None:
    """**Die Ableitung, die den Nachtfall abdeckt.**

    „Immer der naechste ``night_start``" waere um 23:00 bei Nachtbeginn
    22:00 ein Boost von **23 Stunden** — das ist nicht, was das Wort
    verspricht. Der naechste **Wechsel** ist 06:00.
    """
    ende = naechster_nachtfenster_wechsel(_lokal(2, 23, 0), *UEBER_MITTERNACHT)
    assert ende == _lokal(3, 6, 0)


def test_nach_mitternacht_endet_der_boost_am_selben_morgen() -> None:
    """02:00 liegt im Nachtfenster, der Wechsel ist in vier Stunden."""
    ende = naechster_nachtfenster_wechsel(_lokal(3, 2, 0), *UEBER_MITTERNACHT)
    assert ende == _lokal(3, 6, 0)


def test_genau_zum_nachtbeginn_ist_schon_nacht() -> None:
    """Die Grenze gehoert zur Nacht — dieselbe Lesart wie in der Engine.

    ``_is_in_night_window`` in ``rules/engine`` nimmt ``>= night_start``,
    und zwei verschiedene Lesarten derselben Grenze waeren genau die
    Sorte Drift, die §5.53 beschreibt: die Engine senkt ab, der Boost
    rechnet noch mit Tag.
    """
    ende = naechster_nachtfenster_wechsel(_lokal(2, 22, 0), *UEBER_MITTERNACHT)
    assert ende == _lokal(3, 6, 0)


def test_genau_zum_nachtende_ist_schon_tag() -> None:
    """Und die andere Grenze gehoert zum Tag (``< night_end``)."""
    ende = naechster_nachtfenster_wechsel(_lokal(3, 6, 0), *UEBER_MITTERNACHT)
    assert ende == _lokal(3, 22, 0)


# ---------------------------------------------------------------------------
# Nachtfenster innerhalb eines Tages (01:00 bis 05:00)
# ---------------------------------------------------------------------------

INNERHALB = (time(1, 0), time(5, 0))


def test_innerhalb_eines_tages_am_abend() -> None:
    """Abends ist Tag, der naechste Wechsel ist der Nachtbeginn — morgen."""
    ende = naechster_nachtfenster_wechsel(_lokal(2, 20, 0), *INNERHALB)
    assert ende == _lokal(3, 1, 0)


def test_innerhalb_eines_tages_in_der_nacht() -> None:
    ende = naechster_nachtfenster_wechsel(_lokal(2, 3, 0), *INNERHALB)
    assert ende == _lokal(2, 5, 0)


def test_innerhalb_eines_tages_am_vormittag() -> None:
    """Vormittags ist Tag, und der Nachtbeginn liegt in der naechsten Nacht."""
    ende = naechster_nachtfenster_wechsel(_lokal(2, 9, 0), *INNERHALB)
    assert ende == _lokal(3, 1, 0)


# ---------------------------------------------------------------------------
# Die Zeitumstellung
# ---------------------------------------------------------------------------


def test_das_ende_ueberlebt_die_zeitumstellung() -> None:
    """Am 28.03.2027 fehlt in Europe/Vienna die Stunde von 02:00 bis 03:00.

    Das Ende wird in **Ortszeit** gerechnet und dann nach UTC gewandelt;
    ``ZoneInfo`` erledigt den Sprung. Der Test haelt fest, dass die
    Rechnung nicht an einem festen Stundenversatz haengt — die Falle aus
    §5.65, nur in der anderen Richtung.
    """
    vorher = datetime(2027, 3, 27, 23, 0, tzinfo=WIEN)
    ende = naechster_nachtfenster_wechsel(vorher, *UEBER_MITTERNACHT)
    assert ende == datetime(2027, 3, 28, 6, 0, tzinfo=WIEN)
    # 06:00 Ortszeit sind an diesem Tag 04:00 UTC und nicht 05:00.
    assert ende.utcoffset() is not None
    assert ende.astimezone(ZoneInfo("UTC")).hour == 4
