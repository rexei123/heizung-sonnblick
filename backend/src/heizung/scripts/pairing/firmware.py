"""Vicki-Firmware-Schwelle und Versions-Parsing (Sprint 17 / C4).

Eine Quelle fuer die Frage "kann dieses Geraet die Open-Window-Detection per
``0x45`` gesetzt bekommen?". Zwei Konsumenten:

- ``heizung.scripts.activate_open_window_detection`` — entscheidet damit, ob
  es ein Geraet beschickt oder ueberspringt.
- ``heizung.scripts.pairing.batch_inbound_test`` — erstellt damit das
  FW-Inventar vor der Montage.

Vorher stand die Schwelle nur im OW-Skript. Ein zweiter Konsument mit eigener
Kopie waere genau das Drift-Muster aus §5.20: zwei Zahlen, die dasselbe
meinen, und irgendwann meint eine davon etwas anderes.

Die Firmware kommt nicht synchron: ``query_firmware_version`` (0x04) setzt
einen Downlink ab, die Vicki antwortet beim naechsten Uplink, und der
MQTT-Subscriber schreibt den Wert nach ``device.firmware_version``
(``_handle_firmware_version_report``). Wer die Version braucht, fragt vorher
und liest spaeter — beide Konsumenten tun genau das.
"""

from __future__ import annotations

from typing import Literal

# Mindest-FW fuer die 0x45-Encoding-Variante (0.1 °C-Aufloesung).
# Quelle: docs/vendor/mclimate-vicki/§01-open-window-detection.md.
# Darunter braucht es die 0x06-Variante — B-9.11x.b-2, nicht umgesetzt.
MIN_FW_FOR_OW_SET: tuple[int, int] = (4, 2)

FirmwareClass = Literal["ow_faehig", "zu_alt", "keine_antwort"]


def parse_fw_tuple(fw: str | None) -> tuple[int, int] | None:
    """``"4.5"`` -> ``(4, 5)``. ``None`` / Format-Fehler -> ``None``.

    Akzeptiert auch ``"4.5.1"`` (3-Komponenten-Variante, falls der Codec
    spaeter erweitert wird) — nimmt dann nur major.minor.
    """
    if fw is None:
        return None
    parts = fw.split(".")
    if len(parts) < 2:
        return None
    try:
        return (int(parts[0]), int(parts[1]))
    except ValueError:
        return None


def classify_firmware(fw: str | None) -> FirmwareClass:
    """Einordnung fuer das FW-Inventar.

    - ``ow_faehig``: FW >= 4.2, der OW-Rollout beschickt das Geraet.
    - ``zu_alt``: FW bekannt, aber < 4.2 — wird uebersprungen.
    - ``keine_antwort``: keine FW in der DB. Das Geraet ist deswegen
      **nicht** defekt; es faellt nur aus dem OW-Rollout heraus, weil
      ``activate_open_window_detection`` ohne bekannte Version nicht
      beschickt. Fuer den Eingangstest ist das kein Fehlerkriterium.
    """
    parsed = parse_fw_tuple(fw)
    if parsed is None:
        return "keine_antwort"
    return "ow_faehig" if parsed >= MIN_FW_FOR_OW_SET else "zu_alt"


def supports_ow_set(fw: str | None) -> bool:
    """True, wenn der OW-Rollout dieses Geraet beschicken wird."""
    return classify_firmware(fw) == "ow_faehig"


def min_fw_text() -> str:
    """``"4.2"`` — fuer Meldungen, damit die Zahl nicht zweimal im Text steht."""
    return f"{MIN_FW_FOR_OW_SET[0]}.{MIN_FW_FOR_OW_SET[1]}"
