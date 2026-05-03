"""Unit-Tests fuer mqtt_subscriber.

Deckt die Pure-Functions ab (Pydantic-Validierung, Battery-Conversion,
Object-zu-Reading-Mapping). MQTT-Loop und DB-Layer sind nicht im Scope -
End-to-End wurde im Sprint-5-Brief manuell verifiziert.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from heizung.services.mqtt_subscriber import (
    ChirpStackUplink,
    _battery_pct_from_volts,
    _map_to_reading,
    _to_decimal,
)

# ---------------------------------------------------------------------------
# _battery_pct_from_volts
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("volts", "expected"),
    [
        (None, None),
        (3.0, 0),
        (4.2, 100),
        (3.6, 50),
        (3.9, 75),  # vom Mock-Uplink-Test in Sprint 5.6
        (2.5, 0),  # unter Lower-Bound -> geclampt
        (5.0, 100),  # ueber Upper-Bound -> geclampt
    ],
)
def test_battery_pct_clamping(volts: float | None, expected: int | None) -> None:
    assert _battery_pct_from_volts(volts) == expected


# ---------------------------------------------------------------------------
# _to_decimal
# ---------------------------------------------------------------------------


def test_to_decimal_passthrough() -> None:
    assert _to_decimal(21.5) == Decimal("21.5")
    assert _to_decimal("18.3") == Decimal("18.3")
    assert _to_decimal(None) is None


def test_to_decimal_returns_none_for_garbage() -> None:
    assert _to_decimal("not-a-number") is None
    assert _to_decimal({"unexpected": "type"}) is None


# ---------------------------------------------------------------------------
# ChirpStackUplink (Pydantic)
# ---------------------------------------------------------------------------


def _valid_payload() -> dict:
    return {
        "deviceInfo": {"devEui": "0011223344556677"},
        "fCnt": 1,
        "fPort": 1,
        "time": "2026-04-28T08:00:00Z",
        "object": {
            "command": 1,
            "battery_voltage": 3.9,
            "temperature": 24,
            "target_temperature": 21.0,
            "motor_position": 100,
        },
        "rxInfo": [{"rssi": -85, "snr": 7.5}],
        "data": "AQkYKshkAA==",
    }


def test_chirpstack_uplink_validates_minimal_payload() -> None:
    minimal = {
        "deviceInfo": {"devEui": "0011223344556677"},
        "fCnt": 0,
    }
    uplink = ChirpStackUplink.model_validate(minimal)
    assert uplink.deviceInfo.devEui == "0011223344556677"
    assert uplink.fCnt == 0
    assert uplink.object is None
    assert uplink.rxInfo == []


def test_chirpstack_uplink_validates_full_payload() -> None:
    uplink = ChirpStackUplink.model_validate(_valid_payload())
    assert uplink.fCnt == 1
    assert uplink.fPort == 1
    assert uplink.object is not None
    assert uplink.object["target_temperature"] == 21.0
    assert uplink.rxInfo[0].rssi == -85
    assert uplink.rxInfo[0].snr == 7.5


def test_chirpstack_uplink_rejects_missing_dev_eui() -> None:
    with pytest.raises(ValidationError):
        ChirpStackUplink.model_validate({"fCnt": 1})


def test_chirpstack_uplink_rejects_negative_fcnt() -> None:
    with pytest.raises(ValidationError):
        ChirpStackUplink.model_validate({"deviceInfo": {"devEui": "00"}, "fCnt": -1})


# ---------------------------------------------------------------------------
# _map_to_reading
# ---------------------------------------------------------------------------


def test_map_to_reading_full() -> None:
    uplink = ChirpStackUplink.model_validate(_valid_payload())
    row = _map_to_reading(uplink, device_id=42)
    assert row["device_id"] == 42
    assert row["fcnt"] == 1
    assert row["temperature"] == Decimal("24")
    assert row["setpoint"] == Decimal("21.0")
    assert row["valve_position"] == 100
    assert row["battery_percent"] == 75
    assert row["rssi_dbm"] == -85
    assert row["snr_db"] == Decimal("7.5")
    assert row["raw_payload"] == "AQkYKshkAA=="
    assert row["time"] == datetime(2026, 4, 28, 8, 0, 0, tzinfo=UTC)


def test_map_to_reading_object_missing_uses_now() -> None:
    minimal = {"deviceInfo": {"devEui": "00"}, "fCnt": 5}
    uplink = ChirpStackUplink.model_validate(minimal)
    before = datetime.now(tz=UTC)
    row = _map_to_reading(uplink, device_id=1)
    after = datetime.now(tz=UTC)
    assert before <= row["time"] <= after
    assert row["temperature"] is None
    assert row["setpoint"] is None
    assert row["battery_percent"] is None


def test_map_to_reading_partial_object() -> None:
    payload = _valid_payload()
    payload["object"] = {"temperature": 22.5}  # nur temperature
    uplink = ChirpStackUplink.model_validate(payload)
    row = _map_to_reading(uplink, device_id=1)
    assert row["temperature"] == Decimal("22.5")
    assert row["setpoint"] is None
    assert row["valve_position"] is None
    assert row["battery_percent"] is None


def test_map_to_reading_no_rxinfo() -> None:
    payload = _valid_payload()
    payload["rxInfo"] = []
    uplink = ChirpStackUplink.model_validate(payload)
    row = _map_to_reading(uplink, device_id=1)
    assert row["rssi_dbm"] is None
    assert row["snr_db"] is None


# ---------------------------------------------------------------------------
# Sprint 9.0: valve_openness aus neuem Codec hat Vorrang vor motor_position
# ---------------------------------------------------------------------------


def test_map_to_reading_uses_valve_openness_when_present() -> None:
    """Neuer Codec liefert geclamptes valve_openness 0..100."""
    payload = _valid_payload()
    payload["object"]["valve_openness"] = 73
    payload["object"]["motor_position"] = 1984  # raw, soll IGNORIERT werden
    uplink = ChirpStackUplink.model_validate(payload)
    row = _map_to_reading(uplink, device_id=1)
    assert row["valve_position"] == 73


def test_map_to_reading_falls_back_to_motor_position() -> None:
    """Alter Codec ohne valve_openness -> Fallback motor_position (Uebergang)."""
    payload = _valid_payload()
    # valve_openness explizit nicht setzen
    payload["object"].pop("valve_openness", None)
    payload["object"]["motor_position"] = 88
    uplink = ChirpStackUplink.model_validate(payload)
    row = _map_to_reading(uplink, device_id=1)
    assert row["valve_position"] == 88


def test_map_to_reading_valve_openness_zero_is_persisted() -> None:
    """Sprint-9.0-Codec clamping kann 0 liefern — darf nicht als None
    gespeichert werden (sonst wuerde fallback auf motor_position greifen
    und falsche Werte schreiben)."""
    payload = _valid_payload()
    payload["object"]["valve_openness"] = 0
    payload["object"]["motor_position"] = 9999
    uplink = ChirpStackUplink.model_validate(payload)
    row = _map_to_reading(uplink, device_id=1)
    assert row["valve_position"] == 0
