"""Fremde Images haengen an einem Digest, nicht an einem gleitenden Tag.

**Was auf dem Spiel steht.** Ein Tag wie ``chirpstack/chirpstack:4`` oder
``timescale/timescaledb:latest-pg16`` ist unauffaellig, solange das Image
lokal liegt: Compose zieht per Vorgabe ``missing``, also gar nicht. Fehlt es
aber, holt die naechste Neuerstellung, was gerade unter dem Tag liegt. Am
15.11.2026 wurde ``chirpstack`` mitten im Stoerfall neu erstellt; waere das
Image zuvor weggeraeumt gewesen -- am 14.11. wurden 108 Images entfernt --,
haette derselbe Befehl **4.18** gezogen statt 4.17.0. Das ist kein
hypothetischer Fall, sondern ein Beinahe-Treffer.

**Was hier geprueft wird, und was ausdruecklich nicht.** Die Zusicherungen
sind *strukturell*: jedes fremde Image traegt einen Digest, jeder Digest hat
die richtige Form, ueber jedem steht die Klartext-Version, und unsere
eigenen Images tragen **keinen** Digest. Die Digest-Werte selbst stehen
absichtlich **nicht** hier. Eine Kopie waere eine zweite Wahrheit (§5.53):
sie muesste bei jedem Nachziehen mitgepflegt werden, und ein Vergessen
saehe aus wie ein Befund, obwohl nur die Kopie alt ist. Die Datei ist die
Wahrheit; dieser Test sichert ihre Form.

Der eigentliche Regressionsfall, den die Form abdeckt, ist der haeufigste:
jemand fuegt einen Dienst hinzu oder aendert eine Zeile und laesst den
Digest weg. Dann faellt ``test_jedes_fremde_image_traegt_einen_digest``.

**Querverweise:** RUNBOOK 10bg (das Nachzieh-Ritual -- ohne das Ritual ist
Festnageln ein unbemerkter Dauerzustand), H-6 bzw.
``test_deploy_pull_pinning.py`` (unsere eigenen Images, je Commit, ein
anderer Mechanismus), §5.53 (eine Wahrheit).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

REPO_WURZEL = Path(__file__).resolve().parents[2]
COMPOSE = REPO_WURZEL / "infra" / "deploy" / "docker-compose.prod.yml"
RUNBOOK = REPO_WURZEL / "docs" / "RUNBOOK.md"

# Unsere eigenen Images. Sie haengen an ${IMAGE_TAG} und werden von
# deploy-pull.sh je Commit gesetzt (H-6) -- ein Digest hier waere falsch,
# weil er den Tag entwerten wuerde.
EIGENE = "ghcr.io/rexei123/"

DIGEST_MUSTER = re.compile(r"^@sha256:[0-9a-f]{64}$")


@pytest.fixture(scope="module")
def compose_text() -> str:
    return COMPOSE.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def dienste(compose_text: str) -> dict[str, dict]:
    daten = yaml.safe_load(compose_text)
    return daten["services"]


def _image_zeilen(text: str) -> list[tuple[int, str]]:
    """Alle ``image:``-Zeilen mit ihrer Zeilennummer, 1-basiert."""
    gefunden = []
    for nr, zeile in enumerate(text.splitlines(), start=1):
        if zeile.strip().startswith("image:"):
            gefunden.append((nr, zeile.strip()[len("image:") :].strip()))
    return gefunden


def _fremde(text: str) -> list[tuple[int, str]]:
    return [(nr, bild) for nr, bild in _image_zeilen(text) if not bild.startswith(EIGENE)]


def test_die_datei_ist_gueltiges_yaml_und_jeder_dienst_hat_ein_image(
    dienste: dict[str, dict],
) -> None:
    """Die Grundbedingung: das Festnageln darf die Datei nicht zerlegen."""
    assert dienste, "keine Dienste gelesen -- die Datei ist kaputt"
    ohne = sorted(name for name, d in dienste.items() if not d.get("image"))
    assert not ohne, f"Dienste ohne image: {ohne}"


def test_jedes_fremde_image_traegt_einen_digest(compose_text: str) -> None:
    """Der Kern. Ein fremdes Image ohne Digest ist ein gleitender Tag."""
    ohne_digest = [(nr, bild) for nr, bild in _fremde(compose_text) if "@sha256:" not in bild]
    assert not ohne_digest, "fremdes Image ohne Digest (gleitender Tag) in Zeile(n): " + ", ".join(
        f"{nr}: {bild}" for nr, bild in ohne_digest
    )


def test_jeder_digest_hat_die_richtige_form(compose_text: str) -> None:
    """Ein abgeschnittener oder vertippter Digest laesst sich nicht ziehen.

    Ein Digest mit 63 Zeichen oder einem Grossbuchstaben ist kein
    ``docker pull``-Fehler erst am Server -- er ist hier schon falsch.
    """
    falsch = []
    for nr, bild in _fremde(compose_text):
        if "@" not in bild:
            continue
        _, rest = bild.split("@", 1)
        if not DIGEST_MUSTER.match("@" + rest):
            falsch.append((nr, bild))
    assert not falsch, "Digest in falscher Form: " + ", ".join(
        f"{nr}: {bild}" for nr, bild in falsch
    )


def test_der_tag_bleibt_vor_dem_digest_stehen(compose_text: str) -> None:
    """Tag **plus** Digest, nicht Digest allein.

    ``chirpstack/chirpstack@sha256:72ca…`` waere technisch gleichwertig und
    fuer einen Menschen unlesbar. Der Tag ist das, was man beim Ueberfliegen
    erkennt; der Digest entscheidet.
    """
    ohne_tag = []
    for nr, bild in _fremde(compose_text):
        name = bild.split("@", 1)[0]
        if ":" not in name.rsplit("/", 1)[-1]:
            ohne_tag.append((nr, bild))
    assert not ohne_tag, "Digest ohne lesbaren Tag: " + ", ".join(
        f"{nr}: {bild}" for nr, bild in ohne_tag
    )


def test_unsere_eigenen_images_tragen_keinen_digest(compose_text: str) -> None:
    """Sonst waere ``IMAGE_TAG`` entwertet und ein Rueckfall unmoeglich.

    deploy-pull.sh setzt den Tag je Commit (H-6). Ein fester Digest daneben
    wuerde genau den Mechanismus aushebeln, der den Rueckfallpunkt schafft.
    """
    mit_digest = [
        (nr, bild)
        for nr, bild in _image_zeilen(compose_text)
        if bild.startswith(EIGENE) and "@sha256:" in bild
    ]
    assert not mit_digest, (
        "eigenes Image mit festem Digest -- das entwertet IMAGE_TAG: "
        + ", ".join(f"{nr}: {bild}" for nr, bild in mit_digest)
    )


def test_ueber_jedem_digest_steht_die_klartext_version(compose_text: str) -> None:
    """Ein Digest allein sagt keinem Menschen, welche Version laeuft.

    Ohne die Kommentarzeile muesste man zum Nachsehen in die Registry --
    genau in dem Moment, in dem man wissen will, ob der eingefrorene Stand
    noch tragbar ist.
    """
    zeilen = compose_text.splitlines()
    ohne_kommentar = []
    for nr, bild in _fremde(compose_text):
        if "@sha256:" not in bild:
            continue
        vorige = zeilen[nr - 2].strip() if nr >= 2 else ""
        if not vorige.startswith("#") or not re.search(r"\d+\.\d+", vorige):
            ohne_kommentar.append((nr, bild.split("@", 1)[0]))
    assert not ohne_kommentar, "Digest ohne Klartext-Version darueber: " + ", ".join(
        f"{nr}: {bild}" for nr, bild in ohne_kommentar
    )


def test_der_dateikopf_nennt_den_preis_und_das_ritual(compose_text: str) -> None:
    """Wer die Datei oeffnet, muss den Haken sehen, nicht nur die Digests.

    Festnageln heisst: Sicherheitspatches kommen nicht mehr von selbst mit.
    Steht das nicht dort, wo die Digests stehen, ist der eingefrorene Stand
    in einem Jahr ein unbemerkter Dauerzustand (§5.77).
    """
    kopf = compose_text.split("services:", 1)[0]
    assert "10bg" in kopf, "der Kopf verweist nicht auf das Nachzieh-Ritual"
    assert "Sicherheitspatches" in kopf, "der Kopf nennt den Preis nicht"


def test_das_ritual_steht_im_runbook_und_nennt_einen_takt() -> None:
    """Der Verweis aus der Compose-Datei darf nicht ins Leere zeigen.

    Ein haengender Verweis ist mir am 15.11. schon einmal passiert (§10bb
    wurde in einem Statusbericht genannt, bevor der Abschnitt existierte).

    Geprueft wird nicht das Wort „Quartal" -- das stand im ersten Entwurf
    zweimal im Abschnitt, und eine Mutationsprobe blieb deshalb gruen. Ein
    Takt ist erst dann einer, wenn er **Termine** nennt. Deshalb die vier
    Monate: ohne sie driftet „quartalsweise" zu „irgendwann".
    """
    runbook = RUNBOOK.read_text(encoding="utf-8")
    assert "## 10bg." in runbook, "RUNBOOK-Abschnitt 10bg fehlt"
    abschnitt = runbook.split("## 10bg.", 1)[1].split("\n## ", 1)[0]

    # Die Anlaesse muessen im Anlass-Block stehen, nicht irgendwo im
    # Abschnitt. Zwei Mutationsproben blieben gruen, weil „CVE" weiter
    # unten noch einmal vorkommt -- eine Zusicherung auf die ganze Datei
    # ist keine Zusicherung auf die Stelle (§5.88, dieselbe Familie).
    anlass = abschnitt.split("**Anlass", 1)[1].split("### ", 1)[0]
    monate = [m for m in ("Januar", "April", "Juli", "Oktober") if m in anlass]
    assert len(monate) == 4, (
        f"der Anlass-Block nennt keine Termine, nur einen Takt -- gefunden: {monate}"
    )
    assert "CVE" in anlass, "der Anlass-Block nennt den zweiten Anlass nicht"

    # Der Verweis auf die Gateway-Pruefliste gehoert in den Ausroll-Schritt.
    # Dass die Nummer irgendwo im Abschnitt faellt, hilft niemandem, der
    # gerade den Merge gemacht hat.
    ausrollen = abschnitt.split("### Schritt 4", 1)
    assert len(ausrollen) == 2, "Schritt 4 (ausrollen) fehlt"
    assert "10ay" in ausrollen[1].split("**Querverweise", 1)[0], (
        "der Ausroll-Schritt verweist nicht auf die Pruefliste nach einer "
        "Neuerstellung -- genau daran haengt die Gateway-Gefahr"
    )
