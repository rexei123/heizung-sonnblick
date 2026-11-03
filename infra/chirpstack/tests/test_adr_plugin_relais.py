"""Das ADR-Plugin fuer das Relais-Profil, ausgefuehrt mit node.

**Warum dieser Test existiert, und zwar vor dem Ausrollen.** ChirpStack
laedt die Plugin-Dateien beim Start. Eine Datei mit einem Syntaxfehler
oder ohne die erwarteten Funktionen bringt den Server dazu, den
Algorithmus stillschweigend nicht anzubieten -- und im schlechteren Fall
startet er nicht. Am Mittwoch haengen rund hundert Vickis an diesem
Server; ein Plugin, das erst dort auffaellt, ist der teuerste moegliche
Zeitpunkt.

Aus der Gemeinde ist zweierlei berichtet: ChirpStack fuehrt die Datei
als **Skript** aus (rquickjs), nicht als Modul -- ``export`` ist also
nicht zulaessig --, und bei einem Fehler im Skript gibt es **keine**
aussagekraeftige Meldung. Beides zusammen heisst: der Fehler muss hier
auffallen oder nirgends.

**Dieser Test fuehrt die Datei aus**, wie der Codec-Test es tut, und
nicht einen Python-Nachbau. Ein Nachbau haette genau die zwei Fehler
nicht gefunden, die hier moeglich sind: Syntax und fehlende Funktion.

Quelle fuer die Felder von ``req`` und der Antwort: ChirpStack-Doku
„Adaptive data-rate (ADR)" und
``examples/adr_plugins/plugin_skeleton.js`` des Projekts, beide abgerufen
am 02.11.2026.
"""

from __future__ import annotations

import json
import os
import pathlib
import shutil
import subprocess
from typing import Any

import pytest

#: **Der Pfad ist kein Zufall.** Die Datei liegt unter
#: ``configuration/``, weil der Init-Sidecar genau dieses Verzeichnis als
#: ``/template`` einbindet (``docker-compose.prod.yml``). Ein Plugin
#: ausserhalb davon waere im Container nicht erreichbar -- und das waere
#: am Mittwoch aufgefallen, nicht hier.
PLUGIN = (
    pathlib.Path(__file__).resolve().parents[1]
    / "configuration"
    / "adr-plugins"
    / "relais-feste-datenrate.js"
)

NODE = shutil.which("node")

#: Ein Anfrage-Objekt in der Form, die ChirpStack uebergibt. Die Werte
#: sind die gemessenen von Relais 109 am 01.11.2026: DR5, ein Gateway,
#: RSSI um -110 dBm, SNR knapp ueber null.
ANFRAGE: dict[str, Any] = {
    "regionConfigId": "eu868",
    "regionCommonName": "EU868",
    "devEui": "70b3d52ddd001e69",
    "macVersion": "1.0.3",
    "regParamsRevision": "A",
    "adr": True,
    "dr": 5,
    "txPowerIndex": 0,
    "nbTrans": 1,
    "maxTxPowerIndex": 5,
    "requiredSnrForDr": -10.0,
    "installationMargin": 10.0,
    "minDr": 0,
    "maxDr": 5,
    "deviceVariables": {},
    "uplinkHistory": [
        {"fCnt": 8, "maxSnr": 2.5, "maxRssi": -110, "txPowerIndex": 0, "gatewayCount": 1},
        {"fCnt": 13, "maxSnr": -1.0, "maxRssi": -113, "txPowerIndex": 0, "gatewayCount": 1},
    ],
}


def _node_pflicht() -> str:
    """Node oder ein Fehlschlag -- in CI ist ein Skip hier ein Fehler.

    Gleiche Begruendung wie im Codec-Test: der Workflow richtet Node
    ausdruecklich ein, und ein Test, der sich still ueberspringt, ist
    kein Test (Paragraph 5.81).
    """
    if NODE is None:  # pragma: no cover - haengt an der Umgebung
        if os.environ.get("CI"):
            pytest.fail(
                "node fehlt, obwohl CI es einrichtet "
                "(.github/workflows/chirpstack-tools-ci.yml, Schritt 'Setup Node 20')"
            )
        pytest.skip("node nicht gefunden - lokal ohne Node, in CI ein Fehler")
    return NODE


def _ruf(funktion: str, anfrage: dict[str, Any] | None = None) -> Any:
    """Fuehrt die Plugin-Datei als **Skript** aus und ruft eine Funktion.

    ``eval`` statt ``require``: genau so laedt ChirpStack die Datei, und
    ein ``export`` darin wuerde hier scheitern -- wie dort.
    """
    node = _node_pflicht()
    argument = json.dumps(anfrage) if anfrage is not None else ""
    skript = (
        "const fs=require('fs');"
        f"eval(fs.readFileSync({str(PLUGIN)!r},'utf8'));"
        f"process.stdout.write(JSON.stringify({funktion}({argument})));"
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
    return json.loads(lauf.stdout)


def test_die_datei_laeuft_als_skript_und_hat_die_drei_funktionen() -> None:
    """**Der wichtigste Test.** Er prueft nichts Fachliches.

    Er prueft, dass die Datei ueberhaupt laedt und die Schnittstelle
    bedient. Genau das entscheidet, ob ChirpStack am Mittwoch startet.
    """
    assert _ruf("id") == "relais_fest_dr3"
    assert "DR3" in _ruf("name")


def test_die_datenrate_wird_auf_dr3_gesetzt() -> None:
    """Der Zweck: DR3 statt DR5, zwei Wiederholungen, volle Leistung."""
    antwort = _ruf("handle", ANFRAGE)
    assert antwort["dr"] == 3
    assert antwort["nbTrans"] == 2
    assert antwort["txPowerIndex"] == 0


def test_die_region_grenzen_werden_eingehalten() -> None:
    """Ein DR ausserhalb von min_dr/max_dr waere ein abgelehnter Befehl.

    Und ein abgelehnter ``LinkADRReq`` heisst: die Datenrate bleibt, wie
    sie war, ohne Hinweis -- dieselbe Klasse wie ein Melder, dem niemand
    glaubt.
    """
    eng = dict(ANFRAGE, minDr=4, maxDr=5)
    assert _ruf("handle", eng)["dr"] == 4, "unter minDr darf nichts gefordert werden"

    niedrig = dict(ANFRAGE, minDr=0, maxDr=2)
    assert _ruf("handle", niedrig)["dr"] == 2, "ueber maxDr ebenso"


def test_ohne_adr_bleibt_alles_wie_es_war() -> None:
    """Ein Geraet, das ADR nicht anfordert, wird nicht ueberstimmt."""
    ohne = dict(ANFRAGE, adr=False, dr=5, nbTrans=1)
    antwort = _ruf("handle", ohne)
    assert antwort == {"dr": 5, "txPowerIndex": 0, "nbTrans": 1}


def test_die_antwort_hat_genau_die_drei_erwarteten_felder() -> None:
    """Mehr Felder waeren nicht falsch, aber ein Hinweis auf Verwechslung.

    ChirpStack liest ``dr``, ``txPowerIndex`` und ``nbTrans``. Wer hier
    etwa ``spreadingFactor`` zurueckgibt, hat die Schnittstelle mit dem
    Codec verwechselt -- und bekaeme keine Fehlermeldung, sondern nur
    keine Wirkung.
    """
    assert set(_ruf("handle", ANFRAGE)) == {"dr", "txPowerIndex", "nbTrans"}
