"""Sprint 15e-1 — reine Tests fuer die Datums-Ableitung des Imports.

Anreise kommt real OHNE Jahr (``TT.MM.``), Abreise MIT Jahr; das Jahr wird
server-seitig abgeleitet (inkl. Jahreswechsel). Ohne DB.
"""

from __future__ import annotations

from datetime import date

import pytest

from heizung.schemas.occupancy_import import parse_partial_date, resolve_stay_dates


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("04.06.", (4, 6, None)),
        ("06.06.2026", (6, 6, 2026)),
        ("4.6.", (4, 6, None)),
        ("29.02.", (29, 2, None)),  # Schaltjahr-Basis -> ohne Jahr zulaessig
        ("31.12.2026", (31, 12, 2026)),
    ],
)
def test_parse_partial_date_ok(raw: str, expected: tuple[int, int, int | None]) -> None:
    assert parse_partial_date(raw) == expected


@pytest.mark.parametrize("raw", ["06.2026", "32.01.2026", "01.13.", "", "abc", "1.2.3.4"])
def test_parse_partial_date_invalid(raw: str) -> None:
    with pytest.raises(ValueError):
        parse_partial_date(raw)


def test_standardfall_anreise_ohne_jahr() -> None:
    # Anreise ohne Jahr, Abreise mit Jahr -> beide 2026.
    anreise, abreise = resolve_stay_dates("04.06.", "06.06.2026", date(2026, 6, 7))
    assert anreise == date(2026, 6, 4)
    assert abreise == date(2026, 6, 6)


def test_silvester_jahreswechsel() -> None:
    # Anreise 29.12. (ohne Jahr), Abreise 02.01.2027 -> Anreise war im Vorjahr.
    anreise, abreise = resolve_stay_dates("29.12.", "02.01.2027", date(2027, 1, 2))
    assert anreise == date(2026, 12, 29)
    assert abreise == date(2027, 1, 2)


def test_defensiv_anreise_mit_jahr_kein_regress() -> None:
    # 15e-Format (beide mit Jahr) bleibt unveraendert korrekt.
    anreise, abreise = resolve_stay_dates("04.06.2026", "06.06.2026", date(2026, 6, 7))
    assert anreise == date(2026, 6, 4)
    assert abreise == date(2026, 6, 6)


def test_defensiv_beide_ohne_jahr_aus_list_date() -> None:
    # Beide ohne Jahr -> Anker aus list_date.
    anreise, abreise = resolve_stay_dates("04.06.", "06.06.", date(2026, 6, 6))
    assert anreise == date(2026, 6, 4)
    assert abreise == date(2026, 6, 6)


def test_defensiv_beide_ohne_jahr_silvester() -> None:
    # Beide ohne Jahr ueber den Jahreswechsel: Anker aus list_date (02.01.2027),
    # Anreise 29.12. landet nach der Abreise -> Vorjahr.
    anreise, abreise = resolve_stay_dates("29.12.", "02.01.", date(2027, 1, 2))
    assert anreise == date(2026, 12, 29)
    assert abreise == date(2027, 1, 2)
