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
