"""H-6 Nachtrag — der Entrypoint laesst den Container starten, statt zu kreisen.

Geprueft wird das **echte** Skript, nicht ein Nachbau (§5.82): der Test
haengt Attrappen fuer ``python``, ``alembic`` und ``sleep`` vor den ``PATH``
und laesst ``backend/docker-entrypoint.sh`` darauf laufen. Dieselbe Huelle
wie ``test_deploy_pull_pinning.py``.

**Was auf dem Spiel steht.** Nach einem Rueckfall per ``PIN_SHA`` ist die
Datenbank neuer als der Code. ``alembic upgrade head`` bricht dann mit
"Can't locate revision" ab, der Entrypoint versucht es fuenfmal und beendet
sich mit ``exit 1`` — und weil api, celery_worker und celery_beat dasselbe
Image mit demselben Entrypoint fahren und ``restart: always`` gilt, kreist
der ganze Stack ohne API und ohne Engine.

Die Zusicherungen, in der Reihenfolge ihrer Wichtigkeit:

* **Rueckgabe 10 ueberspringt das Upgrade und startet die Anwendung.**
* **Jeder andere Rueckgabe-Code fuehrt zum Upgrade** — auch ein Fehler im
  Vorcheck selbst. Er darf nur verhindern, nie zusaetzlich scheitern.
* **Ein echter Migrationsfehler bricht weiter ab.** Das Ueberspringen
  gilt fuer genau einen Zustand, nicht als Nachsicht gegenueber Alembic.
* **Der uebersprungene Fall steht im Log**, mit einem Wort, nach dem man
  suchen kann.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

BACKEND_WURZEL = Path(__file__).resolve().parents[1]
SKRIPT = BACKEND_WURZEL / "docker-entrypoint.sh"

# Nur auf POSIX, wie ``test_deploy_pull_lock.py`` und
# ``test_deploy_pull_pinning.py`` — die Gruende stehen im Modul-Docstring
# des zweiten (Git Bash liefert ``env=`` nicht durch, loest ``C:/``-Pfade
# nicht auf). CI laeuft auf Linux und fuehrt diese Datei aus.
pytestmark = pytest.mark.skipif(
    os.name != "posix" or shutil.which("bash") is None,
    reason="Shell-Test nur auf POSIX mit bash",
)


def _stub(pfad: Path, inhalt: str) -> None:
    pfad.write_text("#!/bin/sh\n" + inhalt, encoding="utf-8")
    pfad.chmod(0o755)


@pytest.fixture
def umgebung(tmp_path: Path) -> dict[str, object]:
    """Attrappen fuer ``python``, ``alembic`` und ``sleep``.

    ``sleep`` ist dabei kein Luxus: der Fehlerpfad wartet fuenfmal drei
    Sekunden, und ein Test, der 15 Sekunden braucht, wird irgendwann
    uebersprungen statt gelesen.
    """
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    protokoll = tmp_path / "aufrufe.txt"
    p = protokoll.as_posix()

    _stub(
        bin_dir / "python",
        f'echo "python $*" >> "{p}"\nexit "${{VORCHECK_CODE:-0}}"\n',
    )
    _stub(
        bin_dir / "alembic",
        f'echo "alembic $*" >> "{p}"\nif [ -n "$ALEMBIC_FEHLER" ]; then exit 1; fi\nexit 0\n',
    )
    _stub(bin_dir / "sleep", f'echo "sleep $*" >> "{p}"\nexit 0\n')

    env = dict(os.environ)
    env["PATH"] = f"{bin_dir.as_posix()}:/usr/bin:/bin"
    return {"bin": bin_dir, "protokoll": protokoll, "env": env}


def _lauf(umgebung: dict[str, object], **zusatz: str) -> subprocess.CompletedProcess[str]:
    env = dict(umgebung["env"])  # type: ignore[arg-type]
    env.update(zusatz)
    return subprocess.run(
        ["bash", str(SKRIPT), "echo", "ANWENDUNG-GESTARTET"],
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
        check=False,
    )


def _aufrufe(umgebung: dict[str, object]) -> str:
    pfad = umgebung["protokoll"]
    assert isinstance(pfad, Path)
    return pfad.read_text(encoding="utf-8") if pfad.exists() else ""


# ---------------------------------------------------------------------------
# 1. Der Fall, um den es geht
# ---------------------------------------------------------------------------


def test_code_10_ueberspringt_und_startet(umgebung: dict[str, object]) -> None:
    """Datenbank neuer als das Image: kein Upgrade, Anwendung laeuft."""
    lauf = _lauf(umgebung, VORCHECK_CODE="10")

    assert lauf.returncode == 0
    protokoll = _aufrufe(umgebung)
    assert "python -m heizung.scripts.db_revision_check" in protokoll
    # Der Kern: das Upgrade wird nicht einmal versucht.
    assert "alembic" not in protokoll
    assert "ANWENDUNG-GESTARTET" in lauf.stdout
    # Und es steht im Log, mit einem Wort, nach dem man suchen kann.
    assert "UEBERSPRUNGEN" in lauf.stdout + lauf.stderr


# ---------------------------------------------------------------------------
# 2. Der Normalfall und das Fail-Open
# ---------------------------------------------------------------------------


def test_code_0_migriert_wie_bisher(umgebung: dict[str, object]) -> None:
    """Jeder Deploy: Vorcheck sagt ja, Upgrade laeuft, Anwendung startet."""
    lauf = _lauf(umgebung, VORCHECK_CODE="0")

    assert lauf.returncode == 0
    assert "alembic upgrade head" in _aufrufe(umgebung)
    assert "ANWENDUNG-GESTARTET" in lauf.stdout


def test_unerwarteter_code_migriert_trotzdem(umgebung: dict[str, object]) -> None:
    """Vorcheck selbst kaputt (Code 1): Verhalten wie vor dem Vorcheck.

    Ein neues Fehlerbild waere hier schlechter als das alte. Faellt der
    Vorcheck aus, bleibt es beim bekannten: fuenf Versuche, dann
    sichtbarer Absturz — mit einer Diagnose, die im RUNBOOK steht.
    """
    lauf = _lauf(umgebung, VORCHECK_CODE="1")

    assert lauf.returncode == 0
    assert "alembic upgrade head" in _aufrufe(umgebung)
    assert "ANWENDUNG-GESTARTET" in lauf.stdout


# ---------------------------------------------------------------------------
# 3. Nachsicht nur fuer diesen einen Zustand
# ---------------------------------------------------------------------------


def test_echter_migrationsfehler_bricht_weiter_ab(umgebung: dict[str, object]) -> None:
    """Fuenf Versuche, dann ``exit 1`` — unveraendert.

    Das Ueberspringen gilt fuer "DB neuer als Image", nicht als Nachsicht
    gegenueber Alembic. Ein Container, der mit halb angewandten
    Migrationen hochfaehrt, waere schlimmer als einer, der nicht startet.
    """
    lauf = _lauf(umgebung, VORCHECK_CODE="0", ALEMBIC_FEHLER="1")

    assert lauf.returncode == 1
    protokoll = _aufrufe(umgebung)
    assert protokoll.count("alembic upgrade head") == 5
    assert "ANWENDUNG-GESTARTET" not in lauf.stdout


# ---------------------------------------------------------------------------
# 4. Reihenfolge
# ---------------------------------------------------------------------------


def test_vorcheck_laeuft_vor_dem_upgrade(umgebung: dict[str, object]) -> None:
    """Sonst waere er wertlos: der Abbruch passiert im Upgrade."""
    _lauf(umgebung, VORCHECK_CODE="0")
    protokoll = _aufrufe(umgebung)

    assert protokoll.index("python -m") < protokoll.index("alembic")
