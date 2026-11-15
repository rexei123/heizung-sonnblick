"""Die Mindestpause entfällt nach einem langen Lauf.

**Der Anlass, gemessen am 14./15.11.2026.** Ein Relais wird nie dauerhaft
EIN gesetzt — EIN läuft über einen Timer, und der lief nach 30 Minuten
ab, während der Raum zwei bis drei Grad zu kalt war und der Regler jede
Minute `ein` meldete. Danach hielt die **Mindestpause** das Panel weitere
zehn Minuten aus, gerechnet ab dem *gemeldeten* AUS — das selbst schon
neun Minuten alt war, weil das Relais nur alle zehn Minuten meldet.

Von zwanzig Minuten Totzeit je Zyklus war das die Hälfte. Keine Minute
davon hat der Regler gewollt.

**Warum die Regel umgestellt wird und nicht der Fall ausgenommen.** Die
Pause schützt vor schnellem Takten: EIN, AUS, EIN innerhalb weniger
Minuten belastet Kontakte und Gerät. Nach einer Laufzeit von mindestens
`min_lauf` gibt es nichts zu schützen — ein Wechsel je halbe Stunde ist
kein Takten. Die Pause bremste hier also nicht den Regler, sondern den
Wächter, und damit etwas, das niemand entschieden hat.

Die naheliegende Alternative wäre gewesen, nach der **Ursache** des AUS
zu fragen („war es unser Befehl oder der Timer?"). Sie scheitert an den
Daten: `relay_reading.change_reason` ist in allen Zeilen des Hauses
`NULL`, eine Zustandsmeldung bei der Änderung kommt bei uns nicht an. Die
Dauer der vorigen Phase steht dagegen in den Meldungen — und sie ist das,
was die Pause eigentlich meint.

**Dieser PR wirkt allein und zusammen mit `refresh`.** Allein ist er der
Rückfall: die Totzeit sinkt von zwanzig auf etwa zehn Minuten, der
Einschaltanteil steigt von 60–67 auf rund 75 Prozent. Mit `refresh`
greift er fast nie, weil der Timer dann nicht mehr abläuft — er bleibt
aber richtig, und zwar für den Fall, dass drei Nachsetzungen in Folge
verloren gehen.
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
from heizung.rules.zweipunkt import (
    Schaltbefehl,
    Zonenzustand,
    ZweipunktSchwellen,
    entscheide,
)
from heizung.services import relay_state
from heizung.tasks import relay_tasks

NOW = datetime(2026, 11, 15, 9, 0, tzinfo=UTC)

SCHWELLEN = ZweipunktSchwellen(
    ein_delta_k=Decimal("0.5"),
    aus_delta_k=Decimal("0.3"),
    min_lauf=timedelta(minutes=10),
    min_pause=timedelta(minutes=10),
)


def _ent(zustand: Zonenzustand) -> Any:
    """Zone deutlich zu kalt: 20,0 gegen Soll 23,0, Einschaltschwelle 22,5."""
    return entscheide(
        ist=Decimal("20.0"),
        soll=Decimal("23.0"),
        zustand=zustand,
        schwellen=SCHWELLEN,
        now=NOW,
    )


# ---------------------------------------------------------------------------
# Der Regler allein. Keine Datenbank, keine Wanduhr.
# ---------------------------------------------------------------------------


def test_nach_langem_lauf_schaltet_er_sofort_wieder_ein() -> None:
    """**Die Lage vom 14.11.** AUS seit zwei Minuten, vorher 30 Minuten EIN.

    Vorher: ``min_pause_600s`` — acht Minuten warten, obwohl das Panel
    gerade eine halbe Stunde gelaufen ist und der Raum drei Grad zu kalt
    ist.
    """
    zustand = Zonenzustand(
        ein=False,
        seit=NOW - timedelta(minutes=2),
        vorige_dauer=timedelta(minutes=30),
    )
    e = _ent(zustand)
    assert e.befehl is Schaltbefehl.EIN
    assert e.grund == "unter_ein_schwelle"


def test_nach_kurzem_lauf_bleibt_die_pause() -> None:
    """**Die Gegenprobe, und sie ist der Zweck der Pause.**

    Lief das Panel nur vier Minuten, ist ein sofortiges Wiedereinschalten
    genau das Takten, gegen das die Pause gebaut ist. Ohne diesen Test
    wäre „Pause immer entfallen lassen" genauso grün — und das wäre eine
    Verschlechterung, die niemand bemerkt, bis ein Kontakt hinüber ist.
    """
    zustand = Zonenzustand(
        ein=False,
        seit=NOW - timedelta(minutes=2),
        vorige_dauer=timedelta(minutes=4),
    )
    e = _ent(zustand)
    assert e.befehl is Schaltbefehl.UNVERAENDERT
    assert e.grund == "min_pause_600s"


def test_genau_die_mindestlaufzeit_reicht() -> None:
    """Die Grenze ist inklusiv: zehn Minuten Lauf lassen die Pause entfallen.

    Eine Grenze ohne Test ist eine Vermutung darüber, welcher Vergleich
    im Code steht. Hier entscheidet sie zwischen „heizt sofort weiter"
    und „wartet acht Minuten".
    """
    zustand = Zonenzustand(
        ein=False,
        seit=NOW - timedelta(minutes=2),
        vorige_dauer=SCHWELLEN.min_lauf,
    )
    assert _ent(zustand).befehl is Schaltbefehl.EIN

    knapp_darunter = Zonenzustand(
        ein=False,
        seit=NOW - timedelta(minutes=2),
        vorige_dauer=SCHWELLEN.min_lauf - timedelta(seconds=1),
    )
    assert _ent(knapp_darunter).befehl is Schaltbefehl.UNVERAENDERT


def test_ohne_bekannte_vorige_dauer_bleibt_die_pause() -> None:
    """``None`` heisst „wir wissen es nicht" — dann gilt die Pause.

    Das ist der Zustand eines Relais, von dem erst eine Meldung vorliegt,
    und die vorsichtige Richtung: eine Pause zu viel kostet Minuten, eine
    zu wenig kostet Kontakte. Alle Bestandstests kommen über diesen Weg,
    deshalb ist ihr Verhalten unverändert.
    """
    zustand = Zonenzustand(ein=False, seit=NOW - timedelta(minutes=2))
    e = _ent(zustand)
    assert e.befehl is Schaltbefehl.UNVERAENDERT
    assert e.grund == "min_pause_600s"


def test_die_mindestlaufzeit_bleibt_unberuehrt() -> None:
    """Nur die **Pause** entfällt, nicht die Laufzeit.

    Ein Panel, das gerade erst angelaufen ist, bleibt an, auch wenn die
    Zone warm genug wird — sonst taktet es in der anderen Richtung.
    """
    zustand = Zonenzustand(
        ein=True,
        seit=NOW - timedelta(minutes=3),
        vorige_dauer=timedelta(hours=1),
    )
    e = entscheide(
        ist=Decimal("25.0"),
        soll=Decimal("23.0"),
        zustand=zustand,
        schwellen=SCHWELLEN,
        now=NOW,
    )
    assert e.befehl is Schaltbefehl.UNVERAENDERT
    assert e.grund == "min_lauf_600s"


# ---------------------------------------------------------------------------
# Die Dauer kommt aus den Meldungen des Geräts.
# ---------------------------------------------------------------------------

TEST_DB_URL = os.environ.get("TEST_DATABASE_URL")
SKIP_REASON = "TEST_DATABASE_URL nicht gesetzt - DB-Tests brauchen Postgres"
PREFIX = "t-paus"

db_only = pytest.mark.skipif(not TEST_DB_URL, reason=SKIP_REASON)


@pytest_asyncio.fixture
async def setup_engine() -> AsyncIterator[Any]:
    engine = create_async_engine(TEST_DB_URL or "", poolclass=None)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def gesendet(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str, int | None]]:
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
async def rezeption(setup_engine: Any) -> AsyncIterator[Aufbau]:
    """Die Rezeption nach einem Timer-Ablauf, mit den echten Meldezeiten.

    Die Meldungen liegen im Zehn-Minuten-Raster, so wie das Relais sie
    schickt. Daraus liest ``relay_state`` beides: dass es seit zwei
    Minuten aus ist und dass es davor dreissig Minuten gelaufen ist.
    """
    maker = async_sessionmaker(setup_engine, expire_on_commit=False)
    short = uuid.uuid4().hex[:4]
    jetzt = datetime.now(tz=UTC)

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
            label="056 Eingang",
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
            power_return_verified_at=jetzt - timedelta(hours=3),
            overheating_recovery_verified_at=jetzt - timedelta(hours=3),
            commissioned_at=jetzt - timedelta(hours=2),
        )
        session.add_all([fuehler, relais])
        await session.flush()

        # AUS seit 2 min; davor 30 min EIN; davor AUS. Alles im
        # Zehn-Minuten-Raster des Geraets.
        zeiten = [
            (42, False),
            (32, True),
            (22, True),
            (12, True),
            (2, False),
        ]
        session.add_all(
            [
                RelayReading(
                    time=jetzt - timedelta(minutes=vor),
                    device_id=relais.id,
                    relay_on=ein,
                    power_w=1520 if ein else 0,
                )
                for vor, ein in zeiten
            ]
        )
        session.add(
            SensorReading(
                time=jetzt - timedelta(minutes=2),
                device_id=fuehler.id,
                temperature=Decimal("20.0"),
                attached_backplate=False,
            )
        )
        session.add(
            EventLog(
                time=jetzt - timedelta(minutes=1),
                room_id=room.id,
                evaluation_id=uuid.uuid4(),
                layer=EventLogLayer.HARD_CLAMP,
                setpoint_in=Decimal("23.0"),
                setpoint_out=Decimal("23.0"),
                reason=CommandReason.VACANT_SETPOINT,
                details={"downlink_zone_status": [{"zone_id": zone.id, "setpoint_c": 23}]},
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
            await session.execute(
                text("DELETE FROM device WHERE id = ANY(:d)"),
                {"d": [ids.fuehler_id, ids.relais_id]},
            )
            await session.execute(
                text("DELETE FROM room_type WHERE name LIKE :p"), {"p": f"{PREFIX}-%"}
            )
            await session.commit()


@db_only
async def test_die_vorige_dauer_kommt_aus_den_meldungen(
    rezeption: Aufbau, setup_engine: Any
) -> None:
    """``relay_state`` liest die Dauer der vorigen Phase mit.

    **Erwartet sind 20 Minuten, nicht 30 — und das ist Absicht.**
    Gerechnet wird von der ersten EIN-Meldung (vor 32 min) bis zur
    letzten (vor 12 min). Physisch lief das Panel länger: es ging
    irgendwann zwischen -42 und -32 an und zwischen -12 und -2 aus. Die
    Meldungen kommen alle zehn Minuten, mehr Auflösung gibt es nicht.

    Von den beiden möglichen Lesarten nimmt der Helfer die **kleinere**.
    Eine Phase zu kurz zu schätzen heisst, die Pause einmal zu oft
    anzuwenden — ein paar Minuten später heizen. Zu lang zu schätzen
    heisst, sie einmal zu wenig anzuwenden, und das ist der Fall, gegen
    den sie gebaut ist. Die vorsichtige Richtung ist hier die kleinere
    Zahl (§0 S5: letzter bekannter guter Stand schlägt jede Annahme).
    """
    maker = async_sessionmaker(setup_engine, expire_on_commit=False)
    async with maker() as session:
        zustand = await relay_state.bestaetigter_zustand(session, rezeption.relais_id)

    assert zustand.ein is False
    assert zustand.vorige_dauer is not None
    assert zustand.vorige_dauer == timedelta(minutes=20), (
        f"die untere Schranke: erste bis letzte EIN-Meldung: {zustand.vorige_dauer}"
    )


@db_only
async def test_der_orchestrator_schaltet_ohne_pause_wieder_ein(
    rezeption: Aufbau, setup_engine: Any, gesendet: list[tuple[str, str, int | None]]
) -> None:
    """**Ende zu Ende: die zehn Minuten Totzeit sind weg.**

    Das Relais ist seit zwei Minuten aus, vorher lief es dreissig, der
    Raum ist drei Grad zu kalt. Vor dieser Änderung hätte der Regler
    ``min_pause_600s`` gemeldet und nichts gesendet.
    """
    ergebnis = await relay_tasks._steuere_relais_zonen_async(now=datetime.now(tz=UTC))
    zone = next(z for z in ergebnis["details"] if z["zone_id"] == rezeption.zone_id)

    assert zone["regler"] == "ein", f"keine Pause nach dreissig Minuten Lauf: {zone}"
    assert zone["regler_grund"] == "unter_ein_schwelle"
    assert gesendet == [("ein", rezeption.relais_eui, 1800)]
