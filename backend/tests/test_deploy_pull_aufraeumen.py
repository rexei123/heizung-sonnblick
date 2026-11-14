"""``deploy-pull.sh`` raeumt nach dem Deploy alte Images weg (14.11.2026).

Geprueft wird das **echte** Skript, nicht ein Nachbau: der Test legt ein
Wegwerf-Repo an, haengt Attrappen fuer ``docker``, ``git``, ``curl`` und
``df`` vor den ``PATH`` und laesst ``infra/deploy/deploy-pull.sh`` darauf
laufen. Vorbild und Begruendung: ``test_deploy_pull_lock``.

Vier Zusicherungen, und die ersten zwei sind die, die weh tun koennen:

* **Was laeuft, bleibt.** Ein geloeschtes Image unter einem laufenden
  Container ist der Fehler, der beim naechsten ``up -d`` auffaellt und
  dann keine Quelle mehr hat.
* **Das Rueckfallziel bleibt**, auch wenn es aelter ist als die Grenze.
  Wer alte Images loescht, loescht Rueckfallziele (RUNBOOK Paragraph
  10u).
* **Nur alte Tags gehen weg**, und nur die beiden eigenen Repositories —
  kein ``prune``, das ``caddy``, ``redis`` und die ChirpStack-Bilder
  mitnimmt.
* **Ein Fehlschlag beim Aufraeumen laesst den Deploy gruen.** Sonst
  meldet ein Melder am falschen Ort (Paragraph 5.79).

``bash`` ist Voraussetzung; ohne wird uebersprungen. In CI (ubuntu)
laeuft es immer. Unter Windows wurde die Logik am 14.11.2026 von Hand
mit denselben Attrappen belegt.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_WURZEL = Path(__file__).resolve().parents[2]
SKRIPT = REPO_WURZEL / "infra" / "deploy" / "deploy-pull.sh"

pytestmark = pytest.mark.skipif(
    os.name != "posix" or shutil.which("bash") is None,
    reason="braucht POSIX-bash (CI: ubuntu)",
)

#: Der Tag, den dieser Lauf deployt. ``git rev-parse`` in der Attrappe
#: liefert ``deadbeefcafe``, und das Skript schneidet sieben Zeichen ab.
LAUFENDER_TAG = "develop-deadbee"

#: Zwei alte Tags (vor der Grenze) und ein junger. Das Datum steht vorn,
#: wie ``docker images --format '{{.CreatedAt}}'`` es liefert.
IMAGES_API = [
    f"ghcr.io/rexei123/heizung-api:{LAUFENDER_TAG}|2026-11-14 06:00:00 +0100 CET",
    "ghcr.io/rexei123/heizung-api:develop-aaaaaaa|2026-11-13 06:00:00 +0100 CET",
    "ghcr.io/rexei123/heizung-api:develop-bbbbbbb|2026-10-01 06:00:00 +0100 CET",
    "ghcr.io/rexei123/heizung-api:develop-ccccccc|2026-09-15 06:00:00 +0100 CET",
    # Alt, laeuft nicht, ist nicht gepinnt: der Tag, an dem sich zeigt,
    # dass ueberhaupt geloescht wird. Ohne ihn waere der Pin-Test auch
    # mit einer leeren Loeschliste zufrieden (Paragraph 5.55).
    "ghcr.io/rexei123/heizung-api:develop-ddddddd|2026-08-01 06:00:00 +0100 CET",
]
IMAGES_WEB = [
    f"ghcr.io/rexei123/heizung-web:{LAUFENDER_TAG}|2026-11-14 06:00:00 +0100 CET",
    "ghcr.io/rexei123/heizung-web:develop-bbbbbbb|2026-10-01 06:00:00 +0100 CET",
]

#: Was laeuft.
#:
#: **``develop-ccccccc`` ist mit Absicht dabei, und es ist das aelteste
#: Image der Liste** (15.09.). Ohne einen laufenden Tag **jenseits** der
#: Datumsgrenze prueft „was laeuft, bleibt" gar nichts: der junge Tag des
#: Laufs ist schon durch das Datum geschuetzt, und der Test waere auch
#: ohne die Sicherung gruen (Paragraph 5.55 — ein gruener Lauf, der nichts
#: geprueft hat). Genau das hat eine Mutationsprobe am 14.11.2026
#: gezeigt.
#:
#: Der Fall ist nicht konstruiert: ``up -d`` rekreiert nur Container mit
#: Image- oder Config-Drift. Ein Dienst, der seit Wochen nicht angefasst
#: wurde, laeuft weiter auf seinem alten Image.
#:
#: Der Pin-Tag im dritten Test ist **nicht** dabei und muss trotzdem
#: bleiben — sonst waere die zweite Sicherung von der ersten verdeckt.
LAUFEND = [
    f"ghcr.io/rexei123/heizung-api:{LAUFENDER_TAG}",
    f"ghcr.io/rexei123/heizung-web:{LAUFENDER_TAG}",
    "ghcr.io/rexei123/heizung-api:develop-ccccccc",
    "caddy:2-alpine",
]


def _stub(pfad: Path, inhalt: str) -> None:
    pfad.write_text("#!/bin/sh\n" + inhalt, encoding="utf-8")
    pfad.chmod(0o755)


@pytest.fixture
def umgebung(tmp_path: Path) -> dict[str, object]:
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
    protokoll = (tmp_path / "aufrufe.txt").as_posix()

    images_api = "\n".join(IMAGES_API)
    images_web = "\n".join(IMAGES_WEB)
    laufend = "\n".join(LAUFEND)

    # docker: antwortet auf ``images`` und ``ps``, notiert alles.
    #
    # ``DOCKER_RMI_FEHLER=1`` laesst ``rmi`` scheitern — damit prueft ein
    # Test, dass der Deploy trotzdem gruen bleibt.
    _stub(
        bin_dir / "docker",
        f'echo "docker $*" >> "{protokoll}"\n'
        'case "$*" in\n'
        "  *TTL*) echo -2 ;;\n"
        "  *heizung-api*--format*|*--format*heizung-api*)\n"
        f'    printf "%s\\n" "{images_api}" ;;\n'
        "  *heizung-web*--format*|*--format*heizung-web*)\n"
        f'    printf "%s\\n" "{images_web}" ;;\n'
        "  ps*)\n"
        f'    printf "%s\\n" "{laufend}" ;;\n'
        "  rmi*)\n"
        '    if [ "$DOCKER_RMI_FEHLER" = "1" ]; then echo "rmi kaputt" >&2; exit 1; fi ;;\n'
        "esac\n"
        "exit 0\n",
    )
    _stub(
        bin_dir / "git",
        f'echo "git $*" >> "{protokoll}"\n'
        'case "$1" in\n'
        "  rev-parse) echo deadbeefcafe ;;\n"
        "  diff) exit 0 ;;\n"
        "esac\n"
        "exit 0\n",
    )
    _stub(bin_dir / "curl", f'echo "curl $*" >> "{protokoll}"\nexit 0\n')

    env = dict(os.environ)
    env["PATH"] = f"{bin_dir.as_posix()}:/usr/bin:/bin"
    env["DEPLOY_REPO_DIR"] = repo.as_posix()
    env["DEPLOY_LOG"] = (tmp_path / "deploy.log").as_posix()
    env["DOCKER_RMI_FEHLER"] = "0"
    # Die Grenze bleibt die Vorgabe (sieben Tage). Die Attrappe liefert
    # Daten weit davor und weit danach, der Test haengt also nicht am
    # Kalendertag, an dem er laeuft (Paragraph 5.59).
    return {"repo": repo, "protokoll": Path(protokoll), "env": env}


def _lauf(umgebung: dict[str, object], **extra: str) -> subprocess.CompletedProcess[str]:
    env = dict(umgebung["env"])  # type: ignore[arg-type]
    env.update(extra)
    return subprocess.run(
        ["bash", "infra/deploy/deploy-pull.sh"],
        cwd=str(umgebung["repo"]),
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
        check=False,
    )


def _rmi_zeilen(umgebung: dict[str, object]) -> list[str]:
    pfad = umgebung["protokoll"]
    assert isinstance(pfad, Path)
    text = pfad.read_text(encoding="utf-8") if pfad.exists() else ""
    return [z for z in text.splitlines() if z.startswith("docker rmi")]


def test_alte_tags_werden_geloescht(umgebung: dict[str, object]) -> None:
    """Die alten Tags gehen weg — bis auf den, der laeuft."""
    ergebnis = _lauf(umgebung)
    assert ergebnis.returncode == 0, ergebnis.stderr

    geloescht = " ".join(_rmi_zeilen(umgebung))
    assert "heizung-api:develop-bbbbbbb" in geloescht
    assert "heizung-web:develop-bbbbbbb" in geloescht
    assert "develop-ddddddd" in geloescht
    assert "develop-aaaaaaa" not in geloescht, "der junge Tag bleibt"


def test_der_laufende_tag_bleibt(umgebung: dict[str, object]) -> None:
    """**Die erste Sicherung.**

    Ein geloeschtes Image unter einem laufenden Container faellt erst beim
    naechsten ``up -d`` auf — und hat dann keine Quelle mehr, wenn das
    Netz gerade das Problem ist.
    """
    _lauf(umgebung)
    geloescht = " ".join(_rmi_zeilen(umgebung))

    assert LAUFENDER_TAG not in geloescht, geloescht
    # **Der eigentliche Beleg**: dieser Tag ist zwei Monate alt und
    # ueberlebt die Datumsgrenze nur, weil ein Container ihn benutzt.
    assert "develop-ccccccc" not in geloescht, (
        f"ein laufendes Image jenseits der Datumsgrenze wurde geloescht: {geloescht}"
    )


def test_das_rueckfallziel_bleibt_auch_wenn_es_alt_ist(
    umgebung: dict[str, object],
) -> None:
    """**Die zweite Sicherung** (RUNBOOK Paragraph 10u).

    Mit gesetztem ``PIN_SHA`` faehrt der Server diesen Commit, und sein
    Tag ist der des Laufs. Er ist hier **aelter als die Grenze** und muss
    trotzdem bleiben: wer alte Images loescht, loescht Rueckfallziele.

    Dass er nicht nur deshalb bleibt, weil ein Container ihn benutzt,
    stellt die Attrappe sicher — ``docker ps`` nennt ihn nicht.
    """
    repo = umgebung["repo"]
    assert isinstance(repo, Path)
    (repo / "infra" / "deploy" / ".env").write_text(
        "STAGE=test\nIMAGE_TAG=develop\n"
        "HEALTHCHECK_DEPLOY_URL=http://ping.invalid/abc\n"
        "PIN_SHA=bbbbbbb\n",
        encoding="utf-8",
    )
    # Die git-Attrappe muss den Pin als Commit bestaetigen und das
    # Skript im Ziel-Commit als pin-faehig ausgeben.
    bin_dir = Path(str(umgebung["env"]["PATH"]).split(":")[0])  # type: ignore[index]
    protokoll = umgebung["protokoll"]
    assert isinstance(protokoll, Path)
    _stub(
        bin_dir / "git",
        f'echo "git $*" >> "{protokoll.as_posix()}"\n'
        'case "$1" in\n'
        "  rev-parse) echo bbbbbbbcafe ;;\n"
        "  show) echo 'read_env_key PIN_SHA' ;;\n"
        "  log) echo '' ;;\n"
        "  diff) exit 0 ;;\n"
        "esac\n"
        "exit 0\n",
    )

    ergebnis = _lauf(umgebung)
    assert ergebnis.returncode == 0, ergebnis.stdout + ergebnis.stderr

    geloescht = " ".join(_rmi_zeilen(umgebung))
    assert "develop-bbbbbbb" not in geloescht, f"das Rueckfallziel wurde geloescht: {geloescht}"
    # Und der Pin ist keine Generalamnestie: ``ddddddd`` ist genauso alt,
    # laeuft nicht und ist nicht gepinnt — der geht weg. Ohne diese Zeile
    # waere der Test auch mit einer leeren Loeschliste zufrieden.
    assert "develop-ddddddd" in geloescht, geloescht


def test_fremde_images_werden_nicht_angefasst(umgebung: dict[str, object]) -> None:
    """Kein ``prune``: ``caddy``, ``redis``, ChirpStack bleiben.

    Sie kommen aus fremden Registries, und sie wiederzuholen braucht Netz
    zu einem Zeitpunkt, den niemand waehlt.
    """
    _lauf(umgebung)
    protokoll = umgebung["protokoll"]
    assert isinstance(protokoll, Path)
    alles = protokoll.read_text(encoding="utf-8")

    assert "prune" not in alles, alles
    assert "caddy" not in " ".join(_rmi_zeilen(umgebung))
    # Und `rmi` ohne `-f`: ohne das Flag verweigert docker jedes Image,
    # das ein Container benutzt — die Sicherung hinter der Sicherung.
    for zeile in _rmi_zeilen(umgebung):
        assert " -f" not in zeile, zeile


def test_ein_fehlschlag_beim_aufraeumen_laesst_den_deploy_gruen(
    umgebung: dict[str, object],
) -> None:
    """Ein Deploy, der wegen einer Aufraeum-Panne rot meldet, waere ein
    Melder am falschen Ort (Paragraph 5.79)."""
    ergebnis = _lauf(umgebung, DOCKER_RMI_FEHLER="1")

    assert ergebnis.returncode == 0, ergebnis.stdout + ergebnis.stderr
    assert "Fertig." in ergebnis.stdout
    # Und der Dead-Man-Ping geht trotzdem hinaus.
    protokoll = umgebung["protokoll"]
    assert isinstance(protokoll, Path)
    assert "curl" in protokoll.read_text(encoding="utf-8")


def test_null_tage_schaltet_das_aufraeumen_aus(umgebung: dict[str, object]) -> None:
    """Ein Schalter, der nichts tut, waere schlimmer als keiner.

    ``DEPLOY_CLEANUP_DAYS=0`` heisst „nicht aufraeumen" und nicht „alles
    loeschen" — die zweite Lesart waere mit einer Datumsgrenze von heute
    genau das.
    """
    ergebnis = _lauf(umgebung, DEPLOY_CLEANUP_DAYS="0")

    assert ergebnis.returncode == 0, ergebnis.stderr
    assert _rmi_zeilen(umgebung) == []
    assert "uebersprungen" in ergebnis.stdout


def test_ohne_docker_ps_wird_nichts_geloescht(umgebung: dict[str, object], tmp_path: Path) -> None:
    """**Die Sicherheitsprobe aus Paragraph 10az, in Code.**

    Ist nicht zu ermitteln, was laeuft, wird nicht geloescht. Lieber eine
    volle Platte als ein geloeschtes Image unter einem laufenden
    Container.
    """
    bin_dir = Path(str(umgebung["env"]["PATH"]).split(":")[0])  # type: ignore[index]
    protokoll = umgebung["protokoll"]
    assert isinstance(protokoll, Path)
    images_api = "\n".join(IMAGES_API)
    _stub(
        bin_dir / "docker",
        f'echo "docker $*" >> "{protokoll.as_posix()}"\n'
        'case "$*" in\n'
        "  *TTL*) echo -2 ;;\n"
        "  *heizung-api*--format*)\n"
        f'    printf "%s\\n" "{images_api}" ;;\n'
        "  ps*) exit 1 ;;\n"
        "esac\n"
        "exit 0\n",
    )

    ergebnis = _lauf(umgebung)

    assert ergebnis.returncode == 0, ergebnis.stderr
    assert _rmi_zeilen(umgebung) == []
    assert "nicht abfragbar" in ergebnis.stdout
