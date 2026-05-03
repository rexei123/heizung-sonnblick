"""Sprint 9.2 — Downlink-Adapter Tests.

Pure-Function-Tests fuer Encoding + Topic-Build + send_setpoint mit
gemocktem aiomqtt-Client (Pytest-MonkeyPatch).
"""

from __future__ import annotations

import base64
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from heizung.config import get_settings
from heizung.services.downlink_adapter import (
    DownlinkError,
    build_downlink_message,
    build_downlink_topic,
    send_setpoint,
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
    msg = json.loads(build_downlink_message(setpoint))
    raw = base64.b64decode(msg["data"])
    assert list(raw) == expected_bytes
    assert msg["fPort"] == 1
    assert msg["confirmed"] is False


def test_setpoint_below_frost_protection_raises() -> None:
    with pytest.raises(DownlinkError, match="ausserhalb"):
        build_downlink_message(9)


def test_setpoint_above_max_raises() -> None:
    with pytest.raises(DownlinkError, match="ausserhalb"):
        build_downlink_message(31)


def test_non_int_setpoint_raises() -> None:
    with pytest.raises(DownlinkError, match="muss int sein"):
        build_downlink_message(21.5)  # type: ignore[arg-type]


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
