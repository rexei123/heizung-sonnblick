"""Sprint 20f-b — die Engine darf ihren eigenen Zustand nicht als Gastwunsch lesen.

**Der Befund, am 06.10.2026 in Zimmer 101 belegt.** Fuenf aktive Overrides in
einer Zone, drei davon mit ``source=device`` und Ablauf erst beim Check-out.
Niemand hatte gedreht.

Die Zeitlinie vom 05.10.2026, Geraete 009 (Zone 204) und 010 (Zone 205):

    20:00:59  Engine sendet Nachtabsenkung 19 °C
    20:03:25  Keep-alive meldet noch **21** — Class-A-Latenz, das Geraet hat
              den Befehl noch nicht umgesetzt
              -> alte Erkennung sieht "21 statt 19" und legt Override 40 mit
                 **21 °C** an, Ablauf Check-out
    (Engine regelt jetzt auf 21, weil der Override das sagt)
    20:13:36  Geraet meldet **19** — der erste Befehl ist angekommen
              -> alte Erkennung sieht "19 statt 21" und legt Override 42 mit
                 **19 °C** an

Ping-Pong. Beide Overrides sind Phantome.

**Und es war kein Einzelfall, sondern der Normalfall.** Die Bedingung ist
"Engine aendert den Sollwert in einem belegten Zimmer" — also **jede
Nachtabsenkung in jedem belegten Zimmer, jede Nacht**. Jede davon haette
einen Phantom-Override bis zum Check-out erzeugt.

Das 60-s-Ack-Fenster haette das abfangen sollen und kann es nicht: es wird ab
dem **MQTT-Publish** gemessen, nicht ab dem Funk-Versand, und bei Class A
liegen dazwischen bis zu eine Keep-alive-Periode. Von 20:00:59 bis 20:03:25
sind 146 Sekunden.

Diese Datei prueft den Torwaechter: **nur ein ``0x28``-Frame fuehrt zu einem
Override.** Reine Logik mit einem Doppelgaenger fuer die Override-Anlage,
keine Datenbank — deshalb laufen die Tests auch lokal (B-18-5).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from heizung.services import mqtt_subscriber
from heizung.services.mqtt_subscriber import (
    MANUAL_TARGET_REPORT_TYPE,
    ChirpStackUplink,
    _handle_override_detection,
)

DEV_EUI = "70b3d52dd3033393"


def _uplink(obj: dict[str, Any], *, fcnt: int = 100) -> ChirpStackUplink:
    """Ein Uplink mit dem gegebenen Codec-Objekt."""
    return ChirpStackUplink.model_validate(
        {
            "deviceInfo": {"devEui": DEV_EUI},
            "fCnt": fcnt,
            "fPort": 2,
            "time": "2026-10-05T20:03:25Z",
            "object": obj,
            "rxInfo": [{"rssi": -90, "snr": 9.0}],
            "data": "gRKdYZmZEeAw",
        }
    )


class _FakeResult:
    def scalar_one_or_none(self) -> int:
        return 7


class _FakeSession:
    """Loest ``dev_eui -> device_id`` auf, sonst nichts."""

    async def execute(self, *_args: object, **_kwargs: object) -> _FakeResult:
        return _FakeResult()

    async def commit(self) -> None:
        return None

    async def __aenter__(self) -> _FakeSession:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        return None


class Mitschrift:
    """Was der Pfad versucht hat: Override-Anlagen und geoeffnete Sessions."""

    def __init__(self) -> None:
        self.versuche: list[dict[str, object]] = []
        self.sitzungen = 0


@pytest.fixture
def mitschrift(monkeypatch: pytest.MonkeyPatch) -> Mitschrift:
    """Faengt jeden Versuch ab, einen Override anzulegen — und jede Session.

    Gezaehlt wird am **Eingang** von ``handle_uplink_for_override``, nicht am
    Ergebnis: der Torwaechter soll den Pfad gar nicht erst betreten. Ein Test,
    der nur auf "kein Override in der Datenbank" prueft, waere auch gruen,
    wenn der Pfad laeuft und erst ein spaeteres Tor greift — und genau die
    spaeteren Tore (OCCUPIED, Fenster) sind im Phantom-Fall **offen**, weil
    das Zimmer belegt ist.

    ``sitzungen`` ist die zweite, haertere Zusicherung: ein abgewiesener Frame
    darf nicht einmal eine Datenbank-Verbindung kosten. Bei 104 Geraeten und
    einem Keep-alive alle zehn Minuten waere das sonst eine Session je
    Uplink, fuer nichts.
    """
    m = Mitschrift()

    async def _falle(*_args: object, **kwargs: object) -> None:
        m.versuche.append(kwargs)
        return

    def _session() -> _FakeSession:
        m.sitzungen += 1
        return _FakeSession()

    monkeypatch.setattr(mqtt_subscriber, "handle_uplink_for_override", _falle)
    monkeypatch.setattr(mqtt_subscriber, "SessionLocal", _session)
    return m


def m_leer(m: Mitschrift) -> bool:
    """Kein Override-Versuch **und** keine Session — beides muss stimmen."""
    return m.versuche == [] and m.sitzungen == 0


# ---------------------------------------------------------------------------
# 1. Die Sequenz vom 05.10.2026 — der Befund als Test
# ---------------------------------------------------------------------------


async def test_nachtabsenkung_in_belegtem_zimmer_erzeugt_keinen_override(
    mitschrift: Mitschrift,
) -> None:
    """**Die Regressions-Wand.** Genau die Sequenz, die 40 und 42 erzeugt hat.

    Zwei Keep-alives: der erste meldet noch den alten Sollwert (21), weil das
    Geraet die Absenkung noch nicht umgesetzt hat; der zweite meldet den neuen
    (19), nachdem sie angekommen ist. Beide haben am 05.10. je einen Override
    bis zum Check-out erzeugt.

    Erwartung: **kein einziger Versuch**, einen Override anzulegen.
    """
    # 20:03:25 — Geraet haelt noch 21, Engine hat 19 geschickt.
    noch_alt = _uplink(
        {"report_type": "periodic", "command": 129, "target_temperature": 21},
        fcnt=110,
    )
    # 20:13:36 — Geraet hat 19 uebernommen.
    jetzt_neu = _uplink(
        {"report_type": "periodic", "command": 129, "target_temperature": 19},
        fcnt=111,
    )

    await _handle_override_detection(noch_alt)
    await _handle_override_detection(jetzt_neu)

    assert m_leer(mitschrift), "ein Keep-alive darf keinen Override erzeugen"


async def test_setpoint_reply_erzeugt_keinen_override(
    mitschrift: Mitschrift,
) -> None:
    """Die zweite Haelfte des Befunds: das eigene Echo.

    ``0x52`` ist die Bestaetigung **unseres** Downlinks. Bis Sprint 20f-b lief
    die Erkennung auch darauf — der alte Kommentar an der Aufrufstelle lautete
    "der Drehring meldet seinen Setpoint hier zurueck". Das war richtig,
    solange ``0x52`` die einzige Spur einer Drehung war; seit ``0x28``
    dekodiert wird, ist es zirkulaer: die Engine adoptiert ihren eigenen
    Befehl.
    """
    reply = _uplink(
        {
            "report_type": "setpoint_reply",
            "command": 0x52,
            "target_temperature": 21.0,
            "acknowledged": True,
        }
    )

    await _handle_override_detection(reply)

    assert m_leer(mitschrift)


@pytest.mark.parametrize(
    "report_type",
    ["periodic", "setpoint_reply", "firmware_version_reply", "open_window_status_reply"],
)
async def test_kein_anderer_frame_typ_kommt_durch(mitschrift: Mitschrift, report_type: str) -> None:
    """Der Torwaechter laesst **nur** ``manual_target_change`` durch.

    Aufgezaehlt statt "alles ausser 0x28", damit ein neu hinzukommender
    Frame-Typ nicht stillschweigend in den Override-Pfad rutscht: wer einen
    ergaenzt, muss diese Liste anfassen und dabei entscheiden.
    """
    await _handle_override_detection(
        _uplink({"report_type": report_type, "target_temperature": 20})
    )

    assert m_leer(mitschrift)


async def test_frame_ohne_report_type_kommt_nicht_durch(
    mitschrift: Mitschrift,
) -> None:
    """Ein Objekt ohne ``report_type`` ist kein Freifahrtschein.

    Der Fall ist real: ein Frame, den der Codec nicht deuten kann, liefert ein
    Objekt ohne das Feld (so entstanden die NULL-Zeilen, an denen der
    Vor-Check gescheitert ist). Die Bedingung ist deshalb auf Gleichheit
    formuliert und nicht als Ausschlussliste.
    """
    await _handle_override_detection(_uplink({"target_temperature": 20}))

    assert m_leer(mitschrift)


# ---------------------------------------------------------------------------
# 2. Die Gegenprobe: eine echte Drehung kommt durch
# ---------------------------------------------------------------------------


async def test_handverstellung_kommt_durch(
    mitschrift: Mitschrift,
) -> None:
    """Ohne diesen Test waere ein ``return`` am Funktionsanfang auch gruen.

    Der Torwaechter soll genau eine Sorte Frame durchlassen — nicht keine.
    """
    await _handle_override_detection(
        _uplink(
            {
                "report_type": MANUAL_TARGET_REPORT_TYPE,
                "command": 0x28,
                "manual_target_temperature": 22,
                "target_temperature": 22,
                "manual_target_history": [22],
            }
        )
    )

    assert len(mitschrift.versuche) == 1
    assert mitschrift.versuche[0]["uplink_target_temp"] == 22


async def test_handverstellung_ohne_sollwert_kommt_nicht_durch(
    mitschrift: Mitschrift,
) -> None:
    """Auch ein ``0x28`` braucht einen Wert.

    Der Fall entsteht beim zu kurzen Frame (unter zwei Byte): der Codec
    emittiert ``report_type`` und ``command``, aber kein
    ``target_temperature``. Ohne Wert gibt es nichts zu uebernehmen.
    """
    await _handle_override_detection(
        _uplink({"report_type": MANUAL_TARGET_REPORT_TYPE, "command": 0x28})
    )

    assert m_leer(mitschrift)


# ---------------------------------------------------------------------------
# 4. Welche Uhr steht in ``received_at``? — die Merge-Bedingung zu #393
# ---------------------------------------------------------------------------


async def test_received_at_ist_die_gateway_zeit_aus_dem_uplink(
    mitschrift: Mitschrift,
) -> None:
    """``received_at`` ist ``uplink.time``, **nicht** die Serverzeit.

    **Warum dieser Test existiert.** Der Fix in ``device_adapter`` grenzt
    das Ack-Fenster auf Befehle ein, die **vor** dem Uplink an das Gateway
    gingen (``sent_to_gateway_at <= received_at``). Welche Uhr in
    ``received_at`` steht, entscheidet damit, was der Fix tut — und die
    Rechnung zum Fall Zimmer 209 ist mit ``uplink.time`` gemacht
    (07:00:16.774). Waere es die Verarbeitungszeit des Servers, laege sie
    vermutlich **nach** 07:00:21.810, und die Rechnung waere falsch.

    Geprueft wird deshalb der **Aufrufpfad**, nicht die Funktion:
    ``mqtt_subscriber._handle_override_detection`` -> das, was bei
    ``handle_uplink_for_override`` als ``received_at`` ankommt. Die Zeile
    dazwischen ist ``received_at = uplink.time or datetime.now(tz=UTC)``.

    Die Zusicherung ist doppelt formuliert, und das ist Absicht: der
    Vergleich gegen ``uplink.time`` haelt auch, wenn jemand den
    Zeitstempel im Aufbau oben aendert, der gegen den festen Wert zeigt,
    **welche** Zeit gemeint ist.
    """
    uplink = _uplink(
        {
            "report_type": MANUAL_TARGET_REPORT_TYPE,
            "target_temperature": 25.0,
        }
    )

    await _handle_override_detection(uplink)

    assert len(mitschrift.versuche) == 1, "der 0x28-Frame muss durchkommen"
    received_at = mitschrift.versuche[0]["received_at"]
    assert received_at == uplink.time
    assert received_at == datetime(2026, 10, 5, 20, 3, 25, tzinfo=UTC)


async def test_ohne_zeit_im_uplink_wird_die_serverzeit_genommen(
    mitschrift: Mitschrift,
) -> None:
    """Der Rueckfall — und die einzige Stelle, an der die Serverzeit steht.

    ``ChirpStackUplink.time`` ist optional. Fehlt es, nimmt der Pfad
    ``datetime.now(tz=UTC)``. Das ist richtig so (ohne Zeitstempel ist die
    eigene Uhr die beste vorhandene Antwort), aber es ist eine **andere**
    Uhr als im Normalfall, und das soll im Repo stehen und nicht nur im
    PR-Text.

    Gemessen wird gegen eine Spanne, nicht gegen einen Punkt: zwischen dem
    Aufruf und der Zuweisung liegt echte Laufzeit.
    """
    ohne_zeit = ChirpStackUplink.model_validate(
        {
            "deviceInfo": {"devEui": DEV_EUI},
            "fCnt": 100,
            "fPort": 2,
            "object": {
                "report_type": MANUAL_TARGET_REPORT_TYPE,
                "target_temperature": 25.0,
            },
            "rxInfo": [{"rssi": -90, "snr": 9.0}],
        }
    )
    assert ohne_zeit.time is None, "der Aufbau soll genau diesen Fall treffen"

    vorher = datetime.now(tz=UTC)
    await _handle_override_detection(ohne_zeit)
    nachher = datetime.now(tz=UTC)

    assert len(mitschrift.versuche) == 1
    received_at = mitschrift.versuche[0]["received_at"]
    assert isinstance(received_at, datetime)
    assert vorher <= received_at <= nachher
