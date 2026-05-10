"""Sprint 9.2 / 9.11x.b — Downlink-Adapter Tests.

Pure-Function-Tests fuer Encoding + Topic-Build + Wrapper mit
gemocktem aiomqtt-Client (Pytest-MonkeyPatch).

Sprint 9.11x.b: drei neue Wrapper (0x04 FW-Query, 0x45 OW-Set, 0x46
OW-Get) plus Vendor-Cross-Verify-Tests gegen 0x4501020F / 0x4501060D
(Vendor-Doku ``docs/vendor/mclimate-vicki/``). Decimal-Rundungs-Matrix
mit ROUND_HALF_UP fuer delta_c — Wachposten falls jemand auf Banker's
oder Float refactort.
"""

from __future__ import annotations

import base64
import json
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from heizung.config import get_settings
from heizung.services.downlink_adapter import (
    DownlinkError,
    _encode_ow_set_payload,
    build_downlink_message,
    build_downlink_topic,
    get_open_window_detection,
    query_firmware_version,
    send_setpoint,
    set_open_window_detection,
)

# ---------------------------------------------------------------------------
# build_downlink_message — Encoding (Spike-validiert)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("setpoint", "expected_bytes"),
    [
        (10, [0x51, 0x00, 0x64]),  # 100 = 0x0064
        (15, [0x51, 0x00, 0x96]),  # 150 = 0x0096
        (21, [0x51, 0x00, 0xD2]),  # 210 = 0x00D2
        (25, [0x51, 0x00, 0xFA]),  # 250 = 0x00FA
        (30, [0x51, 0x01, 0x2C]),  # 300 = 0x012C
    ],
)
def test_encoding_setpoints(setpoint: int, expected_bytes: list[int]) -> None:
    msg = json.loads(build_downlink_message(setpoint, "AABBCCDD11223344"))
    raw = base64.b64decode(msg["data"])
    assert list(raw) == expected_bytes
    assert msg["fPort"] == 1
    assert msg["confirmed"] is False
    # Sprint 9.6 Fix: devEui muss im Payload sein (lowercase) und
    # mit Topic-DevEUI matchen.
    assert msg["devEui"] == "aabbccdd11223344"


def test_setpoint_below_frost_protection_raises() -> None:
    with pytest.raises(DownlinkError, match="ausserhalb"):
        build_downlink_message(9, "00")


def test_setpoint_above_max_raises() -> None:
    with pytest.raises(DownlinkError, match="ausserhalb"):
        build_downlink_message(31, "00")


def test_non_int_setpoint_raises() -> None:
    with pytest.raises(DownlinkError, match="muss int sein"):
        build_downlink_message(21.5, "00")


# ---------------------------------------------------------------------------
# build_downlink_topic
# ---------------------------------------------------------------------------


def test_topic_is_chirpstack_pattern() -> None:
    topic = build_downlink_topic("AABBCCDDEEFF0011")
    parts = topic.split("/")
    assert parts[0] == "application"
    assert parts[2] == "device"
    assert parts[3] == "aabbccddeeff0011"  # lowercase
    assert parts[4] == "command"
    assert parts[5] == "down"


def test_topic_uses_app_id_from_settings() -> None:
    settings = get_settings()
    topic = build_downlink_topic("00")
    assert settings.chirpstack_app_id in topic


# ---------------------------------------------------------------------------
# send_setpoint mit gemocktem aiomqtt
# ---------------------------------------------------------------------------


async def test_send_setpoint_publishes_correct_topic_and_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End-to-End mit Fake-MQTT-Client. Prueft, dass der richtige Topic
    angesprochen wird und das Payload-JSON valide ist."""

    captured: dict[str, Any] = {}

    class FakeClient:
        async def __aenter__(self) -> FakeClient:
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def publish(self, topic: str, payload: bytes | str, qos: int = 0) -> None:
            captured["topic"] = topic
            captured["payload"] = payload
            captured["qos"] = qos

    fake_factory = MagicMock(return_value=FakeClient())
    monkeypatch.setattr("heizung.services.downlink_adapter.aiomqtt.Client", fake_factory)

    topic = await send_setpoint("AABBCCDD11223344", 21)

    assert topic.endswith("/aabbccdd11223344/command/down")
    assert captured["topic"] == topic
    assert captured["qos"] == 1
    body = json.loads(captured["payload"])
    raw = base64.b64decode(body["data"])
    assert list(raw) == [0x51, 0x00, 0xD2]


async def test_send_setpoint_propagates_validation_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Bei ungueltigem Setpoint wird VOR MQTT-Connect abgebrochen."""

    fake_called = AsyncMock()
    monkeypatch.setattr("heizung.services.downlink_adapter.aiomqtt.Client", fake_called)

    with pytest.raises(DownlinkError):
        await send_setpoint("AA", 35)

    fake_called.assert_not_called()


# ---------------------------------------------------------------------------
# Sprint 9.11x.b — _encode_ow_set_payload Validierung + Decimal-Matrix
# ---------------------------------------------------------------------------


# --- Vendor-Cross-Verify (zentraler Drift-Wachposten) -----------------------


@pytest.mark.parametrize(
    ("enabled", "duration_min", "delta_c", "expected_bytes"),
    [
        # Vendor-Doku §01-open-window-detection.md / §04-commands-cheat-sheet.md
        (True, 10, Decimal("1.5"), [0x45, 0x01, 0x02, 0x0F]),  # 0x4501020F
        (True, 30, Decimal("1.3"), [0x45, 0x01, 0x06, 0x0D]),  # 0x4501060D
        (False, 10, Decimal("1.5"), [0x45, 0x00, 0x02, 0x0F]),  # disable-Variante
    ],
)
def test_ow_set_vendor_cross_verify(
    enabled: bool,
    duration_min: int,
    delta_c: Decimal,
    expected_bytes: list[int],
) -> None:
    """Vendor-Bytes 1:1 reproduzieren. Wenn der Encoder ohne Test-Update
    geaendert wird (z.B. Brief-Bug duration_min ohne /5 zurueckgekehrt
    waere), wird hier sofort rot."""
    assert list(_encode_ow_set_payload(enabled, duration_min, delta_c)) == expected_bytes


# --- duration_min Validation ------------------------------------------------


@pytest.mark.parametrize(
    ("bad_duration",),
    [(7,), (4,), (0,), (1280,), (1276,)],
)
def test_ow_set_duration_min_invalid_raises(bad_duration: int) -> None:
    """duration_min muss in {5, 10, ..., 1275} liegen — sonst DownlinkError."""
    with pytest.raises(DownlinkError, match="duration_min"):
        _encode_ow_set_payload(True, bad_duration, Decimal("1.5"))


# --- delta_c Validation -----------------------------------------------------


def test_ow_set_delta_c_float_raises() -> None:
    """Float wird abgelehnt (CLAUDE.md §6 Decimal-Pflicht)."""
    with pytest.raises(DownlinkError, match="delta_c muss Decimal"):
        _encode_ow_set_payload(True, 10, 1.5)


@pytest.mark.parametrize(
    ("bad_delta",),
    [(Decimal("0.05"),), (Decimal("0"),), (Decimal("7.0"),), (Decimal("6.5"),)],
)
def test_ow_set_delta_c_out_of_range_raises(bad_delta: Decimal) -> None:
    """delta_c muss [0.1, 6.4] sein — sonst DownlinkError."""
    with pytest.raises(DownlinkError, match="ausserhalb"):
        _encode_ow_set_payload(True, 10, bad_delta)


# --- Decimal-Rundungs-Matrix (ROUND_HALF_UP, NICHT Banker's) ---------------


@pytest.mark.parametrize(
    ("delta_c", "expected_byte"),
    [
        (Decimal("1.0"), 0x0A),  # 10
        (Decimal("1.5"), 0x0F),  # 15
        (Decimal("1.54"), 0x0F),  # quantize -> 1.5 -> 15
        (Decimal("1.55"), 0x10),  # ROUND_HALF_UP -> 1.6 -> 16 (NICHT Banker's 1.5)
        (Decimal("1.56"), 0x10),  # quantize -> 1.6 -> 16
        (Decimal("2.0"), 0x14),  # 20
    ],
)
def test_ow_set_delta_c_round_half_up_matrix(delta_c: Decimal, expected_byte: int) -> None:
    """Wachposten gegen versehentliches Banker's-Rounding (Sprint 9.8b
    Lesson) oder Float-Refactor. 1.55 muss auf 1.6 (16) hoch, nicht auf
    1.5 (15) runter."""
    payload = _encode_ow_set_payload(True, 10, delta_c)
    assert payload[3] == expected_byte


# ---------------------------------------------------------------------------
# Sprint 9.11x.b — Wrapper-Tests mit gemocktem aiomqtt
# ---------------------------------------------------------------------------


def _capture_publish(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Erzeugt einen FakeClient, der publish-Args in dict captured.
    Returns das captured-dict."""
    captured: dict[str, Any] = {}

    class FakeClient:
        async def __aenter__(self) -> FakeClient:
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def publish(self, topic: str, payload: bytes | str, qos: int = 0) -> None:
            captured["topic"] = topic
            captured["payload"] = payload
            captured["qos"] = qos

    monkeypatch.setattr(
        "heizung.services.downlink_adapter.aiomqtt.Client",
        MagicMock(return_value=FakeClient()),
    )
    return captured


def _decoded_bytes(captured: dict[str, Any]) -> list[int]:
    body = json.loads(captured["payload"])
    return list(base64.b64decode(body["data"]))


async def test_query_firmware_version_publishes_0x04(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = _capture_publish(monkeypatch)
    topic = await query_firmware_version("AABBCCDD11223344")
    assert _decoded_bytes(captured) == [0x04]
    assert captured["topic"] == topic
    assert captured["topic"].endswith("/aabbccdd11223344/command/down")
    assert captured["qos"] == 1


async def test_set_open_window_detection_publishes_vendor_bytes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = _capture_publish(monkeypatch)
    await set_open_window_detection(
        "AABBCCDD11223344", enabled=True, duration_min=10, delta_c=Decimal("1.5")
    )
    assert _decoded_bytes(captured) == [0x45, 0x01, 0x02, 0x0F]


async def test_get_open_window_detection_publishes_0x46(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = _capture_publish(monkeypatch)
    await get_open_window_detection("AABBCCDD11223344")
    assert _decoded_bytes(captured) == [0x46]


async def test_set_open_window_detection_validation_blocks_mqtt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Validation-Fehler bricht VOR MQTT-Connect ab (analog send_setpoint)."""
    fake_called = AsyncMock()
    monkeypatch.setattr("heizung.services.downlink_adapter.aiomqtt.Client", fake_called)

    with pytest.raises(DownlinkError, match="duration_min"):
        await set_open_window_detection("AA", enabled=True, duration_min=7, delta_c=Decimal("1.5"))

    fake_called.assert_not_called()
