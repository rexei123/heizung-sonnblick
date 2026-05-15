"""Sprint 9.11x.b T7 — Codec-Spiegel-Test (Drift-Schutz Backend ↔ Codec).

Backend-Helper ``downlink_adapter.py`` und ChirpStack-Codec
``infra/chirpstack/codecs/mclimate-vicki.js`` produzieren beide Bytes
fuer dieselben Vicki-Commands. Zwei Implementierungen sind eine Drift-
Quelle (vgl. CLAUDE.md §5.22 + AE-48 §Codec-Erweiterung).

Dieser Test verriegelt **Backend-Encoder gegen Vendor-Erwartungs-Bytes**
(hardcoded aus ``docs/vendor/mclimate-vicki/04-commands-cheat-sheet.md``).
Damit:
    - Backend-Drift wird sofort sichtbar (Test rot)
    - Codec-Drift wird durch identische Vendor-Bytes-Verwendung im
      Codec-Code-Review sichtbar (manueller Spiegel-Vergleich)

Variante mit echter JS-Runtime (``py_mini_racer`` / ``subprocess+node``)
ist Backlog ``B-9.11x.b-1`` — eigener Hygiene-Sprint, nicht 9.11x.b.

Diese Tests dürfen NIE editiert werden, ohne dass im Codec UND im
Backend-Helper die entsprechenden Bytes nachgezogen werden. Wenn ein
Vendor-Update neue Bytes vorschreibt: Vendor-Doku zuerst aktualisieren,
dann Test, dann beide Implementierungen.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from heizung.services.downlink_adapter import (
    VICKI_FW_QUERY_COMMAND,
    VICKI_OW_GET_COMMAND,
    _encode_ow_set_payload,
    _encode_setpoint_payload,
)

# ---------------------------------------------------------------------------
# 0x04 — FW-Query (Sprint 9.11x.b)
# ---------------------------------------------------------------------------


def test_codec_mirror_fw_query() -> None:
    """Vendor: ``0x04`` (1 byte). Backend ``query_firmware_version``
    sendet exakt das via ``send_raw_downlink(dev_eui, bytes([0x04]))``.
    Codec ``encodeDownlink({query_firmware_version: true})`` antwortet
    mit ``[0x04]``."""
    assert VICKI_FW_QUERY_COMMAND == 0x04
    # Backend-Wrapper sendet bytes([VICKI_FW_QUERY_COMMAND]) — keine
    # zusaetzliche Encoder-Funktion noetig (1-byte-Command).


# ---------------------------------------------------------------------------
# 0x04-Reply Decoder-Mirror (Sprint 9.11x.c)
# ---------------------------------------------------------------------------
#
# Spiegel der JS-Decoder-Logik in ``infra/chirpstack/codecs/
# mclimate-vicki.js`` ``decodeCommandReply`` Pfad ``cmd === 0x04``.
# Wenn der JS-Codec geaendert wird, MUSS dieser Spiegel parallel
# aktualisiert werden — sonst faellt einer der Tests um (Vendor-
# Spec-Wachposten gegen Drift). B-9.11x.b-1 (JS-Runtime via
# subprocess+node) wuerde diese Doppel-Implementierung ablösen.


def _mirror_decode_fw_reply(bytes_in: list[int]) -> dict[str, object] | None:
    """Reproduziert JS-Codec-Logik fuer 0x04-Reply (3 Bytes Nibble-Split).

    Reply-Layout (Live-Recon Vicki-001 2026-05-11):
        Byte 0: 0x04 (Reply-Cmd)
        Byte 1: HW-Version (high-nibble=major, low-nibble=minor)
        Byte 2: FW-Version (high-nibble=major, low-nibble=minor)
        Byte 3+: optional eingebetteter Keep-alive (0x81) — hier nicht
                 dekodiert (separater Periodic-Test deckt das ab); der
                 echte JS-Codec mergt die Periodic-Felder ins gleiche
                 data-Object, Reply-Felder gewinnen bei Konflikt.

    Returns None wenn bytes < 3 (Error-Path im echten Codec).
    """
    if len(bytes_in) < 3:
        return None
    hw_byte = bytes_in[1]
    fw_byte = bytes_in[2]
    return {
        "report_type": "firmware_version_reply",
        "command": 0x04,
        "firmware_version": f"{(fw_byte >> 4) & 0x0F}.{fw_byte & 0x0F}",
        "hw_version": f"{(hw_byte >> 4) & 0x0F}.{hw_byte & 0x0F}",
    }


def test_decode_fw_reply_pure_3_bytes() -> None:
    """Test 1: Pure Reply ohne eingebetteten Periodic-Frame."""
    result = _mirror_decode_fw_reply([0x04, 0x26, 0x44])
    assert result is not None
    assert result["firmware_version"] == "4.4"
    assert result["hw_version"] == "2.6"
    assert result["report_type"] == "firmware_version_reply"
    # Pure Reply: KEINE Periodic-Felder wie target_temperature/setpoint.
    assert "target_temperature" not in result
    assert "valve_openness" not in result


def test_decode_fw_reply_combined_frame_keeps_reply_priority() -> None:
    """Test 2: Reply + Keep-alive im selben Uplink (Live-Bytes Vicki-001
    2026-05-11). Reply-Felder (firmware_version, hw_version, report_type)
    muessen erhalten bleiben — sonst springt der Subscriber-Filter
    REPLY_REPORT_TYPES nicht an und _persist_uplink wuerde sensor_reading
    mit Garbage-Werten inserten.

    JS-Codec mergt zusaetzlich Periodic-Felder (target_temperature etc.),
    aber der Mirror-Helper hier dekodiert sie nicht — getestet wird hier
    nur, dass die Reply-Felder bei kombiniertem Frame stabil bleiben.
    """
    bytes_in = [0x04, 0x26, 0x44, 0x81, 0x14, 0x97, 0x62, 0xA2, 0xA2, 0x11, 0xE0, 0x30]
    result = _mirror_decode_fw_reply(bytes_in)
    assert result is not None
    assert result["firmware_version"] == "4.4"
    assert result["hw_version"] == "2.6"
    assert result["report_type"] == "firmware_version_reply"
    assert result["command"] == 0x04


def test_decode_fw_reply_nibble_order_hw_then_fw() -> None:
    """Test 3: Verriegelt die Reihenfolge — Byte 1 ist HW, Byte 2 ist FW.
    Falls jemand HW und FW versehentlich vertauscht, faellt der Test um.
    Synthetisches Sample mit asymmetrischen Werten (HW 4.5, FW 1.2) —
    damit Vertauschung sofort sichtbar wird."""
    result = _mirror_decode_fw_reply([0x04, 0x45, 0x12])
    assert result is not None
    assert result["hw_version"] == "4.5"
    assert result["firmware_version"] == "1.2"


def test_decode_fw_reply_too_short_returns_none() -> None:
    """Test 4: Bytes < 3 -> Error-Path im echten Codec
    (errors-Array, kein firmware_version-Feld emittiert)."""
    assert _mirror_decode_fw_reply([0x04, 0x10]) is None
    assert _mirror_decode_fw_reply([0x04]) is None
    assert _mirror_decode_fw_reply([]) is None


# ---------------------------------------------------------------------------
# 0x45 — Open-Window-Detection setzen (Sprint 9.11x.b)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("enabled", "duration_min", "delta_c", "vendor_bytes", "vendor_hex"),
    [
        # Vendor-Doku §01-open-window-detection.md / §04-commands-cheat-sheet.md
        (True, 10, Decimal("1.5"), [0x45, 0x01, 0x02, 0x0F], "0x4501020F"),
        (True, 30, Decimal("1.3"), [0x45, 0x01, 0x06, 0x0D], "0x4501060D"),
        # Codec-Mirror: aggressivere Variante 1.0 °C aus Cheat-Sheet
        (True, 10, Decimal("1.0"), [0x45, 0x01, 0x02, 0x0A], "0x4501020A"),
        # Disable-Variante (Audit-Pfad)
        (False, 10, Decimal("1.5"), [0x45, 0x00, 0x02, 0x0F], "0x4500020F"),
    ],
)
def test_codec_mirror_ow_set(
    enabled: bool,
    duration_min: int,
    delta_c: Decimal,
    vendor_bytes: list[int],
    vendor_hex: str,
) -> None:
    """Backend ``_encode_ow_set_payload`` muss exakt die Vendor-Bytes
    produzieren. Falls ein Refactor (z.B. duration_byte = duration_min
    statt /5, Bug aus Sprint-Brief 9.11x.b) das Format kippt, faellt
    dieser Test sofort um."""
    actual = list(_encode_ow_set_payload(enabled, duration_min, delta_c))
    assert actual == vendor_bytes, (
        f"Backend-Encoder weicht von Vendor {vendor_hex} ab: "
        f"actual={[f'0x{b:02X}' for b in actual]}, "
        f"expected={[f'0x{b:02X}' for b in vendor_bytes]}"
    )


# ---------------------------------------------------------------------------
# 0x46 — Open-Window-Detection-Status abfragen (Sprint 9.11x.b)
# ---------------------------------------------------------------------------


def test_codec_mirror_ow_get() -> None:
    """Vendor: ``0x46`` (1 byte). Identisch zu FW-Query — der Codec-
    Mirror-Test fixiert nur die Konstante, der Wrapper-Test in
    ``test_downlink_adapter.py`` verifiziert den MQTT-Pfad."""
    assert VICKI_OW_GET_COMMAND == 0x46


# ---------------------------------------------------------------------------
# 0x51 — Setpoint (Sprint 9.2, Regression-Schutz fuer Refactor)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("setpoint", "vendor_bytes"),
    [
        (10, [0x51, 0x00, 0x64]),  # 100 = 0x0064
        (21, [0x51, 0x00, 0xD2]),  # 210 = 0x00D2 (Spike 2026-05-02)
        (30, [0x51, 0x01, 0x2C]),  # 300 = 0x012C
    ],
)
def test_codec_mirror_setpoint(setpoint: int, vendor_bytes: list[int]) -> None:
    """Setpoint-Encoder ist seit Sprint 9.2 stabil. Spike-validiert.
    Test schuetzt vor versehentlichem Refactor des 0x51-Pfads im
    Rahmen der AE-48-Erweiterung."""
    actual = list(_encode_setpoint_payload(setpoint))
    assert actual == vendor_bytes


# ---------------------------------------------------------------------------
# Sprint 9.11y T5 — Inferred-Window event_log-Format-Mirror
# ---------------------------------------------------------------------------
#
# Wachposten gegen S3-Audit-Trail-Drift: ``log_inferred_window_event``
# muss event_log mit den Vendor-Spec-Feldern schreiben (Layer-Enum,
# Reason-Enum, setpoint_in==setpoint_out, details-Struktur). Bricht
# der Helper das Format, brechen Frontend-Decision-Panel-Renderer +
# Diagnose-Queries.


async def test_inferred_window_log_format_with_setpoint() -> None:
    """Standardfall: setpoint_c=20 → setpoint_in==setpoint_out==20,
    Layer/Reason korrekt, details enthaelt delta_c + devices_observed."""
    from datetime import UTC, datetime
    from typing import Any

    from heizung.models.enums import CommandReason, EventLogLayer
    from heizung.rules.inferred_window import InferredWindowResult
    from heizung.services.event_log import log_inferred_window_event

    captured: list[Any] = []

    class _FakeSession:
        def add(self, obj: Any) -> None:
            captured.append(obj)

    result = InferredWindowResult(
        room_id=42,
        detected_at=datetime(2026, 5, 11, 12, 0, 0, tzinfo=UTC),
        delta_c=Decimal("0.7"),
        devices_observed=["aabbccdd11223344", "11223344aabbccdd"],
        setpoint_c=20,
    )

    await log_inferred_window_event(_FakeSession(), result)

    assert len(captured) == 1
    ev = captured[0]
    assert ev.room_id == 42
    assert ev.layer == EventLogLayer.INFERRED_WINDOW_OBSERVATION
    assert ev.reason == CommandReason.INFERRED_WINDOW
    assert ev.time == result.detected_at
    # setpoint_in == setpoint_out markiert passive Beobachtung (kein Effekt).
    assert ev.setpoint_in == Decimal(20)
    assert ev.setpoint_out == Decimal(20)
    # details: detail-String + strukturierte Felder fuer Frontend/Queries.
    assert "detail" in ev.details
    assert ev.details["delta_c"] == "0.7"
    assert ev.details["devices_observed"] == [
        "aabbccdd11223344",
        "11223344aabbccdd",
    ]
    # evaluation_id ist UUID (eigene Mini-Eval, nicht mit Engine-Eval gemischt).
    assert ev.evaluation_id is not None


async def test_inferred_window_log_format_none_setpoint() -> None:
    """Edge-Case: setpoint_c=None (noch nie CC gesendet) → setpoint_in/out
    bleiben None, restliche Felder unveraendert."""
    from datetime import UTC, datetime
    from typing import Any

    from heizung.models.enums import CommandReason, EventLogLayer
    from heizung.rules.inferred_window import InferredWindowResult
    from heizung.services.event_log import log_inferred_window_event

    captured: list[Any] = []

    class _FakeSession:
        def add(self, obj: Any) -> None:
            captured.append(obj)

    result = InferredWindowResult(
        room_id=99,
        detected_at=datetime(2026, 5, 11, 12, 0, 0, tzinfo=UTC),
        delta_c=Decimal("0.5"),
        devices_observed=["dev0"],
        setpoint_c=None,
    )

    await log_inferred_window_event(_FakeSession(), result)

    assert len(captured) == 1
    ev = captured[0]
    assert ev.layer == EventLogLayer.INFERRED_WINDOW_OBSERVATION
    assert ev.reason == CommandReason.INFERRED_WINDOW
    assert ev.setpoint_in is None
    assert ev.setpoint_out is None
    assert ev.details["delta_c"] == "0.5"
