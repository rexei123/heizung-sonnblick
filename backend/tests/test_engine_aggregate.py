"""Pure-Function-Tests fuer ``rules/aggregation.py`` (Sprint 11 T3, AE-51 §4.1).

Verifiziert das Zone-Aggregat ueber healthy Vickis ohne DB. Konsumenten
sind Sprint 12 (Schreib-Pfad) und Sprint 14 (UI-API). In Sprint 11 ist
der Helper noch nicht in der Engine-Read-Pipeline integriert (Phase-0-
Befund T3: ``_load_room_context`` laedt heute keine Reading-Daten);
die Layer-4-Window-Detection in ``engine.layer_window_safety`` bekommt
den ``health_state='healthy'``-Filter direkt in ihrer eigenen Query.
"""

from __future__ import annotations

from decimal import Decimal

from heizung.rules.aggregation import ReadingForAggregate, aggregate_zone_readings


def test_aggregate_single_healthy_vicki() -> None:
    """1 healthy Vicki -> Mittelwert = Einzelwert, OR = Einzelwert."""
    readings = [
        ReadingForAggregate(
            temperature_c=Decimal("21.3"),
            open_window=False,
            health_state="healthy",
        )
    ]
    mean, window = aggregate_zone_readings(readings)
    assert mean == Decimal("21.3")
    assert window is False


def test_aggregate_two_healthy_vickis_same_value() -> None:
    """2 healthy Vickis mit identischem Wert -> Wert unveraendert."""
    readings = [
        ReadingForAggregate(
            temperature_c=Decimal("21.0"),
            open_window=False,
            health_state="healthy",
        ),
        ReadingForAggregate(
            temperature_c=Decimal("21.0"),
            open_window=False,
            health_state="healthy",
        ),
    ]
    mean, window = aggregate_zone_readings(readings)
    assert mean == Decimal("21.0")
    assert window is False


def test_aggregate_two_healthy_vickis_different_values_round_half_even() -> None:
    """Arithmetischer Mittelwert quantisiert auf 0.1 °C mit ROUND_HALF_EVEN.

    Zwei Cases:
    - 20.0 + 22.0 -> 21.0 (sauber, keine Rundung noetig)
    - 20.1 + 20.2 -> 20.15 -> 20.2 (tie at 0.05, even neighbor = 2 ist even,
      daher 20.2 statt 20.1; Banker's Rounding korrekt)
    """
    # Case A: keine Rundung noetig
    readings_a = [
        ReadingForAggregate(
            temperature_c=Decimal("20.0"),
            open_window=False,
            health_state="healthy",
        ),
        ReadingForAggregate(
            temperature_c=Decimal("22.0"),
            open_window=False,
            health_state="healthy",
        ),
    ]
    mean_a, _ = aggregate_zone_readings(readings_a)
    assert mean_a == Decimal("21.0")

    # Case B: ROUND_HALF_EVEN auf .15 -> .2
    readings_b = [
        ReadingForAggregate(
            temperature_c=Decimal("20.1"),
            open_window=False,
            health_state="healthy",
        ),
        ReadingForAggregate(
            temperature_c=Decimal("20.2"),
            open_window=False,
            health_state="healthy",
        ),
    ]
    mean_b, _ = aggregate_zone_readings(readings_b)
    assert mean_b == Decimal("20.2"), (
        f"erwarte 20.2 (ROUND_HALF_EVEN auf 20.15 -> even tenth 2), gefunden {mean_b}"
    )


def test_aggregate_filters_non_healthy() -> None:
    """1 healthy + 1 silent -> silent ignoriert, Mittelwert = healthy-Wert.

    Auch fuer degraded und suspicious sicherheitshalber abgedeckt.
    """
    readings = [
        ReadingForAggregate(
            temperature_c=Decimal("19.0"),
            open_window=False,
            health_state="healthy",
        ),
        ReadingForAggregate(
            temperature_c=Decimal("99.0"),  # absurder Wert -> wuerde Mittelwert sprengen
            open_window=True,  # wuerde OR auf True kippen
            health_state="silent",
        ),
        ReadingForAggregate(
            temperature_c=Decimal("80.0"),
            open_window=True,
            health_state="degraded",
        ),
        ReadingForAggregate(
            temperature_c=Decimal("70.0"),
            open_window=True,
            health_state="suspicious",
        ),
    ]
    mean, window = aggregate_zone_readings(readings)
    assert mean == Decimal("19.0"), (
        f"non-healthy Devices duerfen nicht in den Mittelwert einfliessen, gefunden {mean}"
    )
    assert window is False, (
        f"non-healthy Devices duerfen das OR nicht auf True kippen, gefunden {window}"
    )


def test_aggregate_empty_returns_none() -> None:
    """0 healthy Vickis -> (None, None), unabhaengig davon ob die Liste
    leer ist oder nur nicht-healthy Devices enthaelt."""
    # Variante A: leere Reading-Liste (Zone hat keine Devices zugeordnet)
    mean_a, window_a = aggregate_zone_readings([])
    assert mean_a is None
    assert window_a is None

    # Variante B: Devices da, aber keine healthy
    readings = [
        ReadingForAggregate(
            temperature_c=Decimal("21.0"),
            open_window=False,
            health_state="silent",
        ),
        ReadingForAggregate(
            temperature_c=Decimal("21.0"),
            open_window=True,
            health_state="degraded",
        ),
    ]
    mean_b, window_b = aggregate_zone_readings(readings)
    assert mean_b is None
    assert window_b is None


def test_window_or_aggregation() -> None:
    """OR-Aggregation ueber open_window: True schlaegt False; None zaehlt
    weder als True noch als False (Sprint 9.10 / §5.27 Lesson)."""
    # Case A: True + False -> True
    readings_a = [
        ReadingForAggregate(
            temperature_c=Decimal("21.0"),
            open_window=True,
            health_state="healthy",
        ),
        ReadingForAggregate(
            temperature_c=Decimal("21.0"),
            open_window=False,
            health_state="healthy",
        ),
    ]
    _, window_a = aggregate_zone_readings(readings_a)
    assert window_a is True

    # Case B: True + None -> True (None zaehlt nicht als False, blockt
    # die True-Aggregation aber nicht)
    readings_b = [
        ReadingForAggregate(
            temperature_c=Decimal("21.0"),
            open_window=True,
            health_state="healthy",
        ),
        ReadingForAggregate(
            temperature_c=Decimal("21.0"),
            open_window=None,
            health_state="healthy",
        ),
    ]
    _, window_b = aggregate_zone_readings(readings_b)
    assert window_b is True
