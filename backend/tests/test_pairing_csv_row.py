"""Sprint 13a T2 — PairingCsvRow Pydantic-Modell.

Pure-Function-Tests (kein DB-Zugriff). Decken Happy-Paths, Hex-Pattern-
Validation, Pool-Konsistenz, Lowercase-Normalisierung.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from heizung.scripts.pairing.csv_row import PairingCsvRow

# Test-Fixtures: Gueltige Hex-Strings in verschiedenen Cases.
_VALID_DEV_EUI_LOWER = "70b3d52dd3034de4"
_VALID_DEV_EUI_UPPER = "70B3D52DD3034DE4"
_VALID_APP_KEY_MIXED = "AbCdEf0123456789AbCdEf0123456789"


def test_happy_path_active_device() -> None:
    """Active-Geraet: alle Felder gesetzt, Pool-Konsistenz OK."""
    row = PairingCsvRow(
        stockwerk=1,
        zimmer_nummer=101,
        zimmer_typ="Standard",
        zone_label="Schlafzimmer",
        dev_eui=_VALID_DEV_EUI_LOWER,
        app_key=_VALID_APP_KEY_MIXED,
    )
    assert row.zimmer_nummer == 101
    assert row.zone_label == "Schlafzimmer"
    assert row.is_pool_device is False


def test_happy_path_pool_device() -> None:
    """Reserve-Pool: zimmer_nummer + zone_label sind None, zimmer_typ darf None sein."""
    row = PairingCsvRow(
        stockwerk=None,
        zimmer_nummer=None,
        zimmer_typ=None,
        zone_label=None,
        dev_eui=_VALID_DEV_EUI_LOWER,
        app_key=_VALID_APP_KEY_MIXED,
    )
    assert row.zimmer_nummer is None
    assert row.zone_label is None
    assert row.is_pool_device is True


def test_dev_eui_too_short_raises() -> None:
    """dev_eui mit < 16 Zeichen wird abgewiesen."""
    with pytest.raises(ValidationError) as exc_info:
        PairingCsvRow(
            stockwerk=1,
            zimmer_nummer=101,
            zimmer_typ="Standard",
            zone_label="Schlafzimmer",
            dev_eui="70b3d52d",  # nur 8 Zeichen
            app_key=_VALID_APP_KEY_MIXED,
        )
    assert "dev_eui muss 16 Hex-Zeichen sein" in str(exc_info.value)


def test_dev_eui_non_hex_raises() -> None:
    """dev_eui mit Non-Hex-Zeichen (z.B. 'g') wird abgewiesen."""
    with pytest.raises(ValidationError) as exc_info:
        PairingCsvRow(
            stockwerk=1,
            zimmer_nummer=101,
            zimmer_typ="Standard",
            zone_label="Schlafzimmer",
            dev_eui="70b3d52dd3034dgg",  # 'g' ist kein Hex
            app_key=_VALID_APP_KEY_MIXED,
        )
    assert "dev_eui muss 16 Hex-Zeichen sein" in str(exc_info.value)


def test_app_key_too_short_raises() -> None:
    """app_key mit < 32 Zeichen wird abgewiesen."""
    with pytest.raises(ValidationError) as exc_info:
        PairingCsvRow(
            stockwerk=1,
            zimmer_nummer=101,
            zimmer_typ="Standard",
            zone_label="Schlafzimmer",
            dev_eui=_VALID_DEV_EUI_LOWER,
            app_key="abcdef0123456789",  # nur 16 Zeichen
        )
    assert "app_key muss 32 Hex-Zeichen sein" in str(exc_info.value)


def test_app_key_non_hex_raises() -> None:
    """app_key mit Non-Hex-Zeichen wird abgewiesen."""
    with pytest.raises(ValidationError) as exc_info:
        PairingCsvRow(
            stockwerk=1,
            zimmer_nummer=101,
            zimmer_typ="Standard",
            zone_label="Schlafzimmer",
            dev_eui=_VALID_DEV_EUI_LOWER,
            app_key="ZZZZZZZZ" + "0" * 24,  # 'Z' kein Hex
        )
    assert "app_key muss 32 Hex-Zeichen sein" in str(exc_info.value)


def test_pool_inconsistency_zimmer_set_zone_missing_raises() -> None:
    """Gemischter Pool-Status: zimmer_nummer gesetzt, zone_label None -> Fehler."""
    with pytest.raises(ValidationError) as exc_info:
        PairingCsvRow(
            stockwerk=1,
            zimmer_nummer=101,
            zimmer_typ="Standard",
            zone_label=None,
            dev_eui=_VALID_DEV_EUI_LOWER,
            app_key=_VALID_APP_KEY_MIXED,
        )
    assert "Pool-Inkonsistenz" in str(exc_info.value)


def test_pool_inconsistency_zone_set_zimmer_missing_raises() -> None:
    """Gemischter Pool-Status: zone_label gesetzt, zimmer_nummer None -> Fehler."""
    with pytest.raises(ValidationError) as exc_info:
        PairingCsvRow(
            stockwerk=None,
            zimmer_nummer=None,
            zimmer_typ=None,
            zone_label="Schlafzimmer",
            dev_eui=_VALID_DEV_EUI_LOWER,
            app_key=_VALID_APP_KEY_MIXED,
        )
    assert "Pool-Inkonsistenz" in str(exc_info.value)


def test_lowercase_normalization_uppercase_dev_eui() -> None:
    """dev_eui in uppercase wird auf lowercase normalisiert (CLAUDE.md §5.13)."""
    row = PairingCsvRow(
        stockwerk=1,
        zimmer_nummer=101,
        zimmer_typ="Standard",
        zone_label="Schlafzimmer",
        dev_eui=_VALID_DEV_EUI_UPPER,
        app_key=_VALID_APP_KEY_MIXED,
    )
    assert row.dev_eui == _VALID_DEV_EUI_LOWER
    # app_key analog
    assert row.app_key == _VALID_APP_KEY_MIXED.lower()
