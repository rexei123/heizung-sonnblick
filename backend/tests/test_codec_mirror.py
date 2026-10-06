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
from heizung.services.mqtt_subscriber import REPLY_REPORT_TYPES

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


# ---------------------------------------------------------------------------
# 0x28 — Handverstellung am Drehrad (Sprint 20f, T1)
# ---------------------------------------------------------------------------
#
# **Der Befund, am 05.10.2026 belegt.** Ein 0x28-Frame traegt ab Byte 2 einen
# vollstaendigen 9-Byte-Keep-alive. Der Codec routete alles, was nicht
# 0x52/0x04/0x46 ist, nach ``decodePeriodicReport``, und die bricht am
# Command-Byte ab. Ergebnis war ``{command: 0x28}`` ohne Daten — und der
# Subscriber schrieb daraus eine ``sensor_reading``-Zeile, in der **alles
# NULL** war.
#
# Der Vor-Check des Eingangstests nahm diese Zeile als frisches Reading, las
# ``attached_backplate IS NULL`` und urteilte mit ``--require-motor``
# terminales **FAIL**. Betroffen waren die Geraete 038-044 — alle sieben
# montiert **und** kalibriert (``motorRange`` 434 bis 527).
#
# Wie bei 0x04 ist der Spiegel hier eine Python-Nachbildung der
# JS-Codec-Logik, mit **echten** Bytes vom Geraet. Eine Variante mit echter
# JS-Laufzeit ist Backlog ``B-9.11x.b-1``.


def _mirror_decode_periodic(b: list[int]) -> dict[str, object] | None:
    """Spiegel von ``decodePeriodicReport`` — nur die hier geprueften Felder.

    Bewusst knapp: geprueft wird, dass der eingebettete Keep-alive **gelesen
    statt verworfen** wird. Die vollstaendige Formel-Treue der Temperatur
    deckt ``test_map_to_reading_live_codec_output_fport2_periodic`` ab.
    """
    if len(b) < 9 or b[0] not in (0x01, 0x81):
        return None
    motor_range = ((b[6] & 0x0F) << 8) | b[5]
    motor_pos = (((b[6] >> 4) & 0x0F) << 8) | b[4]
    valve = 0
    if motor_range > 0:
        valve = max(0, min(100, round((1 - motor_pos / motor_range) * 100)))
    status8 = b[8]
    return {
        "report_type": "periodic",
        "command": b[0],
        "target_temperature": b[1],
        "battery_voltage": round(2 + ((b[7] >> 4) & 0x0F) * 0.1, 2),
        "motor_range": motor_range,
        "valve_openness": valve,
        "attachedBackplate": (status8 & 0x20) != 0,
        "calibrationFailed": (status8 & 0x40) != 0,
        "perceiveAsOnline": (status8 & 0x10) != 0,
    }


def _mirror_decode_manual_target(b: list[int]) -> dict[str, object]:
    """Spiegel von ``decodeManualTargetChange`` (Codec Sprint 20f).

    **Ein Uplink kann mehrere Datensaetze tragen** (Befund 06.10.2026,
    Geraet 102). Es gilt der **letzte vollstaendige** — die Saetze sind eine
    Reihenfolge von Verstellungen, und der Zustand am Ende des Uplinks ist der
    letzte davon.
    """
    satz_laenge = 11
    data: dict[str, object] = {}
    if len(b) < 2:
        return {"command": 0x28, "report_type": "manual_target_change"}

    historie: list[int] = []
    letzter: list[int] | None = None
    i = 0
    while i + satz_laenge <= len(b) and b[i] == 0x28:
        letzter = b[i : i + satz_laenge]
        historie.append(b[i + 1])
        i += satz_laenge

    if letzter is None:
        data["manual_target_temperature"] = b[1]
        data["target_temperature"] = b[1]
        data["manual_target_history"] = [b[1]]
        data["report_type"] = "manual_target_change"
        data["command"] = 0x28
        data["manual_target_change"] = True
        return data

    eingebettet = _mirror_decode_periodic(letzter[2:])
    if eingebettet is not None:
        data.update(eingebettet)
    data["manual_target_temperature"] = letzter[1]
    if "target_temperature" not in data:
        data["target_temperature"] = letzter[1]
    data["manual_target_history"] = historie
    data["report_type"] = "manual_target_change"
    data["command"] = 0x28
    data["manual_target_change"] = True
    return data


# Echte Payloads vom 05.10.2026, je 11 Byte.
REAL_0X28 = {
    "015": "28148114959500d201b030",
    "104": "281481149e8fb9b911f030",
}


@pytest.mark.parametrize("hardware_nummer", sorted(REAL_0X28))
def test_0x28_echte_payload_wird_vollstaendig_dekodiert(hardware_nummer: str) -> None:
    """Der eingebettete Keep-alive kommt an — Feld fuer Feld.

    Das ist die Regressions-Wand fuer die falschen FAILs vom 05.10.2026.
    Entscheidend sind zwei Felder: ``attachedBackplate`` (daran hing das
    Urteil des Vor-Checks) und ``motor_range`` (daran haengt, ob der
    Ventil-Wert ueberhaupt etwas bedeutet).
    """
    b = list(bytes.fromhex(REAL_0X28[hardware_nummer]))
    assert len(b) == 11

    d = _mirror_decode_manual_target(b)

    # Der Hand-Sollwert aus Byte 1 — 0x14 = 20 °C, die Montage-Drehung.
    assert d["manual_target_temperature"] == 20
    # Und der eingebettete Keep-alive, der vorher verloren ging.
    assert d["command"] == 0x28
    assert d["attachedBackplate"] is True, "genau dieses Feld fehlte und erzeugte FAIL"
    assert isinstance(d["motor_range"], int)
    assert d["motor_range"] > 0, "motorRange > 0 heisst kalibriert"
    assert d["target_temperature"] == 20
    assert d["calibrationFailed"] is False


def test_0x28_ist_kein_reply_typ_und_erzeugt_damit_ein_reading() -> None:
    """``report_type`` darf **nicht** in ``REPLY_REPORT_TYPES`` stehen.

    Das ist die Stelle, an der 0x28 sich von 0x04 unterscheidet, und zwar
    genau umgekehrt:

    - Bei **0x04** MUSS der Reply-Typ gesetzt bleiben, sonst schreibt
      ``_persist_uplink`` ein Reading mit NULL-Werten (der Frame ist eine
      Antwort, kein Messwert).
    - Bei **0x28** darf er es NICHT, weil der eingebettete Keep-alive ein
      echter Messwert-Satz ist, den wir speichern wollen.

    Wer das Muster von 0x04 mechanisch kopiert, baut genau den Datenverlust
    ein, den dieser Sprint behebt — eine Ebene spaeter.
    """
    d = _mirror_decode_manual_target(list(bytes.fromhex(REAL_0X28["015"])))

    assert d["report_type"] == "manual_target_change"
    assert d["report_type"] not in REPLY_REPORT_TYPES


def test_0x28_ohne_eingebetteten_keepalive_traegt_wenigstens_den_handwert() -> None:
    """Kurzer 0x28-Frame: kein Keep-alive, aber ``target_temperature``.

    Ohne dieses Feld haette die Override-Erkennung nichts zu vergleichen —
    ``_handle_override_detection`` kehrt sofort zurueck, wenn
    ``obj["target_temperature"]`` fehlt (``mqtt_subscriber.py:477``).
    """
    d = _mirror_decode_manual_target([0x28, 0x14])

    assert d["target_temperature"] == 20
    assert d["manual_target_temperature"] == 20
    # Keine Keep-alive-Felder — die Zeile traegt nur den Hand-Wert.
    assert "attachedBackplate" not in d
    assert "motor_range" not in d


def test_0x28_handwert_und_keepalive_werden_getrennt_gefuehrt() -> None:
    """Zwei Felder, nicht eines — damit ein Auseinanderlaufen auffaellt.

    In allen bisher gesehenen Frames stimmen Byte 1 und das
    ``target_temperature`` des eingebetteten Keep-alive ueberein: das Geraet
    hat den gedrehten Wert uebernommen. Synthetisch auseinandergezogen muss
    beides sichtbar bleiben — wer sie spaeter abweichen sieht, hat einen
    Befund und nicht ein Raetsel.
    """
    # Byte 1 = 0x19 (25 °C) Handwert, Keep-alive meldet 0x14 (20 °C).
    b = [0x28, 0x19] + list(bytes.fromhex("8114959500d201b030"))

    d = _mirror_decode_manual_target(b)

    assert d["manual_target_temperature"] == 25
    assert d["target_temperature"] == 20, "Keep-alive gewinnt fuer das Messfeld"


def test_0x28_calibration_failed_kommt_aus_dem_eingebetteten_frame() -> None:
    """Bit 0x40 im letzten Keep-alive-Byte (Sprint 20f, T7).

    Geraet **026** meldete am 05.10.2026 ``status8 = 0x70`` — identisch zu
    den sieben aus dem FAIL-Befund (``0x30``), **ausser** diesem Bit. Es war
    seit Sprint 6.8 im Codec und wurde nie persistiert.
    """
    # Derselbe Keep-alive wie bei 104, nur status8 von 0x30 auf 0x70.
    b = [0x28, 0x14] + list(bytes.fromhex("81149e8fb9b911f070"))

    d = _mirror_decode_manual_target(b)

    assert d["calibrationFailed"] is True
    assert d["attachedBackplate"] is True, "0x20 bleibt gesetzt"
    assert d["perceiveAsOnline"] is True, "0x10 bleibt gesetzt"


# ---------------------------------------------------------------------------
# 0x28 mit MEHREREN Datensaetzen (Befund 06.10.2026)
# ---------------------------------------------------------------------------
#
# **Live-Beleg Geraet 102**, 05.10.2026 07:43:14, fCnt 110, 22 Byte:
#
#     28 10 81 10 a5 84 b8 b8 11 60 30   <- 16 degC
#     28 13 81 13 a5 84 00 b8 01 60 30   <- 19 degC
#
# Der Gast hat zweimal gedreht, und die Vicki hat beide Schritte im selben
# Uplink gemeldet. Die erste Fassung von ``decodeManualTargetChange`` hat nur
# den **ersten** Satz ausgewertet und damit 16 statt 19 geliefert.
#
# Die Folge war nicht kosmetisch: Sprint 20f T2 legt aus diesem Wert einen
# ``device_manual``-Override an, mit vier Stunden Laufzeit. Das Zimmer waere
# also vier Stunden auf 16 °C geregelt worden, waehrend der Gast 19 °C
# eingestellt hat.

# Live-Beleg Geraet 102 — zwei Saetze in einem Uplink.
REAL_0X28_ZWEI_SAETZE = "28108110a584b8b8116030" + "28138113a58400b8016030"


def test_0x28_mehrere_saetze_der_letzte_gilt() -> None:
    """**Die Regressions-Wand fuer den Befund vom 06.10.2026.**

    Erwartung **19**, nicht 16. Begruendung: die Saetze sind eine Reihenfolge
    von Verstellungen, und der Zustand des Geraets am Ende des Uplinks ist der
    letzte davon.

    Der Beleg dafuer steckt im Frame selbst: der eingebettete Keep-alive des
    letzten Satzes traegt dasselbe ``target_temperature`` (19) wie dessen
    Byte 1 — das Geraet hat den Wert uebernommen.
    """
    b = list(bytes.fromhex(REAL_0X28_ZWEI_SAETZE))
    assert len(b) == 22

    d = _mirror_decode_manual_target(b)

    assert d["manual_target_temperature"] == 19, "der ERSTE Satz waere 16"
    assert d["target_temperature"] == 19
    # Und der Keep-alive, der ausgewertet wird, ist der des letzten Satzes:
    # dort steht das Ventil auf 100 %, im ersten auf 0 %.
    assert d["valve_openness"] == 100


def test_0x28_mehrere_saetze_historie_ist_vollstaendig() -> None:
    """Die Zwischenwerte gehen nicht verloren — aber nur zur Diagnose.

    ``manual_target_history`` hat **keinen** Konsumenten im Backend. Sie steht
    im Objekt, damit eine Reihenfolge von Drehungen nachvollziehbar ist, ohne
    den ``raw_payload`` von Hand zu dekodieren.
    """
    d = _mirror_decode_manual_target(list(bytes.fromhex(REAL_0X28_ZWEI_SAETZE)))

    assert d["manual_target_history"] == [16, 19]


def test_0x28_ein_satz_hat_eine_historie_mit_einem_eintrag() -> None:
    """Der Bestandsfall bleibt unveraendert — mit Historie der Laenge 1.

    Haelt fest, dass das Feld immer vorhanden ist. Ein Feld, das nur manchmal
    da ist, erzeugt beim Konsumenten eine Fallunterscheidung, die niemand
    testet.
    """
    for hex_wert in REAL_0X28.values():
        d = _mirror_decode_manual_target(list(bytes.fromhex(hex_wert)))

        assert d["manual_target_history"] == [d["manual_target_temperature"]]
        assert len(d["manual_target_history"]) == 1  # type: ignore[arg-type]


def test_0x28_drei_saetze_der_letzte_gilt() -> None:
    """Die Zerlegung ist nicht auf zwei Saetze festgenagelt.

    Synthetisch: drei Saetze mit unterschiedlichen Hand-Werten. Ohne diesen
    Test koennte die Schleife als ``if`` statt ``while`` geschrieben sein und
    waere beim Zwei-Satz-Beleg trotzdem gruen.
    """
    satz = list(bytes.fromhex(REAL_0X28["015"]))  # Hand-Wert 20
    eins = satz[:]
    zwei = satz[:]
    zwei[1] = 18
    drei = satz[:]
    drei[1] = 23

    d = _mirror_decode_manual_target(eins + zwei + drei)

    assert d["manual_target_temperature"] == 23
    assert d["manual_target_history"] == [20, 18, 23]


def test_0x28_unvollstaendiger_rest_wird_nicht_gedeutet() -> None:
    """Ein halber Datensatz ist keine Aussage.

    Der vollstaendige Satz davor gilt; die Rest-Bytes werden verworfen (der
    echte Codec meldet dazu eine ``warning``). Stillschweigend zu raten waere
    genau der Fehler, den dieser Fix behebt — nur in der anderen Richtung.
    """
    vollstaendig = list(bytes.fromhex(REAL_0X28["015"]))

    d = _mirror_decode_manual_target(vollstaendig + [0x28, 0x14, 0x81])

    assert d["manual_target_temperature"] == 20
    assert d["manual_target_history"] == [20]


def test_0x28_zweiter_satz_ohne_28_praefix_wird_abgebrochen() -> None:
    """Die Zerlegung verlangt ``0x28`` am Satzanfang.

    Ein Uplink, der hinter dem ersten Satz etwas anderes traegt, wird nicht
    als zweiter Hand-Wert gelesen. Ohne diese Bedingung wuerde jedes
    beliebige Byte-Paar an Position 11/12 zu einem Sollwert.
    """
    vollstaendig = list(bytes.fromhex(REAL_0X28["015"]))
    fremd = [0x81, 0x14, 0x95, 0x95, 0x00, 0xD2, 0x01, 0xB0, 0x30, 0x00, 0x00]

    d = _mirror_decode_manual_target(vollstaendig + fremd)

    assert d["manual_target_temperature"] == 20
    assert d["manual_target_history"] == [20]
