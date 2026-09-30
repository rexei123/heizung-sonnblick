"""Sprint 20a — ``deploy-pull.sh`` respektiert die Deploy-Sperre.

Geprueft wird das **echte** Skript, nicht ein Nachbau: der Test legt ein
Wegwerf-Repo an, haengt Attrappen fuer ``docker``, ``curl`` und ``git`` vor
den ``PATH`` und laesst ``infra/deploy/deploy-pull.sh`` darauf laufen. Ein
nachgebautes Skript im Test wuerde nur sich selbst pruefen — und genau die
Zeile, die im Betrieb laeuft, nicht.

Der Gegenstand ist eine einzige Zusicherung mit zwei Seiten:

* **Sperre gesetzt -> kein Pull.** Nichts wird gefetcht, kein Image gezogen,
  kein Container angefasst. Sonst stirbt ein laufender Eingangstest mitten
  in einer Bestaetigungs-Kette und laesst ein Geraet mit ausstehendem
  Downlink zurueck (S4).
* **Keine Sperre -> Pull laeuft.** Sonst waere die Sperre ein Deploy-Stop,
  den niemand als solchen erkennt — der teurere Fehler, weil er wochenlang
  unbemerkt bleibt (§5.7).

``bash`` ist Voraussetzung; ohne wird uebersprungen. In CI (ubuntu) laeuft
es immer.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_WURZEL = Path(__file__).resolve().parents[2]
SKRIPT = REPO_WURZEL / "infra" / "deploy" / "deploy-pull.sh"

# Nur auf POSIX. Unter Windows findet ``which("bash")`` je nach Rechner
# WSL-bash, und die erbt die Windows-Umgebung nicht und kennt "C:/..." nicht
# als Pfad — der Test wuerde dort an seiner eigenen Huelle scheitern, nicht am
# Skript. Die Skript-Logik selbst ist am 30.09.2026 zusaetzlich von Hand unter
# Git Bash belegt worden: Sperre 3600 s ergab "UEBERSPRUNGEN", kein
# ``git fetch``, kein Pull, und einen Ping mit Grund und Ablaufzeit.
pytestmark = pytest.mark.skipif(
    os.name != "posix" or shutil.which("bash") is None,
    reason="braucht POSIX-bash (CI: ubuntu)",
)


def _stub(pfad: Path, inhalt: str) -> None:
    pfad.write_text("#!/bin/sh\n" + inhalt, encoding="utf-8")
    pfad.chmod(0o755)


@pytest.fixture
def umgebung(tmp_path: Path) -> dict[str, object]:
    """Wegwerf-Repo plus Attrappen. Gibt Pfade und das Environment zurueck.

    ``docker`` und ``git`` schreiben jeden Aufruf in eine Datei, damit der
    Test danach sagen kann, **was** das Skript getan hat — nicht nur, mit
    welchem Code es endete. Ein Skript, das mit 0 endet, ohne etwas zu tun,
    ist der Fehler, den dieser Test finden soll.
    """
    repo = tmp_path / "repo"
    (repo / "infra" / "deploy").mkdir(parents=True)
    shutil.copy(SKRIPT, repo / "infra" / "deploy" / "deploy-pull.sh")
    shutil.copy(
        REPO_WURZEL / "infra" / "deploy" / "docker-compose.prod.yml",
        repo / "infra" / "deploy" / "docker-compose.prod.yml",
    )
    (repo / "infra" / "deploy" / ".env").write_text(
        "STAGE=test\nIMAGE_TAG=develop\nHEALTHCHECK_DEPLOY_URL=http://ping.invalid/abc\n",
        encoding="utf-8",
    )

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    protokoll = tmp_path / "aufrufe.txt"
    # Pfade in POSIX-Form: die Attrappen sind `#!/bin/sh`-Skripte, und bash
    # (auch Git Bash unter Windows) versteht "C:/..." — "C:\..." nicht, dort
    # frisst die Shell die Backslashes als Escapes.
    protokoll_sh = protokoll.as_posix()

    # docker: TTL-Antwort kommt aus DOCKER_TTL, alles andere wird nur notiert.
    #
    # ``DOCKER_TTL=FEHLER`` modelliert den realen Ausfall: steht der Stack
    # nicht, scheitert ``compose exec`` selbst — ohne Ausgabe, mit Exit 1.
    # Ein leeres ``DOCKER_TTL`` taugt dafuer NICHT: ``${DOCKER_TTL:--2}``
    # ersetzt auch den leeren Wert und liefert -2, also "Key fehlt" statt
    # "nicht abfragbar". Genau daran waere dieser Test in CI rot geworden.
    _stub(
        bin_dir / "docker",
        f'echo "docker $*" >> "{protokoll_sh}"\n'
        'case "$*" in\n'
        "  *TTL*)\n"
        '    if [ "$DOCKER_TTL" = "FEHLER" ]; then exit 1; fi\n'
        '    echo "$DOCKER_TTL"\n'
        "    ;;\n"
        "esac\n"
        "exit 0\n",
    )
    # git: notiert und antwortet so, dass Phase 1 durchlaeuft.
    _stub(
        bin_dir / "git",
        f'echo "git $*" >> "{protokoll_sh}"\n'
        'case "$1" in\n'
        "  rev-parse) echo deadbeef ;;\n"
        "  diff) exit 0 ;;\n"
        "esac\n"
        "exit 0\n",
    )
    _stub(bin_dir / "curl", f'echo "curl $*" >> "{protokoll_sh}"\nexit 0\n')

    env = dict(os.environ)
    # Minimaler PATH mit POSIX-Trenner: die Attrappen plus die Coreutils, die
    # das Skript braucht (date, tee, grep, cut, tail, head, tr). Den echten
    # PATH des Elternprozesses zu uebernehmen geht unter Windows nicht — er
    # traegt ";" als Trenner, bash erwartet ":".
    env["PATH"] = f"{bin_dir.as_posix()}:/usr/bin:/bin"
    env["DEPLOY_REPO_DIR"] = repo.as_posix()
    env["DEPLOY_LOG"] = (tmp_path / "deploy.log").as_posix()
    return {"repo": repo, "protokoll": protokoll, "env": env, "log": tmp_path / "deploy.log"}


def _lauf(umgebung: dict[str, object], *, ttl: str) -> subprocess.CompletedProcess[str]:
    env = dict(umgebung["env"])  # type: ignore[arg-type]
    env["DOCKER_TTL"] = ttl
    # Relativer Skript-Pfad plus `cwd`: ein absoluter Windows-Pfad mit
    # Laufwerksbuchstaben kommt bei Git Bash als Argument nicht sauber an
    # ("C:/...: No such file or directory"). Unter Linux ist beides gleich.
    return subprocess.run(
        ["bash", "infra/deploy/deploy-pull.sh"],
        cwd=str(umgebung["repo"]),
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


def test_sperre_gesetzt_kein_pull(umgebung: dict[str, object]) -> None:
    """TTL 3600 -> das Skript endet vor Phase 1, ohne Pull und ohne up -d."""
    ergebnis = _lauf(umgebung, ttl="3600")
    aufrufe = _aufrufe(umgebung)

    assert ergebnis.returncode == 0, ergebnis.stderr
    assert "UEBERSPRUNGEN" in ergebnis.stdout, ergebnis.stdout
    # Die drei Dinge, die einen laufenden Eingangstest umbringen wuerden.
    assert "git fetch" not in aufrufe, aufrufe
    assert "pull api web" not in aufrufe, aufrufe
    assert "up -d" not in aufrufe, aufrufe


def test_sperre_gesetzt_pingt_mit_grund(umgebung: dict[str, object]) -> None:
    """Der Monitor erfaehrt, WARUM nicht deployt wurde.

    Ohne Ping schlaegt der Deploy-Monitor nach 20 min Karenz an, und ein
    Montage-Lauf dauert 1-3 Stunden — bei jedem Lauf ein Falsch-Alarm
    (§5.79). Mit Ping, aber ohne Body, stuende im Monitor „alles in
    Ordnung", was auch nicht stimmt. Deshalb beides.
    """
    ergebnis = _lauf(umgebung, ttl="3600")
    aufrufe = _aufrufe(umgebung)

    assert "curl" in aufrufe, aufrufe
    assert "skipped: inbound_test lock" in aufrufe, aufrufe
    assert "TTL bis" in aufrufe, aufrufe
    assert "ping.invalid" in aufrufe, aufrufe
    assert ergebnis.returncode == 0


def test_keine_sperre_deploy_laeuft(umgebung: dict[str, object]) -> None:
    """TTL -2 (Key fehlt) -> Phase 1 und folgende laufen.

    Die Gegenprobe. Ohne sie koennte die Sperre dauerhaft greifen, ohne dass
    es auffaellt — ein Deploy-Stop, den niemand als solchen erkennt, ist der
    teurere Fehler (§5.7: drei Monate stiller Stillstand).
    """
    ergebnis = _lauf(umgebung, ttl="-2")
    aufrufe = _aufrufe(umgebung)

    assert "UEBERSPRUNGEN" not in ergebnis.stdout, ergebnis.stdout
    assert "git fetch" in aufrufe, aufrufe
    assert "up -d" in aufrufe, aufrufe
    assert ergebnis.returncode == 0, ergebnis.stderr


def test_sperre_ohne_ttl_wird_gemeldet_und_sperrt(umgebung: dict[str, object]) -> None:
    """TTL -1: Key da, ohne Ablauf — der gefaehrlichste Fall.

    So einen Key legt ``deploy_lock.acquire`` nie an (es setzt immer ``ex``).
    Steht er trotzdem da, ist etwas anderes passiert, und eine Sperre ohne
    Ablauf blockiert den Deploy fuer immer. Das Skript sperrt dann und sagt
    es deutlich, statt still zu deployen oder still zu blockieren.
    """
    ergebnis = _lauf(umgebung, ttl="-1")
    aufrufe = _aufrufe(umgebung)

    assert "OHNE TTL" in ergebnis.stdout, ergebnis.stdout
    assert "git fetch" not in aufrufe, aufrufe
    assert "ohne TTL" in aufrufe, aufrufe
    assert ergebnis.returncode == 0


def test_redis_nicht_abfragbar_sperrt_nicht(umgebung: dict[str, object]) -> None:
    """Abfrage scheitert -> weiterfahren.

    Ist der Stack unten, laeuft auch kein Eingangstest — der braucht
    denselben Container. Eine Sperre bei unbekanntem Zustand wuerde den
    Deploy bei jedem Redis-Ausfall lahmlegen, und das ist genau der Fall, in
    dem man deployen will.
    """
    ergebnis = _lauf(umgebung, ttl="FEHLER")
    aufrufe = _aufrufe(umgebung)

    assert "nicht abfragbar" in ergebnis.stdout, ergebnis.stdout
    assert "git fetch" in aufrufe, aufrufe
    assert ergebnis.returncode == 0, ergebnis.stderr


def test_key_name_stimmt_mit_dem_python_modul_ueberein() -> None:
    """Die Schnittstelle zwischen Skript und Anwendung ist ein String.

    Das Skript kann ``deploy_lock.DEPLOY_LOCK_KEY`` nicht importieren. Wer
    den Namen auf einer Seite aendert, bekommt eine Sperre, die gesetzt wird
    und nie gelesen — lautlos. Dieser Test ist die Klammer.
    """
    from heizung.services.deploy_lock import DEPLOY_LOCK_KEY

    text = SKRIPT.read_text(encoding="utf-8")
    assert f'LOCK_KEY="{DEPLOY_LOCK_KEY}"' in text
