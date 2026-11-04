"""Befund 1 vom 04.11.2026 — `ENV_NEU` darf die Werte nicht zerstören.

Geprüft wird das **echte** Skript, nicht ein Nachbau (§5.82): der Test legt
ein Wegwerf-Repo mit einer Wegwerf-``.env`` an, sourct
``infra/deploy/env-neu.sh`` darauf und liest, was in der Umgebung landet.
Dieselbe Hülle wie ``test_deploy_pull_pinning.py``.

**Was auf dem Spiel steht.** Am 04.11.2026 hat die alte Fassung — eine
Zeile ``set -a; . .env; set +a`` in der Anleitung — Caddy von 06:59 bis
07:04 in einen Crashloop geschickt. Der bcrypt-Hash steht in der ``.env``
mit verdoppelten Dollarzeichen, weil compose die Verdopplung auflöst; die
**Shell** löst sie zur Prozessnummer auf. Danach trug die Sitzung eine
Zahl, und compose nimmt die Umgebung **vor** der Datei. Die Datei war
richtig, die Umgebung zerstört, und die Prüfung davor las die Datei.

Die Zusicherungen hier, in der Reihenfolge ihrer Wichtigkeit:

* **Ein Wert mit Dollarzeichen landet nicht in der Umgebung.** Das ist der
  Fehler vom 04.11., und es ist die einzige richtige Antwort: compose
  löst die Verdopplung auf, die Umgebung kann den Wert nur falsch tragen.
* **Eine schon vergiftete Sitzung wird geputzt.** Wer vorher von Hand
  ``set -a; . ./.env`` getippt hat, trägt den zerstörten Wert bereits.
  ``ENV_NEU`` muss ihn entfernen, nicht stehen lassen — sonst heilt der
  Helfer den Schaden nicht, den er früher selbst angerichtet hat.
* **Nichts in der ``.env`` wird ausgeführt.** ``. .env`` führt ``$(…)``
  und Backticks in Werten aus. Gelesen wird, nicht interpretiert.
* **Die harmlosen Werte kommen unverändert an**, sonst wäre der Fix eine
  neue Fehlerquelle: ``POSTGRES_USER`` und ``POSTGRES_DB`` hängen 30
  Abfragen im RUNBOOK daran.
* **Die Namen der zurückgehaltenen Werte werden genannt, die Werte nicht.**
  Wer nicht sieht, dass etwas fehlt, sucht an der falschen Stelle.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_WURZEL = Path(__file__).resolve().parents[2]
SKRIPT = REPO_WURZEL / "infra" / "deploy" / "env-neu.sh"


# Nur auf POSIX, wie ``test_deploy_pull_pinning.py`` — die Begründung steht
# dort ausführlich: Git Bash unter Windows bringt drei Hürden mit, jede mit
# einer irreführenden Fehlermeldung. Die Logik ist hier zusätzlich von Hand
# in Git Bash durchgespielt worden (siehe PR-Text); verlassen wird sich auf
# den Lauf in CI, der auf Linux stattfindet.
pytestmark = pytest.mark.skipif(
    os.name != "posix" or shutil.which("bash") is None,
    reason="Shell-Test, braucht POSIX und bash",
)


def _lauf(
    tmp_path: Path,
    env_inhalt: str,
    nachher: str,
    vorab_umgebung: dict[str, str] | None = None,
    statt_env_neu: str = "ENV_NEU",
) -> subprocess.CompletedProcess[str]:
    """Wegwerf-Repo bauen, ``env-neu.sh`` sourcen, ``nachher`` ausführen."""
    deploy = tmp_path / "infra" / "deploy"
    deploy.mkdir(parents=True)
    shutil.copy(SKRIPT, deploy / "env-neu.sh")
    (deploy / ".env").write_text(env_inhalt, encoding="utf-8")

    subprocess.run(["git", "init", "-q", "."], cwd=tmp_path, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.email=t@t",
            "-c",
            "user.name=t",
            "commit",
            "-q",
            "--allow-empty",
            "-m",
            "x",
        ],
        cwd=tmp_path,
        check=True,
    )

    umgebung = dict(os.environ)
    umgebung["HEIZUNG_WURZEL"] = str(tmp_path)
    if vorab_umgebung:
        umgebung.update(vorab_umgebung)

    skript = f'. "{deploy / "env-neu.sh"}"\n{statt_env_neu}\n{nachher}\n'
    return subprocess.run(
        ["bash", "-c", skript],
        cwd=tmp_path,
        env=umgebung,
        capture_output=True,
        text=True,
    )


BCRYPT = "HOTEL_BASIC_AUTH_HASH=$$2a$$14$$abcdefghijklmnopqrstuvwxyz012345"
BASIS = f'POSTGRES_USER=heizung\nPOSTGRES_DB="heizung_prod"\n{BCRYPT}\n'


def test_dollarwert_landet_nicht_in_der_umgebung(tmp_path: Path) -> None:
    """Der Fehler vom 04.11., in einer Zeile."""
    r = _lauf(tmp_path, BASIS, 'echo "HASH=[${HOTEL_BASIC_AUTH_HASH-FEHLT}]"')
    assert r.returncode == 0, r.stderr
    assert "HASH=[FEHLT]" in r.stdout, r.stdout


def test_vergiftete_umgebung_wird_geputzt(tmp_path: Path) -> None:
    """Der Helfer muss den Schaden heilen, den er früher selbst anrichtete.

    Wer vorher von Hand ``set -a; . ./.env`` getippt hat, trägt die
    Prozessnummer schon in der Umgebung. Bliebe sie stehen, hülfe der Fix
    genau in dem Fall nicht, in dem er gebraucht wird.
    """
    r = _lauf(
        tmp_path,
        BASIS,
        'echo "HASH=[${HOTEL_BASIC_AUTH_HASH-FEHLT}]"',
        vorab_umgebung={"HOTEL_BASIC_AUTH_HASH": "123452a1234514123450815"},
    )
    assert r.returncode == 0, r.stderr
    assert "HASH=[FEHLT]" in r.stdout, r.stdout


def test_werte_werden_nicht_ausgefuehrt(tmp_path: Path) -> None:
    """``. .env`` führt ``$(…)`` aus. Lesen darf das nicht."""
    beute = tmp_path / "ausgefuehrt.txt"
    inhalt = BASIS + f'BOESE=$(touch "{beute}")\n'
    r = _lauf(tmp_path, inhalt, 'echo "BOESE=[${BOESE-FEHLT}]"')
    assert r.returncode == 0, r.stderr
    assert not beute.exists(), "die .env wurde ausgeführt"
    assert "BOESE=[FEHLT]" in r.stdout, r.stdout


def test_harmlose_werte_kommen_unveraendert_an(tmp_path: Path) -> None:
    """Sonst wäre der Fix eine neue Fehlerquelle: 30 Abfragen hängen daran."""
    r = _lauf(
        tmp_path,
        BASIS,
        'echo "U=[$POSTGRES_USER] D=[$POSTGRES_DB]"',
    )
    assert r.returncode == 0, r.stderr
    assert "U=[heizung] D=[heizung_prod]" in r.stdout, r.stdout


def test_raute_im_wert_bleibt_teil_des_wertes(tmp_path: Path) -> None:
    """Bewusster Unterschied zur alten Fassung.

    Die Shell sah in ``geheim#rest`` einen Kommentar, compose nicht. Da die
    Werte für compose gedacht sind, ist compose der Maßstab — und ein
    Passwort mit ``#`` wird nicht mehr stillschweigend abgeschnitten.
    """
    r = _lauf(
        tmp_path,
        BASIS + "PASSWORT=geheim#nicht-kommentar\n",
        'echo "P=[$PASSWORT]"',
    )
    assert r.returncode == 0, r.stderr
    assert "P=[geheim#nicht-kommentar]" in r.stdout, r.stdout


def test_zurueckgehaltene_namen_werden_genannt_werte_nicht(tmp_path: Path) -> None:
    """Wer nicht sieht, dass etwas fehlt, sucht an der falschen Stelle.

    Und der Wert selbst darf nicht in der Ausgabe stehen — die Ausgabe
    landet in einem ``tmux``-Protokoll.
    """
    r = _lauf(tmp_path, BASIS, "true")
    assert r.returncode == 0, r.stderr
    assert "HOTEL_BASIC_AUTH_HASH" in r.stdout, r.stdout
    assert "abcdefghijklmnopqrstuvwxyz012345" not in r.stdout, "Wert in der Ausgabe"
    assert "abcdefghijklmnopqrstuvwxyz012345" not in r.stderr, "Wert in der Ausgabe"


def test_image_tag_folgt_dem_commit(tmp_path: Path) -> None:
    """Unveränderte Zusicherung der alten Fassung — hier festgehalten."""
    r = _lauf(tmp_path, BASIS, "true")
    assert r.returncode == 0, r.stderr
    kopf = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert f"IMAGE_TAG=develop-{kopf}" in r.stdout, r.stdout


def test_env_lesen_ist_still_wenn_nichts_zurueckgehalten_wird(tmp_path: Path) -> None:
    """Die Prüfbefehle liefern eine einzige Zahl.

    Zwei Zeilen Rauschen davor sind der Weg, auf dem man die Zahl
    überliest — und am 04.11. ist genau so eine verschluckte Ausgabe als
    Erfolg durchgegangen (Befund 3). ``ENV_LESEN`` setzt deshalb nur und
    schweigt, wenn es nichts zu melden gibt.
    """
    r = _lauf(
        tmp_path,
        "POSTGRES_USER=heizung\nPOSTGRES_DB=heizung_prod\n",
        'echo "ENDE=[$POSTGRES_USER]"',
        statt_env_neu="ENV_LESEN",
    )
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "ENDE=[heizung]", repr(r.stdout)


def test_env_lesen_setzt_keinen_image_tag(tmp_path: Path) -> None:
    """Der Tag gehört vor ``docker compose``, nicht vor eine Abfrage.

    Trennt man das nicht, trägt jede Prüfung einen ``IMAGE_TAG`` ein, der
    beim nächsten compose-Aufruf nach einem bewussten Pin aussieht.
    """
    r = _lauf(
        tmp_path,
        BASIS,
        'echo "TAG=[${IMAGE_TAG-FEHLT}]"',
        statt_env_neu="ENV_LESEN",
    )
    assert r.returncode == 0, r.stderr
    assert "TAG=[FEHLT]" in r.stdout, r.stdout
    # Zurückgehalten wird trotzdem gemeldet — still heißt nicht stumm.
    assert "HOTEL_BASIC_AUTH_HASH" in r.stdout, r.stdout


@pytest.mark.parametrize(
    ("aufruf", "env_inhalt"),
    [
        ("ENV_LESEN", BASIS),
        ("ENV_LESEN", "POSTGRES_USER=heizung\n"),
        ("ENV_NEU", BASIS),
        ("ENV_NEU", "POSTGRES_USER=heizung\n"),
    ],
)
def test_rueckgabewert_null_damit_das_und_und_haelt(
    tmp_path: Path, aufruf: str, env_inhalt: str
) -> None:
    """Achtzehn Stellen im RUNBOOK hängen mit ``&&`` an diesen Aufrufen.

    Gäbe der Helfer einen Fehlercode zurück, wenn **nichts**
    zurückgehalten wurde, fiele die Abfrage dahinter stumm aus — und die
    Antwort, die nicht kommt, sieht aus wie eine Antwort, die man
    übersehen hat. Beide Fälle, mit und ohne zurückgehaltenen Wert, und
    beide Aufrufe.
    """
    r = _lauf(tmp_path, env_inhalt, "", statt_env_neu=f"{aufruf} && echo DANACH")
    assert r.returncode == 0, r.stderr
    assert "DANACH" in r.stdout, f"{aufruf} gab einen Fehlercode zurück: {r.stdout!r}"


def test_env_brauche_meldet_einen_zurueckgehaltenen_wert(tmp_path: Path) -> None:
    """Die Falle, die das Zurückhalten erst erzeugt hat.

    Für ``compose`` ist das Zurückhalten richtig. Ein Shell-Befehl, der den
    Wert als **Argument** weitergibt, bekäme eine leere Zeichenfolge — und
    ``mosquitto_passwd -b`` legt dann stillschweigend ein **leeres
    Passwort** an. Ein Abbruch ist besser.
    """
    r = _lauf(
        tmp_path,
        BASIS,
        "ENV_BRAUCHE HOTEL_BASIC_AUTH_HASH && echo UNERWARTET_OK",
    )
    assert "UNERWARTET_OK" not in r.stdout, r.stdout
    assert "ist nicht gesetzt" in r.stderr, r.stderr


def test_env_brauche_laesst_vorhandene_werte_durch(tmp_path: Path) -> None:
    """Sonst stünde der Riegel vor jedem Block und nützte nichts."""
    r = _lauf(
        tmp_path,
        BASIS,
        "ENV_BRAUCHE POSTGRES_USER POSTGRES_DB && echo GEPRUEFT_OK",
    )
    assert "GEPRUEFT_OK" in r.stdout, r.stdout + r.stderr


def test_fehlende_env_bricht_ab(tmp_path: Path) -> None:
    """Lieber ein Abbruch als eine halb geladene Umgebung."""
    deploy = tmp_path / "infra" / "deploy"
    deploy.mkdir(parents=True)
    shutil.copy(SKRIPT, deploy / "env-neu.sh")
    umgebung = dict(os.environ) | {"HEIZUNG_WURZEL": str(tmp_path)}
    r = subprocess.run(
        ["bash", "-c", f'. "{deploy / "env-neu.sh"}"\nENV_NEU\n'],
        cwd=tmp_path,
        env=umgebung,
        capture_output=True,
        text=True,
    )
    assert r.returncode != 0
    assert "nicht gefunden" in r.stderr


def test_pruefung_sieht_die_umgebung_nicht_nur_die_datei(tmp_path: Path) -> None:
    """Die Prüfung, die am 04.11. gefehlt hat.

    Die alte Kontrolle war ein ``grep`` auf die **Datei** und bestand,
    während die Umgebung schon vergiftet war. ``PRUEF_HASH_UMGEBUNG`` muss
    genau diesen Fall melden.
    """
    r = _lauf(
        tmp_path,
        BASIS,
        "export HOTEL_BASIC_AUTH_HASH=zerstoert\n"
        "PRUEF_HASH_UMGEBUNG HOTEL_BASIC_AUTH_HASH && echo UNERWARTET_OK",
    )
    assert "UNERWARTET_OK" not in r.stdout, r.stdout
    assert "steht in der Umgebung" in r.stderr, r.stderr


def test_pruefung_bestaetigt_den_guten_fall(tmp_path: Path) -> None:
    """Und sie muss durchlassen, was in Ordnung ist — sonst nützt sie nichts."""
    r = _lauf(
        tmp_path,
        BASIS,
        "PRUEF_HASH_UMGEBUNG HOTEL_BASIC_AUTH_HASH && echo GEPRUEFT_OK",
    )
    assert "GEPRUEFT_OK" in r.stdout, r.stdout + r.stderr


def test_pruefung_meldet_fehlende_verdopplung(tmp_path: Path) -> None:
    """Ein einfaches Dollarzeichen in der .env ist der andere Fehlerfall."""
    r = _lauf(
        tmp_path,
        "POSTGRES_USER=heizung\nHOTEL_BASIC_AUTH_HASH=$2a$14$abc\n",
        "PRUEF_HASH_UMGEBUNG HOTEL_BASIC_AUTH_HASH && echo UNERWARTET_OK",
    )
    assert "UNERWARTET_OK" not in r.stdout, r.stdout
    assert "nicht verdoppelt" in r.stderr, r.stderr
