"""Die Grenzen fuer die beiden Protokolle, die unbegrenzt wuchsen.

Gemessen am 16.11.2026, 05:45 UTC am Produktionsserver:

* ``/var/log/heizung-deploy.log`` — 94,7 MB seit dem 20.04.2026 (210 Tage),
  also **0,45 MB/Tag**, und ``grep -rl heizung-deploy /etc/logrotate.d/``
  fand keine Regel.
* ``deploy-chirpstack-1`` — 71,7 MB in 21,8 Stunden, also **79,3 MB/Tag**
  (Mittel ueber 21 volle Stunden: 69 373 349 B). ``LogConfig.Config`` war
  ``map[]`` — keine Grenze, weder in der Compose-Datei noch in einer
  ``daemon.json``.

**Warum die Zahlen hier als Test stehen und nicht nur im README.** RUNBOOK
§10av Schritt 6a liest ``tx_power_index`` je Geraet aus dem jeweils letzten
``LinkADRReq acknowledged`` in ``docker logs deploy-chirpstack-1``. Der Wert
steht in keiner Datenbank von uns, und ADR protokolliert nur, wenn es etwas
aendert — ist die Leistung eingeschwungen, kommt tagelang keine neue Zeile.
Eine zu knappe Grenze macht Schritt 6a also **lautlos** unbrauchbar: der
Befehl laeuft weiter durch und meldet nur weniger Geraete. Im Ist-Stand sind
es nach 21,8 Stunden 55 von rund 90 Geraeten.

Ein Kommentar haette das nicht gehalten. ``test_fenster_haelt_vierzehn_tage``
rechnet die Zusicherung nach, und zwar aus der **gemessenen** Rate: wer
``max-file`` oder ``max-size`` kleiner setzt, bekommt einen roten Test mit
der Anzahl Tage, die dann noch uebrig waere.

Die Herleitung der Zahlen steht in ``infra/deploy/docker/README.md``.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

REPO_WURZEL = Path(__file__).resolve().parents[2]
DEPLOY_DIR = REPO_WURZEL / "infra" / "deploy"
DAEMON_JSON = DEPLOY_DIR / "docker" / "daemon.json"
LOGROTATE_REGEL = DEPLOY_DIR / "logrotate" / "heizung-deploy"
INSTALL_SKRIPT = DEPLOY_DIR / "install-log-limits.sh"
DEPLOY_PULL = DEPLOY_DIR / "deploy-pull.sh"
COMPOSE = DEPLOY_DIR / "docker-compose.prod.yml"

# Gemessen, nicht geschaetzt (siehe Modul-Docstring).
RATE_MB_PRO_TAG = 79.3
RATE_SPITZE_MB_PRO_TAG = 98.8
FENSTER_TAGE_SOLL = 14

# Dienste, deren Compose-Definition dieser PR nicht anfasst — Vorgabe des
# Betreibers vom 16.11.2026. Jede Aenderung an der Definition erstellt den
# Container beim naechsten Deploy neu, und bei diesen drei ist genau das das
# Risiko: §10ay (Mosquitto-Neustart am 04.11. hat das Gateway haengen
# lassen), §10bb (chirpstack lief am 15.11. in Schleife).
DIENSTE_OHNE_COMPOSE_AENDERUNG = ("mosquitto", "chirpstack-gateway-bridge", "chirpstack")

POSIX_ODER_NICHTS = pytest.mark.skipif(
    os.name != "posix" or shutil.which("bash") is None,
    # Dieselbe Begruendung wie in test_deploy_pull_pinning.py: Git Bash unter
    # Windows gibt `env=` nicht durch und loest C:/-Eintraege im PATH nicht
    # auf. Die Skript-Logik ist stattdessen in einem Linux-Container geprueft
    # (siehe PR-Text), CI laeuft auf ubuntu-latest.
    reason="Shell-Skript-Tests nur auf POSIX",
)


def _bytes_aus_docker_groesse(wert: str) -> int:
    """``100m`` -> 104857600. Docker rechnet in Zweierpotenzen."""
    treffer = re.fullmatch(r"(\d+)([kmg]?)", wert.strip().lower())
    if treffer is None:
        raise AssertionError(f"unverstaendliche Groessenangabe: {wert!r}")
    zahl = int(treffer.group(1))
    faktor = {"": 1, "k": 1024, "m": 1024**2, "g": 1024**3}[treffer.group(2)]
    return zahl * faktor


def _log_opts() -> dict[str, str]:
    inhalt = json.loads(DAEMON_JSON.read_text(encoding="utf-8"))
    opts = inhalt["log-opts"]
    assert isinstance(opts, dict)
    return {str(k): str(v) for k, v in opts.items()}


def _garantiertes_fenster_bytes() -> int:
    """Was der json-file-Treiber mindestens aufhebt.

    Gehalten werden die laufende Datei (0 bis ``max-size``) **plus**
    ``max-file - 1`` gefuellte Dateien. Zugesichert ist damit die untere
    Grenze: direkt nach einer Rotation ist die laufende Datei leer.
    """
    opts = _log_opts()
    return (int(opts["max-file"]) - 1) * _bytes_aus_docker_groesse(opts["max-size"])


def _fenster_tage(rate_mb_pro_tag: float) -> float:
    return _garantiertes_fenster_bytes() / (rate_mb_pro_tag * 1_000_000)


def test_daemon_json_ist_gueltiges_json() -> None:
    """Eine fehlerhafte daemon.json hindert dockerd am Starten.

    Gemerkt wuerde das erst beim naechsten Neustart des Dienstes — also
    moeglichst spaet. Deshalb prueft dieser Test die Datei im Repo, und
    §10be prueft am Server zusaetzlich mit ``dockerd --validate``.
    """
    inhalt = json.loads(DAEMON_JSON.read_text(encoding="utf-8"))
    assert inhalt["log-driver"] == "json-file"


def test_fenster_haelt_vierzehn_tage() -> None:
    """Die Zusicherung fuer §10av Schritt 6a, aus der gemessenen Rate."""
    tage = _fenster_tage(RATE_MB_PRO_TAG)
    assert tage >= FENSTER_TAGE_SOLL, (
        f"garantiertes Fenster nur {tage:.1f} Tage bei gemessenen "
        f"{RATE_MB_PRO_TAG} MB/Tag — §10av Schritt 6a braucht {FENSTER_TAGE_SOLL}. "
        "tx_power_index steht in keiner Datenbank, und ADR protokolliert nur "
        "bei Aenderung; ein zu kleines Fenster meldet lautlos weniger Geraete."
    )


def test_fenster_haelt_vierzehn_tage_auch_bei_spitzenrate() -> None:
    """Die hoechste gemessene Einzelstunde (4,12 MB), dauerhaft gehalten.

    Das ist der Puffer gegen mehr Geraete oder mehr Funkverkehr, nicht gegen
    einen Fehlerfall — ein Dienst in Schleife schreibt ein Vielfaches davon.
    """
    tage = _fenster_tage(RATE_SPITZE_MB_PRO_TAG)
    assert tage >= FENSTER_TAGE_SOLL, (
        f"bei Spitzenrate nur {tage:.1f} Tage statt {FENSTER_TAGE_SOLL}"
    )


def test_compress_ist_an() -> None:
    """Ohne compress kostet dasselbe Fenster das Zwanzigfache an Platz.

    Gemessen am echten Protokoll: Faktor 21,6 (20 000 000 B zu 926 450 B).
    Erwartet mit compress rund 169 MiB, ohne compress bis 1,6 GB — bei
    25 GB frei ist das der Unterschied zwischen Deckel und Dauerposten.
    """
    assert _log_opts().get("compress") == "true"


def test_treiber_bleibt_json_file() -> None:
    """§10av Schritt 6a liest ueber ``docker logs``.

    Ein anderer Treiber (journald, local) wuerde die Pipeline aus dem
    RUNBOOK aendern oder leer laufen lassen. Die Vorgabe hier ist auch die
    Zusicherung, dass die Quelle bleibt, was sie ist.
    """
    assert json.loads(DAEMON_JSON.read_text(encoding="utf-8"))["log-driver"] == "json-file"


@pytest.mark.parametrize("dienst", DIENSTE_OHNE_COMPOSE_AENDERUNG)
def test_keine_logging_vorgabe_in_der_compose_datei(dienst: str) -> None:
    """Diese drei duerfen keinen ``logging:``-Block bekommen.

    Nicht weil die Grenze fuer sie falsch waere, sondern weil der Weg
    dorthin sie neu erstellt. Sie bekommen dieselbe Vorgabe aus der
    ``daemon.json``, wenn sie ohnehin neu erstellt werden (§10be).
    """
    inhalt = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))
    assert "logging" not in inhalt["services"][dienst], (
        f"{dienst} hat eine logging-Vorgabe in der Compose-Datei. Damit wird der "
        "Container beim naechsten Deploy neu erstellt — Vorgabe des Betreibers "
        "vom 16.11.2026 war, genau das zu vermeiden (§10ay, §10bb)."
    )


def test_logrotate_regel_zeigt_auf_die_datei_die_deploy_pull_schreibt() -> None:
    """Ein Pfad an zwei Stellen laeuft auseinander, sobald einer sich aendert.

    ``deploy-pull.sh`` Zeile 52 setzt die Vorgabe; die Regel hier muss
    dieselbe Datei nennen. Sonst rotiert logrotate eine Datei, die niemand
    schreibt — ein Melder, der nie anschlaegt.
    """
    treffer = re.search(
        r"^LOG=\$\{DEPLOY_LOG:-([^}]+)\}", DEPLOY_PULL.read_text(encoding="utf-8"), re.MULTILINE
    )
    assert treffer is not None, "LOG-Vorgabe in deploy-pull.sh nicht gefunden"
    pfad = treffer.group(1)
    regel = LOGROTATE_REGEL.read_text(encoding="utf-8")
    assert f"{pfad} {{" in regel, f"logrotate-Regel nennt {pfad} nicht"


@pytest.mark.parametrize(
    ("schluessel", "warum"),
    [
        ("weekly", "0,45 MB/Tag — taeglich waere eine Generation von 0,45 MB"),
        ("rotate 8", "acht Wochen Vorgeschichte"),
        ("maxsize 50M", "Bremse, wenn ein Lauf in Schleife schreibt"),
        ("compress", "Faktor 37 gemessen"),
        ("delaycompress", "ein Lauf in der Rotation schreibt in die umbenannte Datei"),
        ("notifempty", "kein Rotieren ohne neue Zeilen"),
        ("missingok", "kein Fehler, wenn die Datei noch nicht existiert"),
        ("create 0644 root root", "Rechte wie gemessen"),
    ],
)
def test_logrotate_regel_enthaelt(schluessel: str, warum: str) -> None:
    regel = LOGROTATE_REGEL.read_text(encoding="utf-8")
    zeilen = [z.strip() for z in regel.splitlines() if not z.strip().startswith("#")]
    assert schluessel in zeilen, f"{schluessel} fehlt ({warum})"


# ---------------------------------------------------------------------------
# Das Install-Skript, am echten Skript geprueft (§5.82).
# ---------------------------------------------------------------------------


def _attrappen(verzeichnis: Path) -> Path:
    """Attrappen fuer docker, dockerd und systemctl, die sich melden.

    Ruft das Skript eine davon auf, legt sie eine Marke an und scheitert.
    Damit ist "das Skript aendert nichts am laufenden Betrieb" gepruefte
    Eigenschaft und nicht Absicht im Kommentar.
    """
    bin_dir = verzeichnis / "bin"
    bin_dir.mkdir()
    marke = verzeichnis / "marke"
    for name in ("docker", "dockerd", "systemctl"):
        attrappe = bin_dir / name
        attrappe.write_text(f'#!/bin/sh\necho "{name} $*" >> "{marke}"\nexit 1\n')
        attrappe.chmod(0o755)
    return bin_dir


def _lauf(tmp_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    bin_dir = tmp_path / "bin"
    if not bin_dir.exists():
        bin_dir = _attrappen(tmp_path)
    umgebung = dict(os.environ)
    umgebung["PATH"] = f"{bin_dir}{os.pathsep}{umgebung['PATH']}"
    umgebung["ZIEL_LOGROTATE"] = str(tmp_path / "etc" / "logrotate.d" / "heizung-deploy")
    umgebung["ZIEL_DAEMON"] = str(tmp_path / "etc" / "docker" / "daemon.json")
    umgebung.setdefault("QUELL_DIR", str(DEPLOY_DIR))
    return subprocess.run(
        ["bash", str(INSTALL_SKRIPT), *args],
        capture_output=True,
        text=True,
        env=umgebung,
        check=False,
    )


@POSIX_ODER_NICHTS
def test_install_legt_beide_dateien_an(tmp_path: Path) -> None:
    ergebnis = _lauf(tmp_path)
    assert ergebnis.returncode == 0, ergebnis.stdout + ergebnis.stderr
    daemon = tmp_path / "etc" / "docker" / "daemon.json"
    regel = tmp_path / "etc" / "logrotate.d" / "heizung-deploy"
    assert json.loads(daemon.read_text(encoding="utf-8")) == json.loads(
        DAEMON_JSON.read_text(encoding="utf-8")
    )
    assert regel.read_text(encoding="utf-8") == LOGROTATE_REGEL.read_text(encoding="utf-8")


@POSIX_ODER_NICHTS
def test_install_startet_nichts_neu(tmp_path: Path) -> None:
    """Keine Server-Aenderung mit Nebenwirkung auf den Betrieb.

    Das ist die Auflage des Betreibers: bauen und melden, das Ausrollen
    entscheidet er. Ein Skript, das `systemctl restart docker` aufruft,
    waere die Auflage gebrochen — und zwar unbemerkt.
    """
    ergebnis = _lauf(tmp_path)
    assert ergebnis.returncode == 0, ergebnis.stdout + ergebnis.stderr
    marke = tmp_path / "marke"
    assert not marke.exists(), f"Skript hat aufgerufen: {marke.read_text(encoding='utf-8')}"


@POSIX_ODER_NICHTS
def test_install_ist_idempotent(tmp_path: Path) -> None:
    assert _lauf(tmp_path).returncode == 0
    zweiter = _lauf(tmp_path)
    assert zweiter.returncode == 0, zweiter.stdout + zweiter.stderr
    assert "unveraendert" in zweiter.stdout


@POSIX_ODER_NICHTS
def test_install_ueberschreibt_keine_fremde_daemon_json(tmp_path: Path) -> None:
    """Am Server gab es keine. Liegt dort eine, steht Fremdes darin.

    Registry-Spiegel, Adressbereiche, live-restore — eine daemon.json ist
    nicht unsere Datei, sondern die des Hosts. Ueberschreiben waere ein
    stiller Eingriff in eine Konfiguration, die niemand hier gelesen hat.
    """
    ziel = tmp_path / "etc" / "docker" / "daemon.json"
    ziel.parent.mkdir(parents=True)
    ziel.write_text('{"bip": "10.99.0.1/16"}\n', encoding="utf-8")
    ergebnis = _lauf(tmp_path)
    assert ergebnis.returncode != 0
    assert "Nicht ueberschrieben" in ergebnis.stdout
    assert json.loads(ziel.read_text(encoding="utf-8")) == {"bip": "10.99.0.1/16"}


@POSIX_ODER_NICHTS
def test_install_kopiert_kein_kaputtes_json(tmp_path: Path) -> None:
    """Geprueft wird vor dem Kopieren, nicht danach."""
    quelle = tmp_path / "quelle"
    shutil.copytree(DEPLOY_DIR / "docker", quelle / "docker")
    shutil.copytree(DEPLOY_DIR / "logrotate", quelle / "logrotate")
    (quelle / "docker" / "daemon.json").write_text('{"log-driver": ', encoding="utf-8")

    bin_dir = _attrappen(tmp_path)
    umgebung = dict(os.environ)
    umgebung["PATH"] = f"{bin_dir}{os.pathsep}{umgebung['PATH']}"
    umgebung["QUELL_DIR"] = str(quelle)
    umgebung["ZIEL_LOGROTATE"] = str(tmp_path / "etc" / "logrotate.d" / "heizung-deploy")
    umgebung["ZIEL_DAEMON"] = str(tmp_path / "etc" / "docker" / "daemon.json")
    ergebnis = subprocess.run(
        ["bash", str(INSTALL_SKRIPT)],
        capture_output=True,
        text=True,
        env=umgebung,
        check=False,
    )

    assert ergebnis.returncode != 0
    assert "kein gueltiges JSON" in ergebnis.stderr
    assert not (tmp_path / "etc" / "docker" / "daemon.json").exists()
