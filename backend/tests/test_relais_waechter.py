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

from heizung.models.device import Device
from heizung.models.enums import WatchdogStrategy
from heizung.rules.relais_waechter import (
    Offen,
    WaechterAktion,
    WaechterSchwellen,
    naechste_aktion,
)
from heizung.tasks import relay_tasks

NOW = datetime(2026, 10, 23, 9, 0, tzinfo=UTC)

SCHWELLEN = WaechterSchwellen(
    timer_expire=timedelta(minutes=30),
    timer_refresh=timedelta(minutes=15),
    refresh_abstand=timedelta(minutes=5),
    bestaetigungs_frist=timedelta(seconds=60),
    max_versuche=3,
    backoff_max=timedelta(minutes=30),
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
    """Einmal melden. Danach laeuft die gedrosselte Wiederholung.

    Die erste Fassung hat hier **nicht weiter gesendet** und den offenen
    Stand geloescht — womit der naechste Durchlauf von vorn begann. Siehe
    ``test_der_alarm_kommt_genau_einmal``.
    """
    offen = Offen(ziel_ein=True, seit=NOW - timedelta(seconds=241), versuche=3)
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

    erschoepft = Offen(ziel_ein=False, seit=NOW - timedelta(seconds=241), versuche=3)
    assert (
        akt(gewuenscht_ein=False, bestaetigt_ein=True, offen=erschoepft).aktion
        is WaechterAktion.ALARM
    )


# ---------------------------------------------------------------------------
# Backoff und Alarm-Haeufigkeit (Freigabe vom 02.11.2026, Punkte 1 und 2)
# ---------------------------------------------------------------------------


def test_die_frist_verdoppelt_sich_je_versuch() -> None:
    """**Der Befund vom 01.11.2026, 11:22 bis 11:28.**

    Die feste Frist von 60 Sekunden lag genau auf dem Tick-Intervall:
    jeder Durchlauf erzeugte einen Downlink, jeder bei SF12 ueber RX2 mit
    1,32 Sekunden Sendezeit.

    Gepruef wird die Grenze von **beiden** Seiten, sonst haelt der Test
    auch eine Frist fest, die gar nicht waechst.
    """
    for versuche, frist_s in ((1, 60), (2, 120), (3, 240)):
        offen_knapp_davor = Offen(
            ziel_ein=True, seit=NOW - timedelta(seconds=frist_s - 1), versuche=versuche
        )
        assert (
            akt(gewuenscht_ein=True, bestaetigt_ein=False, offen=offen_knapp_davor).aktion
            is WaechterAktion.WARTE
        ), f"bei {versuche} Versuchen darf vor {frist_s} s nichts hinausgehen"

        offen_danach = Offen(
            ziel_ein=True, seit=NOW - timedelta(seconds=frist_s + 1), versuche=versuche
        )
        e = akt(gewuenscht_ein=True, bestaetigt_ein=False, offen=offen_danach)
        assert e.aktion in (WaechterAktion.SENDE_EIN, WaechterAktion.ALARM), (
            f"bei {versuche} Versuchen muss nach {frist_s} s etwas passieren: {e}"
        )


def test_die_frist_ist_bei_einer_halben_stunde_gekappt() -> None:
    """Ohne Kappung waeren es bei zehn Versuchen rund acht Stunden.

    Ein Geraet, das nach einer Funkstoerung zurueckkommt, soll innerhalb
    einer halben Stunde wieder angesprochen werden — nicht am naechsten
    Tag.
    """
    offen = Offen(ziel_ein=True, seit=NOW - timedelta(minutes=29), versuche=10)
    assert akt(gewuenscht_ein=True, bestaetigt_ein=False, offen=offen).aktion is (
        WaechterAktion.WARTE
    )

    offen_spaeter = Offen(ziel_ein=True, seit=NOW - timedelta(minutes=31), versuche=10)
    e = akt(gewuenscht_ein=True, bestaetigt_ein=False, offen=offen_spaeter)
    assert e.aktion is WaechterAktion.SENDE_EIN
    assert e.grund == "wiederholung_gedrosselt_11"


def test_der_alarm_kommt_genau_einmal() -> None:
    """**Der Kern des Befunds.** ``max_versuche`` hat nichts begrenzt.

    Der Alarm loeschte den offenen Stand, der naechste Durchlauf begann
    die Zaehlung von vorn: drei Versuche, Alarm, loeschen, drei
    Versuche — ein Downlink je Minute, endlos. Ein Melder, der sich
    selbst zurueckstellt, ueberwacht nichts (§5.79).

    Jetzt haengt der Alarm an **genau** ``versuche == max_versuche``. Der
    Aufrufer zaehlt hoch, ohne zu senden; alles darueber ist gedrosselte
    Wiederholung ohne weitere Meldung.
    """
    weit_genug = NOW - timedelta(hours=2)

    alarm = akt(
        gewuenscht_ein=True,
        bestaetigt_ein=False,
        offen=Offen(ziel_ein=True, seit=weit_genug, versuche=3),
    )
    assert alarm.aktion is WaechterAktion.ALARM

    danach = akt(
        gewuenscht_ein=True,
        bestaetigt_ein=False,
        offen=Offen(ziel_ein=True, seit=weit_genug, versuche=4),
    )
    assert danach.aktion is WaechterAktion.SENDE_EIN, "kein zweiter Alarm, aber auch keine Stille"
    assert danach.grund == "wiederholung_gedrosselt_5"


def test_aufgeben_gibt_es_nicht() -> None:
    """Auch nach vielen Versuchen bleibt ein Weg zurueck.

    Endgueltig aufzugeben waere die naheliegende Lesart von „dann
    Befund". Sie hiesse: ein Relais an der Funkgrenze verliert irgendwann
    drei Bestaetigungen in Folge — bei den am 01.11. gemessenen 30 %
    Verlust kein Ausnahmefall — und der Waechter legt es **dauerhaft**
    still, ohne dass am Geraet etwas kaputt ist. Der Preis fuer den Weg
    zurueck ist ein Downlink je halbe Stunde, also 1,3 Sekunden
    Sendezeit.
    """
    offen = Offen(ziel_ein=True, seit=NOW - timedelta(days=1), versuche=99)
    e = akt(gewuenscht_ein=True, bestaetigt_ein=False, offen=offen)
    assert e.aktion is WaechterAktion.SENDE_EIN
    assert e.sekunden == 1800


# ---------------------------------------------------------------------------
# Ein offener Befehl, der dem Wunsch widerspricht (Punkt 3 der Freigabe)
# ---------------------------------------------------------------------------


def test_ein_haengendes_ein_wird_nicht_wiederholt_wenn_aus_gewuenscht_ist() -> None:
    """**Der Fall, der den Punkt noetig macht.**

    Ein EIN geht hinaus, das Geraet schaltet, der bestaetigende Uplink
    geht verloren. Fuer uns ist das Relais AUS, waehrend es heizt; der
    Raum wird warm, der Regler will AUS.

    Die erste Fassung gab dem **offenen Befehl** Vorrang und hat damit
    das EIN wiederholt — also genau den Befehl, den niemand mehr wollte.
    Jetzt wird der offene Stand uebergangen; dass hier nichts gesendet
    wird, liegt am gemeldeten Zustand (AUS) und nicht am offenen Befehl.
    """
    offen = Offen(ziel_ein=True, seit=NOW - timedelta(seconds=61), versuche=1)
    e = akt(gewuenscht_ein=False, bestaetigt_ein=False, offen=offen)
    assert e.aktion is not WaechterAktion.SENDE_EIN, "kein EIN gegen den Wunsch"
    assert e.aktion is WaechterAktion.NICHTS
    assert e.grund == "bereits_aus"


def test_aus_geht_hinaus_obwohl_ein_ein_offen_ist() -> None:
    """Das Panel meldet EIN, der Regler will AUS, ein EIN ist offen.

    Der offene Stand darf das AUS nicht bremsen. **Vorrang hat die
    Bestaetigung** — meldet das Geraet EIN, waehrend ein EIN offen ist,
    ist der Befehl erledigt, und erst der naechste Durchlauf schaltet ab.
    Ohne offenen Stand geht das AUS sofort.
    """
    offen = Offen(ziel_ein=True, seit=NOW - timedelta(seconds=61), versuche=1)
    erledigt = akt(gewuenscht_ein=False, bestaetigt_ein=True, offen=offen)
    assert erledigt.grund == "bestaetigt", "der Aufrufer loescht den Stand und zaehlt den Zyklus"

    danach = akt(gewuenscht_ein=False, bestaetigt_ein=True, offen=None)
    assert danach.aktion is WaechterAktion.SENDE_AUS


def test_ein_offenes_aus_unterliegt_weiter_dem_backoff() -> None:
    """Die Ausnahme gilt nur fuer den **widersprechenden** Befehl.

    Ein offenes AUS bei AUS-Wunsch wird nicht sofort nachgeschickt —
    sonst waere die Drossel genau dort ausgehebelt, wo sie am noetigsten
    ist: ein Relais, das ein AUS nicht bestaetigt, bekaeme wieder jede
    Minute einen Downlink.
    """
    offen = Offen(ziel_ein=False, seit=NOW - timedelta(seconds=30), versuche=1)
    e = akt(gewuenscht_ein=False, bestaetigt_ein=True, offen=offen)
    assert e.aktion is WaechterAktion.WARTE
    assert e.grund == "frist_laeuft"


def test_ein_ersetzter_befehl_zaehlt_von_vorn() -> None:
    """Die Versuchszaehlung gilt je **Ziel**, nicht je Geraet.

    Der Weg dorthin ist eng, und ohne ihn waere der Zweig toter Code —
    er braucht die Strategie ``REFRESH``: das Relais ist EIN, ein
    unbestaetigtes **AUS** steht offen, und der Regler will EIN. Dann
    frischt der Waechter auf, und der neue Befehl erbt ohne diese
    Unterscheidung das erschoepfte Budget des AUS. Folge: der frische
    EIN-Befehl wartet sofort die gedrosselten 30 Minuten ab, und der
    Alarm bleibt aus, weil er an ``versuche == max_versuche`` haengt.

    ``REFRESH`` ist heute nicht in Betrieb (AE-78 §4, Freigabe des
    Betreibers steht aus) — der Zweig ist also Vorsorge, und der Test
    sagt, wofuer.
    """
    offen_aus = Offen(ziel_ein=False, seit=NOW - timedelta(seconds=61), versuche=3)
    e = akt(
        gewuenscht_ein=True,
        bestaetigt_ein=True,
        offen=offen_aus,
        strategie=REFRESH,
        letzter_ein_befehl=NOW - timedelta(minutes=10),
    )
    assert e.aktion is WaechterAktion.SENDE_EIN
    assert e.grund == "auffrischung"

    geraet = Device(dev_eui="deadbeef00000001", pending_attempts=3)
    relay_tasks._setze_offen(geraet, ziel_ein=True, jetzt=NOW, offen=offen_aus)
    assert geraet.pending_attempts == 1, "anderes Ziel, also ein anderer Befehl"

    offen_ein = Offen(ziel_ein=True, seit=NOW, versuche=1)
    relay_tasks._setze_offen(geraet, ziel_ein=True, jetzt=NOW, offen=offen_ein)
    assert geraet.pending_attempts == 2, "dasselbe Ziel zaehlt weiter"


def test_ein_offenes_aus_wird_nicht_wiederholt_wenn_ein_gewuenscht_ist() -> None:
    """Dieselbe Regel in die andere Richtung, ohne Sonderfall.

    Das Geraet meldet EIN, ein unbestaetigtes AUS ist offen, und der
    Regler will wieder EIN. Die erste Fassung haette das **AUS**
    wiederholt. Jetzt zaehlt der Wunsch: das Relais ist an, es soll an
    sein, also laeuft der Timer ab (Standardstrategie, S2). Der
    widersprechende offene Stand wird vom Aufrufer geloescht.
    """
    offen = Offen(ziel_ein=False, seit=NOW - timedelta(seconds=61), versuche=1)
    e = akt(gewuenscht_ein=True, bestaetigt_ein=True, offen=offen)
    assert e.aktion is not WaechterAktion.SENDE_AUS, "kein AUS gegen den Wunsch"
    assert e.aktion is WaechterAktion.NICHTS
    assert e.grund == "laeuft_ab_von_selbst"


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


# ---------------------------------------------------------------------------
# Die Strategie kommt aus einer String-Spalte
# ---------------------------------------------------------------------------


def test_rohe_strategie_zeichenkette_verhaelt_sich_wie_das_enum() -> None:
    """**Der Fall, den der Ende-zu-Ende-Test gefunden hat.**

    ``device.watchdog_strategy`` ist ``String(20)``. Die erste Fassung
    verglich im Waechter mit ``is`` gegen das Enum-Mitglied — ein roher
    String ist damit **nicht** identisch, und der Vergleich fiel still in
    den ``else``-Zweig, also in die riskantere ``REFRESH``-Strategie,
    ohne dass sie jemand gewaehlt hatte.

    Der Orchestrator wandelt inzwischen am Rand um. Dieser Test haelt
    zusaetzlich fest, dass der Waechter auch mit dem rohen Wert richtig
    liegt — in der sicheren Richtung nachgiebig, statt still das
    Gegenteil zu tun.
    """
    e = naechste_aktion(
        strategie="expire_and_resend",  # type: ignore[arg-type]
        gewuenscht_ein=True,
        bestaetigt_ein=True,
        offen=None,
        letzter_ein_befehl=None,
        schwellen=SCHWELLEN,
        now=NOW,
    )
    assert e.aktion is WaechterAktion.NICHTS
    assert e.grund == "laeuft_ab_von_selbst", (
        "mit 'is' statt '==' waere hier auffrischung_ohne_vorbefehl "
        "herausgekommen — also ein 0x57 auf ein laufendes EIN (S2-Bruch)"
    )
