"""Downlink-Adapter — sendet Setpoints via Mosquitto an ChirpStack.

Sprint 9.2 (2026-05-03):
ChirpStack v4 nimmt Downlinks ueber MQTT entgegen, Topic-Pattern:
    application/{ApplicationID}/device/{DevEUI}/command/down

Payload-Format (JSON):
    {
        "data": "<base64>",     # Raw-Bytes: 0x51 + 16-bit BE (setpoint*10)
        "fPort": 1,
        "confirmed": false      # Class A: kein Class-A-Confirm noetig (Vicki ack via fPort 2 0x52)
    }

Im Spike (2026-05-02) validiert mit Vicki-001: 21°C-Setpoint kommt am
Drehring an, Vicki bestaetigt mit fPort-2 0x52-Reply.
"""

from __future__ import annotations

import base64
import json
import logging

import aiomqtt

from heizung.config import get_settings
from heizung.rules.constants import FROST_PROTECTION_C

logger = logging.getLogger(__name__)

# Vicki Hardware-Limit: Setpoint nur in 1.0-Schritten. Engine quantisiert
# auf int. Adapter validiert nochmal — wer hier mit float ankommt, hat
# einen Engine-Bug.
MIN_SETPOINT_C: int = int(FROST_PROTECTION_C)
MAX_SETPOINT_C: int = 30

VICKI_SETPOINT_COMMAND: int = 0x51


class DownlinkError(Exception):
    """Wird gehoben wenn Downlink semantisch falsch ist (Setpoint out of range)."""


def _encode_setpoint_payload(setpoint_c: int) -> bytes:
    """0x51 + 16-bit BE Setpoint*10 — Spike 2026-05-02 validiertes Format."""
    if not isinstance(setpoint_c, int):
        raise DownlinkError(f"setpoint muss int sein, ist {type(setpoint_c).__name__}")
    if setpoint_c < MIN_SETPOINT_C or setpoint_c > MAX_SETPOINT_C:
        raise DownlinkError(f"setpoint {setpoint_c} ausserhalb [{MIN_SETPOINT_C},{MAX_SETPOINT_C}]")
    raw = setpoint_c * 10
    return bytes([VICKI_SETPOINT_COMMAND, (raw >> 8) & 0xFF, raw & 0xFF])


def build_downlink_message(setpoint_c: int) -> str:
    """Bauen das ChirpStack-JSON. Public, damit Tests es ohne MQTT pruefen koennen."""
    payload_bytes = _encode_setpoint_payload(setpoint_c)
    payload_b64 = base64.b64encode(payload_bytes).decode("ascii")
    return json.dumps(
        {
            "data": payload_b64,
            "fPort": 1,
            "confirmed": False,
        }
    )


def build_downlink_topic(dev_eui: str) -> str:
    """Topic-String fuer einen Downlink. Public fuer Tests."""
    settings = get_settings()
    # ChirpStack-Konvention: DevEUI lowercase im Topic.
    return settings.downlink_topic_template.format(
        app_id=settings.chirpstack_app_id,
        dev_eui=dev_eui.lower(),
    )


async def send_setpoint(dev_eui: str, setpoint_c: int) -> str:
    """Publiziert einen Setpoint-Downlink.

    :param dev_eui: 16-Hex DevEUI des Vicki-TRV.
    :param setpoint_c: ganzzahliger Soll-Setpoint in degC, Bereich
                       [FROST_PROTECTION_C, MAX_SETPOINT_C].
    :return: Topic, auf den publiziert wurde (fuer Audit-Log).
    :raises DownlinkError: bei ungueltigem Setpoint.
    :raises aiomqtt.MqttError: bei MQTT-Verbindungs-/Publish-Fehler.
    """
    settings = get_settings()
    topic = build_downlink_topic(dev_eui)
    payload = build_downlink_message(setpoint_c)

    async with aiomqtt.Client(
        hostname=settings.mqtt_host,
        port=settings.mqtt_port,
        username=settings.mqtt_user,
        password=settings.mqtt_password,
        identifier=f"{settings.mqtt_client_id}-downlink",
    ) as client:
        await client.publish(topic, payload=payload, qos=1)

    logger.info(
        "downlink gesendet dev_eui=%s setpoint=%s topic=%s",
        dev_eui.lower(),
        setpoint_c,
        topic,
    )
    return topic
