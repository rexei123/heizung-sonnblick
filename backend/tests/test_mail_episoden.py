"""Eine Episode, zwei Mails — der Ablauf der Nacht vom 26./27.11.2026.

**Der echte Ablauf**, Zone Barbereich, wie er im Postfach lag:

====== ====================================== ===========================
22:40  Zonen-Melder: Zone stumm               Minute 0 dieser Datei
23:00  Entwarnung                              +20
01:10  Zonen-Melder: Zone stumm                +150
03:40  Geraet offline: 109 Panel               +300
03:50  Geraet offline: 027 Bar                 +310
06:30  Entwarnung                              +470
====== ====================================== ===========================

Sechs Mails. Dieselbe Nacht mit den Regeln aus diesem PR ergibt **vier**:
die zwei Geraete-Mails entfallen, weil die Zonen-Mail von 01:10 dieselben
zwei Geraete samt letztem Kontakt nennt.

**Die Zeiten sind Abstaende, keine Daten** (Paragraph 5.59, Nachtrag vom
01.11.2026). Der Anker kommt aus der echten Uhr, verglichen wird
ausschliesslich mit Differenzen — damit haengt diese Datei an keinem
Kalender und es gibt keine zweite Zeitquelle.
"""

from __future__ import annotations

import ast
import pathlib
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import redis

from heizung.services import alert_throttle, health_alerts, mailer, redis_client, zonen_episode

#: Die Vorgaben, gegen die gespielt wird (``config.Settings``).
STABIL_MIN = 30
WIEDERHOLUNG_H = 6

#: Der Takt des Beat-Tasks.
TAKT_MIN = 5

#: Minute 0 ist 22:40. Die Zone schweigt in ``[0, 20)`` und ``[150, 470)``.
STUMM_VON_BIS: tuple[tuple[int, int], ...] = ((0, 20), (150, 470))

#: Die beiden Geraete-Mails der echten Nacht.
GERAETE_MAILS_MIN: tuple[int, ...] = (300, 310)

#: Ende der nachgespielten Nacht: 08:00, also 80 Minuten nach der
#: Rueckkehr um 06:30.
ENDE_MIN = 560


class _FakeRedis:
    """Nur ``set`` mit ``nx`` und ``delete`` — mehr braucht die Bremse nicht."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    def set(self, key: str, value: str, *, nx: bool = False, ex: int | None = None) -> bool | None:
        if nx and key in self.store:
            return None
        self.store[key] = value
        return True

    def delete(self, key: str) -> int:
        return 1 if self.store.pop(key, None) is not None else 0


class _Postfach:
    def __init__(self) -> None:
        self.mails: list[dict[str, str]] = []

    def __call__(self, *, recipient: str | None, subject: str, body: str) -> mailer.MailResult:
        self.mails.append({"recipient": recipient or "", "subject": subject, "body": body})
        return mailer.MailResult(True, None, "Testzustellung")


@pytest.fixture
def postfach(monkeypatch: pytest.MonkeyPatch) -> _Postfach:
    p = _Postfach()
    monkeypatch.setattr(health_alerts.mailer, "send_mail", p)
    return p


@pytest.fixture
def fake_redis(monkeypatch: pytest.MonkeyPatch) -> _FakeRedis:
    fake = _FakeRedis()
    monkeypatch.setattr(redis_client, "get_redis_client", lambda: fake)
    return fake


# ---------------------------------------------------------------------------
# Die Nacht, Minute fuer Minute
# ---------------------------------------------------------------------------


def _ist_stumm(minute: int, fenster: tuple[tuple[int, int], ...] = STUMM_VON_BIS) -> bool:
    return any(von <= minute < bis for von, bis in fenster)


class _Verlauf:
    """Spielt den Beat-Takt gegen die Zustandsmaschine.

    Der Zustand liegt am Server im ``business_audit``; hier haelt ihn
    dieses Objekt. Das ist kein Nachbau der Abfrage, sondern ihr
    Ergebnis: ``lies_stand`` liefert genau diese drei Werte, und sie
    haben einen eigenen Test gegen die Datenbank
    (``test_relais_zone_melder``).
    """

    def __init__(self, anker: datetime) -> None:
        self.anker = anker
        self.stand = zonen_episode.Stand()
        #: (Minute, Schritt) je Lauf, der etwas getan hat.
        self.schritte: list[tuple[int, str]] = []

    def tick(self, minute: int, *, stumm: bool) -> str:
        jetzt = self.anker + timedelta(minutes=minute)
        schritt = zonen_episode.naechster_schritt(
            self.stand,
            stumm=stumm,
            jetzt=jetzt,
            wiederholung_h=WIEDERHOLUNG_H,
            stabil_min=STABIL_MIN,
        )
        token = zonen_episode.TOKEN_JE_SCHRITT.get(schritt)
        if token is not None:
            self.schritte.append((minute, schritt))
            self.stand = zonen_episode.Stand(
                aktion=token,
                seit=jetzt,
                letzter_alarm=(
                    jetzt if token == zonen_episode.AKTION_STUMM else self.stand.letzter_alarm
                ),
            )
        return schritt

    @property
    def mails(self) -> list[tuple[int, str]]:
        return [(m, s) for m, s in self.schritte if s in zonen_episode.MIT_MAIL]


def _spiele(fenster: tuple[tuple[int, int], ...] = STUMM_VON_BIS) -> _Verlauf:
    verlauf = _Verlauf(datetime.now(tz=UTC))
    for minute in range(0, ENDE_MIN + 1, TAKT_MIN):
        verlauf.tick(minute, stumm=_ist_stumm(minute, fenster))
    return verlauf


def test_die_echte_nacht_ergibt_vier_zonen_mails_statt_sechs() -> None:
    """**Der Fall, der diesen PR ausgeloest hat.**

    Zwei Episoden, je ein Alarm und eine Entwarnung. Die zwei
    Geraete-Mails um 03:40 und 03:50 fallen in die zweite Episode und
    werden unterdrueckt (eigener Test weiter unten) — aus sechs Mails
    werden vier.

    **Die Wartezeit greift in dieser Nacht nicht**, und das steht hier,
    damit niemand sie fuer die Ursache der Einsparung haelt: die
    Rueckkehr um 23:00 hat zwei Stunden gehalten, die Entwarnung war also
    berechtigt — nur dreissig Minuten zu frueh. Was die Wartezeit
    verhindert, zeigt der Test danach.
    """
    verlauf = _spiele()

    assert verlauf.mails == [
        (0, "alarm"),  # 22:40
        (50, "entwarnung"),  # 23:30 statt 23:00
        (150, "alarm"),  # 01:10
        (500, "entwarnung"),  # 07:00 statt 06:30
    ], f"erwartet zwei Alarme und zwei Entwarnungen, bekommen: {verlauf.mails}"


def test_die_entwarnung_wartet_die_dreissig_minuten_ab() -> None:
    """Zwischen Rueckkehr und Entwarnung liegt die Wartezeit, nicht mehr."""
    verlauf = _spiele()
    schritte = dict(verlauf.schritte)

    assert schritte[20] == "rueckkehr_vermerken", "die Rueckkehr um 23:00 fehlt"
    assert STABIL_MIN == 50 - 20, "die Entwarnung kaeme nicht genau nach der Wartezeit"
    assert all(s != "entwarnung" for m, s in verlauf.schritte if m < 50), (
        "eine Entwarnung vor Ablauf der Wartezeit"
    )


def test_ein_flackern_bleibt_eine_episode() -> None:
    """**Die Variante, in der die Wartezeit traegt.**

    Dieselbe Nacht, aber die Zone meldet um 23:20 wieder nichts — also
    zwanzig Minuten nach der Rueckkehr, innerhalb der Wartezeit. Ohne
    die Regel waeren das zwei Alarme und zwei Entwarnungen; mit ihr ist
    es **eine** Episode.

    Die Entwarnung um 23:00 waere die teure gewesen: wer sie liest, haelt
    den Vorgang fuer abgeschlossen, und zwanzig Minuten spaeter war er es
    nicht — ohne dass jemand es erfahren haette (Paragraph 5.79).

    **Die Wiederholung nach sechs Stunden bleibt**, und das ist kein
    Mangel dieser Rechnung: die Episode laeuft hier von 22:40 bis 06:30,
    also knapp acht Stunden. Eine Zone, die so lange nicht heizt, soll
    sich in Erinnerung rufen — ``relais_zone_wiederholung_h`` ist genau
    dafuer da. Drei Mails fuer acht Stunden statt vier fuer dieselbe
    Nacht, und keine davon behauptet zwischendurch, es sei vorbei.

    Beim ersten Schreiben stand hier die Erwartung „zwei Mails". Der Test
    hat sie widerlegt, nicht der Code — der Eintrag bleibt stehen, weil
    die Zahl sonst wie eine Herleitung aussieht.
    """
    flackern = ((0, 20), (40, 470))
    verlauf = _spiele(flackern)

    assert verlauf.mails == [
        (0, "alarm"),  # 22:40
        (360, "wiederholung"),  # 04:40, sechs Stunden nach dem Alarm
        (500, "entwarnung"),  # 07:00
    ], f"erwartet eine Episode mit Alarm, Wiederholung und Entwarnung: {verlauf.mails}"
    assert all(s != "alarm" for m, s in verlauf.schritte if m > 0), (
        "ein zweiter Alarm in derselben Episode"
    )
    assert "erneut_stumm" in [s for _, s in verlauf.schritte], (
        "der Rueckfall in die Stille ist nicht als solcher vermerkt"
    )


def test_der_rueckfall_erzeugt_keine_zweite_alarmmail() -> None:
    """Ein Alarm, der nie entwarnt wurde, gilt noch."""
    verlauf = _spiele(((0, 20), (40, 470)))
    alarme = [m for m, s in verlauf.schritte if s == "alarm"]
    assert alarme == [0], f"mehr als ein Alarm in einer Episode: {alarme}"


def test_der_rueckfall_setzt_die_wiederholungsbremse_nicht_zurueck() -> None:
    """**Deshalb hat ``erneut_stumm`` ein eigenes Token.**

    Wuerde der Rueckfall als ``RELAIS_ZONE_STUMM`` vermerkt, haenge die
    Wiederholungsbremse an ihm — und ein Link, der alle fuenf Stunden
    einmal flackert, waere **nie** wieder faellig. Die Zone bliebe
    stumm, und nach der ersten Mail kaeme nichts mehr.
    """
    anker = datetime.now(tz=UTC)
    # Alarm vor sechs Stunden und einer Minute, danach ein Flackern.
    stand = zonen_episode.Stand(
        aktion=zonen_episode.AKTION_STUMM_ERNEUT,
        seit=anker - timedelta(minutes=5),
        letzter_alarm=anker - timedelta(hours=WIEDERHOLUNG_H, minutes=1),
    )
    assert (
        zonen_episode.naechster_schritt(
            stand,
            stumm=True,
            jetzt=anker,
            wiederholung_h=WIEDERHOLUNG_H,
            stabil_min=STABIL_MIN,
        )
        == "wiederholung"
    ), "die Wiederholung ist faellig und kommt nicht"


def test_ohne_episode_und_ohne_befund_passiert_nichts() -> None:
    """Der Normalfall, und er darf keine Zeile schreiben."""
    assert (
        zonen_episode.naechster_schritt(
            zonen_episode.Stand(),
            stumm=False,
            jetzt=datetime.now(tz=UTC),
            wiederholung_h=WIEDERHOLUNG_H,
            stabil_min=STABIL_MIN,
        )
        == "nichts"
    )


def test_eine_offene_episode_ohne_versandten_alarm_meldet_statt_zu_schweigen() -> None:
    """Ein Zustand, den diese Maschine nicht erzeugt — und die Richtung.

    Faende sich eine offene Episode ohne einen einzigen versandten Alarm
    in der Historie (von Hand eingetragen, aus einer alten Fassung, aus
    einem halben Lauf), ist die Wahl: schweigen oder melden. Ein
    fehlender Wert darf einen Melder nicht abschalten — dieselbe
    Richtung wie bei einem Uebergang ohne ``heating_zone_id``
    (Paragraph 5.76).
    """
    stand = zonen_episode.Stand(
        aktion=zonen_episode.AKTION_STUMM,
        seit=datetime.now(tz=UTC),
        letzter_alarm=None,
    )
    assert (
        zonen_episode.naechster_schritt(
            stand,
            stumm=True,
            jetzt=datetime.now(tz=UTC),
            wiederholung_h=WIEDERHOLUNG_H,
            stabil_min=STABIL_MIN,
        )
        == "wiederholung"
    )


# ---------------------------------------------------------------------------
# Die zwei Geraete-Mails der echten Nacht
# ---------------------------------------------------------------------------

ZONE_BAR = 4711
ZONE_ANDERS = 4712


def _uebergang(nr: int, *, zone_id: int | None) -> dict[str, Any]:
    """Ein Uebergang, wie ``health_tasks`` ihn sammelt."""
    return {
        "device_id": nr,
        "dev_eui": f"70b3d57ed000{nr:04x}",
        "reason": health_alerts.REASON_OFFLINE,
        "device_name": f"{nr:03d}",
        "room_name": "Bar",
        "zone_name": "Barbereich",
        "heating_zone_id": zone_id,
        "triggered_at": datetime.now(tz=UTC),
        "last_uplink_at": datetime.now(tz=UTC) - timedelta(hours=26),
        "implausible_count_24h": None,
    }


def test_geraete_einer_alarmierten_zone_wecken_nicht_noch_einmal(
    postfach: _Postfach, fake_redis: _FakeRedis
) -> None:
    """03:40 und 03:50 der echten Nacht — zwei Mails, die nichts Neues sagen."""
    ergebnis = health_alerts.handle_silent_transitions(
        [_uebergang(109, zone_id=ZONE_BAR), _uebergang(27, zone_id=ZONE_BAR)],
        recipient="chef@example.com",
        stumme_zonen=frozenset({ZONE_BAR}),
    )

    assert postfach.mails == [], "es ging eine Mail hinaus, obwohl die Zone schon gemeldet ist"
    assert ergebnis.gemeldet == 0
    assert {u["dev_eui"] for u in ergebnis.unterdrueckt} == {
        "70b3d57ed000006d",
        "70b3d57ed000001b",
    }, "die unterdrueckten Geraete gehen nicht an den Aufrufer zurueck"


def test_ohne_laufende_episode_wird_unveraendert_gemeldet(
    postfach: _Postfach, fake_redis: _FakeRedis
) -> None:
    """Die Unterdrueckung ist eine Ausnahme, kein neuer Normalfall."""
    ergebnis = health_alerts.handle_silent_transitions(
        [_uebergang(109, zone_id=ZONE_BAR)],
        recipient="chef@example.com",
        stumme_zonen=frozenset(),
    )
    assert ergebnis.gemeldet == 1
    assert len(postfach.mails) == 1
    assert ergebnis.unterdrueckt == ()


def test_eine_andere_zone_wird_nicht_mitunterdrueckt(
    postfach: _Postfach, fake_redis: _FakeRedis
) -> None:
    """**Der Filter haengt an der Zone, nicht am Haus.**

    Waere er hausweit, haette eine einzige stumme Zone alle
    Geraete-Mails des Hauses abgeschaltet — genau die Sorte Nebenwirkung,
    die man erst bemerkt, wenn eine Meldung ausgeblieben ist.
    """
    ergebnis = health_alerts.handle_silent_transitions(
        [_uebergang(109, zone_id=ZONE_BAR), _uebergang(31, zone_id=ZONE_ANDERS)],
        recipient="chef@example.com",
        stumme_zonen=frozenset({ZONE_BAR}),
    )
    assert ergebnis.gemeldet == 1, "das Geraet der anderen Zone fehlt in der Mail"
    assert [u["dev_eui"] for u in ergebnis.unterdrueckt] == ["70b3d57ed000006d"]
    assert "031" in postfach.mails[0]["body"]


def test_eine_unterdrueckte_mail_verbraucht_kein_zeitfenster(
    postfach: _Postfach, fake_redis: _FakeRedis
) -> None:
    """**Die Reihenfolge von Filter und Bremse ist eine Entscheidung.**

    Stuende die Bremse vorn, waere das Geraet nach der Unterdrueckung
    sechs Stunden gesperrt — und nach dem Ende der Episode bliebe es
    stumm **und** ungemeldet. Der Filter sitzt deshalb davor.
    """
    health_alerts.handle_silent_transitions(
        [_uebergang(109, zone_id=ZONE_BAR)],
        recipient="chef@example.com",
        stumme_zonen=frozenset({ZONE_BAR}),
    )
    assert postfach.mails == []

    # Die Episode ist zu Ende, das Geraet schweigt weiter.
    ergebnis = health_alerts.handle_silent_transitions(
        [_uebergang(109, zone_id=ZONE_BAR)],
        recipient="chef@example.com",
        stumme_zonen=frozenset(),
    )
    assert ergebnis.gemeldet == 1, "die Bremse hat zugeschlagen, obwohl nie eine Mail hinausging"


def test_bei_redis_ausfall_wird_trotzdem_unterdrueckt(
    postfach: _Postfach, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Der Filter haengt nicht an Redis — die Bremse tut das.

    ``alert_throttle`` laesst bei Redis-Ausfall bewusst alles durch
    (lieber eine Mail zuviel als eine zu wenig). Die Unterdrueckung liest
    den Zustand aus dem ``business_audit`` und ist davon unabhaengig.
    Dieser Test haelt fest, dass die beiden Mechanismen nicht
    zusammenhaengen.
    """

    class _Kaputt:
        def set(self, *args: Any, **kwargs: Any) -> None:
            raise redis.ConnectionError("simulierter Ausfall")

        def delete(self, *args: Any, **kwargs: Any) -> None:
            raise redis.ConnectionError("simulierter Ausfall")

    monkeypatch.setattr(redis_client, "get_redis_client", lambda: _Kaputt())
    ergebnis = health_alerts.handle_silent_transitions(
        [_uebergang(109, zone_id=ZONE_BAR)],
        recipient="chef@example.com",
        stumme_zonen=frozenset({ZONE_BAR}),
    )
    assert postfach.mails == []
    assert ergebnis.gemeldet == 0


def test_die_bremse_wird_weiter_je_geraet_gefragt(
    postfach: _Postfach, fake_redis: _FakeRedis
) -> None:
    """Bestandszusage, die dieser PR nicht antasten darf (Sprint 18 / T2)."""
    health_alerts.handle_silent_transitions(
        [_uebergang(109, zone_id=ZONE_ANDERS)], recipient="chef@example.com"
    )
    zweit = health_alerts.handle_silent_transitions(
        [_uebergang(109, zone_id=ZONE_ANDERS)], recipient="chef@example.com"
    )
    assert zweit.gemeldet == 0, "die Wiederholungsbremse je Geraet ist ausgefallen"
    assert len(postfach.mails) == 1
    assert alert_throttle.KIND_DEVICE_SILENT in next(iter(fake_redis.store))


# ---------------------------------------------------------------------------
# Was sofort bleibt
# ---------------------------------------------------------------------------

#: Die Module, die die Episoden-Maschine benutzen **duerfen**.
ERLAUBTE_NUTZER: frozenset[str] = frozenset(
    {
        "tasks/funk_tasks.py",  # schreibt die Episode
        "tasks/health_tasks.py",  # liest sie, um Geraete-Mails zu filtern
    }
)

#: Die vier Wege, die unverzueglich melden — Vorgabe des Betreibers vom
#: 27.11.2026. Sie stehen hier namentlich, damit der Test sagt, **was**
#: er schuetzt, und nicht nur, dass eine Menge gleich ist.
SOFORT: tuple[str, ...] = (
    "tasks/funk_tasks.py:Totalausfall",
    "tasks/schutz_tasks.py:Schutzausloesung",
    "tasks/gehaeuse_tasks.py:Gehaeuse ab 50 Grad",
    "tasks/platten_tasks.py:Platte laeuft voll",
)


def test_nur_zwei_module_kennen_die_episoden_maschine() -> None:
    """**Die vier sofortigen Alarme bleiben ungefiltert.**

    Totalausfall, Schutzausloesung, Gehaeusetemperatur ab 50 Grad und die
    volle Platte gehen unverzueglich hinaus — ohne Episode, ohne
    Sammeln, ohne Ruhezeiten-Filter. Keiner dieser Wege darf die
    Zustandsmaschine benutzen.

    Der Test prueft das an den **Importen** und nicht an einer Absicht im
    Text: wer die Maschine spaeter an einen dieser Melder haengt, bekommt
    hier eine rote Zeile und muss die Entscheidung bewusst treffen. Das
    ist derselbe Wachposten-Entwurf wie bei der Alarmtabelle im RUNBOOK
    — eine Zusage, die nachgerechnet wird, statt eine, die man liest.
    """
    wurzel = pathlib.Path(__file__).resolve().parents[1] / "src" / "heizung"
    nutzer: set[str] = set()
    for datei in wurzel.rglob("*.py"):
        baum = ast.parse(datei.read_text(encoding="utf-8"), filename=str(datei))
        for knoten in ast.walk(baum):
            namen: list[str] = []
            if isinstance(knoten, ast.ImportFrom) and knoten.module:
                namen = [knoten.module, *[a.name for a in knoten.names]]
            elif isinstance(knoten, ast.Import):
                namen = [a.name for a in knoten.names]
            if any("zonen_episode" in n for n in namen):
                nutzer.add(datei.relative_to(wurzel).as_posix())

    assert nutzer == set(ERLAUBTE_NUTZER), (
        f"unerwartete Nutzer der Episoden-Maschine: {sorted(nutzer - ERLAUBTE_NUTZER)}; "
        f"fehlend: {sorted(set(ERLAUBTE_NUTZER) - nutzer)}. "
        f"Diese vier Wege melden unverzueglich: {', '.join(SOFORT)}"
    )


def test_die_vier_sofortigen_wege_existieren_noch() -> None:
    """Der Wachposten oben taugt nur, solange es die vier Dateien gibt.

    Ohne diesen Test waere die Liste ``SOFORT`` eine Behauptung ueber
    Dateien, die es vielleicht nicht mehr gibt — und der Test darueber
    bliebe gruen (Paragraph 5.77).
    """
    wurzel = pathlib.Path(__file__).resolve().parents[1] / "src" / "heizung"
    for eintrag in SOFORT:
        pfad, _, zweck = eintrag.partition(":")
        assert (wurzel / pfad).is_file(), f"{pfad} fehlt, und damit der Weg fuer {zweck}"
