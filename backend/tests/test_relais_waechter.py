"""Waechter-Tests (Sprint 24, Paket C, S1/S2).

Reine Funktion, keine Datenbank, ``now`` als Pflicht-Argument — also
auch keine Zeitbombe (§5.59).

Die beiden Mutationsproben des Briefs, die hier hingehoeren:

- **M1** EIN ueber ``0xC1`` statt ``0x57``. Der Waechter kann das
  strukturell nicht: ``SENDE_EIN`` traegt eine Dauer, und die
  Befehlsschicht hat keine Funktion, die ``0xC1 01`` baut. Der Test
  dazu haelt fest, dass jedes EIN eine Dauer nennt.
- **M2** ``0x57`` gesendet, obwohl der zuletzt bestaetigte Zustand EIN
  ist (Standardstrategie). Das ist der Kern von S2.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from heizung.models.enums import WatchdogStrategy
from heizung.rules.relais_waechter import (
    Offen,
    WaechterAktion,
    WaechterSchwellen,
    naechste_aktion,
)

NOW = datetime(2026, 10, 23, 9, 0, tzinfo=UTC)

SCHWELLEN = WaechterSchwellen(
    timer_expire=timedelta(minutes=30),
    timer_refresh=timedelta(minutes=15),
    refresh_abstand=timedelta(minutes=5),
    bestaetigungs_frist=timedelta(seconds=60),
    max_versuche=3,
)

EXPIRE = WatchdogStrategy.EXPIRE_AND_RESEND
REFRESH = WatchdogStrategy.REFRESH


def akt(
    *,
    gewuenscht_ein: bool,
    bestaetigt_ein: bool | None,
    strategie: WatchdogStrategy = EXPIRE,
    offen: Offen | None = None,
    letzter_ein_befehl: datetime | None = None,
    now: datetime = NOW,
):
    return naechste_aktion(
        strategie=strategie,
        gewuenscht_ein=gewuenscht_ein,
        bestaetigt_ein=bestaetigt_ein,
        offen=offen,
        letzter_ein_befehl=letzter_ein_befehl,
        schwellen=SCHWELLEN,
        now=now,
    )


# ---------------------------------------------------------------------------
# S1 — EIN nur mit Dauer
# ---------------------------------------------------------------------------


def test_jedes_ein_traegt_eine_dauer() -> None:
    """**Mutationsprobe M1 in Testform.**

    Es gibt keinen Weg zu einem EIN ohne Dauer. Ein ``0xC1 01`` waere
    genau das: ein EIN ohne Ablauf. Der Waechter kann es nicht
    ausdruecken, weil ``SENDE_EIN`` immer ``sekunden`` traegt — und die
    Befehlsschicht hat gar keine Funktion dafuer.
    """
    e = akt(gewuenscht_ein=True, bestaetigt_ein=False)
    assert e.aktion is WaechterAktion.SENDE_EIN
    assert e.sekunden == 1800, "30 min bei der Standardstrategie"


def test_refresh_nimmt_die_kuerzere_laufzeit() -> None:
    """15 min statt 30: die kurze Zeit ist der Sinn dieser Strategie.

    Sie ist die Obergrenze fuer die Zeit, die ein Panel nach einem
    Serverausfall noch heizt.
    """
    e = akt(gewuenscht_ein=True, bestaetigt_ein=False, strategie=REFRESH)
    assert e.sekunden == 900


def test_aus_traegt_keine_dauer() -> None:
    e = akt(gewuenscht_ein=False, bestaetigt_ein=True)
    assert e.aktion is WaechterAktion.SENDE_AUS
    assert e.sekunden is None


# ---------------------------------------------------------------------------
# S2 — kein 0x57 auf ein laufendes EIN (Standardstrategie)
# ---------------------------------------------------------------------------


def test_standardstrategie_setzt_nicht_auf_ein_laufendes_ein_nach() -> None:
    """**Mutationsprobe M2 in Testform, und der Kern von S2.**

    Das Relais ist bestaetigt EIN und soll EIN bleiben. Die
    Standardstrategie sendet **nichts** — der Timer laeuft ab, das
    Geraet meldet den Wechsel, und erst dann wird neu gesetzt.

    Warum nicht nachsetzen: die Doku definiert nicht, was „previous
    state" bedeutet, wenn ein Timer-Befehl waehrend eines laufenden
    Timers eintrifft (AE-78 §4). Bedeutet es „der Zustand vor diesem
    Befehl", schreibt das Nachsetzen EIN als Rueckfallzustand fest, und
    das Relais bleibt dauerhaft EIN.
    """
    e = akt(gewuenscht_ein=True, bestaetigt_ein=True)
    assert e.aktion is WaechterAktion.NICHTS
    assert e.grund == "laeuft_ab_von_selbst"


def test_nach_dem_ablauf_wird_neu_gesetzt() -> None:
    """Der Zyklus der Standardstrategie: Geraet meldet AUS, wir setzen neu."""
    e = akt(gewuenscht_ein=True, bestaetigt_ein=False)
    assert e.aktion is WaechterAktion.SENDE_EIN
    assert e.grund == "ein_gewuenscht"


# ---------------------------------------------------------------------------
# REFRESH — nachsetzen, aber nur im Abstand
# ---------------------------------------------------------------------------


def test_refresh_frischt_im_abstand_auf() -> None:
    e = akt(
        gewuenscht_ein=True,
        bestaetigt_ein=True,
        strategie=REFRESH,
        letzter_ein_befehl=NOW - timedelta(minutes=5),
    )
    assert e.aktion is WaechterAktion.SENDE_EIN
    assert e.grund == "auffrischung"


def test_refresh_frischt_vor_dem_abstand_nicht_auf() -> None:
    """Sonst waere jeder Tick ein Downlink — Sendezeit ohne Gewinn (§0 S4)."""
    e = akt(
        gewuenscht_ein=True,
        bestaetigt_ein=True,
        strategie=REFRESH,
        letzter_ein_befehl=NOW - timedelta(minutes=4, seconds=59),
    )
    assert e.aktion is WaechterAktion.NICHTS
    assert e.grund == "auffrischung_noch_nicht_faellig"


def test_refresh_ohne_vorbefehl_setzt_sofort() -> None:
    """Bestaetigt EIN, aber wir wissen nicht, wann wir das gesetzt haben.

    Das ist der Zustand nach einem Neustart des Servers. Sofort
    nachzusetzen ist hier die sichere Richtung: der laufende Timer
    koennte in einer Sekunde ablaufen.
    """
    e = akt(gewuenscht_ein=True, bestaetigt_ein=True, strategie=REFRESH)
    assert e.aktion is WaechterAktion.SENDE_EIN
    assert e.grund == "auffrischung_ohne_vorbefehl"


# ---------------------------------------------------------------------------
# Unbekannter Zustand
# ---------------------------------------------------------------------------


def test_unbekannter_zustand_schaltet_nicht_ein() -> None:
    """``None`` ist nicht AUS.

    Die naheliegende Vereinfachung waere, einen unbekannten Zustand als
    AUS zu lesen. Dann wuerde der erste Befehl ein Relais einschalten,
    von dem wir nicht wissen, ob es schon heizt — und bei einem
    Panel, das wir nicht sehen, ist das die falsche Richtung.
    """
    e = akt(gewuenscht_ein=True, bestaetigt_ein=None)
    assert e.aktion is WaechterAktion.NICHTS
    assert e.grund == "zustand_unbekannt"


def test_unbekannter_zustand_sendet_auch_kein_aus() -> None:
    """Ein ``0xC1 00`` ins Blaue ist Sendezeit ohne Wirkung."""
    e = akt(gewuenscht_ein=False, bestaetigt_ein=None)
    assert e.aktion is WaechterAktion.NICHTS


# ---------------------------------------------------------------------------
# Bestaetigung, Wiederholung, Alarm
# ---------------------------------------------------------------------------


def test_offener_befehl_wartet_innerhalb_der_frist() -> None:
    offen = Offen(ziel_ein=True, seit=NOW - timedelta(seconds=30), versuche=1)
    e = akt(gewuenscht_ein=True, bestaetigt_ein=False, offen=offen)
    assert e.aktion is WaechterAktion.WARTE
    assert e.grund == "frist_laeuft"


def test_bestaetigter_befehl_ist_erledigt() -> None:
    offen = Offen(ziel_ein=True, seit=NOW - timedelta(seconds=5), versuche=1)
    e = akt(gewuenscht_ein=True, bestaetigt_ein=True, offen=offen)
    assert e.aktion is WaechterAktion.NICHTS
    assert e.grund == "bestaetigt"


def test_nach_der_frist_wird_wiederholt() -> None:
    offen = Offen(ziel_ein=True, seit=NOW - timedelta(seconds=61), versuche=1)
    e = akt(gewuenscht_ein=True, bestaetigt_ein=False, offen=offen)
    assert e.aktion is WaechterAktion.SENDE_EIN
    assert e.grund == "wiederholung_2"
    assert e.sekunden == 1800


def test_nach_drei_versuchen_kommt_der_alarm() -> None:
    """Nicht weiter senden. Jeder Downlink ist Sendezeit, und ein Geraet
    an der Funkgrenze wuerde sonst bei jedem Tick angefunkt — dieselbe
    Begruendung wie beim Engine-Abgleich (Sprint 20f T3)."""
    offen = Offen(ziel_ein=True, seit=NOW - timedelta(seconds=61), versuche=3)
    e = akt(gewuenscht_ein=True, bestaetigt_ein=False, offen=offen)
    assert e.aktion is WaechterAktion.ALARM
    assert e.grund == "keine_bestaetigung_nach_3_versuchen"


def test_auch_ein_aus_wird_wiederholt_und_alarmiert() -> None:
    """Die Wiederholung gilt in **beide** Richtungen.

    Ein unbestaetigtes AUS ist der unangenehmere Fall: das Panel heizt
    womoeglich weiter. Ohne diesen Zweig waere nur das EIN abgesichert.
    """
    offen = Offen(ziel_ein=False, seit=NOW - timedelta(seconds=61), versuche=1)
    e = akt(gewuenscht_ein=False, bestaetigt_ein=True, offen=offen)
    assert e.aktion is WaechterAktion.SENDE_AUS
    assert e.grund == "wiederholung_2"

    erschoepft = Offen(ziel_ein=False, seit=NOW - timedelta(seconds=61), versuche=3)
    assert (
        akt(gewuenscht_ein=False, bestaetigt_ein=True, offen=erschoepft).aktion
        is WaechterAktion.ALARM
    )


def test_offener_befehl_hat_vorrang_vor_einem_neuen_wunsch() -> None:
    """Erst die Bestaetigung, dann Neues.

    Haette der Wunsch Vorrang, koennten sich bei einem Regler, der
    zwischen EIN und AUS pendelt, zwei unbestaetigte Befehle
    ueberlagern — und am Ende wuesste niemand, welcher gilt.
    """
    offen = Offen(ziel_ein=True, seit=NOW - timedelta(seconds=10), versuche=1)
    e = akt(gewuenscht_ein=False, bestaetigt_ein=False, offen=offen)
    assert e.aktion is WaechterAktion.WARTE


# ---------------------------------------------------------------------------
# AUS
# ---------------------------------------------------------------------------


def test_aus_gewuenscht_und_ein_bestaetigt_schaltet_aus() -> None:
    e = akt(gewuenscht_ein=False, bestaetigt_ein=True)
    assert e.aktion is WaechterAktion.SENDE_AUS
    assert e.grund == "aus_gewuenscht"


def test_aus_gewuenscht_und_aus_bestaetigt_tut_nichts() -> None:
    e = akt(gewuenscht_ein=False, bestaetigt_ein=False)
    assert e.aktion is WaechterAktion.NICHTS
    assert e.grund == "bereits_aus"


def test_aus_gilt_in_beiden_strategien_gleich() -> None:
    """Die Strategien unterscheiden sich nur beim EIN.

    Das ist Absicht: ein AUS hat keine Dauer und keinen Timer, es gibt
    also nichts zu unterscheiden. Dieser Test haelt fest, dass niemand
    eine Strategie-Verzweigung in den AUS-Pfad einbaut.
    """
    for strategie in (EXPIRE, REFRESH):
        e = akt(gewuenscht_ein=False, bestaetigt_ein=True, strategie=strategie)
        assert e.aktion is WaechterAktion.SENDE_AUS
        assert e.sekunden is None
