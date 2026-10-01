"""Der celery_beat-Healthcheck, geprueft statt nur geschrieben.

Der Test liest den Befehl **aus der Compose-Datei** und fuehrt ihn gegen ein
Wegwerf-Verzeichnis aus. Ein nachgebauter Ausdruck im Test wuerde nur sich
selbst pruefen — und genau die Zeile, die im Betrieb laeuft, nicht.

Warum es diesen Test ueberhaupt gibt: bis zum 30.09.2026 erbte
``celery_beat`` den HEALTHCHECK aus dem Dockerfile
(``curl -f http://localhost:8000/health``, backend/Dockerfile:44-45). Beat
fuehrt keinen uvicorn, der Check konnte nur scheitern, und der Container
stand monatelang auf ``unhealthy`` bei laufendem Beat (CLAUDE.md §5.32).
Das war kosmetisch — aber es hat den Status als Diagnose-Signal entwertet,
und RUNBOOK §10l musste dem Hotelier ausdruecklich sagen, dieses eine
``unhealthy`` zu ignorieren. Ein Melder, den man ignorieren muss, ueberwacht
nichts.

Ein falscher Ersatz waere derselbe Fehler mit neuer Ursache: ein Check auf
einen Dateinamen, den es nicht gibt, meldet ebenfalls dauerhaft
``unhealthy``. Deshalb dieser Test.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest
import yaml

COMPOSE = Path(__file__).resolve().parents[2] / "infra" / "deploy" / "docker-compose.prod.yml"


def _healthcheck_test(service: str) -> list[str]:
    inhalt = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))
    return list(inhalt["services"][service]["healthcheck"]["test"])


def _python_ausdruck(verzeichnis: Path) -> str:
    """Holt den Python-Ausdruck aus dem Compose-Befehl und zielt ihn um.

    Im Betrieb prueft er ``/tmp``; hier soll er das Wegwerf-Verzeichnis
    pruefen. Ersetzt wird nur der Pfad — die Logik bleibt die aus der Datei.
    """
    befehl = _healthcheck_test("celery_beat")
    assert befehl[:3] == ["CMD", "python", "-c"], befehl
    ausdruck = befehl[3]
    assert "/tmp/celerybeat-schedule*" in ausdruck, ausdruck
    return ausdruck.replace(
        "/tmp/celerybeat-schedule*", f"{verzeichnis.as_posix()}/celerybeat-schedule*"
    )


def _lauf(verzeichnis: Path) -> int:
    ergebnis = subprocess.run(
        [sys.executable, "-c", _python_ausdruck(verzeichnis)],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert not ergebnis.stderr, ergebnis.stderr
    return ergebnis.returncode


def _altern(pfad: Path, sekunden: int) -> None:
    alt = time.time() - sekunden
    os.utime(pfad, (alt, alt))


# ---------------------------------------------------------------------------
# celery_beat: der neue Check
# ---------------------------------------------------------------------------


def test_beat_hat_einen_eigenen_healthcheck() -> None:
    """Ohne eigenen Block erbt der Container den curl-Check aus dem Dockerfile.

    Das ist die Regression, die dieser Test verhindert: wer den Block
    entfernt, bekommt wieder einen Container, der dauerhaft ``unhealthy``
    meldet, obwohl Beat arbeitet.
    """
    befehl = _healthcheck_test("celery_beat")
    assert befehl, "celery_beat braucht einen eigenen healthcheck-Block"
    assert "curl" not in " ".join(befehl), (
        "curl im Beat-Healthcheck: Beat fuehrt keinen uvicorn (§5.32)"
    )


def test_frische_schedule_datei_ist_healthy(tmp_path: Path) -> None:
    (tmp_path / "celerybeat-schedule.db").touch()
    assert _lauf(tmp_path) == 0


def test_alte_schedule_datei_ist_unhealthy(tmp_path: Path) -> None:
    """Zwanzig Minuten alt -> Beat tickt nicht mehr.

    Das ist die Wirkung, um die es geht (§5.76): nicht "laeuft der Prozess",
    sondern "hat er in den letzten zehn Minuten etwas getan".
    """
    datei = tmp_path / "celerybeat-schedule.db"
    datei.touch()
    _altern(datei, 20 * 60)
    assert _lauf(tmp_path) == 1


def test_keine_schedule_datei_ist_unhealthy(tmp_path: Path) -> None:
    """Kein Schedule -> Beat hat nie geschrieben."""
    assert _lauf(tmp_path) == 1


@pytest.mark.parametrize(
    "name",
    [
        "celerybeat-schedule",  # Name unveraendert
        "celerybeat-schedule.db",  # gdbm
        "celerybeat-schedule.dat",  # dbm.dumb
        "celerybeat-schedule.dir",  # dbm.dumb
    ],
)
def test_jede_dbm_variante_wird_gefunden(tmp_path: Path, name: str) -> None:
    """Der Grund fuer das Muster statt eines festen Pfades.

    ``--schedule=/tmp/celerybeat-schedule`` gibt den Pfad an
    ``shelve.open()``, und welche Datei daraus wird, entscheidet die zur
    Laufzeit verfuegbare dbm-Implementierung: ``.db`` bei gdbm,
    ``.dir``/``.dat``/``.bak`` bei ``dbm.dumb``, oder der Name unveraendert.

    Ein Check auf den exakten Pfad waere dauerhaft rot, wenn die Datei anders
    heisst — dasselbe Symptom wie vor der Umstellung, nur mit neuer Ursache.
    Dieser Test ist die Klammer dagegen.
    """
    (tmp_path / name).touch()
    assert _lauf(tmp_path) == 0


def test_die_neueste_datei_entscheidet(tmp_path: Path) -> None:
    """``dbm.dumb`` legt drei Dateien an, von denen nur eine frisch ist.

    Geprueft wird das Maximum der Aenderungszeiten, nicht die erste Datei,
    die der Glob findet — sonst haengt das Urteil an der
    Verzeichnis-Reihenfolge.
    """
    alt = tmp_path / "celerybeat-schedule.bak"
    alt.touch()
    _altern(alt, 60 * 60)
    (tmp_path / "celerybeat-schedule.dat").touch()
    assert _lauf(tmp_path) == 0


def test_fenster_ist_zehn_minuten(tmp_path: Path) -> None:
    """Die Grenze liegt bei 600 s, nicht bei 300.

    Zehn Minuten und nicht fuenf, weil die Sync-Kadenz des
    ``PersistentScheduler`` (rund drei Minuten, ``sync_every``) ein
    Celery-interner Default ist — genau die Sorte Zahl, die sich unter einer
    unfixierten Abhaengigkeit verschiebt (§5.80). Bei fuenf Minuten waere ein
    gesunder Beat nach zwei ausgefallenen Syncs rot.

    Erwartungswert aus dieser Begruendung, nicht aus einem Lauf (§5.79).
    """
    datei = tmp_path / "celerybeat-schedule.db"
    datei.touch()
    _altern(datei, 9 * 60)
    assert _lauf(tmp_path) == 0, "9 Minuten muessen noch healthy sein"
    _altern(datei, 11 * 60)
    assert _lauf(tmp_path) == 1, "11 Minuten muessen unhealthy sein"


# ---------------------------------------------------------------------------
# celery_worker: der bestehende Check bleibt, wie er ist
# ---------------------------------------------------------------------------


def test_worker_healthcheck_ist_echt_und_unveraendert() -> None:
    """Der Worker-Check war nie geerbt — er ist explizit und bleibt.

    Geprueft im Auftrag vom 30.09.2026. ``celery inspect ping`` laeuft ueber
    den Broker: faellt Redis aus, meldet der Worker ``unhealthy``, obwohl der
    Prozess lebt. Das ist vertretbar (ein Worker ohne Broker arbeitet nicht),
    aber es ist kein reiner Prozess-Check — und dieser Test haelt fest, dass
    die Entscheidung bewusst so steht.
    """
    befehl = _healthcheck_test("celery_worker")
    assert befehl == [
        "CMD",
        "celery",
        "-A",
        "heizung.celery_app",
        "inspect",
        "ping",
        "-t",
        "5",
    ], befehl
