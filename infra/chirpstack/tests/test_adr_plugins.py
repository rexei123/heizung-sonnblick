"""Das ADR-Plugin fuer das Relais-Profil -- in zwei Umgebungen geprueft.

**Es gibt genau ein Plugin, und das ist eine Entscheidung.** Ein zweites
fuer die Vickis war am 13.11.2026 gebaut (feste Sendeleistung, Datenrate
adaptiv) und ist wieder entfallen: fuer sie loest
``installation_margin = 20`` in ``region_eu868.toml`` dasselbe Problem
mit **einer Zahl** statt mit einem zweiten Mechanismus, hausweit, ohne
Sonderprofil und ohne Abweichungs-Liste (Paragraph 0 S6).

Was die Zahl **nicht** loest, ist die Datenrate: der
Standard-Algorithmus senkt sie nie. Am 16.11.2026 hat er 108 sogar von
DR3 auf **DR5** hochgezogen, bei Reserve 20 und voller Sendeleistung --
belegt mit vier ``LinkADRReq acknowledged`` im Protokoll. Genau dafuer
ist dieses Plugin da.

## Warum diese Datei zweimal geladen wird

**Am 15.11.2026 waren 54 Tests gruen, und ChirpStack startete nicht.**
Der Docstring an dieser Stelle behauptete, ChirpStack fuehre die Datei
als *Skript* aus, ``export`` sei unzulaessig -- und der Test lud sie per
``eval``, also genau so. ChirpStack 4.17 deklariert sie aber als
**ES-Modul** und holt die Funktionen am Modul-Objekt. Die beiden
Anforderungen schliessen sich aus, und der Test hat die falsche
festgenagelt. Sieben Minuten Ausfall, von 08:53 bis 09:00.

Das war Paragraph 5.55 in seiner teuersten Form: *laeuft der Test dort,
wo der Code laufen muss?* Die Antwort war nein, und niemand konnte es
sehen. Deshalb jetzt zwei Stufen:

1. **Der Vertrag, unter Node, bei jedem Lauf** (schnell, ~1 s): die
   Datei wird als ES-Modul importiert und die drei **benannten Exporte**
   gelesen. Das ist derselbe Vertrag, den ``m.get("id")`` prueft.
2. **Die echte Engine, im echten Image** (langsam, ~60 s): ``chirpstack
   /chirpstack:4`` -- dieselbe Fassung wie am Server -- laeuft gegen eine
   Wegwerf-Datenbank und laedt unsere echte ``chirpstack.toml``. Zwei
   Zusicherungen: diese Fassung laedt, **und die Fassung vom 15.11. ohne
   ``export`` bricht mit genau der damaligen Meldung ab**. Die zweite ist
   die wichtigere -- ohne sie waere Stufe 2 ein Test, der nicht zeigen
   kann, dass er etwas prueft.

Stufe 2 braucht Postgres und Redis, und das ist gemessen, nicht
geschaetzt: ChirpStack 4.17 baut den Datenbank-Pool auf und wandert das
Schema **bevor** es die ADR-Plugins laedt. Ein Plugin-Test ohne
Datenbank ist deshalb nicht moeglich.

Quelle fuer die Felder von ``req`` und der Antwort: ChirpStack-Doku
„Adaptive data-rate (ADR)" und
``examples/adr_plugins/plugin_skeleton.js`` des Projekts, beide abgerufen
am 02.11.2026. Quelle fuer die Ladeform: ``chirpstack/src/adr/plugin.rs``
(``Module::declare`` + ``m.get``), abgerufen am 15.11.2026 -- und seit
dem 16.11.2026 hier gemessen statt gelesen.
"""

from __future__ import annotations

import json
import os
import pathlib
import re
import shutil
import subprocess
import time
import uuid
from typing import Any

import pytest

#: **Der Pfad ist kein Zufall.** Die Datei liegt unter
#: ``configuration/``, weil der Init-Sidecar genau dieses Verzeichnis als
#: ``/template`` einbindet (``docker-compose.prod.yml``). Ein Plugin
#: ausserhalb davon waere im Container nicht erreichbar.
KONFIG = pathlib.Path(__file__).resolve().parents[1] / "configuration"
PLUGIN_VERZEICHNIS = KONFIG / "adr-plugins"
PLUGIN_RELAIS = PLUGIN_VERZEICHNIS / "relais-feste-datenrate.js"
COMPOSE_PROD = KONFIG.parents[1] / "deploy" / "docker-compose.prod.yml"

NODE = shutil.which("node")
DOCKER = shutil.which("docker")

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


# ---------------------------------------------------------------- Stufe 1


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
    """Laedt die Datei als **ES-Modul** und ruft einen benannten Export.

    ``import()`` statt ``eval``: ChirpStack deklariert die Datei als
    Modul und holt ``id``/``name``/``handle`` am Modul-Objekt. Ein
    ``eval`` wie in der Fassung bis zum 15.11.2026 prueft das Gegenteil
    -- es verlangt Funktionen **ohne** ``export`` und war damit der
    Grund, warum der Ausfall 54 gruene Tests ueberlebt hat.

    Die drei Exporte werden hier **einzeln** geprueft, bevor gerufen
    wird: ``m.handle`` waere sonst nur ``undefined is not a function``,
    und das sagt nicht, welcher Export fehlt.
    """
    node = _node_pflicht()
    argument = json.dumps(anfrage) if anfrage is not None else ""
    skript = (
        f"const m = await import({plugin.as_uri()!r});"
        "for (const n of ['id','name','handle'])"
        "  if (typeof m[n] !== 'function')"
        "    throw new Error(n + ' fehlt als benannter Export');"
        f"process.stdout.write(JSON.stringify(m.{funktion}({argument})));"
    )
    lauf = subprocess.run(  # noqa: S603 - fester Pfad, kein Shell
        [node, "--input-type=module", "-e", skript],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if lauf.returncode != 0:
        pytest.fail(f"node-Fehler: {lauf.stderr.strip()}")
    return json.loads(lauf.stdout)


def test_die_datei_laedt_als_modul_und_exportiert_die_drei_funktionen() -> None:
    """**Der wichtigste schnelle Test.** Er prueft nichts Fachliches.

    Er prueft, dass die Datei als Modul laedt und die drei Funktionen
    **exportiert**. Genau das entscheidet, ob ChirpStack startet -- und
    genau das hat die Fassung bis zum 15.11.2026 nicht getan.
    """
    assert _ruf("id") == "relais_fest_dr1"
    assert "DR1" in _ruf("name")


def test_die_datenrate_wird_auf_dr1_gesetzt() -> None:
    """Der Zweck: DR1 statt DR3/DR5, zwei Wiederholungen, volle Leistung.

    **Der Wachposten fuer die Aenderung vom 13.11.2026.** Die Datei stand
    auf DR3 -- gebaut gegen 109, das auf DR5 festhing. Fuer 108 waere das
    wirkungslos: ChirpStack hatte es am 12.11. selbst auf DR3 gezogen und
    am 16.11. sogar auf DR5, und dort verlor es 16 Prozent seiner
    Meldungen.

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


def test_die_datei_ist_verdrahtet() -> None:
    """**Zweimal umgedreht: am 15.11. heraus, am 16.11. wieder hinein.**

    Am 15.11.2026 stand hier das Gegenteil -- der Eintrag **durfte
    nicht** in ``chirpstack.toml`` stehen, weil er den Dienst beim Start
    abbrechen liess. Die Bedingung dafuer war ausdruecklich formuliert:
    *„Wer den Eintrag zurueckbringt, bringt zusammen mit ihm einen Test,
    der die Datei so laedt wie ChirpStack."* Dieser Test ist
    ``test_die_datei_laedt_in_der_echten_engine`` weiter unten, und er
    ist die Begruendung, warum dieser hier jetzt die Umkehrung prueft.

    Ohne den Eintrag liegt die Datei im Container und niemand laedt sie
    -- der Verlust von 16 Prozent an 108 bliebe bestehen.
    """
    toml = (KONFIG / "chirpstack.toml").read_text(encoding="utf-8")
    # Kommentarzeilen zaehlen nicht: der Abschnitt darueber erklaert die
    # Geschichte und nennt den Namen dabei. Ein Test, der den Kommentar
    # mitliest, waere gruen, obwohl die Zeile fehlt (Paragraph 5.88).
    nutzzeilen = [z for z in toml.splitlines() if not z.strip().startswith("#")]
    eintraege = [z for z in nutzzeilen if "adr_plugins" in z]
    assert len(eintraege) == 1, f"genau ein adr_plugins-Eintrag erwartet, gefunden: {eintraege}"
    assert PLUGIN_RELAIS.name in eintraege[0], (
        f"der Eintrag zeigt nicht auf {PLUGIN_RELAIS.name}: {eintraege[0]}"
    )


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
    region = (KONFIG / "region_eu868.toml").read_text(encoding="utf-8")
    zeilen = [z.strip() for z in region.splitlines() if z.strip().startswith("installation_margin")]
    assert zeilen == ["installation_margin = 20.0"], (
        f"erwartet genau eine Zeile 'installation_margin = 20.0', gefunden: {zeilen}"
    )


def test_der_init_sidecar_kopiert_das_verzeichnis() -> None:
    """**Die Zeile, an der es sonst scheitert.**

    Der Pfad steht in ``chirpstack.toml`` und zeigt auf
    ``/etc/chirpstack/adr-plugins``. Der Sidecar rendert nur die beiden
    TOML-Dateien in das Volume; ohne ein ``cp`` des Verzeichnisses ist die
    Datei im Container **nicht da**, und ChirpStack meldet dazu nur
    ``Read ADR plugin: No such file or directory`` -- gemessen am
    16.11.2026, als der Pfad in der Probe noch falsch stand.

    Dieser Test prueft die Verdrahtung, nicht ihre Wirkung -- er fuehrt
    kein Compose aus. Er faellt genau dann, wenn jemand die Zeile
    entfernt oder das Verzeichnis umbenennt.
    """
    compose = COMPOSE_PROD.read_text(encoding="utf-8")
    assert "cp -r /template/adr-plugins /output/" in compose, (
        "ohne diese Zeile liegen die Plugins nicht im Container"
    )


# ---------------------------------------------------------------- Stufe 2

#: Wie lange auf ein Urteil gewartet wird. Der erste Lauf zieht drei
#: Images; danach dauert ein Lauf rund zwanzig Sekunden.
GEDULD_S = 240

#: Nach dem Laden des Plugins noch kurz zusehen, ob der Dienst steht.
#: Ein Plugin-Fehler beendet ChirpStack -- wer zu schnell hinsieht, haelt
#: einen gleich danach abbrechenden Dienst fuer einen laufenden.
NACHSCHAU_S = 4


def _docker_pflicht() -> str:
    """Docker oder ein Fehlschlag -- in CI ist ein Skip hier ein Fehler.

    Dieselbe Begruendung wie bei Node, und hier waere ein stiller Skip
    besonders teuer: dieser Test ist die Bedingung, unter der der
    ``adr_plugins``-Eintrag ueberhaupt wieder in der Konfiguration steht.
    Ein Test, der sich im Zweifel selbst ueberspringt, haette den Ausfall
    vom 15.11. auch nicht verhindert.
    """
    if DOCKER is None:  # pragma: no cover - haengt an der Umgebung
        if os.environ.get("CI"):
            pytest.fail("docker fehlt, obwohl die CI auf ubuntu-latest laeuft")
        pytest.skip("docker nicht gefunden - lokal ohne Docker, in CI ein Fehler")
    return DOCKER


def _docker(
    *args: str, pruefen: bool = True, zeit: int = GEDULD_S
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - fester Pfad, kein Shell
        [_docker_pflicht(), *args],
        capture_output=True,
        text=True,
        timeout=zeit,
        check=pruefen,
    )


def _chirpstack_image() -> str:
    """Das Image aus der **Produktions-Compose**, nicht eines von hier.

    Eine zweite Nennung waere eine zweite Wahrheit (Paragraph 5.53): der
    Test wuerde dann irgendwann eine andere Fassung pruefen als der
    Server faehrt, und das waere genau die Luecke, die am 15.11. offen
    war. Seit dem Festnageln auf Digests steht hier auch der Digest --
    der Test prueft damit nachweislich dasselbe Image.
    """
    text = COMPOSE_PROD.read_text(encoding="utf-8")
    # Der Dienstblock ``chirpstack:`` auf zwei Leerzeichen Einrueckung,
    # danach die erste ``image:``-Zeile. ``chirpstack-postgres`` und
    # ``chirpstack-gateway-bridge`` duerfen nicht mitgelesen werden,
    # deshalb das Doppelpunkt-Ende im Namen.
    treffer = re.search(r"^  chirpstack:\n(?:.*\n)*?    image:\s*(\S+)", text, re.MULTILINE)
    assert treffer, "kein image fuer den Dienst 'chirpstack' in docker-compose.prod.yml gefunden"
    return treffer.group(1)


@pytest.fixture(scope="module")
def funk_backend() -> Any:
    """Wegwerf-Postgres und -Redis, nur fuer diesen Modul-Lauf.

    **Warum ueberhaupt eine Datenbank.** Gemessen am 16.11.2026:
    ChirpStack 4.17 baut den Postgres-Pool auf und wandert das Schema
    (``Applying schema migrations``), **bevor** es ``Setting up ADR
    plugin`` erreicht. Ohne Datenbank kommt der Lauf nie bis zum Plugin,
    und ein Test ohne Datenbank koennte deshalb nichts ueber das Plugin
    sagen.

    **Kein Port wird veroeffentlicht.** Die drei Behaelter reden ueber
    ein eigenes Netz. Das haelt den Lauf von allem fern, was auf diesem
    Rechner sonst lauscht -- und niemand muss einen fremden Dienst
    beenden, um Platz zu machen.

    Die Namen tragen eine Zufallsendung, damit zwei Laeufe nebeneinander
    nicht uebereinander herfallen, und aufgeraeumt wird nur, was dieser
    Lauf selbst angelegt hat.
    """
    _docker_pflicht()
    marke = f"adrtest-{uuid.uuid4().hex[:8]}"
    netz, pg, redis = f"{marke}-net", f"{marke}-pg", f"{marke}-redis"
    try:
        _docker("network", "create", netz)
        _docker(
            "run", "-d", "--name", pg, "--network", netz,
            "-e", "POSTGRES_USER=chirpstack",
            "-e", "POSTGRES_PASSWORD=probe",
            "-e", "POSTGRES_DB=chirpstack",
            "postgres:16-alpine",
        )  # fmt: skip
        _docker("run", "-d", "--name", redis, "--network", netz, "redis:7-alpine")

        frist = time.monotonic() + 120
        while time.monotonic() < frist:
            if _docker("exec", pg, "pg_isready", "-U", "chirpstack", pruefen=False).returncode == 0:
                break
            time.sleep(1)
        else:  # pragma: no cover - haengt an der Umgebung
            pytest.fail("die Wegwerf-Datenbank wurde nicht bereit")

        # Dieselben Erweiterungen, die postgres-init/01-extensions.sql am
        # Server anlegt. Ohne sie bricht ChirpStacks Schema-Wanderung ab,
        # und der Fehler saehe aus wie ein Plugin-Fehler.
        _docker(
            "exec", pg, "psql", "-U", "chirpstack", "-d", "chirpstack", "-c",
            "CREATE EXTENSION IF NOT EXISTS pg_trgm; CREATE EXTENSION IF NOT EXISTS hstore;",
        )  # fmt: skip
        yield {"netz": netz, "pg": pg, "redis": redis}
    finally:
        for name in (pg, redis):
            _docker("rm", "-f", name, pruefen=False)
        _docker("network", "rm", netz, pruefen=False)


def _baue_konfiguration(ziel: pathlib.Path, backend: dict[str, str], plugin_text: str) -> None:
    """Unsere **echte** Konfiguration, nur mit umgebogenen Zielen.

    Genommen wird ``configuration/chirpstack.toml`` -- damit prueft der
    Lauf auch unseren ``adr_plugins``-Eintrag und nicht einen Nachbau.
    Umgebogen werden nur drei Dinge: Postgres, Redis und das
    Plugin-Verzeichnis.

    **Es kommt kein Geheimnis in diese Konfiguration.** Die Vorlage
    traegt Platzhalter (``${CHIRPSTACK_API_SECRET}``), und die werden
    hier durch Testwerte ersetzt. Aufgeloest wird die Vorlage sonst nur
    im Volume am Server, und diese Fassung sieht der Test nie.
    """
    ziel.mkdir(parents=True, exist_ok=True)
    (ziel / "adr-plugins").mkdir(exist_ok=True)
    (ziel / "adr-plugins" / PLUGIN_RELAIS.name).write_text(plugin_text, encoding="utf-8")
    (ziel / "region_eu868.toml").write_text(
        (KONFIG / "region_eu868.toml").read_text(encoding="utf-8"), encoding="utf-8"
    )

    toml = (KONFIG / "chirpstack.toml").read_text(encoding="utf-8")
    ersatz = {
        "POSTGRES_DSN": (
            f"postgres://chirpstack:probe@{backend['pg']}:5432/chirpstack?sslmode=disable"
        ),
        "CHIRPSTACK_API_SECRET": "nur-fuer-den-test",
        "MQTT_CHIRPSTACK_USER": "probe",
        "MQTT_CHIRPSTACK_PASSWORD": "probe",
    }
    toml = re.sub(r"\$\{(\w+)\}", lambda m: ersatz.get(m.group(1), "probe"), toml)
    toml, n_redis = re.subn(
        r'servers = \["redis://[^"]+"\]',
        f'servers = ["redis://{backend["redis"]}:6379/1"]',
        toml,
    )
    assert n_redis == 1, "die Redis-Zeile wurde nicht umgebogen"

    # Der Behaelter laeuft als Nicht-Root und darf ``/etc/chirpstack``
    # nicht anlegen (gemessen: ``mkdir: Permission denied``). Die
    # Konfiguration liegt deshalb unter ``/tmp/cfg``, und der
    # Plugin-Pfad muss mit. Die Zusicherung auf den Treffer ist wichtig:
    # ohne sie wuerde ein umbenanntes Verzeichnis dazu fuehren, dass der
    # Lauf gar kein Plugin laedt -- und gruen aussieht.
    toml, n_pfad = re.subn(r"/etc/chirpstack/adr-plugins/", "/tmp/cfg/adr-plugins/", toml)
    assert n_pfad == 1, (
        "der Plugin-Pfad '/etc/chirpstack/adr-plugins/' kam nicht genau einmal vor "
        f"(gefunden: {n_pfad}) -- ohne Umbiegen laedt der Lauf kein Plugin"
    )
    (ziel / "chirpstack.toml").write_text(toml, encoding="utf-8")


def _starte_chirpstack(backend: dict[str, str], konfig: pathlib.Path) -> tuple[str, str, int]:
    """Startet das echte Image und gibt (Protokoll, Status, Exit-Code).

    Die Konfiguration wird **hineinkopiert**, nicht eingebunden: ein
    Bind-Mount verhaelt sich auf Windows anders als auf Linux, und ein
    Test, der je Betriebssystem etwas anderes prueft, ist genau das
    Problem, gegen das dieser Test gebaut ist.
    """
    marke = f"adrrun-{uuid.uuid4().hex[:8]}"
    cid = _docker(
        "create", "--name", marke, "--network", backend["netz"],
        "--entrypoint", "sh", _chirpstack_image(),
        "-c", "exec /usr/bin/chirpstack -c /tmp/cfg",
    ).stdout.strip()  # fmt: skip
    try:
        _docker("cp", str(konfig), f"{cid}:/tmp/cfg")
        _docker("start", cid)

        frist = time.monotonic() + GEDULD_S
        protokoll = ""
        while time.monotonic() < frist:
            protokoll = (
                _docker("logs", cid, pruefen=False).stdout
                + _docker("logs", cid, pruefen=False).stderr
            )
            status = _docker("inspect", cid, "--format", "{{.State.Status}}").stdout.strip()
            if status != "running":
                break
            if "Setting up ADR plugin" in protokoll:
                # Geladen -- aber ein Fehler beendet den Dienst erst
                # gleich danach. Also kurz zusehen.
                time.sleep(NACHSCHAU_S)
                break
            time.sleep(1)

        protokoll = (
            _docker("logs", cid, pruefen=False).stdout + _docker("logs", cid, pruefen=False).stderr
        )
        status = _docker("inspect", cid, "--format", "{{.State.Status}}").stdout.strip()
        code = int(_docker("inspect", cid, "--format", "{{.State.ExitCode}}").stdout.strip())
        return protokoll, status, code
    finally:
        _docker("rm", "-f", cid, pruefen=False)


#: Die Meldung aus dem Ausfall vom 15.11.2026, 08:53 Uhr. Wortwoertlich,
#: damit die Probe nicht irgendeinen Fehler akzeptiert, sondern diesen.
AUSFALL_MELDUNG = (
    "Get id function: JS error: Error converting from js 'undefined' into type 'function'"
)


@pytest.mark.slow
def test_die_datei_laedt_in_der_echten_engine(
    funk_backend: dict[str, str], tmp_path: pathlib.Path
) -> None:
    """**Die Bedingung, unter der ``adr_plugins`` wieder in der Konfiguration steht.**

    Kein Nachbau, keine zweite Engine: ``chirpstack/chirpstack:4`` aus
    der Produktions-Compose, unsere ``chirpstack.toml``, unsere
    Plugin-Datei. Zwei Zusicherungen, und die zweite ist die, die am
    15.11. gefehlt hat:

    * Das Protokoll nennt ``Setting up ADR plugin`` -- die Datei wurde
      ueberhaupt gefunden und angefasst.
    * Der Dienst **laeuft danach weiter**. Ein Plugin-Fehler beendet
      ChirpStack mit Exit-Code 1; das ist der Unterschied zwischen „laedt"
      und „laedt nicht", und er ist nicht an einer Textzeile zu erkennen,
      sondern am Zustand des Dienstes.

    MQTT-Fehler im Protokoll sind **erwartet** und kein Mangel: der Test
    gibt keinen Broker, und ChirpStack laeuft ohne ihn weiter. Deshalb
    wird hier nicht auf „kein ERROR" geprueft, sondern auf die beiden
    Dinge, die das Plugin betreffen.
    """
    konfig = tmp_path / "cfg"
    _baue_konfiguration(konfig, funk_backend, PLUGIN_RELAIS.read_text(encoding="utf-8"))
    protokoll, status, code = _starte_chirpstack(funk_backend, konfig)

    assert "Setting up ADR plugin" in protokoll, (
        "ChirpStack hat das Plugin nicht angefasst -- Pfad oder Eintrag falsch.\n"
        f"Protokoll:\n{protokoll[-2000:]}"
    )
    assert AUSFALL_MELDUNG not in protokoll, (
        "die Meldung vom 15.11.2026 ist zurueck: die Datei exportiert id() nicht.\n"
        f"Protokoll:\n{protokoll[-2000:]}"
    )
    assert "Read ADR plugin" not in protokoll, (
        f"ChirpStack hat die Datei nicht lesen koennen.\nProtokoll:\n{protokoll[-2000:]}"
    )
    assert status == "running", (
        f"ChirpStack ist beendet (Status {status}, Exit {code}) -- ein geladenes "
        f"Plugin laesst den Dienst laufen.\nProtokoll:\n{protokoll[-2000:]}"
    )


@pytest.mark.slow
def test_die_fassung_ohne_export_bricht_in_der_echten_engine_ab(
    funk_backend: dict[str, str], tmp_path: pathlib.Path
) -> None:
    """**Die Probe, die den Test ueber sich selbst aussagen laesst.**

    Ein Test, der nur zeigt, dass die gute Fassung laedt, kann nicht
    zeigen, dass er ueberhaupt etwas prueft -- genau das war am 15.11.
    der Fall, nur umgekehrt. Deshalb laeuft hier die **Fassung vom
    15.11.2026** durch dasselbe Image: dieselbe Datei, nur ohne
    ``export``.

    Erwartet wird nicht „irgendein Fehler", sondern **die Meldung aus dem
    Ausfall**, wortwoertlich, und ein beendeter Dienst mit Exit-Code 1.

    Die Rueckbau-Zusicherung davor ist nicht Zierde: wenn die Datei
    eines Tages keine ``export``-Anweisungen mehr hat, wuerde das
    Entfernen nichts aendern, der Lauf waere trotzdem rot, und diese
    Probe wuerde eine Wirkung behaupten, die sie nicht hat.
    """
    mit_export = PLUGIN_RELAIS.read_text(encoding="utf-8")
    ohne_export, ersetzt = re.subn(
        r"^export function ", "function ", mit_export, flags=re.MULTILINE
    )
    assert ersetzt == 3, (
        f"erwartet drei 'export function'-Zeilen zum Entfernen, gefunden: {ersetzt} -- "
        "ohne sie prueft diese Probe nichts"
    )

    konfig = tmp_path / "cfg-ohne-export"
    _baue_konfiguration(konfig, funk_backend, ohne_export)
    protokoll, status, code = _starte_chirpstack(funk_backend, konfig)

    assert "Setting up ADR plugin" in protokoll, (
        f"das Plugin wurde nicht angefasst.\nProtokoll:\n{protokoll[-2000:]}"
    )
    assert AUSFALL_MELDUNG in protokoll, (
        f"erwartet war die Meldung aus dem Ausfall vom 15.11.2026.\nProtokoll:\n{protokoll[-2000:]}"
    )
    assert status == "exited" and code == 1, (
        f"erwartet war ein beendeter Dienst mit Exit 1, gefunden {status}/{code}"
    )
