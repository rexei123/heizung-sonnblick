"""Der Relais-Regler nimmt den Sollwert **seiner Zone**, nicht den des Zimmers.

**Befund des Betreibers vom 15.11.2026, am Live-Stand belegt.** Der
Barbereich war am 14.11. dreimal auf 23 Grad uebersteuert
(``frontend_bereich``, 13:05 und 17:10, dazu 13.11. 17:46). Die
Zonenkarte und der Verlauf zeigten 23. Das Panel regelte das Totband um
**22** aus — den Sollwert des Raumtyps.

Die ``hard_clamp``-Zeile von 17:11 trug **beide** Zahlen:

```
setpoint_out = 22.0
details->downlink_zone_status = [{"zone_id": 302, ..., "setpoint_c": 23}]
```

Der Regler las die Spalte, die Anzeige das JSON-Feld. Zwei Wahrheiten in
einer Zeile (Paragraph 5.53), und die Steuerung hatte die falsche: der
Wunsch des Mitarbeiters kam nie am Gerät an.

**Warum es ausgerechnet an einem Relais auffiel.** Bei einem Thermostat
traegt der Dispatch den Zonenwert selbst zum Gerät — die Uebersteuerung
wirkt dort, ohne dass jemand den Sollwert nachlesen muesste. Ein Relais
hat kein Sollwert-Register; es wird geschaltet, und dafuer muss der
Regler den Sollwert **lesen**. Seit #410 ist das Relais ausserdem kein
angesteuertes Geraet mehr, der Dispatch kommt also gar nicht mehr an ihm
vorbei. Damit war dieser Lesepfad der einzige — und er war der falsche.

Diese Datei prueft die Korrektur an der Bestueckung, die es im Haus
wirklich gibt: ein Relais in Betrieb, ein Vicki auf „nur messen", eine
aktive Zonen-Uebersteuerung.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from heizung.models.device import Device
from heizung.models.enums import (
    CommandReason,
    DeviceKind,
    DeviceVendor,
    EventLogLayer,
    HeatingZoneKind,
)
from heizung.models.event_log import EventLog
from heizung.models.heating_zone import HeatingZone
from heizung.models.relay_reading import RelayReading
from heizung.models.room import Room
from heizung.models.room_type import RoomType
from heizung.models.sensor_reading import SensorReading
from heizung.services.event_log import SollStand, lies_soll_stand
from heizung.tasks import relay_tasks

TEST_DB_URL = os.environ.get("TEST_DATABASE_URL")
SKIP_REASON = "TEST_DATABASE_URL nicht gesetzt - DB-Tests brauchen Postgres"
PREFIX = "t-zsoll"

pytestmark = pytest.mark.skipif(not TEST_DB_URL, reason=SKIP_REASON)


# ---------------------------------------------------------------------------
# Der Helfer allein. Reine Funktion, keine Datenbank.
# ---------------------------------------------------------------------------


def test_der_zonenwert_schlaegt_den_zimmerwert() -> None:
    """Die Regel in einer Zeile: steht ein Wert fuer diese Zone da, gilt er."""
    stand = SollStand(je_zimmer={7: Decimal("22.0")}, je_zone={7: {302: 23}})
    assert stand.fuer(7, 302) == Decimal("23")


def test_ohne_zonenwert_bleibt_der_zimmerwert() -> None:
    """Der Rueckfall: eine Zeile vor dem 31.10.2026 kennt kein ``setpoint_c``.

    Ohne diesen Zweig stuende die Zone nach einem Deploy eine Minute
    lang ohne Sollwert da — und ein Regler ohne Sollwert schaltet nicht.
    """
    stand = SollStand(je_zimmer={7: Decimal("22.0")}, je_zone={})
    assert stand.fuer(7, 302) == Decimal("22.0")


def test_eine_andere_zone_des_zimmers_zaehlt_nicht() -> None:
    """**Die Gegenprobe, die ``.get(room_id)`` allein bestehen wuerde.**

    Ein Zimmer hat mehrere Zonen. Wer den Zonenwert nimmt, ohne nach der
    **eigenen** Zone zu fragen, bekommt den der Nachbarzone — und das
    waere derselbe Fehler noch einmal, nur schwerer zu sehen.
    """
    stand = SollStand(je_zimmer={7: Decimal("22.0")}, je_zone={7: {299: 25}})
    assert stand.fuer(7, 302) == Decimal("22.0")


def test_ohne_zone_gibt_es_den_zimmerwert() -> None:
    """``zone_id is None`` ist die Zimmerliste ohne Referenzzone, kein Fehler."""
    stand = SollStand(je_zimmer={7: Decimal("22.0")}, je_zone={7: {302: 23}})
    assert stand.fuer(7, None) == Decimal("22.0")


def test_ein_unbekanntes_zimmer_hat_keinen_sollwert() -> None:
    """Kein Engine-Lauf im Frischefenster → ``None``, nicht 0.

    Der Unterschied traegt im Regler eine Entscheidung: ``None`` heisst
    „nicht schalten" (``kein_engine_soll``), eine 0 waere Frostschutz.
    """
    stand = SollStand(je_zimmer={}, je_zone={})
    assert stand.fuer(7, 302) is None


# ---------------------------------------------------------------------------
# Der Regler an der echten Bestueckung.
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def setup_engine() -> AsyncIterator[Any]:
    engine = create_async_engine(TEST_DB_URL or "", poolclass=None)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def gesendet(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str, int | None]]:
    """Mitschreiber fuer Downlinks. Keine echten Befehle aus einem Test."""
    aufrufe: list[tuple[str, str, int | None]] = []

    async def _ein(dev_eui: str, sekunden: int) -> str:
        aufrufe.append(("ein", dev_eui, sekunden))
        return "topic/ein"

    async def _aus(dev_eui: str) -> str:
        aufrufe.append(("aus", dev_eui, None))
        return "topic/aus"

    monkeypatch.setattr(relay_tasks.relay_adapter, "relais_ein_fuer", _ein)
    monkeypatch.setattr(relay_tasks.relay_adapter, "relais_aus", _aus)
    return aufrufe


@pytest.fixture(autouse=True)
def drossel(monkeypatch: pytest.MonkeyPatch) -> None:
    """Die Zustands-Abfrage haengt an Redis; hier geht es um den Sollwert.

    **Autouse**, weil ein Lauf ohne Redis sonst nicht mit einem Fehler
    endet, sondern mit einer ausbleibenden Abfrage — der schwer zu
    lesenden Sorte Fehlschlag. Die Bremse selbst hat ihre eigene Datei.
    """
    monkeypatch.setattr(
        relay_tasks.relais_abfrage, "darf_fragen", lambda device_id, *, abstand_s: True
    )


class Aufbau:
    def __init__(self, room_id: int, zone_id: int, fuehler_id: int, relais_eui: str) -> None:
        self.room_id = room_id
        self.zone_id = zone_id
        self.fuehler_id = fuehler_id
        self.relais_eui = relais_eui
        self.relais_id = 0


@pytest_asyncio.fixture
async def bar(setup_engine: Any) -> AsyncIterator[Aufbau]:
    """Die Bar, wie sie im Haus steht.

    Raumtyp **nicht buchbar**, Sollwert 22 Grad (das ist der „Raum
    intern" des Betreibers). Eine Zone „Barbereich", darin ein Relais in
    Betrieb und ein Vicki auf ``measure_only`` — 027 hat kein Ventil, er
    misst nur.

    Das Relais meldet AUS, und zwar in **zwei** Zeilen: aus seit 40
    Minuten, zuletzt gehoert vor 5 Minuten. Das ist der normale Zustand
    eines abgeschalteten Panels, und beide Aussagen braucht der Waechter
    getrennt — eine Zeile truege sie auf einmal und wuerde die
    Mindestpause mit dem Haltbarkeitsdatum des Zustands vermischen
    (Paragraph 5.51).
    """
    maker = async_sessionmaker(setup_engine, expire_on_commit=False)
    short = uuid.uuid4().hex[:4]
    jetzt = datetime.now(tz=UTC)

    async with maker() as session:
        rt = RoomType(
            name=f"{PREFIX}-rt-{short}",
            is_bookable=False,
            default_t_occupied=Decimal("22.0"),
        )
        session.add(rt)
        await session.flush()

        room = Room(number=f"{PREFIX}-{short}", room_type_id=rt.id)
        session.add(room)
        await session.flush()

        zone = HeatingZone(room_id=room.id, kind=HeatingZoneKind.OTHER, name="Barbereich")
        session.add(zone)
        await session.flush()

        fuehler = Device(
            dev_eui=f"deadbeef{uuid.uuid4().hex[:8]}",
            kind=DeviceKind.THERMOSTAT,
            vendor=DeviceVendor.MCLIMATE,
            model="vicki",
            label="027 Bar",
            heating_zone_id=zone.id,
            health_state="healthy",
            measure_only=True,
        )
        relais = Device(
            dev_eui=f"deadbeef{uuid.uuid4().hex[:8]}",
            kind=DeviceKind.RELAY,
            vendor=DeviceVendor.MCLIMATE,
            model="16ASPM",
            label="109 Panel",
            heating_zone_id=zone.id,
            health_state="healthy",
            power_return_verified_at=jetzt - timedelta(hours=2),
            overheating_recovery_verified_at=jetzt - timedelta(hours=2),
            commissioned_at=jetzt - timedelta(hours=1),
        )
        session.add_all([fuehler, relais])
        await session.flush()

        session.add_all(
            [
                RelayReading(
                    time=jetzt - timedelta(minutes=40),
                    device_id=relais.id,
                    relay_on=False,
                    power_w=0,
                ),
                RelayReading(
                    time=jetzt - timedelta(minutes=5),
                    device_id=relais.id,
                    relay_on=False,
                    power_w=0,
                ),
            ]
        )
        # **22,1 Grad** — die Temperatur, bei der es am 14.11. gehangen
        # hat. Im Totband um 22 (21,5 bis 22,3) liegt sie drin, unter der
        # Einschaltschwelle von 23 (22,5) liegt sie drunter. Dieselbe
        # Zahl, zwei Entscheidungen: daran haengt dieser Test.
        session.add(
            SensorReading(
                time=jetzt - timedelta(minutes=2),
                device_id=fuehler.id,
                temperature=Decimal("22.1"),
                attached_backplate=False,
            )
        )
        await session.commit()
        ids = Aufbau(room.id, zone.id, fuehler.id, relais.dev_eui)
        ids.relais_id = relais.id

    try:
        yield ids
    finally:
        async with maker() as session:
            await session.execute(
                text("DELETE FROM event_log WHERE room_id = :r"), {"r": ids.room_id}
            )
            await session.execute(
                text("DELETE FROM relay_reading WHERE device_id = :d"), {"d": ids.relais_id}
            )
            await session.execute(
                text("DELETE FROM sensor_reading WHERE device_id = ANY(:d)"),
                {"d": [ids.fuehler_id, ids.relais_id]},
            )
            await session.execute(text("DELETE FROM room WHERE id = :r"), {"r": ids.room_id})
            # ``device.heating_zone_id`` ist nullable: CASCADE vom Zimmer
            # raeumt die Zone, setzt das Geraet aber nur auf NULL. Ohne
            # diese Zeile sammeln sich Relais ohne Zone (Paragraph 5.39).
            await session.execute(
                text("DELETE FROM device WHERE id = ANY(:d)"),
                {"d": [ids.fuehler_id, ids.relais_id]},
            )
            await session.execute(
                text("DELETE FROM room_type WHERE name LIKE :p"), {"p": f"{PREFIX}-%"}
            )
            await session.commit()


async def _trace(engine: Any, aufbau: Aufbau, *, zimmer_soll: str, zonen_soll: int | None) -> None:
    """Eine ``hard_clamp``-Zeile, wie die Engine sie schreibt.

    ``zonen_soll=None`` laesst ``setpoint_c`` weg — so sahen die Zeilen
    vor dem 31.10.2026 aus, und so sieht die erste Minute nach einem
    Deploy aus.
    """
    status: dict[str, Any] = {
        "zone_id": aufbau.zone_id,
        "detail": "relais_zone_ohne_sollwertgeraet",
        "count_sent": 0,
        "count_skipped": 0,
        "count_failed": 0,
        "all_failed": False,
    }
    if zonen_soll is not None:
        status["setpoint_c"] = zonen_soll

    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        session.add(
            EventLog(
                time=datetime.now(tz=UTC) - timedelta(minutes=1),
                room_id=aufbau.room_id,
                evaluation_id=uuid.uuid4(),
                layer=EventLogLayer.HARD_CLAMP,
                setpoint_in=Decimal(zimmer_soll),
                setpoint_out=Decimal(zimmer_soll),
                reason=CommandReason.VACANT_SETPOINT,
                details={"downlink_zone_status": [status]},
            )
        )
        await session.commit()


async def test_die_zonen_uebersteuerung_wirkt_auf_das_relais(
    bar: Aufbau, setup_engine: Any, gesendet: list[tuple[str, str, int | None]]
) -> None:
    """**Der Fehler, den der Betreiber gemeldet hat — die Lage vom 14.11.**

    Zimmerwert 22 (Raumtyp), Zonenwert 23 (Uebersteuerung Barbereich),
    beides in derselben Zeile. Ist 22,1.

    Vorher: der Regler las die 22, 22,1 liegt in deren Totband, es ging
    **nichts** heraus — und der Mitarbeiter sah eine Uebersteuerung, die
    in der Oberflaeche stand und am Panel nicht ankam.

    Jetzt: der Regler liest die 23, 22,1 liegt unter der
    Einschaltschwelle von 22,5, und das Panel heizt.
    """
    await _trace(setup_engine, bar, zimmer_soll="22.0", zonen_soll=23)

    ergebnis = await relay_tasks._steuere_relais_zonen_async(now=datetime.now(tz=UTC))
    zone = next(z for z in ergebnis["details"] if z["zone_id"] == bar.zone_id)

    assert zone["soll"] == "23", f"der Regler muss mit dem Zonenwert rechnen: {zone}"
    assert zone["ist"] == "22.1"
    assert zone["regler"] == "ein"
    assert zone["regler_grund"] == "unter_ein_schwelle"
    assert gesendet == [("ein", bar.relais_eui, 1800)], "ein 0x57 mit 30 min"


async def test_ohne_uebersteuerung_bleibt_das_totband_des_raumtyps(
    bar: Aufbau, setup_engine: Any, gesendet: list[tuple[str, str, int | None]]
) -> None:
    """**Die Gegenprobe. Ohne sie waere „immer einschalten" genauso gruen.**

    Dieselben 22,1 Grad, aber Zimmer- und Zonenwert sind beide 22. Dann
    ist 22,1 das Totband (21,5 bis 22,3), und ein Panel, das hier
    anlaeuft, taktet gegen eine Temperatur, die passt.
    """
    await _trace(setup_engine, bar, zimmer_soll="22.0", zonen_soll=22)

    ergebnis = await relay_tasks._steuere_relais_zonen_async(now=datetime.now(tz=UTC))
    zone = next(z for z in ergebnis["details"] if z["zone_id"] == bar.zone_id)

    assert zone["soll"] == "22"
    assert zone["regler"] == "unveraendert"
    assert zone["regler_grund"] == "im_totband"
    assert gesendet == [], "im Totband geht kein Befehl heraus"


async def test_ohne_zonenwert_rechnet_der_regler_mit_dem_zimmerwert(
    bar: Aufbau, setup_engine: Any, gesendet: list[tuple[str, str, int | None]]
) -> None:
    """Der Rueckfall, am Regler und nicht nur am Helfer geprueft.

    Eine Zeile ohne ``setpoint_c`` — die erste Minute nach einem Deploy.
    Der Regler muss dann den Zimmerwert nehmen und nicht stehenbleiben:
    ``kein_engine_soll`` waere hier falsch, denn ein Sollwert steht ja da.

    Zimmerwert 24, Ist 22,1 → unter der Schwelle von 23,5, also EIN.
    """
    await _trace(setup_engine, bar, zimmer_soll="24.0", zonen_soll=None)

    ergebnis = await relay_tasks._steuere_relais_zonen_async(now=datetime.now(tz=UTC))
    zone = next(z for z in ergebnis["details"] if z["zone_id"] == bar.zone_id)

    assert zone["soll"] == "24.0", f"Rueckfall auf den Zimmerwert: {zone}"
    assert zone["regler"] == "ein"
    assert gesendet == [("ein", bar.relais_eui, 1800)]


async def test_der_zonenwert_einer_anderen_zone_wirkt_nicht(
    bar: Aufbau, setup_engine: Any, gesendet: list[tuple[str, str, int | None]]
) -> None:
    """Eine Uebersteuerung der **Nachbarzone** darf hier nichts bewirken.

    Die Zeile traegt einen Zonenwert, aber fuer eine fremde Zone. Wer
    ``je_zone[room_id]`` nimmt und den ersten Wert daraus liest, heizt
    die Bar nach dem Wunsch der Rezeption — derselbe Fehler noch einmal,
    nur schwerer zu sehen.
    """
    maker = async_sessionmaker(setup_engine, expire_on_commit=False)
    async with maker() as session:
        session.add(
            EventLog(
                time=datetime.now(tz=UTC) - timedelta(minutes=1),
                room_id=bar.room_id,
                evaluation_id=uuid.uuid4(),
                layer=EventLogLayer.HARD_CLAMP,
                setpoint_in=Decimal("22.0"),
                setpoint_out=Decimal("22.0"),
                reason=CommandReason.VACANT_SETPOINT,
                details={
                    "downlink_zone_status": [
                        {"zone_id": bar.zone_id + 10_000, "setpoint_c": 26, "detail": "fremd"}
                    ]
                },
            )
        )
        await session.commit()

    ergebnis = await relay_tasks._steuere_relais_zonen_async(now=datetime.now(tz=UTC))
    zone = next(z for z in ergebnis["details"] if z["zone_id"] == bar.zone_id)

    assert zone["soll"] == "22.0", f"der fremde Zonenwert darf nicht greifen: {zone}"
    assert gesendet == []


async def test_regler_und_anzeige_lesen_denselben_wert(
    bar: Aufbau, setup_engine: Any, gesendet: list[tuple[str, str, int | None]]
) -> None:
    """**Punkt (d): eine Quelle, nicht zwei gleich aussehende.**

    Der Helfer, den die Anzeige benutzt, und die Zahl, mit der der Regler
    gerechnet hat, muessen uebereinstimmen. Geprueft wird nicht, dass
    beide dieselbe Funktion **aufrufen** — das waere eine Aussage ueber
    den Quelltext —, sondern dass dasselbe **herauskommt**.
    """
    await _trace(setup_engine, bar, zimmer_soll="22.0", zonen_soll=23)

    ergebnis = await relay_tasks._steuere_relais_zonen_async(now=datetime.now(tz=UTC))
    zone = next(z for z in ergebnis["details"] if z["zone_id"] == bar.zone_id)

    maker = async_sessionmaker(setup_engine, expire_on_commit=False)
    async with maker() as session:
        stand = await lies_soll_stand(session, [bar.room_id])
    anzeige = stand.fuer(bar.room_id, bar.zone_id)

    assert anzeige is not None
    assert Decimal(zone["soll"]) == anzeige, (
        f"Regler rechnete mit {zone['soll']}, die Anzeige zeigt {anzeige}"
    )
    assert anzeige == Decimal("23")
