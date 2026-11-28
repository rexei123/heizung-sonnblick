"""Die echte ChirpStack-Engine als Pruefstand -- Wegwerf-Aufbau je Modul.

**Warum ein Behaelter und nicht ein Nachbau.** Am 15.11.2026 waren 54
Tests gruen und ChirpStack startete nicht: die Plugin-Datei hatte eine
Form, die der Test verlangte und das Programm nicht (CLAUDE.md 5.55).
Seither gilt fuer alles, was ChirpStack aus unserer Konfiguration liest:
geprueft wird im **echten Abbild**, derselben Fassung wie am Server.

Was hier steht, ist nur der Aufbau. Die Zusicherungen stehen in den
Test-Dateien.

**Kein Port wird veroeffentlicht**, die drei Behaelter reden ueber ein
eigenes Netz. Das haelt den Lauf von allem fern, was auf diesem Rechner
sonst lauscht -- niemand muss einen fremden Dienst beenden, um Platz zu
machen (Goldene Regel 12). Die Namen tragen eine Zufallsendung, damit
zwei Laeufe nebeneinander nicht uebereinander herfallen, und aufgeraeumt
wird nur, was dieser Lauf selbst angelegt hat.

**Es kommt kein Geheimnis in die Test-Konfiguration.** Die Vorlage traegt
Platzhalter, und die werden hier durch Testwerte ersetzt. Aufgeloest wird
die Vorlage sonst nur im Volume am Server, und diese Fassung sieht der
Test nie.

**Doppelt vorhanden, und das ist bekannt.** ``test_adr_plugins.py``
bringt in PR #425 denselben Aufbau noch einmal in der Datei selbst mit.
Wird #425 gemergt, gehoert die dortige Fassung geloescht und durch diese
hier ersetzt -- eine Naht, nicht zwei Wahrheiten (Paragraph 5.53). Der
Grund fuer die Doppelung ist eine Entscheidung, nicht Nachlaessigkeit:
#425 haengt an einer offenen Frage zum Relais (RUNBOOK Paragraph 10av,
Nachtrag vom 17.11.2026), und die Datenraten-Grenze soll davon nicht
abhaengen.
"""

from __future__ import annotations

import os
import pathlib
import re
import shutil
import subprocess
import time
import uuid
from collections.abc import Iterator

import pytest

#: Die Konfiguration, die der Init-Sidecar am Server in das Volume
#: rendert (``docker-compose.prod.yml``). Genau diese Dateien liest der
#: Pruefstand -- kein Nachbau.
KONFIG = pathlib.Path(__file__).resolve().parents[1] / "configuration"
COMPOSE_PROD = KONFIG.parents[1] / "deploy" / "docker-compose.prod.yml"
PLUGIN_VERZEICHNIS = KONFIG / "adr-plugins"

DOCKER = shutil.which("docker")

#: Wie lange auf ein Urteil gewartet wird. Der erste Lauf zieht drei
#: Abbilder; danach dauert ein Start rund sechs Sekunden.
GEDULD_S = 240

#: Nach dem Hochlaufen noch kurz zusehen, ob der Dienst steht. Ein
#: Konfigurationsfehler beendet ChirpStack -- wer zu schnell hinsieht,
#: haelt einen gleich danach abbrechenden Dienst fuer einen laufenden.
NACHSCHAU_S = 4

#: Die Zeile, an der ChirpStack die Regionsdateien gelesen hat.
REGIONEN_GELADEN = "Setting up regions"


def docker_pflicht() -> str:
    """Docker oder ein Fehlschlag -- in CI ist ein Skip hier ein Fehler.

    Ein Test, der sich im Zweifel selbst ueberspringt, ist kein Test
    (Paragraph 5.81), und gerade dieser haelt eine Einstellung fest, die
    den Funk aller Geraete betrifft.
    """
    if DOCKER is None:  # pragma: no cover - haengt an der Umgebung
        if os.environ.get("CI"):
            pytest.fail("docker fehlt, obwohl die CI auf ubuntu-latest laeuft")
        pytest.skip("docker nicht gefunden - lokal ohne Docker, in CI ein Fehler")
    return DOCKER


def docker(
    *args: str, pruefen: bool = True, zeit: int = GEDULD_S
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - fester Pfad, kein Shell
        [docker_pflicht(), *args],
        capture_output=True,
        text=True,
        timeout=zeit,
        check=pruefen,
    )


def chirpstack_abbild() -> str:
    """Das Abbild aus der **Produktions-Compose**, nicht eines von hier.

    Eine zweite Nennung waere eine zweite Wahrheit (Paragraph 5.53): der
    Test wuerde dann irgendwann eine andere Fassung pruefen als der
    Server faehrt -- genau die Luecke, die am 15.11.2026 offen war. Seit
    dem Festnageln auf Digests steht hier auch der Digest.
    """
    text = COMPOSE_PROD.read_text(encoding="utf-8")
    treffer = re.search(r"^  chirpstack:\n(?:.*\n)*?    image:\s*(\S+)", text, re.MULTILINE)
    assert treffer, "kein image fuer den Dienst 'chirpstack' in docker-compose.prod.yml gefunden"
    return treffer.group(1)


@pytest.fixture(scope="module")
def funk_backend() -> Iterator[dict[str, str]]:
    """Wegwerf-Postgres und -Redis, nur fuer diesen Modul-Lauf.

    **Warum ueberhaupt eine Datenbank.** Gemessen am 16.11.2026:
    ChirpStack 4.17 baut den Postgres-Pool auf und wandert das Schema
    (``Applying schema migrations``), **bevor** es die Regionen und die
    ADR-Algorithmen einrichtet. Ohne Datenbank kommt der Lauf nie bis
    dorthin, und ein Test ohne Datenbank koennte deshalb nichts ueber
    unsere Konfiguration sagen.
    """
    docker_pflicht()
    marke = f"funktest-{uuid.uuid4().hex[:8]}"
    netz, pg, redis = f"{marke}-net", f"{marke}-pg", f"{marke}-redis"
    try:
        docker("network", "create", netz)
        docker(
            "run", "-d", "--name", pg, "--network", netz,
            "-e", "POSTGRES_USER=chirpstack",
            "-e", "POSTGRES_PASSWORD=probe",
            "-e", "POSTGRES_DB=chirpstack",
            "postgres:16-alpine",
        )  # fmt: skip
        docker("run", "-d", "--name", redis, "--network", netz, "redis:7-alpine")

        # **Gewartet wird auf die Wirkung, nicht auf den Melder**
        # (Paragraph 5.76). ``pg_isready`` meldet hier schon nach einer
        # Sekunde Erfolg -- da laeuft aber noch der **Hilfs-Server**, den
        # das Abbild zum Anlegen der Datenbank startet und danach wieder
        # beendet. Wer in dieser Luecke das erste ``psql`` schickt,
        # bekommt Exit 2, und der Fehlschlag sieht aus wie ein kaputtes
        # Abbild. Gemessen am 27.11.2026: von Hand lief derselbe Befehl
        # sauber durch, im Test nicht.
        #
        # Deshalb ist der Befehl, auf den es ankommt, selbst die Probe --
        # er wird wiederholt, bis er durchgeht. Dieselben Erweiterungen
        # legt am Server ``postgres-init/01-extensions.sql`` an; ohne sie
        # bricht ChirpStacks Schema-Wanderung ab, und dieser Fehler saehe
        # aus wie ein Konfigurationsfehler.
        frist = time.monotonic() + 120
        letzte = ""
        while time.monotonic() < frist:
            lauf = docker(
                "exec", pg, "psql", "-U", "chirpstack", "-d", "chirpstack", "-c",
                "CREATE EXTENSION IF NOT EXISTS pg_trgm; CREATE EXTENSION IF NOT EXISTS hstore;",
                pruefen=False,
            )  # fmt: skip
            if lauf.returncode == 0:
                break
            letzte = (lauf.stdout + lauf.stderr).strip()
            time.sleep(1)
        else:  # pragma: no cover - haengt an der Umgebung
            pytest.fail(f"die Wegwerf-Datenbank wurde nicht bereit. Letzte Meldung: {letzte}")

        yield {"netz": netz, "pg": pg, "redis": redis}
    finally:
        for name in (pg, redis):
            docker("rm", "-f", name, pruefen=False)
        docker("network", "rm", netz, pruefen=False)


def baue_konfiguration(
    ziel: pathlib.Path,
    backend: dict[str, str],
    *,
    region_text: str | None = None,
) -> None:
    """Unsere **echte** Konfiguration, nur mit umgebogenen Zielen.

    Umgebogen werden Postgres, Redis und -- falls ein ADR-Plugin
    verdrahtet ist -- der Plugin-Pfad. Alles andere bleibt, wie der
    Server es liest.
    """
    ziel.mkdir(parents=True, exist_ok=True)
    (ziel / "region_eu868.toml").write_text(
        region_text
        if region_text is not None
        else (KONFIG / "region_eu868.toml").read_text(encoding="utf-8"),
        encoding="utf-8",
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
    # Konfiguration liegt deshalb unter ``/tmp/cfg``. Ist ein Plugin
    # verdrahtet, muss der Pfad mit -- sonst meldet ChirpStack
    # ``Read ADR plugin: No such file or directory`` und bricht ab.
    if re.search(r"^\s*adr_plugins", toml, re.MULTILINE):
        toml, n_pfad = re.subn(r"/etc/chirpstack/adr-plugins/", "/tmp/cfg/adr-plugins/", toml)
        assert n_pfad >= 1, "ein Plugin ist verdrahtet, aber der Pfad liess sich nicht umbiegen"
        (ziel / "adr-plugins").mkdir(exist_ok=True)
        for datei in PLUGIN_VERZEICHNIS.glob("*.js"):
            (ziel / "adr-plugins" / datei.name).write_text(
                datei.read_text(encoding="utf-8"), encoding="utf-8"
            )

    (ziel / "chirpstack.toml").write_text(toml, encoding="utf-8")


def starte_chirpstack(backend: dict[str, str], konfig: pathlib.Path) -> tuple[str, str, int]:
    """Startet das echte Abbild und gibt (Protokoll, Status, Exit-Code).

    Die Konfiguration wird **hineinkopiert**, nicht eingebunden: ein
    Bind-Mount verhaelt sich auf Windows anders als auf Linux, und ein
    Test, der je Betriebssystem etwas anderes prueft, ist genau das
    Problem, gegen das dieser Pruefstand gebaut ist.
    """
    marke = f"funkrun-{uuid.uuid4().hex[:8]}"
    cid = docker(
        "create", "--name", marke, "--network", backend["netz"],
        "--entrypoint", "sh", chirpstack_abbild(),
        "-c", "exec /usr/bin/chirpstack -c /tmp/cfg",
    ).stdout.strip()  # fmt: skip
    try:
        docker("cp", str(konfig), f"{cid}:/tmp/cfg")
        docker("start", cid)

        frist = time.monotonic() + GEDULD_S
        while time.monotonic() < frist:
            if _status(cid) != "running":
                break
            if REGIONEN_GELADEN in _protokoll(cid):
                # Geladen -- aber ein Fehler beendet den Dienst erst
                # gleich danach. Also kurz zusehen.
                time.sleep(NACHSCHAU_S)
                break
            time.sleep(1)

        return _protokoll(cid), _status(cid), _exit_code(cid)
    finally:
        docker("rm", "-f", cid, pruefen=False)


def _protokoll(cid: str) -> str:
    lauf = docker("logs", cid, pruefen=False)
    return lauf.stdout + lauf.stderr


def _status(cid: str) -> str:
    return docker("inspect", cid, "--format", "{{.State.Status}}").stdout.strip()


def _exit_code(cid: str) -> int:
    return int(docker("inspect", cid, "--format", "{{.State.ExitCode}}").stdout.strip())
