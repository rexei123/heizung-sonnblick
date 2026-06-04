"""Sprint 15d T4 — Pure-Function-Tests fuer ``services/battery_health.py`` (AE-65).

Kein DB / kein I/O — reine Schwellen-Logik. Prueft die vier Zustaende an den
Grenzen und die Wirkung der konfigurierbaren ``warn_threshold``.
"""

from __future__ import annotations

import pytest

from heizung.services.battery_health import (
    BATTERY_CRITICAL_PCT,
    DEFAULT_BATTERY_WARN_PCT,
    battery_health_state,
)


def test_constants_match_adr_65() -> None:
    """Schutz gegen versehentliches Verschieben der AE-65-Schwellen."""
    assert BATTERY_CRITICAL_PCT == 10
    assert DEFAULT_BATTERY_WARN_PCT == 20


@pytest.mark.parametrize(
    ("pct", "expected"),
    [
        (None, "unbekannt"),  # kein Reading / Codec-NULL
        (0, "kritisch"),  # Untergrenze
        (9, "kritisch"),  # direkt unter der Kritisch-Schwelle
        (10, "warn"),  # exakt 10 ist NICHT mehr kritisch (10 < 10 falsch), aber < 20
        (15, "warn"),
        (19, "warn"),  # direkt unter der Warn-Schwelle
        (20, "ok"),  # exakt an der Warn-Schwelle ist ok (>= 20)
        (50, "ok"),
        (100, "ok"),  # Codec-Saettigung
    ],
)
def test_battery_health_state_default_threshold(pct: int | None, expected: str) -> None:
    """Default-Schwelle 20: ok>=20, warn 10..19, kritisch <10, None unbekannt."""
    assert battery_health_state(pct, DEFAULT_BATTERY_WARN_PCT) == expected


def test_warn_threshold_shifts_the_warn_boundary() -> None:
    """Anderer Config-Wert verschiebt die warn/ok-Grenze (AE-65)."""
    # Hoehere Schwelle (25): 24 ist jetzt warn, 25 ist ok.
    assert battery_health_state(24, 25) == "warn"
    assert battery_health_state(25, 25) == "ok"
    # Niedrigere Schwelle (15): 14 ist warn, 15 ist ok.
    assert battery_health_state(14, 15) == "warn"
    assert battery_health_state(15, 15) == "ok"


def test_kritisch_is_absolute_and_beats_warn() -> None:
    """``kritisch`` (< 10) schlaegt ``warn`` auch bei sehr kleiner Schwelle.

    Selbst wenn ``warn_threshold`` <= 10 gesetzt waere, bleibt < 10 kritisch —
    die Reihenfolge im Mapping ist verbindlich.
    """
    assert battery_health_state(5, 5) == "kritisch"
    assert battery_health_state(9, 10) == "kritisch"
    assert battery_health_state(8, 8) == "kritisch"
