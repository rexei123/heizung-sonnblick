"""Zwei Stellen im RUNBOOK, die ohne Wachposten still veralten.

Ein Warnkasten ist die billigste Stelle der Welt, um etwas zu loeschen:
er stoert beim Lesen, er stoert beim Umschreiben, und niemand merkt sein
Fehlen -- bis die Abfrage darunter wieder falsch verstanden wird. Beide
Zusicherungen hier haben einen konkreten Anlass vom 15./16.11.2026.

**Was hier NICHT geprueft wird, und warum nicht.** Naheliegend waere ein
allgemeiner Pruefer: „jeder ``§``-Verweis zeigt auf einen Abschnitt, den
es gibt". Er wuerde den Fehler aus #420 fangen (ein Verweis auf die Lehre
§5.90, die es nicht gibt) und den vom 15.11. (ein Verweis auf §10bb,
bevor der Abschnitt geschrieben war). Gemessen am 16.11.2026 scheitert er
aber an den **ueberlappenden Nummernraeumen**: ``§5.0`` und ``§5.0a``
sind RUNBOOK-Abschnitte, ``§5.89`` ist eine CLAUDE.md-Lehre, und die
Verweise sagen nicht, in welches Dokument sie zeigen. Dazu kommen 49
weitere Nummern (``§0.3``, ``§6.1``, ``§2.4`` ...), die in CLAUDE.md
nicht als Ueberschrift stehen. Ein belastbarer Pruefer braucht ein
Anker-Inventar beider Dateien und eine Triage dieser 49 -- das ist ein
eigener PR, nicht eine Zeile hier. Steht auf der Liste.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_WURZEL = Path(__file__).resolve().parents[2]
RUNBOOK = REPO_WURZEL / "docs" / "RUNBOOK.md"
CLAUDE = REPO_WURZEL / "CLAUDE.md"


@pytest.fixture(scope="module")
def runbook() -> str:
    return RUNBOOK.read_text(encoding="utf-8")


def _abschnitt(text: str, nummer: str) -> str:
    """Der Text eines RUNBOOK-Abschnitts, ohne die folgenden."""
    kopf = f"\n## {nummer}."
    assert kopf in text, f"RUNBOOK-Abschnitt {nummer} fehlt"
    rest = text.split(kopf, 1)[1]
    return rest.split("\n## ", 1)[0]


def test_schritt_6a_nennt_seine_deckung(runbook: str) -> None:
    """**Die Abfrage antwortet nur fuer etwa die Haelfte der Geraete.**

    Gemessen am 16.11.2026: 55 Geraete im ADR-Protokoll, 109 in unserer
    Datenbank, 103 davon meldend. ADR schreibt ``LinkADRReq
    acknowledged`` nur bei einer **Aenderung** -- ein Geraet, dessen
    Stufe passt, steht nicht im Protokoll.

    **Warum das ein Wachposten braucht.** „Ein Drittel ist auf eine
    kleinere Stufe gegangen" und „die Haelfte der Geraete steht nicht im
    Protokoll" sehen in der Ausgabe von 6a **gleich** aus. Ohne den
    Kasten liest jemand am Mittwoch eine Wirkung aus einer Luecke
    (Paragraph 5.68), und die 48-Stunden-Kontrolle waere eine Bestaetigung,
    die nichts bestaetigt.

    Geprueft wird die **Zahl mit ihrer Beschriftung**, und zwar **im
    Kasten** -- nicht als nackte Zeichenfolge im Abschnitt. Zwei
    Mutationsproben blieben zuerst gruen, weil „55" auch in „§5.55"
    steckt und „6b" anderswo in 10av vorkommt: eine Zusicherung auf die
    ganze Datei ist keine Zusicherung auf die Stelle (Paragraph 5.88).
    """
    abschnitt = _abschnitt(runbook, "10av")
    marke = "**⚠ Diese Abfrage antwortet nur"
    assert marke in abschnitt, (
        "der Deckungs-Kasten bei Schritt 6a fehlt -- ohne ihn liest jemand "
        "eine Wirkung aus einer Luecke"
    )
    kasten = abschnitt.split(marke, 1)[1].split("\n**b)", 1)[0]

    for muster, was in (
        (r"ADR-Protokoll:\s*55\b", "55 Geraete im ADR-Protokoll"),
        (r"unserer DB:\s*109\b", "109 Geraete in unserer Datenbank"),
        (r"24h:\s*103\b", "103 meldende Geraete"),
    ):
        assert re.search(muster, kasten), f"der Kasten nennt nicht: {was}"

    assert re.search(r"Schritt\s+6b", kasten), (
        "der Kasten sagt nicht, welcher Schritt belastbar ist -- eine Warnung "
        "ohne Ausweg wird ignoriert (Paragraph 5.79)"
    )


def test_die_gateway_pruefung_nennt_den_mqtt_weg_und_nicht_basic_station(
    runbook: str,
) -> None:
    """**Der Abschnitt, der mich zweimal in dieselbe Falle geführt hat.**

    §10ay beschrieb den Weg des UG65 als Basic Station: ein ``tail -f``
    auf das Caddy-Protokoll mit ``grep router``. Das UG65 spricht aber
    **MQTT auf 1883** und meldet sich bei Mosquitto als ``gateway-ug65``
    an. Die Korrektur steht seit dem 07.11.2026 an drei anderen Stellen
    im RUNBOOK — **nur dieser Abschnitt wurde nicht nachgezogen.**

    Die alte Zeile war nicht wirkungslos, sondern **irreführend**: sie
    zeigt bei gesundem Gateway dauerhaft nichts, und der Text darunter
    sagte, genau das heiße „das Gerät versucht es nicht". Wer ihr folgte,
    zog den Stecker ohne Anlass. Am 16.11.2026 habe ich daraus zweimal
    eine falsche Prüfung in eine Laufliste geschrieben.

    **Was dieser Test leistet:** er hält den Abschnitt auf dem MQTT-Weg
    fest. Eine Rückkehr der Caddy-Zeile wäre damit rot statt still.
    """
    ay = _abschnitt(runbook, "10ay")
    assert "gateway-ug65" in ay, (
        "10ay nennt den MQTT-Benutzer des Gateways nicht — ohne ihn ist "
        "die Prüfung nicht durchführbar"
    )
    # **Nicht auf „sensor_reading" prüfen.** Das steht auch in Schritt 1
    # des Abschnitts (Uplinks zählen), und eine Mutationsprobe blieb
    # deshalb grün. Geprüft wird der Block **neben** der Gateway-Prüfung,
    # erkennbar am eigenen Fenster von drei Minuten — Schritt 1 nimmt
    # fünf (§5.88, dieselbe Familie).
    nach_gateway = ay.split("gateway-ug65", 1)[1]
    assert "interval '3 minutes'" in nach_gateway, (
        "neben der Gateway-Prüfung fehlt die Messwert-Prüfung — ohne sie "
        "hängt die Entscheidung an einer einzigen Logzeile"
    )
    assert "BEIDES leer" in nach_gateway or "beides leer" in nach_gateway, (
        "die STOPP-Regel sagt nicht, dass BEIDE Prüfungen leer sein "
        "müssen — eine einzelne Null ist kein Grund für den Stecker"
    )
    assert "--line-buffered router" not in ay, (
        "die Basic-Station-Prüfung ist zurück — das UG65 spricht MQTT auf "
        "1883, und diese Zeile zeigt bei gesundem Gateway nie etwas"
    )


def test_die_regel_fuer_ein_stummes_relais_nennt_schwelle_und_zieldatenrate(
    runbook: str,
) -> None:
    """Eine Regel ohne Schwelle ist ein Ratschlag.

    **Vorgabe des Betreibers, 16.11.2026:** wird 108 stumm, hilft ein
    Stromstoß (Rejoin auf DR0). Erst wenn das **öfter als einmal im
    Monat** nötig ist, wird das Plugin aktiviert — und dann mit
    ``ZIEL_DR = 0``, nicht 1.

    Beide Zahlen gehören in den Text: ohne die Schwelle weiß niemand,
    wann der Handgriff vom Einzelfall zum Wartungsaufwand wird, und ohne
    die Zieldatenrate würde der nächste PR die DR1 von damals übernehmen
    — gegen die Messung, die zu dieser Regel geführt hat.
    """
    av = _abschnitt(runbook, "10av")
    assert "EINMAL IM MONAT" in av or "einmal im Monat" in av, (
        "die Regel nennt keine Schwelle, ab der das Plugin fällig wird"
    )
    assert "ZIEL_DR = 0" in av, (
        "die Regel nennt die Zieldatenrate nicht — DR1 wäre 2,5 dB "
        "weniger Reserve, und genau das war der Befund"
    )


def test_die_geheimnis_lehre_wird_mit_der_richtigen_nummer_zitiert(runbook: str) -> None:
    """**Ein Verweis, der ins Leere zeigte -- aus meinem eigenen #420.**

    Abschnitt 10bb nannte die Lehre „Konfiguration mit Geheimnissen
    gezielt pruefen" als **§5.90**. Diese Nummer gibt es nicht; gemeint
    ist **§5.89**. Die falsche Nummer ist von dort in die Uebergabe einer
    zweiten Sitzung gewandert und waere ohne diese Korrektur
    weitergereist.

    **Warum ein toter Verweis schlimmer wird, nicht besser.** Solange die
    Nummer frei ist, merkt man beim Nachschlagen, dass etwas fehlt. Sobald
    irgendwann eine Lehre 5.90 entsteht, zeigt der Verweis stillschweigend
    auf eine **fremde** Lehre -- und dann sieht er richtig aus.
    """
    bb = _abschnitt(runbook, "10bb")
    assert "§5.89" in bb, "10bb zitiert die Geheimnis-Lehre nicht als §5.89"
    assert "§5.90" not in bb, "10bb zitiert §5.90 -- diese Lehre gibt es nicht, gemeint ist §5.89"

    # Und die zitierte Lehre muss es wirklich geben: sonst waere die
    # Korrektur nur eine andere falsche Nummer.
    lehren = set(re.findall(r"^### (5\.\d+)\s", CLAUDE.read_text(encoding="utf-8"), re.MULTILINE))
    assert "5.89" in lehren, "die Lehre 5.89 fehlt in CLAUDE.md"
