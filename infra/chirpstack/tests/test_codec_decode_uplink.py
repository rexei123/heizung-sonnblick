"""Der Codec wird als JavaScript ausgefuehrt, nicht in Python nachgebaut.

**Warum das noetig wurde.** ``backend/tests/test_codec_mirror.py`` spiegelt
die Decoder-**Logik** in Python: es prueft, dass aus ``15 05 1E`` die Werte
5 und 30 folgen. Genau dieser Test war gruen, waehrend in der Anlage
nichts ankam — denn der Fehler lag nicht in der Logik, sondern im
**Routing**: ``decodeUplink`` schickte ``0x15`` nie an
``decodeCommandReply``, sondern an ``decodePeriodicReport``.

Live-Beleg des Betreibers, 26.10.2026: Geraet ``70b3d52dd303337d``,
Uplink 09:44:51, fCnt 3897, ``data = "FQ8ZgRKbfNnZEfAw"`` ->

    15 0F 19 | 81 12 9B 7C D9 D9 11 F0 30

Das Geraet meldete seine Grenzen (15/25) **und** einen angehaengten
Keep-alive. ChirpStack zeigte im ``object``-Block: ``{command: 21}``.
Reply und Keep-alive verloren.

Das ist Paragraph 5.83 in Reinform: die Zusicherung „der Codec dekodiert
0x15" galt auf der Ebene, auf der sie geprueft war (dem Zweig), und nicht
auf der, die zaehlt (dem ganzen Durchlauf). Ein Python-Spiegel kann das
**nicht** finden — er hat kein ``decodeUplink``.

**Deshalb fuehrt dieser Test die Datei aus.** ``node`` liest den Codec,
ruft ``decodeUplink`` mit den echten Bytes und gibt JSON zurueck. Keine
Abhaengigkeit, kein Paketmanager: ``node -e`` und eine Datei.

**Mutationsprobe** (von Hand, dokumentiert): nimmt man ``0x15`` aus
``REPLY_COMMANDS`` heraus, faellt
``test_live_frame_vom_26_10_wird_vollstaendig_dekodiert`` mit
``report_type`` statt ``temp_range_reply`` gleich ``None`` und
``command = 21``. Geprueft am 26.10.2026.
"""

from __future__ import annotations

import base64
import json
import os
import pathlib
import re
import shutil
import subprocess
from typing import Any

import pytest

CODEC = pathlib.Path(__file__).resolve().parents[1] / "codecs" / "mclimate-vicki.js"

#: Der Live-Frame des Betreibers. Base64 wie in ChirpStack.
LIVE_FRAME_B64 = "FQ8ZgRKbfNnZEfAw"

NODE = shutil.which("node")


def _decode(bytes_: bytes, *, fport: int = 2) -> dict[str, Any]:
    """Ruft ``decodeUplink`` im echten Codec auf.

    ``node -e`` mit ``eval`` auf den Dateiinhalt: der Codec ist eine
    ChirpStack-Datei ohne Modul-Exporte, und ihn fuer den Test mit einem
    ``module.exports`` zu versehen waere eine Aenderung an der Datei, die
    in der Anlage laeuft — also genau die Sorte Unterschied zwischen
    Pruefstand und Betrieb, die dieser Test beseitigen soll.
    """
    if NODE is None:  # pragma: no cover - haengt an der Umgebung
        # **In CI ist ein Skip hier ein Fehler**, kein Zustand: der
        # Workflow richtet Node ausdruecklich ein, und ein Test, der sich
        # still ueberspringt, ist kein Test (Paragraph 5.81 — die
        # Statusfarbe sagt es nicht).
        if os.environ.get("CI"):
            pytest.fail(
                "node fehlt, obwohl CI es einrichtet "
                "(.github/workflows/chirpstack-tools-ci.yml, Schritt 'Setup Node 20')"
            )
        pytest.skip("node nicht gefunden — lokal ohne Node, in CI ein Fehler")
    skript = (
        "const fs=require('fs');"
        f"eval(fs.readFileSync({str(CODEC)!r},'utf8'));"
        f"const b=Buffer.from({list(bytes_)!r});"
        f"process.stdout.write(JSON.stringify(decodeUplink({{bytes:[...b],fPort:{fport}}})));"
    )
    lauf = subprocess.run(  # noqa: S603 - fester Pfad, kein Shell
        [NODE, "-e", skript],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if lauf.returncode != 0:
        pytest.fail(f"node-Fehler: {lauf.stderr.strip()}")
    ergebnis: dict[str, Any] = json.loads(lauf.stdout)
    return ergebnis


def test_live_frame_vom_26_10_wird_vollstaendig_dekodiert() -> None:
    """Reply **und** Keep-alive aus demselben Frame.

    Die Erwartungswerte fuer die Grenzen stehen in der Hersteller-Doku
    (ganze Grad, ohne Skalierung) und sind hier vom Geraet belegt: 0x0F =
    15, 0x19 = 25.

    Die Keep-alive-Felder sind **nicht** aus der Doku, sondern Ausgabe
    desselben Decoders, der sie seit Sprint 9 fuer jeden Periodic-Report
    liefert. Sie stehen hier, weil der Punkt des Tests ist, dass sie
    **ueberhaupt** da sind: vor dem Fix fehlten sie alle.
    """
    ergebnis = _decode(base64.b64decode(LIVE_FRAME_B64))
    daten = ergebnis["data"]

    assert daten.get("report_type") == "temp_range_reply", (
        f"0x15 landet nicht im Reply-Zweig — steht es in REPLY_COMMANDS? (bekommen: {daten})"
    )
    assert daten["temp_range_min"] == 15
    assert daten["temp_range_max"] == 25

    # Der angehaengte Keep-alive. Ohne mergeEmbeddedKeepalive fehlt das
    # alles, und die Messung dieses Frames ist weg.
    assert "temperature" in daten, "der angehaengte Keep-alive ist verloren"
    assert daten["temperature"] == pytest.approx(22.35, abs=0.01)
    assert daten["battery_voltage"] == pytest.approx(3.5, abs=0.01)
    assert daten["attachedBackplate"] is True
    assert daten["childLock"] is False

    assert not ergebnis.get("errors")


def test_werkseinstellung_aus_der_vendor_doku() -> None:
    """``0x15 05 1E`` = 5/30 — der Beleg der Hersteller-Doku, ohne Keep-alive.

    Quelle: docs.mclimate.eu, Vicki-Protokoll, „Limit target temperature
    range", abgerufen 21.10.2026.
    """
    daten = _decode(bytes([0x15, 0x05, 0x1E]))["data"]
    assert daten["report_type"] == "temp_range_reply"
    assert (daten["temp_range_min"], daten["temp_range_max"]) == (5, 30)
    # Kein Keep-alive im Frame, also auch keine Mess-Felder — und
    # **kein** erfundener.
    assert "temperature" not in daten


def test_zu_kurzer_frame_meldet_einen_fehler() -> None:
    ergebnis = _decode(bytes([0x15, 0x05]))
    assert ergebnis["data"]["report_type"] == "temp_range_reply"
    assert ergebnis.get("errors")


def test_periodic_report_bleibt_unberuehrt() -> None:
    """Die Gegenprobe: ein normaler Keep-alive geht weiter seinen Weg.

    Der Fix hat am Routing gedreht, und eine Liste, die zu viel enthaelt,
    waere der Fehler in die andere Richtung — ein Periodic-Report im
    Reply-Zweig traegt ``report_type`` und der Subscriber ueberspringt
    seine Messung.
    """
    keepalive = bytes([0x81, 0x12, 0x9B, 0x7C, 0xD9, 0xD9, 0x11, 0xF0, 0x30])
    daten = _decode(keepalive)["data"]
    # ``periodic`` und nicht etwa kein ``report_type``: der Decoder setzt
    # ihn selbst (nachgesehen, nicht angenommen — meine erste Fassung
    # dieses Tests behauptete das Gegenteil und fiel deshalb).
    #
    # Der Punkt ist, dass er **kein Reply-Typ** ist: nur die aus
    # REPLY_REPORT_TYPES lassen den Subscriber die Messung ueberspringen.
    assert daten["report_type"] == "periodic"
    assert daten["temperature"] == pytest.approx(22.35, abs=0.01)


def test_jeder_befehl_den_wir_senden_hat_ein_zuhause() -> None:
    """Der Spiegel zum Backend: kein Reply-Code ohne Routing.

    Das ist die Pruefung, deren Fehlen den Live-Befund erst moeglich
    gemacht hat. Sie liest die Liste aus dem Codec und die gesendeten
    Befehle aus ``downlink_adapter`` — beide aus dem Quelltext, keine
    dritte Liste.

    **Nicht jeder gesendete Befehl hat eine Antwort mit eigenem
    Command-Byte** (``0x51`` wird mit ``0x52`` beantwortet, ``0x45`` und
    ``0x08`` gar nicht). Deshalb steht die Zuordnung hier ausdruecklich
    und nicht als Annahme „Antwort = derselbe Code".
    """
    adapter = (
        pathlib.Path(__file__).resolve().parents[3]
        / "backend"
        / "src"
        / "heizung"
        / "services"
        / "downlink_adapter.py"
    )
    quelle = adapter.read_text(encoding="utf-8")

    # Welcher gesendete Befehl wird mit welchem Command-Byte beantwortet.
    # ``None`` heisst: keine Antwort mit eigenem Code (die Wirkung steht
    # im naechsten Keep-alive).
    erwartete_antwort = {
        "VICKI_SETPOINT_COMMAND": 0x52,
        "VICKI_FW_QUERY_COMMAND": 0x04,
        "VICKI_OW_SET_COMMAND": None,
        "VICKI_OW_GET_COMMAND": 0x46,
        "VICKI_TEMP_RANGE_SET_COMMAND": None,
        "VICKI_TEMP_RANGE_GET_COMMAND": 0x15,
        "VICKI_CHILD_LOCK_SET": None,
        "VICKI_CHILD_LOCK_GET": 0x14,
    }
    gesendet = set(re.findall(r"^(VICKI_[A-Z_]+)(?::\s*int)?\s*=\s*0x", quelle, re.MULTILINE))
    assert gesendet == set(erwartete_antwort), (
        "downlink_adapter sendet andere Befehle als hier zugeordnet — "
        f"neu: {gesendet - set(erwartete_antwort)}, "
        f"weg: {set(erwartete_antwort) - gesendet}"
    )

    codec = CODEC.read_text(encoding="utf-8")
    beginn = codec.index("var REPLY_COMMANDS")
    ende = codec.index("];", beginn)
    geroutet = {int(w, 16) for w in re.findall(r"0x([0-9a-fA-F]{2})", codec[beginn:ende])}

    fehlend = {
        name: hex(code)
        for name, code in erwartete_antwort.items()
        if code is not None and code not in geroutet
    }
    assert not fehlend, (
        "Reply-Codes ohne Eintrag in REPLY_COMMANDS — ihre Antwort landet "
        f"in decodePeriodicReport und ist verloren: {fehlend}"
    )
