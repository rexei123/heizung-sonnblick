"""H-6 T2-T6 — der Server zieht das Image zu dem Commit, den er fährt.

Geprüft wird das **echte** Skript, nicht ein Nachbau (§5.82): der Test legt
ein Wegwerf-Repo an, hängt Attrappen für ``docker``, ``git`` und ``curl`` vor
den ``PATH`` und lässt ``infra/deploy/deploy-pull.sh`` darauf laufen. Dieselbe
Hülle wie ``test_deploy_pull_lock.py``.

**Was auf dem Spiel steht.** Vorher lief der Betrieb auf einem gleitenden
Tag: die Compose-Datei sagt ``:${IMAGE_TAG:-develop}``, der Timer zog, was
gerade darunter lag. Zwei Folgen, und die zweite ist die teure:

1. Es gab **keinen Rückfallpunkt**. Bricht ein Merge die Steuerung, ist der
   Weg zurück „den vorigen Stand wiederfinden und von Hand einen anderen Tag
   setzen" — während der Timer alle fünf Minuten erneut ``develop`` zieht.
2. Es war **nicht nachweisbar, was läuft**. „Der Server ist auf develop"
   sagt nichts über den Commit. Das ist §5.68 in der Infrastruktur.

Die Zusicherungen hier, in der Reihenfolge ihrer Wichtigkeit:

* **Der Tag folgt dem Commit**, auf den Phase 1 gesynct hat — nicht einer
  Pfadsuche im ``git log`` (das war der Fehler von 2026-04-30, §5.4).
* **``PIN_SHA`` gewinnt und überlebt den Timer.** Sonst wäre ein Rückfall
  nach fünf Minuten weg.
* **Ein unbekannter Pin bricht ab** statt auf den Branch zurückzufallen. Ein
  Tippfehler würde sonst stumm den neuesten Stand deployen — das Gegenteil
  dessen, was jemand wollte, der gerade zurückrollt.
* **Die ``.env`` wird nicht geschrieben.** Eine Datei, die der Timer alle
  fünf Minuten überschreibt, ist kein Ort für eine Entscheidung des Menschen.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_WURZEL = Path(__file__).resolve().parents[2]
SKRIPT = REPO_WURZEL / "infra" / "deploy" / "deploy-pull.sh"


# Nur auf POSIX, wie ``test_deploy_pull_lock.py``.
#
# **Ein Versuch, das zu ueberwinden, ist hier gescheitert und das ist die
# Notiz dazu.** Git Bash unter Windows bringt drei Huerden mit, jede mit einer
# irrefuehrenden Fehlermeldung: ``env=`` liefert neue Variablen nicht durch
# (das Skript meldet dann „unbound variable"), ``C:/…``-Eintraege im ``PATH``
# werden nicht aufgeloest (das Skript findet das **echte** ``git`` und meldet
# ``fatal: not a git repository``), und ein Windows-Pfad mit Backslashes
# kommt bei ``cd`` als Escape-Folge an. Jede Huerde sieht nach einem Fehler
# im Skript aus.
#
# Die Skript-Logik ist stattdessen **in einem Linux-Container** geprueft
# (siehe PR-Text): dieselben Attrappen, dieselben vier Pfade. Damit ist das
# Geprueft-werden nicht an CI ausgeliefert, und die Huelle hier bleibt so
# einfach wie die des Schwesterfiles.
pytestmark = pytest.mark.skipif(
    os.name != "posix" or shutil.which("bash") is None,
    reason="braucht POSIX-bash (CI: ubuntu)",
)


BRANCH_SHA = "aaaaaaaabbbbbbbbccccccccdddddddd11111111"
PIN_SHA = "9999999988888888777777776666666655555555"


def _stub(pfad: Path, inhalt: str) -> None:
    pfad.write_text("#!/bin/sh\n" + inhalt, encoding="utf-8")
    pfad.chmod(0o755)


@pytest.fixture
def umgebung(tmp_path: Path) -> dict[str, object]:
    """Wegwerf-Repo plus Attrappen.

    Die ``git``-Attrappe ist der Kern: sie beantwortet ``rev-parse`` je nach
    Argument und **protokolliert jeden Aufruf**. Nur so kann der Test sagen,
    ob das Skript auf den Branch oder auf den Pin gegangen ist — der
    Rückgabe-Code allein sagt das nicht.
    """
    repo = tmp_path / "repo"
    (repo / "infra" / "deploy").mkdir(parents=True)
    shutil.copy(SKRIPT, repo / "infra" / "deploy" / "deploy-pull.sh")
    shutil.copy(
        REPO_WURZEL / "infra" / "deploy" / "docker-compose.prod.yml",
        repo / "infra" / "deploy" / "docker-compose.prod.yml",
    )

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    protokoll = tmp_path / "aufrufe.txt"
    protokoll_sh = protokoll.as_posix()

    # docker: TTL = -2 (keine Sperre). ``pull`` scheitert, wenn
    # DOCKER_PULL_FEHLER gesetzt ist — damit wird der T3-Pfad geprüft.
    # ``manifest inspect`` antwortet nach DOCKER_MANIFEST.
    _stub(
        bin_dir / "docker",
        f'echo "docker $*" >> "{protokoll_sh}"\n'
        'case "$*" in\n'
        "  *TTL*) echo -2 ;;\n"
        '  *"pull"*)\n'
        '    if [ -n "$DOCKER_PULL_FEHLER" ]; then exit 1; fi\n'
        "    ;;\n"
        '  *"manifest inspect"*)\n'
        '    if [ "$DOCKER_MANIFEST" = "fehlt" ]; then exit 1; fi\n'
        "    ;;\n"
        '  *"image inspect"*) echo "ghcr.io/x@sha256:0123456789abcdef0123" ;;\n'
        "esac\n"
        "exit 0\n",
    )

    # git: rev-parse beantwortet die drei Formen, die das Skript nutzt.
    #
    # ``--verify --quiet <pin>^{commit}`` entscheidet, ob der Pin existiert —
    # gesteuert über GIT_PIN_BEKANNT, damit beide Fälle prüfbar sind.
    _stub(
        bin_dir / "git",
        f'echo "git $*" >> "{protokoll_sh}"\n'
        'case "$1" in\n'
        "  rev-parse)\n"
        '    case "$*" in\n'
        '      *"--verify --quiet"*"^{commit}"*)\n'
        '        if [ "$GIT_PIN_BEKANNT" = "nein" ]; then exit 1; fi\n'
        f'        echo "{PIN_SHA}" ;;\n'
        '      *"--abbrev-ref"*) echo "develop" ;;\n'
        f'      *"origin/"*) echo "{BRANCH_SHA}" ;;\n'
        '      *HEAD*) echo "$GIT_HEAD_SHA" ;;\n'
        f'      *) echo "{PIN_SHA}" ;;\n'
        "    esac\n"
        "    ;;\n"
        "  diff) exit 0 ;;\n"
        # ``show <pin>:infra/deploy/deploy-pull.sh`` fragt der Pin-Waechter:
        # kennt das Skript im Ziel-Commit die Pin-Logik? Vorgabe ja, sonst
        # waeren alle Pin-Tests hier auf einen Abbruch gelaufen.
        "  show)\n"
        '    case "$*" in\n'
        "      *docker-entrypoint.sh*)\n"
        # Zweiter Waechter: bringt das Ziel-Image den Revisions-Vorcheck?
        '        if [ "$GIT_ZIEL_VORCHECK" = "nein" ]; then exit 0; fi\n'
        "        echo 'python -m heizung.scripts.db_revision_check' ;;\n"
        "      *)\n"
        '        if [ "$GIT_ZIEL_PINFAEHIG" = "nein" ]; then exit 0; fi\n'
        "        echo 'PIN_SHA_VAL=$(read_env_key PIN_SHA)' ;;\n"
        "    esac\n"
        "    ;;\n"
        # ``log -- backend/alembic/versions/`` fragt der zweite Waechter:
        # liegen Migrationen zwischen Ziel und laufendem Stand? Vorgabe
        # nein, sonst haetten alle Pin-Tests den neuen Abbruch getroffen.
        "  log)\n"
        '    if [ "$GIT_MIGRATIONEN" = "ja" ]; then echo "abc1234"; fi\n'
        "    ;;\n"
        "esac\n"
        "exit 0\n",
    )
    _stub(bin_dir / "curl", f'echo "curl $*" >> "{protokoll_sh}"\nexit 0\n')

    env = dict(os.environ)
    env["PATH"] = f"{bin_dir.as_posix()}:/usr/bin:/bin"
    env["DEPLOY_REPO_DIR"] = repo.as_posix()
    env["DEPLOY_LOG"] = (tmp_path / "deploy.log").as_posix()
    env["GIT_HEAD_SHA"] = "0000000000000000000000000000000000000000"
    return {
        "repo": repo,
        "bin": bin_dir,
        "protokoll": protokoll,
        "protokoll_sh": protokoll_sh,
        "env": env,
        "log": tmp_path / "deploy.log",
        "envdatei": repo / "infra" / "deploy" / ".env",
    }


def _env_schreiben(umgebung: dict[str, object], pin: str | None = None) -> None:
    pfad = umgebung["envdatei"]
    assert isinstance(pfad, Path)
    zeilen = [
        "STAGE=test",
        "IMAGE_TAG=develop",
        "HEALTHCHECK_DEPLOY_URL=http://ping.invalid/abc",
    ]
    if pin is not None:
        zeilen.append(f"PIN_SHA={pin}")
    pfad.write_text("\n".join(zeilen) + "\n", encoding="utf-8")


def _lauf(umgebung: dict[str, object], **zusatz: str) -> subprocess.CompletedProcess[str]:
    """Das Skript laufen lassen. Attrappen und Zustand kommen aus ``env``."""
    env = dict(umgebung["env"])  # type: ignore[arg-type]
    env.update(zusatz)
    return subprocess.run(
        ["bash", "infra/deploy/deploy-pull.sh"],
        cwd=str(umgebung["repo"]),
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
        check=False,
    )


def _log(umgebung: dict[str, object]) -> str:
    pfad = umgebung["log"]
    assert isinstance(pfad, Path)
    return pfad.read_text(encoding="utf-8") if pfad.exists() else ""


def _aufrufe(umgebung: dict[str, object]) -> str:
    pfad = umgebung["protokoll"]
    assert isinstance(pfad, Path)
    return pfad.read_text(encoding="utf-8") if pfad.exists() else ""


# ---------------------------------------------------------------------------
# 1. Der Tag folgt dem Commit
# ---------------------------------------------------------------------------


def test_tag_kommt_aus_dem_branch_kopf(umgebung: dict[str, object]) -> None:
    """``<branch>-<sha7>`` aus dem Commit, auf den Phase 1 synct.

    **Nicht** aus ``git log -- backend/...``. Genau diese Pfadsuche ist am
    2026-04-30 gescheitert (§5.4): bei einem Merge findet sie den
    Source-Branch-Commit, CI taggt aber mit dem Merge-Commit.
    """
    _env_schreiben(umgebung)
    lauf = _lauf(umgebung)
    assert lauf.returncode == 0, _log(umgebung)

    assert f"IMAGE_TAG=develop-{BRANCH_SHA[:7]}" in _log(umgebung)
    # Und die Pfadsuche von damals kommt nicht vor.
    assert "log --" not in _aufrufe(umgebung)


def test_tag_wird_an_compose_uebergeben(umgebung: dict[str, object]) -> None:
    """Der Pull laeuft mit dem gepinnten Tag, nicht mit dem gleitenden.

    Geprueft an der Log-Zeile, die den Tag beim Pull nennt: die Attrappe
    sieht die Umgebungsvariable nicht, wohl aber das Skript.
    """
    _env_schreiben(umgebung)
    lauf = _lauf(umgebung)
    assert lauf.returncode == 0

    protokoll = _aufrufe(umgebung)
    assert "compose" in protokoll and "pull api web" in protokoll
    assert f"pull api web (IMAGE_TAG=develop-{BRANCH_SHA[:7]})" in _log(umgebung)


def test_abschlusszeile_nennt_commit_tag_und_digests(umgebung: dict[str, object]) -> None:
    """Die Zeile, die bei „seit wann laeuft was" gelesen wird.

    Vorher stand der Commit im Log und der Digest in ``docker images``, und
    niemand hielt sie gegeneinander — „der Server laeuft auf develop" war
    eine Behauptung (§5.68).
    """
    _env_schreiben(umgebung)
    _lauf(umgebung)

    log = _log(umgebung)
    assert f"HEAD={BRANCH_SHA}" in log
    assert f"IMAGE_TAG=develop-{BRANCH_SHA[:7]}" in log
    assert "api=sha256:" in log
    assert "web=sha256:" in log


# ---------------------------------------------------------------------------
# 2. PIN_SHA gewinnt
# ---------------------------------------------------------------------------


def test_pin_gewinnt_gegen_den_branch_kopf(umgebung: dict[str, object]) -> None:
    """**Der Rueckfallpunkt.** Gesetzter Pin -> dieser Commit, dieses Image.

    Working-Tree **und** Image: darin stecken Compose-Datei, Caddyfiles,
    ChirpStack-TOMLs und Mosquitto-Config. Ein Rueckfall, der nur das Image
    zurueckdreht, kombiniert alte Container mit neuer Compose-Datei.
    """
    _env_schreiben(umgebung, pin=PIN_SHA)
    lauf = _lauf(umgebung)
    assert lauf.returncode == 0, _log(umgebung)

    log = _log(umgebung)
    assert f"IMAGE_TAG=develop-{PIN_SHA[:7]}" in log
    assert f"develop-{BRANCH_SHA[:7]}" not in log, "der Branch-Kopf darf nicht gewinnen"
    assert "Automatik aus" in log
    # Losgelöster HEAD, kein `reset --hard` auf den Branch.
    protokoll = _aufrufe(umgebung)
    assert "checkout --quiet --detach" in protokoll
    assert "reset --hard" not in protokoll


def test_pin_ueberlebt_einen_zweiten_lauf(umgebung: dict[str, object]) -> None:
    """**Die eigentliche Zusicherung.** Der Timer darf den Pin nicht loeschen.

    Ein Rueckfall, der nach fuenf Minuten weg ist, ist kein Rueckfall. Der
    zweite Lauf laeuft mit demselben Stand wie der erste — das Skript setzt
    dabei ``GIT_HEAD_SHA`` nicht fort, deshalb wird hier ausdruecklich der
    Zustand „HEAD steht schon auf dem Pin" gefahren.
    """
    _env_schreiben(umgebung, pin=PIN_SHA)
    assert _lauf(umgebung).returncode == 0
    zweiter = _lauf(umgebung, GIT_HEAD_SHA=PIN_SHA)
    assert zweiter.returncode == 0

    # Gezaehlt werden **Laeufe**, nicht Vorkommen: der Tag steht pro Lauf in
    # vier Zeilen (Ansage, Pull, Abschluss, Ping). Die Ansage-Zeile ist die
    # eindeutige — sie beginnt direkt nach dem Zeitstempel mit ``IMAGE_TAG=``.
    log = _log(umgebung)
    ansagen = [z for z in log.splitlines() if z.split("] ", 1)[-1].startswith("IMAGE_TAG=")]
    assert len(ansagen) == 2, ansagen
    assert all(f"develop-{PIN_SHA[:7]}" in z for z in ansagen), ansagen
    assert "Working-Tree bereits auf" in log


def test_env_wird_nicht_geschrieben(umgebung: dict[str, object]) -> None:
    """**T5.** Das Skript faesst die ``.env`` nicht an.

    Sonst waere der Pin nach fuenf Minuten ueberschrieben — und damit ein
    Rueckfall, der sich selbst aufhebt.
    """
    _env_schreiben(umgebung, pin=PIN_SHA)
    pfad = umgebung["envdatei"]
    assert isinstance(pfad, Path)
    vorher = pfad.read_text(encoding="utf-8")

    _lauf(umgebung)

    assert pfad.read_text(encoding="utf-8") == vorher


def test_pin_geleert_holt_den_branch_zurueck(umgebung: dict[str, object]) -> None:
    """Gegenprobe: ohne Pin folgt der Server wieder dem Branch.

    Ohne diesen Test waere auch ein Skript gruen, das den Pin niemals
    loslaesst — und dann waere jeder Rueckfall endgueltig.
    """
    _env_schreiben(umgebung, pin=PIN_SHA)
    assert _lauf(umgebung).returncode == 0
    _env_schreiben(umgebung, pin=None)
    assert _lauf(umgebung).returncode == 0

    log = _log(umgebung)
    assert f"IMAGE_TAG=develop-{PIN_SHA[:7]}" in log
    assert f"IMAGE_TAG=develop-{BRANCH_SHA[:7]}" in log


def test_unbekannter_pin_bricht_ab(umgebung: dict[str, object]) -> None:
    """**Die wichtigste Fehlerrichtung.** Tippfehler im Pin -> Abbruch.

    Ein Rueckfall auf den Branch waere hier stumm das Gegenteil dessen, was
    jemand wollte, der gerade zurueckrollt: der Server zoege den neuesten
    Stand. Lieber ein Deploy, der steht und es sagt.
    """
    _env_schreiben(umgebung, pin="tippfehler123")
    lauf = _lauf(umgebung, GIT_PIN_BEKANNT="nein")

    assert lauf.returncode == 1
    log = _log(umgebung)
    assert "ABBRUCH" in log
    assert "kein Commit" in log
    # Kein Container angefasst, kein Image gezogen.
    protokoll = _aufrufe(umgebung)
    assert "pull api web" not in protokoll
    assert "up -d" not in protokoll
    # Und der Monitor erfaehrt den Grund, sonst schlaegt er nur stumm an.
    assert "curl" in protokoll


def test_ziel_ohne_pin_logik_bricht_ab(umgebung: dict[str, object]) -> None:
    """Der Pin-Waechter: ein Ziel-Commit, dessen Skript den Pin nicht kennt.

    **Die lautlose Fehlerrichtung**, und damit die gefaehrlichere als der
    Tippfehler darueber. Der Timer startet das Skript aus dem Working-Tree,
    und der Working-Tree geht beim Pin mit zurueck. Zeigt der Pin auf einen
    Commit vor der Pin-Logik, laeuft beim naechsten Tick das alte Skript,
    ignoriert ``PIN_SHA`` und synct auf den Branch-Kopf — der Rueckfall hebt
    sich nach fuenf Minuten selbst auf.

    Der Lauf von Hand haette vorher korrekt gemeldet, die Pruefung nach
    RUNBOOK §10u Schritt 5 waere gruen gewesen. Genau deshalb muss der
    Abbruch **vor** dem Rueckfall kommen und nicht in die Doku allein.
    """
    _env_schreiben(umgebung, pin="30b6ffe")
    lauf = _lauf(umgebung, GIT_ZIEL_PINFAEHIG="nein")

    assert lauf.returncode == 1
    log = _log(umgebung)
    assert "ABBRUCH" in log
    assert "ohne Pin-Logik" in log
    # Der Hinweis muss sagen, was zu tun ist — der Lauf passiert unter Druck.
    assert "§10u" in log
    # Kein Rueckfall, kein halber Zustand: nicht ausgecheckt, nichts gezogen.
    protokoll = _aufrufe(umgebung)
    assert "checkout" not in protokoll
    assert "pull api web" not in protokoll
    assert "up -d" not in protokoll
    assert "curl" in protokoll


def test_migration_ohne_vorcheck_im_ziel_bricht_ab(umgebung: dict[str, object]) -> None:
    """Migrationen dazwischen + Ziel-Image ohne Revisions-Vorcheck -> Abbruch.

    Der alte Container fuehrt beim Start ``alembic upgrade head`` aus und
    findet in ``alembic_version`` eine Revision, die sein
    ``versions/``-Verzeichnis nicht kennt. Alembic bricht ab, der
    Entrypoint nach fuenf Versuchen auch — und weil api, celery_worker und
    celery_beat dasselbe Image mit demselben Entrypoint fahren und
    ``restart: always`` gilt, kreist der Stack ohne API und ohne Engine.

    Das passiert **unabhaengig von der Additivitaet** der Migration:
    Alembic scheitert an seiner Buchfuehrung, bevor eine Zeile Schema
    geprueft wird.
    """
    _env_schreiben(umgebung, pin="85125ae")
    lauf = _lauf(umgebung, GIT_MIGRATIONEN="ja", GIT_ZIEL_VORCHECK="nein")

    assert lauf.returncode == 1
    log = _log(umgebung)
    assert "ABBRUCH" in log
    assert "Revisions-Vorcheck" in log
    assert "Neustart-Schleife" in log
    assert "§10u" in log
    protokoll = _aufrufe(umgebung)
    assert "checkout" not in protokoll
    assert "up -d" not in protokoll
    assert "curl" in protokoll


def test_migration_mit_vorcheck_im_ziel_laeuft(umgebung: dict[str, object]) -> None:
    """Dieselbe Lage, aber das Ziel-Image kann es: der Rueckfall laeuft.

    Die Gegenprobe zum Test darueber — ohne sie wuesste niemand, ob der
    Waechter unterscheidet oder nur verbietet.
    """
    _env_schreiben(umgebung, pin=PIN_SHA)
    lauf = _lauf(umgebung, GIT_MIGRATIONEN="ja")

    assert lauf.returncode == 0
    log = _log(umgebung)
    assert "ABBRUCH" not in log
    assert f"PIN_SHA gesetzt: {PIN_SHA}" in log
    assert "up -d" in _aufrufe(umgebung)


def test_ohne_migrationen_fragt_niemand_nach_dem_vorcheck(
    umgebung: dict[str, object],
) -> None:
    """Kein Migrations-Risiko, keine zusaetzliche Huerde.

    Liegt zwischen Ziel und laufendem Stand keine Migration, steht die DB
    schon auf dem Kopf, den das Ziel-Image kennt — ``upgrade head`` ist
    dann ein No-Op. Ein Ziel ohne Vorcheck ist in diesem Fall
    unproblematisch, und ein Waechter, der ihn trotzdem verlangt, wuerde
    den Rueckfall in genau dem Fall verbieten, fuer den er gebaut ist.
    """
    _env_schreiben(umgebung, pin=PIN_SHA)
    lauf = _lauf(umgebung, GIT_ZIEL_VORCHECK="nein")

    assert lauf.returncode == 0
    assert "ABBRUCH" not in _log(umgebung)
    assert "up -d" in _aufrufe(umgebung)


# ---------------------------------------------------------------------------
# 3. Fehlender Tag (T3)
# ---------------------------------------------------------------------------


def test_fehlgeschlagener_pull_aendert_keinen_container(
    umgebung: dict[str, object],
) -> None:
    """Abbruch **vor** Phase 3 — kein halber Deploy.

    Der Pull ist gleichzeitig die Existenzpruefung: er aendert keinen
    Container, nur den lokalen Image-Speicher.
    """
    _env_schreiben(umgebung)
    lauf = _lauf(umgebung, DOCKER_PULL_FEHLER="1", DOCKER_MANIFEST="fehlt")

    assert lauf.returncode == 1
    assert "up -d" not in _aufrufe(umgebung)
    assert "abort: pull failed" in _aufrufe(umgebung)


def test_diagnose_unterscheidet_fehlenden_tag_von_registry_ausfall(
    umgebung: dict[str, object],
) -> None:
    """Zwei Ursachen, zwei Reaktionen — und das Log sagt welche.

    Ein **fehlender Tag** heisst, dass ein Build nicht gelaufen ist; eine
    **unerreichbare Registry** ist voruebergehend. Ohne die Unterscheidung
    sucht jemand im falschen System.
    """
    _env_schreiben(umgebung)

    _lauf(umgebung, DOCKER_PULL_FEHLER="1", DOCKER_MANIFEST="fehlt")
    assert "NICHT vorhanden" in _log(umgebung)

    (umgebung["log"]).write_text("", encoding="utf-8")  # type: ignore[union-attr]
    _lauf(umgebung, DOCKER_PULL_FEHLER="1")
    log = _log(umgebung)
    assert ": vorhanden." in log
    assert "war es die Registry" in log


# ---------------------------------------------------------------------------
# 4. Die Sperre bleibt vorn
# ---------------------------------------------------------------------------


def test_sperre_schlaegt_auch_den_pin(umgebung: dict[str, object]) -> None:
    """Phase 0 laeuft **vor** allem Neuen (§0.3).

    Ein Rueckfall mitten in einem Eingangstest waere derselbe Schaden wie
    ein Deploy: der Lauf stirbt in einer Bestaetigungs-Kette und laesst ein
    Geraet mit ausstehendem Downlink zurueck (S4). Der Pin aendert daran
    nichts.
    """
    _env_schreiben(umgebung, pin=PIN_SHA)
    bin_dir = umgebung["bin"]
    assert isinstance(bin_dir, Path)
    _stub(
        bin_dir / "docker",
        'echo "docker $*" >> "' + (umgebung["protokoll"]).as_posix() + '"\n'  # type: ignore[union-attr]
        'case "$*" in\n'
        "  *TTL*) echo 3600 ;;\n"
        "esac\n"
        "exit 0\n",
    )

    lauf = _lauf(umgebung)

    assert lauf.returncode == 0
    log = _log(umgebung)
    assert "UEBERSPRUNGEN" in log
    assert "IMAGE_TAG" not in log
    protokoll = _aufrufe(umgebung)
    assert "fetch" not in protokoll
    assert "pull api web" not in protokoll
