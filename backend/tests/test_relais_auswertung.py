"""Das Auswertungswerkzeug fuer die Panel-Frage.

Geprueft wird vor allem das, woran eine Auswertung stillschweigend falsch
wird: die **Gewichtung** (eine Stunde mit zehn erfassten Minuten darf
nicht so schwer zaehlen wie eine volle), die **Zeitzone** am Eingang, und
dass der Sollwert nach derselben Regel gelesen wird wie im Regler.

Der Ausgabetext ist nicht geprueft. Er ist fuer Menschen und aendert sich;
ein Test darauf waere ein Test auf Formatierung und wuerde bei jeder
Verbesserung rot (§5.79 — ein Melder, dem niemand glaubt).
"""

from __future__ import annotations

import argparse
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
from heizung.scripts import relais_auswertung as werkzeug

NOW = datetime(2026, 11, 15, 9, 0, tzinfo=UTC)


class _Zeile:
    """Eine ``hard_clamp``-Zeile, wie die Abfrage sie liefert."""

    def __init__(self, setpoint_out: Decimal | None, zonen: Any) -> None:
        self.setpoint_out = setpoint_out
        self.zonen = zonen


# ---------------------------------------------------------------------------
# Der Sollwert: dieselbe Regel wie im Regler.
# ---------------------------------------------------------------------------


def test_der_zonenwert_schlaegt_den_zimmerwert() -> None:
    """Die Lage vom 14.11.: Zimmer 22, Zone 23.

    Ein Werkzeug, das hier die 22 zeigt, wuerde die Uebersteuerung des
    Mitarbeiters verschweigen — und genau diese Abweichung soll es ja
    sichtbar machen.
    """
    zeile = _Zeile(Decimal("22.0"), [{"zone_id": 302, "setpoint_c": 23}])
    assert werkzeug._soll_der_stunde(zeile, 140, 302) == Decimal("23")


def test_ohne_zonenwert_der_zimmerwert() -> None:
    """Zeilen aus der Zeit vor dem 31.10.2026 tragen kein ``setpoint_c``."""
    zeile = _Zeile(Decimal("22.0"), None)
    assert werkzeug._soll_der_stunde(zeile, 140, 302) == Decimal("22.0")


def test_der_wert_einer_fremden_zone_wirkt_nicht() -> None:
    """Ein Zimmer hat mehrere Zonen — der Wert der Nachbarzone gilt nicht."""
    zeile = _Zeile(Decimal("22.0"), [{"zone_id": 299, "setpoint_c": 25}])
    assert werkzeug._soll_der_stunde(zeile, 140, 302) == Decimal("22.0")


def test_ein_wahrheitswert_ist_kein_sollwert() -> None:
    """``isinstance(True, int)`` ist wahr — die Falle aus §5.73.

    Ein JSON-``true`` wuerde als Sollwert 1 durchgehen, und die Auswertung
    zeigte Frostschutz, wo eine Uebersteuerung steht.
    """
    zeile = _Zeile(Decimal("22.0"), [{"zone_id": 302, "setpoint_c": True}])
    assert werkzeug._soll_der_stunde(zeile, 140, 302) == Decimal("22.0")


# ---------------------------------------------------------------------------
# Die Zeitzone am Eingang.
# ---------------------------------------------------------------------------


def test_seit_wird_als_ortszeit_gelesen_winter() -> None:
    """Der Mensch tippt die Uhrzeit an seiner Wand (§5.65).

    Im November ist Europe/Vienna UTC+1. Als UTC gelesen waere der Beginn
    eine Stunde zu frueh, und eine Stunde ist bei dieser Messung genau
    die Auflösung.
    """
    assert werkzeug._parse_seit("2026-11-16 10:00") == datetime(2026, 11, 16, 9, 0, tzinfo=UTC)


def test_seit_wird_als_ortszeit_gelesen_sommer() -> None:
    """Im Juli sind es zwei Stunden. Dieselbe Eingabe, anderer Abstand."""
    assert werkzeug._parse_seit("2026-07-16 10:00") == datetime(2026, 7, 16, 8, 0, tzinfo=UTC)


def test_eine_angabe_mit_zone_bleibt_unveraendert() -> None:
    """Steht die Zone dran, wird nichts hinzugedichtet."""
    assert werkzeug._parse_seit("2026-11-16T10:00:00+00:00") == datetime(
        2026, 11, 16, 10, 0, tzinfo=UTC
    )


# ---------------------------------------------------------------------------
# Die Gewichtung — hier wird eine Auswertung stillschweigend falsch.
# ---------------------------------------------------------------------------


def _stunde(
    versatz: int, anteil: int | None, minuten: int, ist: str | None = None, soll: str | None = None
) -> werkzeug.Stunde:
    return werkzeug.Stunde(
        stunde=NOW + timedelta(hours=versatz),
        ein_prozent=anteil,
        erfasste_minuten=minuten,
        einschaltungen=1,
        ist_mittel=Decimal(ist) if ist else None,
        ist_min=Decimal(ist) if ist else None,
        ist_max=Decimal(ist) if ist else None,
        soll=Decimal(soll) if soll else None,
    )


def _bericht(stunden: list[werkzeug.Stunde]) -> werkzeug.Zonenbericht:
    return werkzeug.Zonenbericht(
        zone_id=299,
        room_id=139,
        zone_name="Eingang",
        zimmer="Rezeption",
        relais=["108"],
        stunden=stunden,
    )


def test_der_gesamtanteil_wiegt_nach_erfasster_zeit() -> None:
    """**Nicht der Mittelwert der Stundenwerte.**

    Eine Randstunde mit sechs erfassten Minuten und 100 Prozent neben
    einer vollen Stunde mit 60 Prozent: der Mittelwert waere 80, richtig
    sind 64. Am Rand des Fensters sind die Stunden immer kurz, der Fehler
    traete also bei **jedem** Lauf auf.
    """
    bericht = _bericht([_stunde(0, 100, 6), _stunde(1, 60, 60)])
    assert bericht.anteil_gesamt == 64


def test_stunden_ohne_meldung_zaehlen_nicht_als_null() -> None:
    """Eine Luecke ist keine Null.

    Ein Fenster ohne Meldung heisst „wir haben nichts gehoert". Es als 0
    Prozent zu zaehlen waere eine Behauptung ueber ein Geraet, von dem
    wir nichts wissen — und sie zoege den Gesamtanteil nach unten, also
    genau in die Richtung, die eine Fehlentscheidung ueber das Panel
    begruenden wuerde.
    """
    bericht = _bericht([_stunde(0, None, 0), _stunde(1, 60, 60)])
    assert bericht.anteil_gesamt == 60


def test_ohne_jede_erfasste_zeit_gibt_es_keinen_anteil() -> None:
    assert _bericht([_stunde(0, None, 0)]).anteil_gesamt is None


def test_nur_stunden_mit_heizwunsch_zaehlen_fuer_die_panel_frage() -> None:
    """Eine warme Stunde sagt nichts ueber die Leistung des Panels.

    Dort ist ein niedriger Einschaltanteil **richtig**. Sie mitzurechnen
    wuerde die Zahl verwaessern, an der die Entscheidung haengt.
    """
    stunden = [
        _stunde(0, 100, 60, ist="20.0", soll="23.0"),  # 3 K zu kalt
        _stunde(1, 10, 60, ist="23.5", soll="23.0"),  # warm genug
        _stunde(2, 90, 60, ist="22.0", soll="23.0"),  # 1 K zu kalt
        _stunde(3, 50, 60),  # ohne Zahlen
    ]
    heiz = _bericht(stunden).stunden_mit_heizwunsch
    assert [s.ein_prozent for s in heiz] == [100, 90]


def test_der_abstand_ist_soll_minus_ist() -> None:
    """Positiv heisst „zu kalt" — und ohne eine der beiden Zahlen ``None``."""
    assert _stunde(0, 50, 60, ist="20.5", soll="23.0").abstand == Decimal("2.5")
    assert _stunde(0, 50, 60, ist="20.5").abstand is None
    assert _stunde(0, 50, 60, soll="23.0").abstand is None


# ---------------------------------------------------------------------------
# Gegen die Datenbank.
# ---------------------------------------------------------------------------

TEST_DB_URL = os.environ.get("TEST_DATABASE_URL")
PREFIX = "t-ausw"

db_only = pytest.mark.skipif(
    not TEST_DB_URL, reason="TEST_DATABASE_URL nicht gesetzt - DB-Tests brauchen Postgres"
)


@pytest_asyncio.fixture
async def setup_engine() -> AsyncIterator[Any]:
    engine = create_async_engine(TEST_DB_URL or "", poolclass=None)
    yield engine
    await engine.dispose()


class Aufbau:
    def __init__(self, room_id: int, zone_id: int, fuehler_id: int, relais_id: int) -> None:
        self.room_id = room_id
        self.zone_id = zone_id
        self.fuehler_id = fuehler_id
        self.relais_id = relais_id


@pytest_asyncio.fixture
async def haus(setup_engine: Any) -> AsyncIterator[Aufbau]:
    """Eine Relais-Zone mit zwei Stunden Geschichte.

    Stunde 1: durchgehend EIN. Stunde 2: halb. Die Meldungen liegen im
    Zehn-Minuten-Raster des Geraets.
    """
    maker = async_sessionmaker(setup_engine, expire_on_commit=False)
    short = uuid.uuid4().hex[:4]
    # Feste Stundengrenzen, damit die Zuordnung eindeutig ist.
    basis = datetime.now(tz=UTC).replace(minute=0, second=0, microsecond=0) - timedelta(hours=3)

    async with maker() as session:
        rt = RoomType(
            name=f"{PREFIX}-rt-{short}", is_bookable=False, default_t_occupied=Decimal("23.0")
        )
        session.add(rt)
        await session.flush()
        room = Room(number=f"{PREFIX}-{short}", room_type_id=rt.id)
        session.add(room)
        await session.flush()
        zone = HeatingZone(room_id=room.id, kind=HeatingZoneKind.OTHER, name="Eingang")
        session.add(zone)
        await session.flush()

        fuehler = Device(
            dev_eui=f"deadbeef{uuid.uuid4().hex[:8]}",
            kind=DeviceKind.THERMOSTAT,
            vendor=DeviceVendor.MCLIMATE,
            model="vicki",
            label="056",
            heating_zone_id=zone.id,
            health_state="healthy",
            measure_only=True,
        )
        relais = Device(
            dev_eui=f"deadbeef{uuid.uuid4().hex[:8]}",
            kind=DeviceKind.RELAY,
            vendor=DeviceVendor.MCLIMATE,
            model="16ASPM",
            label="108",
            heating_zone_id=zone.id,
            health_state="healthy",
            commissioned_at=basis - timedelta(hours=1),
        )
        session.add_all([fuehler, relais])
        await session.flush()

        # Stunde 1 (basis): sechs Meldungen, alle EIN.
        # Stunde 2: drei EIN, dann drei AUS.
        meldungen: list[tuple[datetime, bool]] = []
        for i in range(6):
            meldungen.append((basis + timedelta(minutes=10 * i), True))
        for i in range(6):
            meldungen.append((basis + timedelta(hours=1, minutes=10 * i), i < 3))
        # Eine Abschlussmeldung, damit die letzte Phase ein Ende hat.
        meldungen.append((basis + timedelta(hours=2), False))
        session.add_all(
            [
                RelayReading(time=t, device_id=relais.id, relay_on=ein, power_w=1520 if ein else 0)
                for t, ein in meldungen
            ]
        )
        session.add_all(
            [
                SensorReading(
                    time=basis + timedelta(minutes=30),
                    device_id=fuehler.id,
                    temperature=Decimal("20.0"),
                    attached_backplate=False,
                ),
                SensorReading(
                    time=basis + timedelta(hours=1, minutes=30),
                    device_id=fuehler.id,
                    temperature=Decimal("22.0"),
                    attached_backplate=False,
                ),
            ]
        )
        session.add_all(
            [
                EventLog(
                    time=basis + timedelta(minutes=30),
                    room_id=room.id,
                    evaluation_id=uuid.uuid4(),
                    layer=EventLogLayer.HARD_CLAMP,
                    setpoint_in=Decimal("23.0"),
                    setpoint_out=Decimal("23.0"),
                    reason=CommandReason.VACANT_SETPOINT,
                    details={"downlink_zone_status": [{"zone_id": zone.id, "setpoint_c": 23}]},
                ),
                EventLog(
                    time=basis + timedelta(hours=1, minutes=30),
                    room_id=room.id,
                    evaluation_id=uuid.uuid4(),
                    layer=EventLogLayer.HARD_CLAMP,
                    setpoint_in=Decimal("23.0"),
                    setpoint_out=Decimal("23.0"),
                    reason=CommandReason.VACANT_SETPOINT,
                    details={"downlink_zone_status": [{"zone_id": zone.id, "setpoint_c": 23}]},
                ),
            ]
        )
        await session.commit()
        ids = Aufbau(room.id, zone.id, fuehler.id, relais.id)

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
            await session.execute(
                text("DELETE FROM device WHERE id = ANY(:d)"),
                {"d": [ids.fuehler_id, ids.relais_id]},
            )
            await session.execute(
                text("DELETE FROM room_type WHERE name LIKE :p"), {"p": f"{PREFIX}-%"}
            )
            await session.commit()


@db_only
async def test_der_anteil_wird_aus_den_meldungen_gerechnet(haus: Aufbau, setup_engine: Any) -> None:
    """Eine Stunde voll EIN, die naechste halb — und genau das steht da.

    Das ist die Probe, dass die zeitgewichtete Rechnung stimmt. Ein Test
    auf „irgendein Prozentwert kommt heraus" waere gruen, auch wenn die
    Fensterfunktion die Phasen falsch zuordnet.
    """
    maker = async_sessionmaker(setup_engine, expire_on_commit=False)
    async with maker() as session:
        zonen = await werkzeug._zonen_mit_relais(session)
        passend = [(z, r) for z, r in zonen if z.id == haus.zone_id]
        assert passend, "die Zone mit dem Relais muss gefunden werden"
        zone, relais = passend[0]
        bericht = await werkzeug._bericht(
            session,
            zone,
            relais,
            ab=datetime.now(tz=UTC) - timedelta(hours=4),
            bis=datetime.now(tz=UTC),
        )

    mit_anteil = [s for s in bericht.stunden if s.ein_prozent is not None]
    assert [s.ein_prozent for s in mit_anteil] == [100, 50], (
        f"erste Stunde voll, zweite halb: {[(s.stunde, s.ein_prozent) for s in mit_anteil]}"
    )
    assert bericht.stunden[0].soll == Decimal("23")
    assert bericht.stunden[0].ist_mittel == Decimal("20.00")
    assert bericht.stunden[0].abstand == Decimal("3.00")


@db_only
async def test_ein_nicht_in_betrieb_genommenes_relais_kommt_nicht_vor(
    haus: Aufbau, setup_engine: Any
) -> None:
    """``commissioned_at IS NULL`` heisst „schaltet nicht".

    Seine Zone in einer Auswertung ueber Heizleistung zu fuehren waere
    eine Zeile mit null Prozent, die wie ein Befund aussieht und keiner
    ist.
    """
    maker = async_sessionmaker(setup_engine, expire_on_commit=False)
    async with maker() as session:
        geraet = await session.get(Device, haus.relais_id)
        assert geraet is not None
        geraet.commissioned_at = None
        await session.commit()

    async with maker() as session:
        zonen = await werkzeug._zonen_mit_relais(session)
    assert [z.id for z, _ in zonen if z.id == haus.zone_id] == []


def test_main_liest_die_argumente_und_startet_nur(monkeypatch: pytest.MonkeyPatch) -> None:
    """``main()`` parst und gibt weiter — ohne Event-Loop im Test (§5.14).

    **Dieser Test darf ``_verteile`` nicht aufrufen**, sondern ersetzt
    es. Der erste Versuch rief es auf, und weil die Suite einen eigenen
    Loop fuehrt, schlug ``asyncio.run`` mit „cannot be called from a
    running event loop" fehl. Genau davor warnt die Lesson, und sie
    beschreibt auch die Naht: ``main`` parst, ``_verteile`` startet, und
    der Test prueft die erste Haelfte.

    Geprueft wird die Vorgabe von 24 Stunden — eine falsche Vorgabe waere
    ein Fenster, das niemand gewaehlt hat.
    """
    gesehen: list[argparse.Namespace] = []

    def _statt(args: argparse.Namespace) -> int:
        gesehen.append(args)
        return 0

    monkeypatch.setattr(werkzeug, "_verteile", _statt)
    monkeypatch.setattr("sys.argv", ["relais_auswertung"])
    assert werkzeug.main() == 0
    assert gesehen[0].stunden == 24
    assert gesehen[0].seit is None

    gesehen.clear()
    monkeypatch.setattr("sys.argv", ["relais_auswertung", "--seit", "2026-11-16 10:00"])
    assert werkzeug.main() == 0
    assert gesehen[0].seit == "2026-11-16 10:00"
