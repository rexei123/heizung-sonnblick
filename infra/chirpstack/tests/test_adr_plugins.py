"""Das ADR-Plugin fuer das Relais-Profil, ausgefuehrt mit node.

**Es gibt genau ein Plugin, und das ist eine Entscheidung.** Ein zweites
fuer die Vickis war am 13.11.2026 gebaut (feste Sendeleistung, Datenrate
adaptiv) und ist wieder entfallen: fuer sie loest
``installation_margin = 20`` in ``region_eu868.toml`` dasselbe Problem
mit **einer Zahl** statt mit einem zweiten Mechanismus, hausweit, ohne
Sonderprofil und ohne Abweichungs-Liste (Paragraph 0 S6).

Was die Zahl **nicht** loest, ist die Datenrate: der
Standard-Algorithmus senkt sie nie. Relais 108 bleibt damit auf DR3
eingeklemmt, wo es am 12.11. 16 Prozent seiner Meldungen verlor -- und
genau dafuer ist dieses Plugin da.

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
PLUGIN_VERZEICHNIS = pathlib.Path(__file__).resolve().parents[1] / "configuration" / "adr-plugins"
PLUGIN_RELAIS = PLUGIN_VERZEICHNIS / "relais-feste-datenrate.js"

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


def _ruf(
    funktion: str,
    anfrage: dict[str, Any] | None = None,
    *,
    plugin: pathlib.Path = PLUGIN_RELAIS,
) -> Any:
    """Fuehrt eine Plugin-Datei als **Skript** aus und ruft eine Funktion.

    ``eval`` statt ``require``: genau so laedt ChirpStack die Datei, und
    ein ``export`` darin wuerde hier scheitern -- wie dort.
    """
    node = _node_pflicht()
    argument = json.dumps(anfrage) if anfrage is not None else ""
    skript = (
        "const fs=require('fs');"
        f"eval(fs.readFileSync({str(plugin)!r},'utf8'));"
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
    assert _ruf("id") == "relais_fest_dr1"
    assert "DR1" in _ruf("name")


def test_die_datenrate_wird_auf_dr1_gesetzt() -> None:
    """Der Zweck: DR1 statt DR3/DR5, zwei Wiederholungen, volle Leistung.

    **Der Wachposten fuer die Aenderung vom 13.11.2026.** Die Datei stand
    auf DR3 -- gebaut gegen 109, das auf DR5 festhing. Fuer 108 waere das
    wirkungslos: ChirpStack hatte es am 12.11. selbst auf DR3 gezogen (um
    09:04 auf DR2, um 09:27 auf DR3, beide mit ``LinkADRReq
    acknowledged``), und dort verlor es 16 Prozent seiner Meldungen.

    Ein Rueckfall auf DR3 waere ohne diesen Test nicht zu bemerken: das
    Plugin laedt, der Algorithmus greift, und es wirkt nichts.
    """
    antwort = _ruf("handle", ANFRAGE)
    assert antwort["dr"] == 1, "DR3 war die alte Zieldatenrate und ist das Problem"
    assert antwort["nbTrans"] == 2
    assert antwort["txPowerIndex"] == 0


def test_die_leistung_wird_auf_voll_gesetzt_auch_wenn_sie_schon_gesenkt_war() -> None:
    """**Eine Mutationsprobe hat gezeigt, dass dafuer kein Test existierte.**

    Die Probe ersetzte ``txPowerIndex: 0`` durch ``req.txPowerIndex`` --
    also „durchreichen statt festnageln" -- und blieb gruen: die
    Standard-Anfrage oben traegt selbst schon Index 0, und
    Durchreichen liefert dann dieselbe Null.

    Der Fall aus dem Betrieb ist ein anderer: ADR hatte **109** am
    13.11.2026 auf ``tx_power_index=6`` gesenkt (ca. 4 dBm). Genau dort
    muss das Plugin die Leistung zurueckholen.
    """
    gesenkt = dict(ANFRAGE, txPowerIndex=6, maxTxPowerIndex=7)
    assert _ruf("handle", gesenkt)["txPowerIndex"] == 0, (
        "eine gesenkte Leistung muss das Plugin auf voll zuruecksetzen"
    )


def test_die_region_grenzen_werden_eingehalten() -> None:
    """Ein DR ausserhalb von min_dr/max_dr waere ein abgelehnter Befehl.

    Und ein abgelehnter ``LinkADRReq`` heisst: die Datenrate bleibt, wie
    sie war, ohne Hinweis -- dieselbe Klasse wie ein Melder, dem niemand
    glaubt.
    """
    eng = dict(ANFRAGE, minDr=4, maxDr=5)
    assert _ruf("handle", eng)["dr"] == 4, "unter minDr darf nichts gefordert werden"

    niedrig = dict(ANFRAGE, minDr=0, maxDr=0)
    assert _ruf("handle", niedrig)["dr"] == 0, "ueber maxDr ebenso"


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


def test_die_datei_steht_in_der_plugin_liste() -> None:
    """Die Datei muss in ``chirpstack.toml`` **aufgelistet** sein.

    Ein Plugin, das im Repo liegt und nicht in der Liste steht, ist kein
    Plugin -- und das faellt sonst erst am Server auf, wo das
    Geraeteprofil den Algorithmus nicht anbietet und stillschweigend auf
    den Standard zurueckfaellt.

    **Geprueft wird die Liste, nicht die Datei.** Die erste Fassung suchte
    den Dateinamen im ganzen TOML -- und blieb gruen, als eine
    Mutationsprobe die Zeile aus der Liste entfernte: der Name steht auch
    im Kommentar darueber. Ein Test, der den Kommentar liest, prueft die
    Absicht statt der Wirkung (Paragraph 5.55).
    """
    toml = (PLUGIN_VERZEICHNIS.parent / "chirpstack.toml").read_text(encoding="utf-8")
    assert "adr_plugins = [" in toml, "die Plugin-Liste fehlt ganz"
    liste = toml.split("adr_plugins = [", 1)[1].split("]", 1)[0]
    eintrag = f'"/etc/chirpstack/adr-plugins/{PLUGIN_RELAIS.name}"'
    assert eintrag in liste, f"{eintrag} fehlt in der adr_plugins-Liste"


def test_die_installationsreserve_steht_auf_zwanzig() -> None:
    """**Der Wachposten fuer die Entscheidung vom 16.11.2026.**

    ``installation_margin`` ist die SNR-Reserve, auf die ADR
    hinoptimiert. Mit der Vorgabe **10** stand das Ziel bei DR5 auf +2,5
    dB, und 90 von 109 Geraeten landeten auf ``tx_power_index 7`` (ca. 2
    dBm) -- bei Fuehler 056 riss der Link, vierzehn Stunden.

    Ein Rueckfall auf 10 waere ohne diesen Test nicht zu bemerken: nichts
    bricht, nichts meldet, und die Leistung sickert ueber Tage wieder
    weg.
    """
    region = (PLUGIN_VERZEICHNIS.parent / "region_eu868.toml").read_text(encoding="utf-8")
    zeilen = [z.strip() for z in region.splitlines() if z.strip().startswith("installation_margin")]
    assert zeilen == ["installation_margin = 20.0"], (
        f"erwartet genau eine Zeile 'installation_margin = 20.0', gefunden: {zeilen}"
    )


def test_der_init_sidecar_kopiert_das_verzeichnis() -> None:
    """**Die Zeile, an der es sonst scheitert.**

    Der Pfad steht in ``chirpstack.toml`` und zeigt auf
    ``/etc/chirpstack/adr-plugins``. Der Sidecar rendert nur die beiden
    TOML-Dateien in das Volume; ohne ein ``cp`` des Verzeichnisses ist die
    Datei im Container **nicht da**, und ChirpStack meldet dazu nichts
    Aussagekraeftiges.

    Dieser Test prueft die Verdrahtung, nicht ihre Wirkung -- er fuehrt
    kein Compose aus. Er faellt genau dann, wenn jemand die Zeile
    entfernt oder das Verzeichnis umbenennt.
    """
    compose = (PLUGIN_VERZEICHNIS.parents[2] / "deploy" / "docker-compose.prod.yml").read_text(
        encoding="utf-8"
    )
    assert "cp -r /template/adr-plugins /output/" in compose, (
        "ohne diese Zeile liegen die Plugins nicht im Container"
    )
