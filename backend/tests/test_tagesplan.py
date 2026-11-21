"""Tagesplan, die Teile ohne Datenbank (21.11.2026).

Drei Gegenstaende, und sie haengen zusammen:

1. ``heizung.uhrzeit`` — die Schreibweise ``HH:MM`` mit ``24:00``. Sie ist
   am 21.11.2026 aus ``services/betriebszeit`` hierher gewandert, weil der
   Tagesplan dieselbe Eingabe annimmt. Der Auszug muss
   **verhaltensneutral** sein (§5.47), und das prueft hier eine eigene
   Gruppe: ``parse_uhrzeit`` bildet ``24:00`` weiterhin auf ``00:00`` ab.
2. ``rules/tagesplan`` — welches Fenster eine Minute enthaelt, und welche
   Zeiten **kein** Fenster abdeckt. Das Zweite ist die Absenkung, und es
   ist die Zahl, die im Verlauf als Band erscheint.
3. ``schemas/tagesplan`` — die Eingabepruefung. Hier steht der Satz, den
   der Betreiber liest, wenn zwei Fenster sich ueberschneiden.

**Die Grenzen sind der Inhalt dieser Datei.** Ein Fenster 06:00-08:00 und
ein Fenster 08:00-21:00 sind erlaubt und ueberschneiden sich nicht; 08:00
gehoert zum zweiten. Eine Pruefung um 07:00 und 12:00 waere auch mit einer
um eine Minute verschobenen Grenze gruen — deshalb wird hier auf die
Minute geprueft.
"""

from __future__ import annotations

from datetime import datetime, time
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from heizung.rules.tagesplan import (
    TagesFenster,
    fenster_bei,
    luecken,
    minute_des_tages,
)
from heizung.schemas.tagesplan import MAX_FENSTER, TagesplanUpdate
from heizung.services import betriebszeit
from heizung.uhrzeit import MINUTEN_PRO_TAG, UhrzeitError, als_text, parse_minuten

# ---------------------------------------------------------------------------
# 1. Die Schreibweise
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("eingabe", "minuten"),
    [
        ("00:00", 0),
        ("06:00", 360),
        ("08:00", 480),
        ("21:00", 1260),
        ("23:59", 1439),
        ("24:00", 1440),
        (" 07:30 ", 450),
    ],
)
def test_uhrzeit_wird_zu_minuten(eingabe: str, minuten: int) -> None:
    assert parse_minuten(eingabe) == minuten


def test_vierundzwanzig_uhr_bleibt_das_ende_des_tages() -> None:
    """**Der Grund, warum nicht ``time`` gespeichert wird.**

    ``24:00`` ist 1440 und damit **groesser** als jeder Beginn. Als ``time``
    waere es ``00:00`` und damit kleiner als alles — ein Fenster „15:00 bis
    24:00" haette ein Ende vor seinem Anfang.
    """
    assert parse_minuten("24:00") == MINUTEN_PRO_TAG
    assert parse_minuten("24:00") > parse_minuten("15:00")


@pytest.mark.parametrize(
    "eingabe",
    ["25:00", "7:30", "", "12:60", "24:01", "24:30", "abc", "7", "07:0", "-1:00"],
)
def test_was_keine_uhrzeit_ist_wird_abgewiesen(eingabe: str) -> None:
    with pytest.raises(UhrzeitError):
        parse_minuten(eingabe)


@pytest.mark.parametrize("minuten", [0, 1, 360, 1439, 1440])
def test_hin_und_zurueck(minuten: int) -> None:
    """``als_text`` ist die Umkehrung — **auch** bei 1440.

    Wer „24:00" eingegeben hat, soll „24:00" wiedersehen. Ein Wert, der
    anders zurueckkommt als er hineinging, ist die Sorte Kleinigkeit, die
    beim Nachsehen Zeit kostet.
    """
    assert parse_minuten(als_text(minuten)) == minuten


def test_vierundzwanzig_uhr_wird_als_vierundzwanzig_uhr_gezeigt() -> None:
    assert als_text(1440) == "24:00"
    assert als_text(0) == "00:00"


@pytest.mark.parametrize("minuten", [-1, 1441, 2000])
def test_ausserhalb_eines_tages_ist_keine_uhrzeit(minuten: int) -> None:
    with pytest.raises(UhrzeitError):
        als_text(minuten)


# ---------------------------------------------------------------------------
# 1b. Der Auszug war verhaltensneutral (§5.47)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("eingabe", "erwartet"),
    [
        ("24:00", time(0, 0)),
        ("00:00", time(0, 0)),
        ("15:00", time(15, 0)),
        (" 07:30 ", time(7, 30)),
    ],
)
def test_die_betriebszeit_rechnet_unveraendert(eingabe: str, erwartet: time) -> None:
    """``parse_uhrzeit`` nutzt seit dem 21.11.2026 ``parse_minuten``.

    **Die Abbildung auf ``00:00`` muss bleiben.** Die Betriebszeit
    speichert in einer ``Time``-Spalte, und die Fensterpruefung der Engine
    rechnet mit ``night_start = 00:00`` richtig (``services/betriebszeit``
    begruendet es). Haette der Auszug hier etwas geaendert, waere es eine
    Verhaltensaenderung an der Steuerung, getarnt als Aufraeumen.
    """
    assert betriebszeit.parse_uhrzeit(eingabe) == erwartet


def test_der_fehler_der_betriebszeit_bleibt_fangbar() -> None:
    """``BetriebszeitError`` muss weiter greifen.

    Der Endpunkt fangt genau diesen Typ (``except
    betriebszeit.BetriebszeitError``). Wuerde ``parse_uhrzeit`` jetzt den
    Fehler des Format-Moduls durchlassen, antwortete die API mit 500
    statt mit 422 — und zwar nur bei einer Fehleingabe, also genau dann,
    wenn niemand hinsieht.
    """
    with pytest.raises(betriebszeit.BetriebszeitError):
        betriebszeit.parse_uhrzeit("25:00")


# ---------------------------------------------------------------------------
# 2. Welches Fenster gilt
# ---------------------------------------------------------------------------


def _f(von: str, bis: str, temperatur: str = "22.0", kennung: int = 1) -> TagesFenster:
    return TagesFenster(
        id=kennung,
        von_minute=parse_minuten(von),
        bis_minute=parse_minuten(bis),
        temperatur=Decimal(temperatur),
    )


#: Der Plan aus dem Wunsch des Betreibers: 06:00-08:00 auf 25, 08:00-21:00
#: auf 22, sonst Absenkung.
PLAN = [_f("06:00", "08:00", "25.0", 1), _f("08:00", "21:00", "22.0", 2)]


@pytest.mark.parametrize(
    ("uhrzeit", "erwartete_kennung", "warum"),
    [
        ("05:59", None, "eine Minute vor dem ersten Fenster"),
        ("06:00", 1, "die erste Minute gehoert dazu"),
        ("07:59", 1, "die letzte Minute des ersten Fensters"),
        ("08:00", 2, "die Grenze gehoert dem **folgenden** Fenster"),
        ("20:59", 2, "letzte Minute des zweiten Fensters"),
        ("21:00", None, "das Ende gehoert nicht mehr dazu"),
        ("23:59", None, "spaete Luecke"),
        ("00:00", None, "fruehe Luecke"),
    ],
)
def test_die_grenzen_sind_halboffen(
    uhrzeit: str, erwartete_kennung: int | None, warum: str
) -> None:
    """``von <= minute < bis`` — und 08:00 ist der Fall, der es zeigt.

    Waere die Grenze beidseitig geschlossen, gehoerte 08:00 zu **beiden**
    Fenstern, und welcher Sollwert gilt, entschiede die Reihenfolge der
    Zeilen. Genau das verbietet §0 S2, und genau deshalb erlaubt die
    ``EXCLUDE``-Bedingung der Tabelle aneinander stossende Fenster: sie
    rechnet mit demselben halboffenen Bereich.
    """
    treffer = fenster_bei(PLAN, parse_minuten(uhrzeit))
    assert (None if treffer is None else treffer.id) == erwartete_kennung, warum


def test_ohne_fenster_gilt_nichts() -> None:
    """Kein Plan heisst: diese Funktion entscheidet nicht.

    Nicht „alles ist Luecke" — die Engine faellt dann auf das Nachtfenster
    zurueck, und das ist etwas anderes.
    """
    assert fenster_bei([], 720) is None
    assert luecken([]) == []


def test_die_minute_kommt_aus_der_ortszeit() -> None:
    """Gerechnet wird mit der Wanduhrzeit, Sekunden fallen weg."""
    lokal = datetime(2026, 11, 21, 7, 30, 59, tzinfo=ZoneInfo("Europe/Vienna"))
    assert minute_des_tages(lokal) == 450


# ---------------------------------------------------------------------------
# 2b. Die Luecken — das ist die Absenkung
# ---------------------------------------------------------------------------


def test_die_luecken_des_wunsch_plans() -> None:
    """00:00-06:00 und 21:00-24:00. **Vor dem ersten und nach dem letzten.**

    Das Band im Verlauf wird aus diesen Spannen gezeichnet
    (``services/room_history.tagesplan_baender``). Fehlte die Spanne nach
    dem letzten Fenster, saehe die Nacht im Diagramm aus wie Betrieb.
    """
    assert luecken(PLAN) == [(0, 360), (1260, 1440)]


def test_eine_luecke_in_der_mitte() -> None:
    """Mittagspause: 12:00-14:00 ist nicht abgedeckt."""
    plan = [_f("08:00", "12:00", kennung=1), _f("14:00", "22:00", kennung=2)]
    assert luecken(plan) == [(0, 480), (720, 840), (1320, 1440)]


def test_ein_voller_tag_hat_keine_luecke() -> None:
    """00:00-24:00 in zwei Fenstern: nichts bleibt uebrig.

    Das ist der Plan eines Bereichs, der nie absenken soll — und er darf
    kein Band zeichnen.
    """
    plan = [_f("00:00", "12:00", kennung=1), _f("12:00", "24:00", kennung=2)]
    assert luecken(plan) == []


def test_die_reihenfolge_der_eingabe_ist_gleichgueltig() -> None:
    """Unsortiert hineingegeben, sortiert gerechnet.

    ``lade_fenster`` ordnet nach Beginn; diese Funktion verlaesst sich
    nicht darauf, weil ein Aufrufer aus der Oberflaeche sie auch mit einer
    frisch getippten Liste rufen kann.
    """
    plan = [_f("08:00", "21:00", kennung=2), _f("06:00", "08:00", kennung=1)]
    assert luecken(plan) == [(0, 360), (1260, 1440)]


def test_ein_fenster_bis_mitternacht_laesst_am_abend_nichts_offen() -> None:
    plan = [_f("15:00", "24:00", kennung=1)]
    assert luecken(plan) == [(0, 900)]


# ---------------------------------------------------------------------------
# 3. Die Eingabepruefung
# ---------------------------------------------------------------------------


def _eingabe(*fenster: tuple[str, str, str]) -> dict[str, object]:
    return {"fenster": [{"von": v, "bis": b, "temperatur": t} for v, b, t in fenster]}


def test_der_wunsch_plan_wird_angenommen() -> None:
    plan = TagesplanUpdate.model_validate(
        _eingabe(("06:00", "08:00", "25.0"), ("08:00", "21:00", "22.0"))
    )
    assert [f.von_minute for f in plan.fenster] == [360, 480]
    assert plan.fenster[0].temperatur == Decimal("25.0")


def test_aneinander_stossende_fenster_sind_erlaubt() -> None:
    """**Die wichtigste Zusicherung der Pruefung.**

    Haette sie die Grenze als Ueberschneidung gelesen, waere der Plan aus
    dem Wunsch des Betreibers nicht eingebbar — man muesste 07:59 tippen
    und haette eine Minute Absenkung mitten am Morgen.
    """
    TagesplanUpdate.model_validate(_eingabe(("06:00", "08:00", "25.0"), ("08:00", "21:00", "22.0")))


def test_ueberschneidung_wird_abgewiesen() -> None:
    with pytest.raises(ValidationError) as fehler:
        TagesplanUpdate.model_validate(
            _eingabe(("06:00", "10:00", "25.0"), ("08:00", "21:00", "22.0"))
        )
    text = str(fehler.value)
    assert "ueberschneiden" in text
    assert "08:00" in text, "die Meldung muss die strittige Uhrzeit nennen"


def test_die_reihenfolge_der_eingabe_verbirgt_keine_ueberschneidung() -> None:
    """Dieselbe Ueberschneidung, rueckwaerts eingegeben.

    Ohne das Sortieren vor der Pruefung waere sie unsichtbar — und die
    Oberflaeche schickt die Zeilen in der Reihenfolge, in der sie getippt
    wurden, nicht in der der Uhr.
    """
    with pytest.raises(ValidationError):
        TagesplanUpdate.model_validate(
            _eingabe(("08:00", "21:00", "22.0"), ("06:00", "10:00", "25.0"))
        )


@pytest.mark.parametrize(
    ("von", "bis"),
    [("23:00", "01:00"), ("08:00", "08:00"), ("24:00", "24:00"), ("12:00", "11:00")],
)
def test_kein_fenster_ueber_mitternacht_und_keines_ohne_dauer(von: str, bis: str) -> None:
    """Ein umschlagendes Fenster wird **abgewiesen**, nicht zerlegt.

    Es automatisch in zwei Zeilen zu zerlegen waere freundlich und falsch:
    danach stuenden im Formular zwei Zeilen, die der Betreiber nicht
    eingegeben hat, und beim naechsten Speichern wuerde er sich fragen,
    woher sie kommen. Die Meldung sagt stattdessen, wie es gemeint ist.
    """
    with pytest.raises(ValidationError) as fehler:
        TagesplanUpdate.model_validate(_eingabe((von, bis, "22.0")))
    assert "Mitternacht" in str(fehler.value)


@pytest.mark.parametrize("eingabe", ["7:30", "25:00", "24:30", "", "12:60"])
def test_eine_falsche_uhrzeit_wird_abgewiesen(eingabe: str) -> None:
    with pytest.raises(ValidationError):
        TagesplanUpdate.model_validate(_eingabe((eingabe, "21:00", "22.0")))


@pytest.mark.parametrize("temperatur", ["5", "9.9", "30.1", "40"])
def test_ein_sollwert_ausserhalb_der_geraetegrenzen_wird_abgewiesen(temperatur: str) -> None:
    """10 bis 30 Grad — die Grenzen der Vicki.

    Dieselben Zahlen stehen als ``CHECK`` an der Tabelle. Die Kappung in
    Schicht 5 wuerde einen Wert darueber ohnehin zurechtbiegen; eine Zahl
    zu speichern, die nie ankommt, waere ein Feld, das etwas anderes
    bewirkt als es sagt.
    """
    with pytest.raises(ValidationError):
        TagesplanUpdate.model_validate(_eingabe(("06:00", "08:00", temperatur)))


def test_ein_leerer_plan_ist_gueltig() -> None:
    """Die leere Liste loescht den Plan — sie ist kein Fehler."""
    assert TagesplanUpdate.model_validate({"fenster": []}).fenster == []


def test_mehr_als_zwoelf_fenster_werden_abgewiesen() -> None:
    zu_viele = tuple(
        (als_text(i * 60), als_text(i * 60 + 30), "22.0") for i in range(MAX_FENSTER + 1)
    )
    with pytest.raises(ValidationError):
        TagesplanUpdate.model_validate(_eingabe(*zu_viele))
