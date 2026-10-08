"""H-6 T1: baut der Workflow, wenn er bauen muss — und haengt er sonst um?

**Warum dieser Test am echten Workflow arbeitet.** Er liest die
``run``-Zeilen des Entscheidungs-Schritts aus
``.github/workflows/build-images.yml`` und fuehrt sie gegen kuenstliche
Git-Baeume aus. Ein nachgebautes Skript im Test wuerde nur sich selbst
pruefen (§5.82) — und genau diese Entscheidung traegt die gefaehrliche
Fehlerrichtung des ganzen Sprints:

* **Falsch „geaendert"** -> es wird gebaut. Harmlos, nur das alte Verhalten.
* **Falsch „unveraendert"** -> es wird **umgehaengt**, und der Server zieht
  ein veraltetes Image unter einem Tag, der einen neuen Commit behauptet.
  Nichts wird rot, nichts faellt auf.

Der Workflow vergleicht deshalb **Tree-Hashes** und keine Dateinamen: ein
Baum ist entweder gleich oder nicht, ein Regex auf Pfaden kann sich irren.
Diese Tests halten beides fest — dass der Vergleich wirkt, und dass er in
der sicheren Richtung irrt, wenn etwas fehlt.

Kein Docker, kein GHCR, keine Datenbank. Nur ``git`` in einem Temp-Verzeichnis.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

WORKFLOW = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "build-images.yml"


def _finde_bash() -> str | None:
    r"""Eine ``bash``, die wirklich laeuft — mit Probe statt mit ``which``.

    Unter Windows findet ``shutil.which("bash")`` zuerst
    ``C:\Windows\System32\bash.exe`` — den **WSL-Starter**. Der
    versucht eine Distribution zu starten, laeuft in einen
    Netzwerk-Timeout und gibt eine UTF-16-Meldung aus. Im Test sah das aus
    wie ein Skript-Fehler und kostete einen Lauf von fuenf Minuten.

    Deshalb wird jeder Kandidat **ausprobiert**, nicht nur gefunden. Auf
    Ubuntu trifft der erste Kandidat, auf dem Arbeitsrechner Git Bash.
    """
    kandidaten = [
        "/usr/bin/bash",
        "/bin/bash",
        r"C:\Program Files\Gitinash.exe",
        r"C:\Program Files (x86)\Gitinash.exe",
        shutil.which("bash") or "",
    ]
    for k in kandidaten:
        if not k or not Path(k).exists():
            continue
        try:
            probe = subprocess.run(
                [k, "-c", "echo ok"],
                capture_output=True,
                text=True,
                timeout=15,
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        if probe.returncode == 0 and probe.stdout.strip() == "ok":
            return k
    return None


BASH = _finde_bash()

pytestmark = pytest.mark.skipif(
    BASH is None or shutil.which("git") is None,
    reason="braucht eine lauffaehige bash und git",
)


def _entscheidungs_skript() -> str:
    """Die ``run``-Zeilen des Entscheidungs-Schritts, aus dem Workflow gelesen.

    Gesucht wird nach der Schritt-``id``, nicht nach dem Namen: der Name ist
    deutscher Prosatext und wuerde sich bei einer Umformulierung aendern,
    ohne dass sich etwas an der Sache aendert.
    """
    daten = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    schritte = daten["jobs"]["was-hat-sich-geaendert"]["steps"]
    treffer = [s for s in schritte if s.get("id") == "baeume"]
    assert len(treffer) == 1, (
        "Der Schritt mit id=baeume fehlt oder ist mehrfach vorhanden. "
        "Dieser Test liest die Entscheidung aus dem Workflow — wer sie "
        "umbaut, zieht ihn mit."
    )
    return treffer[0]["run"]


def _git(verzeichnis: Path, *args: str) -> str:
    ergebnis = subprocess.run(
        ["git", *args],
        cwd=verzeichnis,
        capture_output=True,
        text=True,
        check=True,
    )
    return ergebnis.stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """Ein Repo mit ``backend/``, ``frontend/`` und dem Workflow."""
    r = tmp_path / "repo"
    r.mkdir()
    _git(r, "init", "--quiet", "--initial-branch=develop")
    _git(r, "config", "user.email", "test@local")
    _git(r, "config", "user.name", "Test")
    _git(r, "config", "commit.gpgsign", "false")

    for vz in ("backend", "frontend"):
        (r / vz / "src").mkdir(parents=True)
        (r / vz / "src" / "a.txt").write_text("eins\n", encoding="utf-8")
    (r / ".github" / "workflows").mkdir(parents=True)
    # Inhalt egal — verglichen wird nur, OB sich die Datei geaendert hat.
    (r / ".github" / "workflows" / "build-images.yml").write_text("x\n", encoding="utf-8")
    (r / "STATUS.md").write_text("stand\n", encoding="utf-8")
    (r / "docs").mkdir()
    (r / "docs" / "brief.md").write_text("text\n", encoding="utf-8")

    _git(r, "add", "-A")
    _git(r, "commit", "--quiet", "-m", "erster")
    return r


def _entscheide(repo: Path) -> dict[str, str]:
    """Das Workflow-Skript gegen ``HEAD`` ausfuehren und die Ausgaben lesen."""
    ausgabe = repo / "github_output"
    ausgabe.write_text("", encoding="utf-8")
    skript = repo / "entscheidung.sh"
    skript.write_text(_entscheidungs_skript(), encoding="utf-8", newline="\n")

    # ``GITHUB_OUTPUT`` wird **in bash** gesetzt, nicht ueber ``env=``.
    #
    # Zwei Umwege haben nicht funktioniert und sind den Kommentar wert, weil
    # beide Fehlermeldungen in die Irre fuehren:
    #
    # 1. ``env={"PATH": ...}`` allein — unter Windows startet der Prozess
    #    ohne ``SystemRoot`` nicht, und die Meldung kommt als UTF-16-Text
    #    aus einer Systemschicht. Sieht wie ein Skript-Fehler aus.
    # 2. ``env=dict(os.environ) | {"GITHUB_OUTPUT": ...}`` — Git Bash unter
    #    Windows liefert eine so hinzugefuegte Variable nicht durch. Das
    #    Skript meldet dann ``GITHUB_OUTPUT: unbound variable`` (wegen
    #    ``set -u``), also so, als fehlte die Zeile im Workflow.
    #
    # Der Mantel setzt sie und liest den Workflow-Text mit ``.`` ein. Damit
    # bleibt der gepruefte Text unveraendert — er wird nicht nachgebaut
    # (§5.82), nur anders aufgerufen.
    mantel = repo / "mantel.sh"
    mantel.write_text(
        "export GITHUB_OUTPUT=github_output\n. ./entscheidung.sh\n",
        encoding="utf-8",
        newline="\n",
    )

    lauf = subprocess.run(
        [BASH or "bash", "mantel.sh"],
        cwd=repo,
        capture_output=True,
        text=True,
    )
    assert lauf.returncode == 0, f"stdout:\n{lauf.stdout}\nstderr:\n{lauf.stderr}"

    werte: dict[str, str] = {}
    for zeile in ausgabe.read_text(encoding="utf-8").splitlines():
        if "=" in zeile:
            k, _, v = zeile.partition("=")
            werte[k] = v
    werte["_log"] = lauf.stdout
    return werte


def _commit(repo: Path, nachricht: str) -> None:
    _git(repo, "add", "-A")
    _git(repo, "commit", "--quiet", "-m", nachricht)


# ---------------------------------------------------------------------------
# 1. Der Fall, um den es geht
# ---------------------------------------------------------------------------


def test_nur_doku_geaendert_haengt_beide_um(repo: Path) -> None:
    """**Der Zweck von Weg C.** Ein Doku-Commit baut nichts.

    Genau der Fall, der heute keinen Tag bekommt (``d7e54fd``, PR #261:
    nur ``STATUS.md``) — und der mit Pinning den Deploy stehen liesse.
    """
    (repo / "STATUS.md").write_text("neuer stand\n", encoding="utf-8")
    (repo / "docs" / "brief.md").write_text("mehr text\n", encoding="utf-8")
    _commit(repo, "nur Doku")

    e = _entscheide(repo)
    assert e["backend"] == "false"
    assert e["frontend"] == "false"
    assert e["vorgaenger"]


def test_backend_geaendert_baut_nur_api(repo: Path) -> None:
    """Die Entscheidung faellt **je Image**.

    Das ist der Gewinn gegenueber dem alten ``paths``-Filter: der stand auf
    Workflow-Ebene, ein Backend-Commit baute also das Web-Image mit. Beleg
    aus dem echten Verlauf: ``935facc`` (PR #276, nur Frontend) hat vorher
    beide Images gebaut.
    """
    (repo / "backend" / "src" / "a.txt").write_text("zwei\n", encoding="utf-8")
    _commit(repo, "backend")

    e = _entscheide(repo)
    assert e["backend"] == "true"
    assert e["frontend"] == "false"


def test_frontend_geaendert_baut_nur_web(repo: Path) -> None:
    (repo / "frontend" / "src" / "a.txt").write_text("zwei\n", encoding="utf-8")
    _commit(repo, "frontend")

    e = _entscheide(repo)
    assert e["backend"] == "false"
    assert e["frontend"] == "true"


def test_beide_geaendert_baut_beide(repo: Path) -> None:
    (repo / "backend" / "src" / "a.txt").write_text("zwei\n", encoding="utf-8")
    (repo / "frontend" / "src" / "a.txt").write_text("zwei\n", encoding="utf-8")
    _commit(repo, "beide")

    e = _entscheide(repo)
    assert e["backend"] == "true"
    assert e["frontend"] == "true"


# ---------------------------------------------------------------------------
# 2. Wo ein Pfad-Regex sich geirrt haette
# ---------------------------------------------------------------------------


def test_tiefe_aenderung_wird_erkannt(repo: Path) -> None:
    """Eine neue Datei tief im Baum zaehlt.

    Der Tree-Hash des Wurzelverzeichnisses aendert sich bei jeder Aenderung
    darunter, egal wie tief. Ein Regex muesste das Muster richtig haben.
    """
    tief = repo / "backend" / "src" / "heizung" / "services"
    tief.mkdir(parents=True)
    (tief / "neu.py").write_text("pass\n", encoding="utf-8")
    _commit(repo, "tief")

    e = _entscheide(repo)
    assert e["backend"] == "true"


def test_umbenennung_wird_erkannt(repo: Path) -> None:
    """Eine Umbenennung innerhalb von ``backend/`` aendert den Baum.

    Der Inhalt der Dateien ist danach derselbe, die Namen nicht — und das
    Image aendert sich, weil der Build den Baum kopiert.
    """
    _git(repo, "mv", "backend/src/a.txt", "backend/src/b.txt")
    _commit(repo, "umbenannt")

    e = _entscheide(repo)
    assert e["backend"] == "true"


def test_gleichnamiges_verzeichnis_woanders_zaehlt_nicht(repo: Path) -> None:
    """``docs/backend/`` ist nicht ``backend/``.

    Der Tree-Vergleich sieht nur den Baum an der Wurzel; ein Regex ohne
    ``^``-Anker haette hier gebaut.
    """
    (repo / "docs" / "backend").mkdir()
    (repo / "docs" / "backend" / "notiz.md").write_text("text\n", encoding="utf-8")
    _commit(repo, "doku ueber backend")

    e = _entscheide(repo)
    assert e["backend"] == "false"
    assert e["frontend"] == "false"


def test_inhaltsgleiche_aenderung_haengt_um(repo: Path) -> None:
    """**Der Vorteil gegenueber dem Dateinamen-Vergleich.**

    Eine Datei wird geaendert und im selben Commit zurueckgeaendert — der
    Baum ist am Ende identisch, das Image waere bitgleich. Ein
    ``git diff --name-only`` ueber zwei Commits haette hier auch nichts
    gemeldet; der Fall ist aber derjenige, an dem man sieht, dass der
    Vergleich ueber **Inhalt** geht und nicht ueber Aktivitaet.
    """
    (repo / "backend" / "src" / "a.txt").write_text("zwischenstand\n", encoding="utf-8")
    _commit(repo, "aenderung")
    (repo / "backend" / "src" / "a.txt").write_text("zwischenstand\n", encoding="utf-8")
    (repo / "STATUS.md").write_text("notiz\n", encoding="utf-8")
    _commit(repo, "nur Doku, backend-Baum unveraendert")

    e = _entscheide(repo)
    assert e["backend"] == "false"


# ---------------------------------------------------------------------------
# 3. Die sichere Fehlerrichtung
# ---------------------------------------------------------------------------


def test_workflow_aenderung_baut_immer_beide(repo: Path) -> None:
    """Die Datei steht nicht im Build-Kontext, bestimmt aber, wie gebaut wird."""
    (repo / ".github" / "workflows" / "build-images.yml").write_text("y\n", encoding="utf-8")
    _commit(repo, "workflow")

    e = _entscheide(repo)
    assert e["backend"] == "true"
    assert e["frontend"] == "true"
    assert "build-images.yml geaendert" in e["_log"]


def test_fehlendes_verzeichnis_baut(repo: Path) -> None:
    """Verschwindet ``frontend/``, wird gebaut — nicht umgehaengt.

    ``git rev-parse`` liefert fuer einen fehlenden Pfad nichts; das Skript
    setzt dann einen Platzhalter, der sich vom Baum des Vorgaengers
    unterscheidet. Die Entscheidung faellt damit in die sichere Richtung.
    """
    shutil.rmtree(repo / "frontend")
    _commit(repo, "frontend weg")

    e = _entscheide(repo)
    assert e["frontend"] == "true"


def test_ohne_vorgaenger_wird_gebaut(repo: Path, tmp_path: Path) -> None:
    """**Der Bootstrap-Fall, und er ist der gefaehrlichste.**

    Ohne Vorgaenger gibt es kein Tag zum Umhaengen. Ein leeres
    ``vorgaenger`` wuerde den Re-Tag-Schritt eine Quelle namens
    ``<branch>-`` suchen lassen — der Schritt faengt das zwar ab, aber die
    Entscheidung muss hier schon richtig sein.
    """
    leer = tmp_path / "leer"
    leer.mkdir()
    _git(leer, "init", "--quiet", "--initial-branch=develop")
    _git(leer, "config", "user.email", "test@local")
    _git(leer, "config", "user.name", "Test")
    _git(leer, "config", "commit.gpgsign", "false")
    (leer / "backend").mkdir()
    (leer / "backend" / "a.txt").write_text("eins\n", encoding="utf-8")
    _git(leer, "add", "-A")
    _git(leer, "commit", "--quiet", "-m", "erster")

    e = _entscheide(leer)
    assert e["backend"] == "true"
    assert e["frontend"] == "true"
    assert e["vorgaenger"] == ""
    assert "Kein Vorgaenger" in e["_log"]


# ---------------------------------------------------------------------------
# 4. Der Workflow selbst
# ---------------------------------------------------------------------------


def test_kein_paths_filter_mehr() -> None:
    """``paths`` darf nicht zurueckkommen.

    Mit einem Filter bekommt ein Commit, der ihn nicht trifft, **gar keinen**
    Lauf — und damit keinen Tag. Dann ist die Invariante „jeder Commit hat
    ein Image" gebrochen, auf der das Pinning aufsitzt, und der Deploy
    bleibt stehen.

    Der Test prueft eine **Abwesenheit**; ein Verhaltens-Test koennte das
    nicht, weil der Filter vor dem Lauf greift (§5.55 ist die
    Schwester-Lesson: ein gruener Lauf, der nicht stattgefunden hat).
    """
    daten = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    # ``on`` ist in YAML 1.1 ein Boolean-Schluessel — ``yaml.safe_load``
    # liefert deshalb ``True`` und nicht ``"on"``.
    ausloeser = daten.get("on") or daten[True]
    assert "paths" not in ausloeser["push"], (
        "paths-Filter in build-images.yml. Mit ihm bekommt ein Commit ohne "
        "Treffer keinen Tag, und das Pinning aus AE-77 bricht."
    )
    assert "paths-ignore" not in ausloeser["push"]


def test_builds_reihen_sich_ein() -> None:
    """``cancel-in-progress`` muss aus sein.

    Ein abgebrochener Lauf hinterlaesst einen Commit ohne Tag. Der
    Re-Tag-Schritt des naechsten Commits findet seine Quelle dann nicht und
    baut — also genau das, was Weg C vermeiden soll. Entscheidung des
    Hoteliers vom 08.10.2026.
    """
    daten = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    assert daten["concurrency"]["cancel-in-progress"] is False


def test_beide_jobs_haengen_an_der_entscheidung() -> None:
    """Ohne ``needs`` liefe ein Job los, bevor die Entscheidung da ist."""
    daten = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    for job in ("build-api", "build-web"):
        assert daten["jobs"][job]["needs"] == "was-hat-sich-geaendert", job


def test_checkout_holt_den_vorgaenger() -> None:
    """``fetch-depth: 2`` — der Default 1 hat keinen Parent.

    Ohne diese Zeile faellt die Entscheidung immer auf „kein Vorgaenger"
    und es wird immer gebaut. Das waere nicht gefaehrlich, aber Weg C waere
    wirkungslos — und zwar ohne dass etwas rot wird.
    """
    daten = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    schritte = daten["jobs"]["was-hat-sich-geaendert"]["steps"]
    checkout = [s for s in schritte if str(s.get("uses", "")).startswith("actions/checkout")]
    assert len(checkout) == 1
    assert checkout[0]["with"]["fetch-depth"] == 2
