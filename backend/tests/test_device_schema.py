"""Unit-Tests fuer Device-Pydantic-Schemas.

API-Integration-Tests (TestClient + DB) folgen, wenn wir testcontainers
einfuehren - aktuell deckt diese Suite die Validierungs-Logik.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from heizung.models.enums import DeviceKind, DeviceVendor
from heizung.schemas.device import DeviceCreate, DeviceUpdate

# ---------------------------------------------------------------------------
# DeviceCreate
# ---------------------------------------------------------------------------


def _valid_create_payload() -> dict:
    return {
        "dev_eui": "0011223344556677",
        "kind": "thermostat",
        "vendor": "mclimate",
        "model": "Vicki",
        "label": "vicki-zimmer-101",
    }


def test_device_create_minimal() -> None:
    d = DeviceCreate(**_valid_create_payload())
    assert d.dev_eui == "0011223344556677"
    assert d.kind == DeviceKind.THERMOSTAT
    assert d.vendor == DeviceVendor.MCLIMATE
    assert d.is_active is True
    assert d.heating_zone_id is None
    assert d.app_eui is None


def test_device_create_normalizes_dev_eui_to_lowercase() -> None:
    payload = _valid_create_payload() | {"dev_eui": "0011223344AABBCC"}
    d = DeviceCreate(**payload)
    assert d.dev_eui == "0011223344aabbcc"


def test_device_create_normalizes_app_eui() -> None:
    payload = _valid_create_payload() | {"app_eui": "FFEEDDCCBBAA9988"}
    d = DeviceCreate(**payload)
    assert d.app_eui == "ffeeddccbbaa9988"


def test_device_create_rejects_short_eui() -> None:
    with pytest.raises(ValidationError, match="EUI"):
        DeviceCreate(**(_valid_create_payload() | {"dev_eui": "001122"}))


def test_device_create_rejects_non_hex_eui() -> None:
    with pytest.raises(ValidationError, match="EUI"):
        DeviceCreate(**(_valid_create_payload() | {"dev_eui": "001122334455667X"}))


def test_device_create_rejects_unknown_vendor() -> None:
    with pytest.raises(ValidationError):
        DeviceCreate(**(_valid_create_payload() | {"vendor": "acme"}))


def test_device_create_rejects_empty_model() -> None:
    with pytest.raises(ValidationError):
        DeviceCreate(**(_valid_create_payload() | {"model": ""}))


# ---------------------------------------------------------------------------
# DeviceUpdate
# ---------------------------------------------------------------------------


def test_device_update_all_optional() -> None:
    u = DeviceUpdate()
    assert u.model_dump(exclude_unset=True) == {}


def test_device_update_partial() -> None:
    u = DeviceUpdate(label="neuer Name", heating_zone_id=42)
    dump = u.model_dump(exclude_unset=True)
    assert dump == {"label": "neuer Name", "heating_zone_id": 42}


def test_device_update_normalizes_app_eui() -> None:
    u = DeviceUpdate(app_eui="AAAABBBBCCCCDDDD")
    assert u.app_eui == "aaaabbbbccccdddd"


def test_device_update_rejects_invalid_eui() -> None:
    with pytest.raises(ValidationError):
        DeviceUpdate(app_eui="zzz")
