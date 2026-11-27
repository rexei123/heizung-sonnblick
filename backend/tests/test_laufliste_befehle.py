"""Die Laufliste (RUNBOOK 10bi) wiederholt Befehle — wortgleich (27.11.2026).

**Warum diese Doppelung ueberhaupt da ist.** Eine Laufliste, die bei
jedem Schritt „siehe Paragraph 10ay" sagt, ist um 10 Uhr mit einem
Gateway in der Hand nicht benutzbar. Die Befehle stehen deshalb **in** der
Liste, obwohl sie anderswo schon stehen.

**Warum sie einen Wachposten braucht.** Derselbe Befehl an zwei Stellen
sind zwei Wahrheiten, sobald eine davon geaendert wird (Paragraph 5.53) —
und die Stelle, die niemand ansieht, ist dann im Wartungsfenster die
falsche. Genau dieses Muster hat am 17.11.2026 schon einmal zugeschlagen:
Paragraph 10ay pruefte das Gateway ueber das **Caddy**-Protokoll, obwohl
das UG65 per MQTT publiziert, und die Laufliste vom 16.11. hatte den
Fehler mitgenommen.

**Was der Test prueft:** dass jeder der doppelten Befehle **mehr als
einmal** in der Datei steht. Faellt eine Stelle weg oder wird eine
geaendert, sinkt die Zahl auf 1 und der Test nennt beide Orte.

**Was er nicht prueft:** ob der Befehl richtig ist. Das kann nur ein
Mensch am Server, und dafuer stehen in der Laufliste die *ERWARTET*-Zeilen.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_WURZEL = Path(__file__).resolve().parents[2]
RUNBOOK = REPO_WURZEL / "docs" / "RUNBOOK.md"

#: Je Eintrag: (Befehl, wo er herkommt, wozu er in der Laufliste steht).
#:
#: **Kurz gehalten.** Nicht jeder Befehl der Laufliste gehoert hierher,
#: sondern die, die eine **Quelle** haben: wird dort etwas geaendert, muss
#: es hier mitwandern. Ein Befehl, der nur in der Laufliste steht, hat
#: keine zweite Wahrheit und braucht keinen Wachposten.
DOPPELTE_BEFEHLE: tuple[tuple[str, str, str], ...] = (
    (
        "/opt/heizung-sonnblick/infra/deploy/backup.sh && ls -lt /var/backups/heizung | head -3",
        "10ab Schritt 0.2",
        "Schritt 0c der Laufliste: die Sicherung vor dem Termin",
    ),
    (
        "docker logs deploy-mosquitto-1 --since 5m 2>&1 | grep -c \"u'gateway-ug65'\"",
        "10ay",
        "Schritt 1d: hat sich das Gateway neu verbunden",
    ),
    (
        "max(time) AT TIME ZONE 'Europe/Vienna' AS juengste FROM sensor_reading "
        "WHERE time > now() - interval '3 minutes';",
        "10ay",
        "Schritt 1d: kommen Messwerte (das Ende der Kette)",
    ),
)


@pytest.fixture(scope="module")
def runbook() -> str:
    return RUNBOOK.read_text(encoding="utf-8")


def test_die_laufliste_steht_im_runbook(runbook: str) -> None:
    """Ohne den Abschnitt prueft alles darunter nichts (Paragraph 5.55)."""
    assert "## 10bi. Ein Wartungsfenster" in runbook


@pytest.mark.parametrize(("befehl", "quelle", "wozu"), DOPPELTE_BEFEHLE)
def test_der_befehl_steht_an_beiden_stellen(
    runbook: str, befehl: str, quelle: str, wozu: str
) -> None:
    """Wortgleich an beiden Stellen — sonst driftet die Laufliste."""
    anzahl = runbook.count(befehl)
    assert anzahl >= 2, (
        f"Dieser Befehl steht nur {anzahl}x im RUNBOOK, erwartet sind mindestens 2 "
        f"(Quelle: Paragraph {quelle}; Laufliste: {wozu}).\n"
        f"  {befehl}\n"
        "Wurde er an einer Stelle geaendert, gehoert die Aenderung an beide — "
        "oder der Eintrag aus DOPPELTE_BEFEHLE raus, wenn die Doppelung "
        "absichtlich endet."
    )


def test_die_laufliste_prueft_das_gateway_nicht_ueber_caddy(runbook: str) -> None:
    """Der Fehler vom 17.11.2026 darf nicht zurueckkommen.

    Das UG65 spricht **kein** Basic Station; es publiziert per MQTT auf
    1883 und meldet sich bei Mosquitto als ``gateway-ug65`` an. Ein
    ``grep`` im Caddy-Protokoll beantwortet die Frage nicht — und der
    Abschnitt, aus dem die Laufliste ihre Befehle nimmt, hatte genau das
    bis zum 17.11. stehen.
    """
    teil = runbook.split("## 10bi. Ein Wartungsfenster", 1)[1]
    niedrig = teil.lower()
    for marke in ("caddy", "basic station", "basicstation"):
        if marke not in niedrig:
            continue
        # „Nicht Caddy" als Warnung ist erlaubt — ein Pruefbefehl auf das
        # Caddy-Protokoll nicht.
        for zeile in teil.splitlines():
            if marke in zeile.lower() and "docker logs deploy-caddy" in zeile:
                pytest.fail(
                    "Die Laufliste prueft das Gateway ueber das Caddy-Protokoll. "
                    "Das UG65 publiziert per MQTT auf 1883 (Korrektur vom "
                    "17.11.2026, Paragraph 10ay)."
                )
