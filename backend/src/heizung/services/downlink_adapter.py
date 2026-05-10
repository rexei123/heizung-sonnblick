"""Downlink-Adapter — sendet Vicki-Befehle via Mosquitto an ChirpStack.

Sprint 9.2 (2026-05-03): MQTT-Pfad fuer Setpoint (cmd 0x51) etabliert.
Sprint 9.11x.b (2026-05-10, AE-48): Hybrid-Helper-Architektur
    - ``send_raw_downlink``: generischer Low-Level (alle Commands)
    - ``send_setpoint``: 0x51-Wrapper (bestehender Vertrag, ruft intern
      ``send_raw_downlink``)
    - ``query_firmware_version``: 0x04 (FW-Get, asynchrone Antwort)
    - ``set_open_window_detection``: 0x45 (FW>=4.2, 0.1 °C-Resolution)
    - ``get_open_window_detection``: 0x46

ChirpStack v4 nimmt Downlinks ueber MQTT entgegen, Topic-Pattern:
    application/{ApplicationID}/device/{DevEUI}/command/down

Payload-Format (JSON):
    {
        "devEui": "<lowercase-hex>",
        "data": "<base64>",
        "fPort": 1,
        "confirmed": false
    }

ChirpStack v4 verlangt ``devEui`` im Payload (muss mit Topic-DevEUI
uebereinstimmen). Ohne dieses Feld verwirft ChirpStack den Downlink
mit ``Processing command error: Payload dev_eui does not match topic
dev_eui`` (Sprint 9.6 Live-Test-Fix, CLAUDE.md §5.13).

Spike 2026-05-02: 21°C-Setpoint kommt am Vicki-Drehring an, Vicki
bestaetigt mit fPort-2 0x52-Reply.
"""

from __future__ import annotations

import base64
import json
import logging
from decimal import ROUND_HALF_UP, Decimal

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
VICKI_FW_QUERY_COMMAND: int = 0x04
VICKI_OW_SET_COMMAND: int = 0x45
VICKI_OW_GET_COMMAND: int = 0x46

# 0x45-Encoding (Vendor-Doku docs/vendor/mclimate-vicki/01-open-window-detection.md):
# Byte 1 = enable/disable, Byte 2 = duration_min/5, Byte 3 = delta_c*10.
# duration_min muss durch 5 teilbar sein (5..1275 = 255*5), delta_c liegt
# zwischen 0.1 und 6.4 °C in 0.1-Schritten (0x01..0x40, da Byte = delta*10).
OW_DURATION_MIN_MIN: int = 5
OW_DURATION_MIN_MAX: int = 1275
OW_DURATION_STEP_MIN: int = 5
OW_DELTA_MIN_C: Decimal = Decimal("0.1")
OW_DELTA_MAX_C: Decimal = Decimal("6.4")


class DownlinkError(Exception):
    """Wird gehoben wenn Downlink semantisch falsch ist (out of range etc.)."""


def _encode_setpoint_payload(setpoint_c: int) -> bytes:
    """0x51 + 16-bit BE Setpoint*10 — Spike 2026-05-02 validiertes Format."""
    if not isinstance(setpoint_c, int):
        raise DownlinkError(f"setpoint muss int sein, ist {type(setpoint_c).__name__}")
    if setpoint_c < MIN_SETPOINT_C or setpoint_c > MAX_SETPOINT_C:
        raise DownlinkError(f"setpoint {setpoint_c} ausserhalb [{MIN_SETPOINT_C},{MAX_SETPOINT_C}]")
    raw = setpoint_c * 10
    return bytes([VICKI_SETPOINT_COMMAND, (raw >> 8) & 0xFF, raw & 0xFF])


def _encode_ow_set_payload(
    enabled: bool,
    duration_min: int,
    delta_c: Decimal,
) -> bytes:
    """0x45 + enable + duration_min/5 + delta_c*10 (FW>=4.2, 0.1 °C-Resolution).

    Range-Validation gegen Vendor-Spec: duration_min muss in
    {5, 10, ..., 1275} liegen, delta_c in [0.1, 6.4] °C in 0.1-Schritten.
    """
    if not isinstance(delta_c, Decimal):
        raise DownlinkError(f"delta_c muss Decimal sein, ist {type(delta_c).__name__}")
    if (
        duration_min < OW_DURATION_MIN_MIN
        or duration_min > OW_DURATION_MIN_MAX
        or duration_min % OW_DURATION_STEP_MIN != 0
    ):
        raise DownlinkError(
            f"duration_min muss in {{{OW_DURATION_MIN_MIN}, "
            f"{OW_DURATION_MIN_MIN + OW_DURATION_STEP_MIN}, ..., "
            f"{OW_DURATION_MIN_MAX}}} liegen, ist {duration_min}"
        )
    if delta_c < OW_DELTA_MIN_C or delta_c > OW_DELTA_MAX_C:
        raise DownlinkError(f"delta_c {delta_c} ausserhalb [{OW_DELTA_MIN_C}, {OW_DELTA_MAX_C}] °C")

    enabled_byte = 0x01 if enabled else 0x00
    duration_byte = duration_min // OW_DURATION_STEP_MIN
    delta_byte = int(delta_c.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP) * 10)
    return bytes([VICKI_OW_SET_COMMAND, enabled_byte, duration_byte, delta_byte])


def build_downlink_message(setpoint_c: int, dev_eui: str) -> str:
    """Bauen das ChirpStack-JSON. Public, damit Tests es ohne MQTT pruefen koennen.

    Sprint 9.11x.b: Bleibt als Setpoint-spezifischer Builder erhalten
    (0x51-Pfad). Generische Variante via ``_build_downlink_message_raw``.
    """
    payload_bytes = _encode_setpoint_payload(setpoint_c)
    return _build_downlink_message_raw(dev_eui, payload_bytes, fport=1, confirmed=False)


def _build_downlink_message_raw(
    dev_eui: str,
    payload_bytes: bytes,
    *,
    fport: int = 1,
    confirmed: bool = False,
) -> str:
    """Generischer JSON-Builder fuer beliebige Downlink-Bytes.

    ChirpStack v4 verlangt ``devEui`` im Payload (lowercase, muss mit
    Topic-DevEUI matchen). Sonst wird der Downlink verworfen
    (CLAUDE.md §5.13).
    """
    payload_b64 = base64.b64encode(payload_bytes).decode("ascii")
    return json.dumps(
        {
            "devEui": dev_eui.lower(),
            "data": payload_b64,
            "fPort": fport,
            "confirmed": confirmed,
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


async def send_raw_downlink(
    dev_eui: str,
    payload_bytes: bytes,
    *,
    fport: int = 1,
    confirmed: bool = False,
) -> str:
    """Generischer MQTT-Publish auf ChirpStack-Downlink-Topic (AE-48).

    Eine Single-Source-of-Truth fuer den MQTT-Pfad. Wrapper (Setpoint,
    FW-Query, OW-Set/Get) bauen ihre Bytes und delegieren hierher —
    so wird MQTT-Mechanik nur einmal getestet.

    :return: Topic, auf den publiziert wurde (fuer Audit-Log).
    :raises aiomqtt.MqttError: bei MQTT-Verbindungs-/Publish-Fehler.
    """
    settings = get_settings()
    topic = build_downlink_topic(dev_eui)
    payload = _build_downlink_message_raw(dev_eui, payload_bytes, fport=fport, confirmed=confirmed)

    async with aiomqtt.Client(
        hostname=settings.mqtt_host,
        port=settings.mqtt_port,
        username=settings.mqtt_user,
        password=settings.mqtt_password,
        identifier=f"{settings.mqtt_client_id}-downlink",
    ) as client:
        await client.publish(topic, payload=payload, qos=1)

    logger.info(
        "downlink gesendet dev_eui=%s cmd=0x%02X topic=%s",
        dev_eui.lower(),
        payload_bytes[0] if payload_bytes else 0,
        topic,
    )
    return topic


async def query_firmware_version(dev_eui: str) -> str:
    """Sendet 0x04 — Vicki antwortet asynchron im naechsten Uplink mit
    Bytes ``0x04 {HW_major} {HW_minor} {FW_major} {FW_minor}`` (Vendor-
    Doku §04-commands-cheat-sheet). Codec emittiert dann
    ``firmware_version: "{FW_major}.{FW_minor}"``, MQTT-Subscriber
    schreibt das in ``device.firmware_version``.

    Kein confirmed-Flag — Antwort kommt als Uplink, nicht als ACK.
    """
    return await send_raw_downlink(dev_eui, bytes([VICKI_FW_QUERY_COMMAND]))


async def set_open_window_detection(
    dev_eui: str,
    enabled: bool,
    duration_min: int,
    delta_c: Decimal,
) -> str:
    """Sendet 0x45 — aktiviert/deaktiviert Vicki-Open-Window-Algorithmus
    (FW>=4.2, 0.1 °C-Resolution-Variante, Vendor-Doku §01).

    :param enabled: True = OW-Detection an, False = aus.
    :param duration_min: Dauer der Ventil-Schliessung bei Erkennung
                         (5..1275 Min in 5-Min-Schritten).
    :param delta_c: Temperatur-Delta-Schwelle (0.1..6.4 °C). MUSS Decimal
                    sein — Float wird abgelehnt (CLAUDE.md §6).
    :raises DownlinkError: bei out-of-range duration_min oder delta_c.
    """
    payload_bytes = _encode_ow_set_payload(enabled, duration_min, delta_c)
    return await send_raw_downlink(dev_eui, payload_bytes)


async def get_open_window_detection(dev_eui: str) -> str:
    """Sendet 0x46 — Vicki antwortet asynchron mit dem aktuellen
    OW-Setting in Bytes ``0x46 {enabled} {duration_byte} {delta_byte}``
    (Vendor-Doku §04). MQTT-Subscriber loggt die Werte als strukturierten
    JSON-Eintrag (S6: Logger statt event_log-DB-Insert)."""
    return await send_raw_downlink(dev_eui, bytes([VICKI_OW_GET_COMMAND]))


async def send_setpoint(dev_eui: str, setpoint_c: int) -> str:
    """Publiziert einen Setpoint-Downlink (0x51).

    Sprint 9.11x.b: refactored auf ``send_raw_downlink``. Verhalten
    identisch zu Sprint 9.2 — bestehender 0x51-Test bleibt gruen.

    :param dev_eui: 16-Hex DevEUI des Vicki-TRV.
    :param setpoint_c: ganzzahliger Soll-Setpoint in degC, Bereich
                       [FROST_PROTECTION_C, MAX_SETPOINT_C].
    :return: Topic, auf den publiziert wurde (fuer Audit-Log).
    :raises DownlinkError: bei ungueltigem Setpoint.
    :raises aiomqtt.MqttError: bei MQTT-Verbindungs-/Publish-Fehler.
    """
    payload_bytes = _encode_setpoint_payload(setpoint_c)
    return await send_raw_downlink(dev_eui, payload_bytes)
