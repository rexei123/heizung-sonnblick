"""Das erste Frame von Relais 109 — dekodiert vom echten Codec.

**Der Befund des Betreibers, 01.11.2026.** Relais 109
(``70b3d52ddd001e69``) hat um 07:35:18 UTC seinen ersten Uplink
geschickt, fPort 2, fCnt 1, SF12, ohne Last und mit eingeschaltetem
Relais::

    04 21 15 | 12 0a | 19 78 | 1b 00 | 1d 02 18 | a4 00 |
    01 1f 00 00 00 00 00 00 e4 00 00 01

``mclimate-16aspm.js`` hat daran **falsch** dekodiert, und zwar schon am
ersten Feld: ``responseLength(0x04)`` stand auf **5**, weil die
Vendor-Schreibweise ``0x04{HW_major}{HW_minor}{FW_major}{FW_minor}`` wie
vier Bytes aussieht. Es sind **drei** Bytes mit Nibble-Split. Der Dekoder
sprang damit um zwei Bytes zu weit, landete mitten in der naechsten
Antwort und brach mit ``unknown command code 0x19`` ab — **alles** nach
der Version war verloren, einschliesslich des angehaengten Keepalives mit
Relais-Zustand und Netzspannung.

**Diese Korrektur gab es im Haus schon.** Beim Vicki ist dieselbe Stelle
am 11.05.2026 berichtigt worden (Sprint 9.11x.c), und sie steht seither
in ``docs/vendor/mclimate-vicki/04-commands-cheat-sheet.md`` §1 mit dem
Satz, die Vendor-Beschreibung sei „ungenau". Beim zweiten Geraet ist die
Korrektur nicht mitgewandert. Das ist Paragraph 5.79: eine Lehre gilt fuer
den Stand, an dem sie gezogen wurde, und nicht fuer den Code, der danach
entsteht.

**Warum dieser Test den Codec ausfuehrt und ihn nicht nachbaut:** derselbe
Grund wie in ``test_codec_decode_uplink.py`` — ein Python-Spiegel hat kein
``decodeUplink`` und findet keinen Laengen- oder Routing-Fehler. Genau
einer lag hier vor.

**Quellen fuer die Erwartungswerte**, alle abgerufen am 01.11.2026 aus der
Hersteller-Doku (``docs.mclimate.eu``, Abschnitt „16ASPM device
communication protocol"):

===== ================================ ==========================
Code  Bedeutung                        Form
===== ================================ ==========================
0x04  HW- und SW-Version               3 Bytes, Nibbles
0x12  Keepalive-Periode                2 Bytes, Minuten
0x19  Join-Wiederholung                2 Bytes, T[s] = XX * 5
0x1B  Uplink-Art                       2 Bytes, 00 unbestaetigt
0x1D  Funk-Wachhund                    3 Bytes, bestaetigt + Stunden
0xA4  LoRaWAN-Region                   2 Bytes, 00 = EU868
0x01  Keepalive                        12 Bytes
===== ================================ ==========================

**Mutationsproben** (von Hand, 01.11.2026, alle rot):

===== ======================================= =============================
Probe Eingebauter Fehler                      Faellt
===== ======================================= =============================
C1    ``responseLength(0x04)`` zurueck auf 5   ``firmware_version`` fehlt
C2    0x04 wieder byteweise statt Nibbles      Version ``33.21`` statt 2.1
C3    0x19 aus der Laengentabelle              ``unknown_reply`` ab Byte 5
C4    0x1D auf Laenge 2                        Region und Keepalive weg
C5    ``signedTemp`` im Keepalive entfernt     -2 °C wird 130 °C
===== ======================================= =============================

C4 ist die lehrreichste: eine **falsche Laenge** bei einer Antwort, die
der Test gar nicht prueft, nimmt alles Folgende mit. Deshalb prueft dieser
Test nicht einzelne Felder, sondern **das ganze Frame plus die leere
Fehlerliste**.
"""

from __future__ import annotations

import base64
import json
import os
import pathlib
import shutil
import subprocess
from typing import Any

import pytest

CODEC = pathlib.Path(__file__).resolve().parents[1] / "codecs" / "mclimate-16aspm.js"
JS_TESTS = pathlib.Path(__file__).resolve().parents[1] / "codecs" / "test-mclimate-16aspm.js"

#: Das erste Frame von Relais 109, Base64 wie in ChirpStack.
ERSTES_FRAME_B64 = "BCEVEgoZeBsAHQIYpAABHwAAAAAAAOQAAAE="

NODE = shutil.which("node")


def _node_pflicht() -> str:
    """Node oder ein Fehlschlag — in CI ist ein Skip hier ein Fehler.

    Gleiche Begruendung wie in ``test_codec_decode_uplink.py``: der
    Workflow richtet Node ausdruecklich ein, und ein Test, der sich still
    ueberspringt, ist kein Test (Paragraph 5.81).
    """
    if NODE is None:  # pragma: no cover - haengt an der Umgebung
        if os.environ.get("CI"):
            pytest.fail(
                "node fehlt, obwohl CI es einrichtet "
                "(.github/workflows/chirpstack-tools-ci.yml, Schritt 'Setup Node 20')"
            )
        pytest.skip("node nicht gefunden - lokal ohne Node, in CI ein Fehler")
    return NODE


def _decode(bytes_: bytes, *, fport: int = 2) -> dict[str, Any]:
    """Ruft ``decodeUplink`` im echten Codec auf, ohne die Datei zu aendern."""
    node = _node_pflicht()
    skript = (
        "const fs=require('fs');"
        f"eval(fs.readFileSync({str(CODEC)!r},'utf8'));"
        f"const b=Buffer.from({list(bytes_)!r});"
        f"process.stdout.write(JSON.stringify(decodeUplink({{bytes:[...b],fPort:{fport}}})));"
    )
    lauf = subprocess.run(  # noqa: S603 - fester Pfad, kein Shell
        [node, "-e", skript],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if lauf.returncode != 0:
        pytest.fail(f"node-Fehler: {lauf.stderr.strip()}")
    ergebnis: dict[str, Any] = json.loads(lauf.stdout)
    return ergebnis


def test_erstes_frame_von_109_wird_vollstaendig_dekodiert() -> None:
    """Alle 26 Bytes, sieben Antworten, keine Fehlermeldung.

    Der Test vergleicht den **ganzen** Datenblock und nicht einzelne
    Felder. Das ist Absicht: der Fehler war eine falsche Laenge, und eine
    falsche Laenge verschiebt alles Folgende. Wer einzelne Felder prueft,
    prueft die Felder vor dem Sprung.
    """
    ergebnis = _decode(base64.b64decode(ERSTES_FRAME_B64))

    assert ergebnis["errors"] == [], (
        "Der Codec hat Fehler gemeldet; vor der Korrektur stand hier 'unknown command code 0x19'"
    )
    assert ergebnis["data"] == {
        "report_type": "command_response",
        # 0x04 — Nibbles, nicht Bytes.
        "hw_version": "2.1",
        "firmware_version": "1.5",
        # 0x12 — Werkswert 10 Minuten.
        "keepAlivePeriod_min": 10,
        # 0x19 — 0x78 * 5 = 600 s, der Werkswert.
        "joinRetryPeriod_s": 600,
        # 0x1B — Werkswert.
        "uplinkType": "unconfirmed",
        # 0x1D — beides Werkswerte: 0x02 bestaetigt, 0x18 = 24 h.
        "watchdogConfirmed": 2,
        "watchdogUnconfirmed_h": 24,
        # 0xA4 — passt zum Profil, das der Betreiber angelegt hat.
        "lorawanRegion": "EU868",
        # Der angehaengte Keepalive. **Diese Werte sind der Beweis, dass
        # die Laenge jetzt stimmt** — vor der Korrektur fehlten sie alle.
        "internalTemperature": 31,
        "energy_raw": 0,
        "energy_kWh": 0,
        "power_W": 0,
        "acVoltage_V": 228,
        "acCurrent_mA": 0,
        "relayState": "ON",
        "keepalive_included": True,
    }


def test_keepalive_ohne_last_ist_kein_defekt() -> None:
    """Null bei Leistung, Strom und Energie ist dokumentiert, nicht kaputt.

    Die Hersteller-Doku sagt es ausdruecklich: Stroeme unter 100 mA werden
    **nicht gemessen**, und dann stehen Strom, Leistung und Energiezaehler
    auf null. Ohne diesen Satz liest man das erste Frame eines Relais ohne
    Last als defekten Zaehler — und genau so lag es hier vor.

    Was **nicht** null ist, ist die Netzspannung: 228 V. Sie ist der
    Nachweis, dass das Geraet am Netz haengt und messen kann.
    """
    daten = _decode(base64.b64decode(ERSTES_FRAME_B64))["data"]

    assert daten["power_W"] == 0
    assert daten["acCurrent_mA"] == 0
    assert daten["energy_raw"] == 0
    assert daten["acVoltage_V"] == 228, "Spannung ist der Nachweis, dass gemessen wird"
    assert daten["relayState"] == "ON", "Der Betreiber hat es ohne Last eingeschaltet"


def test_negative_geraetetemperatur_kippt_nicht_nach_oben() -> None:
    """Bit 7 im Keepalive ist ab FW 1.3 das Vorzeichen.

    Vorzeichenlos gelesen wuerde aus -2 °C eine **130 °C**. Das ist nicht
    nur eine falsche Anzeige: die Ueberhitzungs-Schwelle des Geraets liegt
    im Bereich 80-90 °C, und ein Wert von 130 steht in derselben Spalte,
    in der ein Mensch nach einer Auslösung sucht.

    Relais 109 meldet FW 1.5 und ist damit betroffen. Im ersten Frame war
    Bit 7 frei (0x1f), der Fehler also unsichtbar — deshalb dieser Test
    mit einem eigenen Frame statt mit dem Live-Frame.
    """
    # Keepalive allein, Temperatur-Byte 0x82 = Vorzeichen + 2.
    kalt = _decode(bytes([0x01, 0x82, 0, 0, 0, 0, 0, 0, 0xE4, 0, 0, 0x00]), fport=2)

    assert kalt["data"]["internalTemperature"] == -2


def test_die_js_suite_laeuft_mit() -> None:
    """Fuehrt ``test-mclimate-16aspm.js`` aus.

    **Die Datei lag seit Sprint 24 im Repo und ist nie gelaufen.** Kein
    Workflow ruft sie, kein pytest sammelt sie — rund 400 Zeilen
    Codec-Tests, die bei jedem Fehler geschwiegen haben. Genau so sah der
    Laengen-Fehler in ``0x04`` sechs Tage lang gruen aus (Paragraph 5.55:
    ein gruener Lauf, der nichts geprueft hat — hier gab es nicht einmal
    einen Lauf).

    Der Aufruf ist eine Zeile. Das Fehlen war keine Entscheidung, sondern
    eine Luecke.
    """
    node = _node_pflicht()
    lauf = subprocess.run(  # noqa: S603 - fester Pfad, kein Shell
        [node, str(JS_TESTS)],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert lauf.returncode == 0, f"JS-Suite rot:\n{lauf.stdout}\n{lauf.stderr}"
