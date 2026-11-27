"""Die Alarmtabelle im RUNBOOK ist so lang wie die Zahl der Alarmwege.

**Der Anlass.** Am 18.11.2026 stand in der Tabelle „Welche Alarme es gibt"
ein Kasten, der sagte, sie sei unvollstaendig: zwei Melder fehlten. Beim
Nachtragen am 27.11.2026 fehlten nicht zwei, sondern **fuenf** — neben dem
Zonen-Melder und dem Platten-Waechter auch der erschoepfte Abgleich, die
ueberfaellige Belegungsliste und die Erinnerung an einen festgesetzten
Stand. Drei davon hatte niemand als Luecke notiert; sie sind einfach
dazugekommen, und die Tabelle ist stehen geblieben.

**Warum ein Test und nicht ein Vorsatz.** Eine Doku-Tabelle, die von Hand
nachgezogen wird, ist nach drei Sprints falsch — und dann schlimmer als
keine, weil sie wie ein Befund gelesen wird (Paragraph 5.77, dasselbe
Argument wie beim Handbuch in Goldene Regel 13). Der Betreiber liest sie
im Alarmfall. Was dort fehlt, sucht er nicht.

**Woran der Test haengt, und warum gerade daran.** Gezaehlt werden die
Stellen im Quellcode, die ``mailer.send_mail`` **benutzen** — nicht
Vorkommen im Text, sondern Verweise im Syntaxbaum. Wer einen Alarmweg
baut, kommt daran nicht vorbei: eine Mail ohne ``send_mail`` gibt es
nicht. Eine Liste von Alarm-Namen im Test waere dagegen eine zweite
Tabelle, die genauso altert wie die erste.

**Was der Test nicht kann.** Er prueft die **Anzahl**, nicht den Inhalt.
Ob die Zeile den richtigen Schwellwert nennt, sieht nur ein Mensch — und
genau deshalb geht der Test bei einer Abweichung mit einer Anleitung rot
und nicht mit „11 != 12". Zwei Alarme in **einem** Aufrufer (Alarm und
Entwarnung teilen sich im Repo einen Versandhelfer) sind **eine** Zeile;
das ist die Zuordnung, die der Test voraussetzt, und sie steht unten.
"""

from __future__ import annotations

import ast
from pathlib import Path

#: Der Abschnitt, um den es geht.
UEBERSCHRIFT = "### Welche Alarme es gibt"

#: Dateien, die ``mailer.send_mail`` benutzen, **ohne** ein Alarm zu sein.
#:
#: ``scripts/send_test_mail.py`` ist der Probeversand aus dem RUNBOOK
#: (Schritt 2 der Mail-Einrichtung). Er meldet keine Lage, sondern prueft
#: den Weg — und er hat seinen eigenen Abschnitt, eine Zeile in der
#: Alarmtabelle waere dort falsch.
KEINE_ALARME = {"scripts/send_test_mail.py"}


def _repo() -> Path:
    return Path(__file__).resolve().parents[2]


def _versandstellen() -> dict[str, int]:
    """Je Datei: wie oft ``mailer.send_mail`` dort verwendet wird.

    Gezaehlt werden ``Attribute``-Knoten und nicht Textstellen. Das
    trifft beide Formen, in denen das Repo versendet — den direkten
    Aufruf und die Uebergabe an ``asyncio.to_thread(mailer.send_mail,
    ...)`` — und es trifft **keine** Erwaehnung in einem Docstring, von
    denen es im Repo ein halbes Dutzend gibt.
    """
    wurzel = _repo() / "backend" / "src" / "heizung"
    treffer: dict[str, int] = {}
    for datei in sorted(wurzel.rglob("*.py")):
        rel = datei.relative_to(wurzel).as_posix()
        if rel in KEINE_ALARME:
            continue
        baum = ast.parse(datei.read_text(encoding="utf-8"))
        anzahl = sum(
            1
            for knoten in ast.walk(baum)
            if isinstance(knoten, ast.Attribute)
            and knoten.attr == "send_mail"
            and isinstance(knoten.value, ast.Name)
            and knoten.value.id == "mailer"
        )
        if anzahl:
            treffer[rel] = anzahl
    return treffer


def _tabellenzeilen() -> list[str]:
    """Die Datenzeilen der Tabelle unter der Ueberschrift.

    Kopfzeile und Trennzeile zaehlen nicht mit; die Tabelle endet an der
    ersten Zeile, die nicht mit ``|`` beginnt.
    """
    text = (_repo() / "docs" / "RUNBOOK.md").read_text(encoding="utf-8")
    assert UEBERSCHRIFT in text, f"Abschnitt {UEBERSCHRIFT!r} fehlt im RUNBOOK"
    rest = text.split(UEBERSCHRIFT, 1)[1].splitlines()
    zeilen: list[str] = []
    gestartet = False
    for zeile in rest:
        if zeile.startswith("|"):
            gestartet = True
            zeilen.append(zeile)
        elif gestartet:
            break
    # Kopf und Trennstrich weg.
    return zeilen[2:]


def test_jeder_alarmweg_hat_eine_zeile() -> None:
    """So viele Zeilen wie Versandstellen — sonst fehlt eine Zeile.

    Die Zuordnung, Stand 27.11.2026:

    ======================================= ===================================
    Versandstelle                           Zeile
    ======================================= ===================================
    ``services/health_alerts``              Thermostat meldet sich nicht
    ``services/occupancy_import_service``   Keine Belegungsliste **und**
    (zweimal)                               Belegungsliste ueberfaellig
    ``services/pin_reminder``               Stand festgesetzt
    ``tasks/engine_tasks``                  Geraet nimmt den Sollwert nicht an
    ``tasks/funk_tasks`` (dreimal)          Funkqualitaet gefallen, Keine
                                            Messwerte, Zone ohne Fuehlerwert
    ``tasks/gehaeuse_tasks``                Relais wird warm
    ``tasks/platten_tasks``                 Platte laeuft voll
    ``tasks/schutz_tasks``                  Relais hat sich abgeschaltet
    ======================================= ===================================
    """
    stellen = _versandstellen()
    zeilen = _tabellenzeilen()
    gesamt = sum(stellen.values())
    assert gesamt == len(zeilen), (
        f"{gesamt} Versandstellen im Code, aber {len(zeilen)} Zeilen in der "
        f"Alarmtabelle des RUNBOOK ({UEBERSCHRIFT}).\n"
        "Kommt ein Alarmweg hinzu, gehoert eine Zeile dazu — mit Ausloeser "
        "und Sperrzeit, und mit dem Namen der Schwelle statt ihrer Zahl, "
        "wenn sie verstellbar ist.\n"
        "Ist der neue Aufruf **kein** Alarm (etwa ein zweiter Probeversand), "
        f"gehoert seine Datei in KEINE_ALARME in {Path(__file__).name}, mit "
        "Begruendung.\n"
        f"Gefunden: {stellen}"
    )


def test_die_tabelle_behauptet_nicht_mehr_unvollstaendig_zu_sein() -> None:
    """Der Kasten vom 18.11.2026 ist weg — und darf nicht zurueckkommen.

    Ein Hinweis „diese Tabelle ist unvollstaendig" ist die ehrliche Form,
    solange niemand sie nachtraegt. Als Dauerzustand ist er das
    Gegenteil: ein Melder, dem man nicht glauben muss (Paragraph 5.79).
    Wer wieder eine Luecke vermerkt, statt sie zu schliessen, laeuft hier
    auf.
    """
    text = (_repo() / "docs" / "RUNBOOK.md").read_text(encoding="utf-8")
    abschnitt = text.split(UEBERSCHRIFT, 1)[1].split("### ", 1)[0].lower()
    for marke in ("unvollstaendig", "unvollständig", "nicht aufgeführt", "nicht aufgefuehrt"):
        assert marke not in abschnitt, (
            f"Die Alarmtabelle vermerkt wieder eine Luecke ({marke!r}). "
            "Die Zeile nachtragen ist billiger als der Vermerk — und der "
            "Vermerk wird im Alarmfall nicht gelesen."
        )
