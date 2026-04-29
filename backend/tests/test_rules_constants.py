"""Regression-Tests fuer Sicherheits-Konstanten der Regel-Engine.

Aenderung dieser Werte muss bewusst sein und Test-Update erzwingen.
"""

from decimal import Decimal

from heizung.rules.constants import (
    FROST_PROTECTION_C,
    MAX_GUEST_OVERRIDE_C,
    MIN_GUEST_OVERRIDE_C,
)


def test_frost_protection_is_10_celsius() -> None:
    """Wasserrohr-Frostschutz: 10 °C ist der vereinbarte Wert (STRATEGIE Regel 8).
    Aenderung erzwingt Code-Review."""
    assert Decimal("10.0") == FROST_PROTECTION_C


def test_guest_override_bounds_consistent() -> None:
    """Min < Max, beide ueber Frostschutz."""
    assert MIN_GUEST_OVERRIDE_C < MAX_GUEST_OVERRIDE_C
    assert MIN_GUEST_OVERRIDE_C > FROST_PROTECTION_C


def test_guest_override_max_realistic() -> None:
    """Max-Override darf nicht ueber 30 °C (Hotel-Komfort + Gesundheit)."""
    assert Decimal("30.0") >= MAX_GUEST_OVERRIDE_C
