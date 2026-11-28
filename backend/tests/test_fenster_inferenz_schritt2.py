"""Fenster-Erkennung Schritt 2: die Ventilstellung entscheidet (27.11.2026).

**Der Anlass ist eine Messung.** Am 05.11.2026 meldete der Betreiber
Zimmer 306: ein Gast, der sichtbar oft lueftet, Einbrueche um 3 bis 4
Grad — und in 30 Tagen bei 13.179 Meldungen **0x** ``open_window =
true``. Die Analyse bestaetigte **49 Einbrueche ab 1,5 Grad, davon 37 mit
oeffnendem Ventil**.

Diese 37 sind der Gegenstand dieser Datei. Ein Temperaturfall allein
sagt nichts: ein Raum, dessen Sollwert abgesenkt wurde, kuehlt genauso.
Ein Fall mit **aufgehendem Ventil** sagt, dass das Geraet gegengeheizt
und nicht nachgekommen ist.

**Die Faelle sind nachgebaut, nicht gemessen.** Die 49 Ereignisse liegen
in der Datenbank des Servers; sie hier als Datei abzulegen waere eine
Kopie, die beim ersten Nachziehen nicht mehr zum Original passt. Was
diese Datei prueft, ist die **Regel**; wer sie gegen die 49 halten will,
nimmt ``scripts/fensterinferenz`` auf dem Server — dafuer ist es gebaut.

**Dieser Schritt bleibt passiv** (AE-47): kein Sollwert, kein Downlink,
keine Schicht in der Pipeline. Der letzte Test hier haelt das fest.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path as FsPath

import pytest
import pytest_asyncio
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from alembic import command
from heizung.models.control_command import ControlCommand
from heizung.models.device import Device
from heizung.models.enums import (
    CommandReason,
    DeviceKind,
    DeviceVendor,
    EventLogLayer,
    HeatingZoneKind,
)
from heizung.models.heating_zone import HeatingZone
from heizung.models.room import Room
from heizung.models.room_type import RoomType
from heizung.models.sensor_reading import SensorReading
from heizung.rules.inferred_window import detect_inferred_window
from heizung.services.event_log import log_inferred_window_event

DATABASE_URL = os.environ.get("DATABASE_URL")
PREFIX = "t-inf"

pytestmark = pytest.mark.skipif(
    not DATABASE_URL, reason="DATABASE_URL nicht gesetzt - DB-Tests brauchen Postgres"
)

#: Der Augenblick, aus dem der Detektor rechnet. Aus der echten Uhr,
#: damit die Zeilen in der Hypertable nicht in ferner Vergangenheit
#: liegen; alle Angaben darunter sind **Abstaende** davon
#: (Paragraph 5.59).
JETZT = datetime.now(tz=UTC).replace(microsecond=0)


@pytest_asyncio.fixture(scope="module", autouse=True)
async def _migrate_db() -> None:
    if not DATABASE_URL:
        return
    backend_root = FsPath(__file__).resolve().parents[1]
    cfg = Config(str(backend_root / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend_root / "alembic"))
    cfg.set_main_option("sqlalchemy.url", DATABASE_URL)
    await asyncio.to_thread(command.upgrade, cfg, "head")


@pytest_asyncio.fixture
async def setup_engine() -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(DATABASE_URL or "", poolclass=None)
    yield engine
    await engine.dispose()


class Aufbau:
    def __init__(self, room_id: int, zone_id: int, dev_id: int, dev_eui: str) -> None:
        self.room_id = room_id
        self.zone_id = zone_id
        self.dev_id = dev_id
        self.dev_eui = dev_eui


@pytest_asyncio.fixture
async def zimmer(setup_engine: AsyncEngine) -> AsyncIterator[Aufbau]:
    """Ein Zimmer mit einem Vicki und einem **stehenden** Sollwert.

    Der stehende Sollwert ist Bedingung 1 des Detektors: aendert die
    Steuerung ihren Wunsch im Lookback, ist der Temperaturfall ihre
    eigene Folge und kein Befund.
    """
    maker = async_sessionmaker(setup_engine, expire_on_commit=False)
    short = uuid.uuid4().hex[:6]

    async with maker() as session:
        rt = RoomType(name=f"{PREFIX}-rt-{short}", default_t_occupied=Decimal("22.0"))
        session.add(rt)
        await session.flush()
        room = Room(number=f"{PREFIX}-{short}", room_type_id=rt.id)
        session.add(room)
        await session.flush()
        zone = HeatingZone(room_id=room.id, kind=HeatingZoneKind.BEDROOM, name="Schlafzimmer")
        session.add(zone)
        await session.flush()
        dev = Device(
            dev_eui=f"inf{uuid.uuid4().hex[:13]}",
            kind=DeviceKind.THERMOSTAT,
            vendor=DeviceVendor.MCLIMATE,
            model="vicki",
            label=f"{PREFIX}-{short}",
            heating_zone_id=zone.id,
            health_state="healthy",
        )
        session.add(dev)
        await session.flush()
        session.add(
            ControlCommand(
                device_id=dev.id,
                target_setpoint=Decimal("20.0"),
                reason=CommandReason.OCCUPIED_SETPOINT,
                issued_at=JETZT - timedelta(minutes=40),
                sent_to_gateway_at=JETZT - timedelta(minutes=40),
            )
        )
        await session.commit()
        ids = Aufbau(room.id, zone.id, dev.id, dev.dev_eui)

    try:
        yield ids
    finally:
        # Von Hand aufraeumen (Paragraph 5.39). Dass genau das in dieser
        # Datenbank nicht ueberall passiert, hat am 27.11.2026 zweimal
        # einen fremden Test rot gemacht.
        async with maker() as session:
            await session.execute(
                text("DELETE FROM event_log WHERE room_id = :r"), {"r": ids.room_id}
            )
            await session.execute(
                text("DELETE FROM sensor_reading WHERE device_id = :d"), {"d": ids.dev_id}
            )
            await session.execute(
                text("DELETE FROM control_command WHERE device_id = :d"), {"d": ids.dev_id}
            )
            await session.execute(text("DELETE FROM room WHERE id = :r"), {"r": ids.room_id})
            await session.execute(text("DELETE FROM device WHERE id = :d"), {"d": ids.dev_id})
            await session.execute(
                text("DELETE FROM room_type WHERE name = :n"), {"n": f"{PREFIX}-rt-{short}"}
            )
            await session.commit()


async def _melde(
    engine: AsyncEngine,
    aufbau: Aufbau,
    reihe: list[tuple[int, str, int | None]],
    *,
    device_id: int | None = None,
) -> None:
    """Meldungen als ``(Minuten zurueck, Temperatur, Ventil)``."""
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        session.add_all(
            [
                SensorReading(
                    time=JETZT - timedelta(minutes=vor),
                    device_id=device_id or aufbau.dev_id,
                    temperature=Decimal(temp),
                    valve_position=ventil,
                    fcnt=vor,
                )
                for vor, temp, ventil in reihe
            ]
        )
        await session.commit()


async def _befund(engine: AsyncEngine, aufbau: Aufbau):  # noqa: ANN202 - Rueckgabe des Dienstes
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        return await detect_inferred_window(session, aufbau.room_id, JETZT)


# ---------------------------------------------------------------------------
# Der Unterscheider.
# ---------------------------------------------------------------------------


async def test_fall_mit_aufgehendem_ventil_ist_ein_befund(
    zimmer: Aufbau, setup_engine: AsyncEngine
) -> None:
    """Der Fall der 37: zwei Grad runter, Ventil von 10 auf 70.

    Das Geraet heizt gegen und kommt nicht nach — Waermeverlust.
    """
    await _melde(
        setup_engine,
        zimmer,
        [(20, "22.0", 10), (10, "21.0", 40), (2, "20.0", 70)],
    )
    befund = await _befund(setup_engine, zimmer)
    assert befund is not None
    assert befund.delta_c == Decimal("2.0")
    assert befund.devices_observed == [zimmer.dev_eui]
    assert (befund.ventil_von, befund.ventil_bis) == (10, 70)


async def test_fall_mit_geschlossenem_ventil_ist_kein_befund(
    zimmer: Aufbau, setup_engine: AsyncEngine
) -> None:
    """Der Unterschied zwischen 49 und 37 — und der Zweck von Schritt 2.

    Derselbe Temperaturfall, aber das Ventil bleibt zu: der Raum kuehlt,
    weil er kuehlen soll. Vor dem 27.11.2026 waere das ein Treffer
    gewesen, und er waere Laerm.
    """
    await _melde(
        setup_engine,
        zimmer,
        [(20, "22.0", 0), (10, "21.0", 0), (2, "20.0", 0)],
    )
    assert await _befund(setup_engine, zimmer) is None


async def test_ein_zugehendes_ventil_ist_kein_befund(
    zimmer: Aufbau, setup_engine: AsyncEngine
) -> None:
    """Das Ventil schliesst, waehrend die Temperatur faellt.

    Dann regelt das Geraet herunter — es ist warm genug oder der Sollwert
    ist gefallen. Ein Befund daraus waere die Umkehrung der Begruendung.
    """
    await _melde(
        setup_engine,
        zimmer,
        [(20, "22.0", 60), (10, "21.0", 30), (2, "20.0", 5)],
    )
    assert await _befund(setup_engine, zimmer) is None


async def test_ein_schon_weit_offenes_ventil_ist_ein_befund(
    zimmer: Aufbau, setup_engine: AsyncEngine
) -> None:
    """Ein Ventil auf 100 kann nicht weiter aufgehen.

    Ohne den ``weit offen``-Zweig waere genau der **deutlichste**
    Waermeverlust unsichtbar: das Geraet heizt mit allem, was es hat, und
    der Detektor sieht „kein Anstieg".
    """
    await _melde(
        setup_engine,
        zimmer,
        [(20, "23.0", 100), (10, "21.5", 100), (2, "20.0", 100)],
    )
    befund = await _befund(setup_engine, zimmer)
    assert befund is not None
    assert (befund.ventil_von, befund.ventil_bis) == (100, 100)


async def test_ein_wackeln_um_drei_punkte_ist_kein_befund(
    zimmer: Aufbau, setup_engine: AsyncEngine
) -> None:
    """Ein Ventil wackelt um ein bis zwei Punkte.

    Ohne Schwelle waere jedes Rauschen ein „oeffnendes Ventil" — und der
    Unterscheider waere keiner.
    """
    await _melde(
        setup_engine,
        zimmer,
        [(20, "22.0", 12), (10, "21.0", 13), (2, "20.0", 15)],
    )
    assert await _befund(setup_engine, zimmer) is None


async def test_ohne_zwei_ventilstellungen_gibt_es_keinen_befund(
    zimmer: Aufbau, setup_engine: AsyncEngine
) -> None:
    """Der Weg des Ventils ist unbekannt — also kein Urteil.

    Nicht weil nichts passiert waere, sondern weil wir es nicht
    unterscheiden koennen. Ein Melder, der meldet, wenn er nichts
    unterscheiden kann, ist genau der Laerm, den Schritt 2 vermeidet
    (Paragraph 5.55).

    **Die einzige Stellung ist 95 und nicht 80**, und das ist der ganze
    Test. Mit 80 waere er auch gruen, wenn der Detektor **eine** Stellung
    genuegen liesse: 80 ist kein Anstieg und nicht „weit offen", also
    faellt er so oder so durch. Mit 95 greift der ``weit offen``-Zweig —
    wer die Zwei-Stellungen-Bedingung aufweicht, bekommt einen Treffer
    und dieser Test wird rot. Die erste Fassung hatte 80, und die
    Mutationsprobe blieb gruen (Paragraph 5.55, zum dritten Mal in diesem
    Durchgang).
    """
    await _melde(
        setup_engine,
        zimmer,
        [(20, "22.0", None), (10, "21.0", None), (2, "20.0", 95)],
    )
    assert await _befund(setup_engine, zimmer) is None


# ---------------------------------------------------------------------------
# Schwelle und Fenster.
# ---------------------------------------------------------------------------


async def test_ein_fall_unter_der_schwelle_ist_kein_befund(
    zimmer: Aufbau, setup_engine: AsyncEngine
) -> None:
    """1,4 Grad — knapp unter 1,5.

    Der Pruefsatz des Betreibers zaehlt ab 1,5 Grad; die Schwelle ist
    deshalb genau dort, und dieser Test ist die Zusicherung darueber.
    """
    await _melde(
        setup_engine,
        zimmer,
        [(20, "21.4", 10), (10, "20.5", 40), (2, "20.0", 70)],
    )
    assert await _befund(setup_engine, zimmer) is None


async def test_genau_an_der_schwelle_ist_ein_befund(
    zimmer: Aufbau, setup_engine: AsyncEngine
) -> None:
    """1,5 Grad — ``>=`` und nicht ``>``.

    „Ab 1,5" heisst einschliesslich. Eine Grenze, bei der der genannte
    Wert nicht mitzaehlt, ist beim Vergleich mit dem Pruefsatz um die
    Faelle daneben, die genau dort liegen.
    """
    await _melde(
        setup_engine,
        zimmer,
        [(20, "21.5", 10), (2, "20.0", 70)],
    )
    befund = await _befund(setup_engine, zimmer)
    assert befund is not None
    assert befund.delta_c == Decimal("1.5")


async def test_was_vor_dem_fenster_liegt_zaehlt_nicht(
    zimmer: Aufbau, setup_engine: AsyncEngine
) -> None:
    """Der Lookback ist 25 Minuten.

    Die hohe Meldung liegt 40 Minuten zurueck und damit ausserhalb; im
    Fenster bleibt ein Fall von 0,5 Grad. Ohne diesen Test waere die 25
    eine Zahl ohne Zusicherung.
    """
    await _melde(
        setup_engine,
        zimmer,
        [(40, "23.0", 10), (20, "20.5", 40), (2, "20.0", 70)],
    )
    assert await _befund(setup_engine, zimmer) is None


async def test_zwanzig_minuten_liegen_im_fenster(zimmer: Aufbau, setup_engine: AsyncEngine) -> None:
    """Die Gegenprobe: 20 Minuten sind drin.

    Ohne sie waere der Test oben auch gruen, wenn der Lookback auf fuenf
    Minuten stuende — eine leere Erwartung, die aus zwei Gruenden
    erfuellt sein kann (Paragraph 5.55).
    """
    await _melde(
        setup_engine,
        zimmer,
        [(20, "22.0", 10), (2, "20.0", 70)],
    )
    assert await _befund(setup_engine, zimmer) is not None


# ---------------------------------------------------------------------------
# Je Geraet, und passiv.
# ---------------------------------------------------------------------------


async def test_fall_und_ventil_muessen_zum_selben_geraet_gehoeren(
    zimmer: Aufbau, setup_engine: AsyncEngine
) -> None:
    """Ein Fall an Geraet A und ein offenes Ventil an Geraet B sind zwei
    Beobachtungen und kein Befund.

    Ueber die Geraete zu mischen waere die Sorte Korrelation, aus der
    Fehlalarme werden.
    """
    maker = async_sessionmaker(setup_engine, expire_on_commit=False)
    async with maker() as session:
        zweites = Device(
            dev_eui=f"inf{uuid.uuid4().hex[:13]}",
            kind=DeviceKind.THERMOSTAT,
            vendor=DeviceVendor.MCLIMATE,
            model="vicki",
            label=f"{PREFIX}-zwei",
            heating_zone_id=zimmer.zone_id,
            health_state="healthy",
        )
        session.add(zweites)
        await session.commit()
        zweites_id = zweites.id

    try:
        # Geraet A: der Fall, Ventil zu.
        await _melde(setup_engine, zimmer, [(20, "22.0", 0), (10, "21.0", 0), (2, "20.0", 0)])
        # Geraet B: Ventil geht auf, Temperatur stabil.
        await _melde(
            setup_engine,
            zimmer,
            [(20, "21.0", 10), (10, "21.0", 50), (2, "21.0", 80)],
            device_id=zweites_id,
        )
        assert await _befund(setup_engine, zimmer) is None
    finally:
        async with maker() as session:
            await session.execute(
                text("DELETE FROM sensor_reading WHERE device_id = :d"), {"d": zweites_id}
            )
            await session.execute(text("DELETE FROM device WHERE id = :d"), {"d": zweites_id})
            await session.commit()


async def test_der_befund_schreibt_die_ventilzahlen_ins_protokoll(
    zimmer: Aufbau, setup_engine: AsyncEngine
) -> None:
    """Die Zeile muss ihr eigenes Kriterium nennen.

    Ohne die Ventilzahlen steht dort „Fenster vermutet" ohne den Grund —
    und beim Nachsehen ist das eine Behauptung (Paragraph 5.68).
    """
    await _melde(
        setup_engine,
        zimmer,
        [(20, "22.0", 10), (2, "20.0", 70)],
    )
    maker = async_sessionmaker(setup_engine, expire_on_commit=False)
    async with maker() as session:
        befund = await detect_inferred_window(session, zimmer.room_id, JETZT)
        assert befund is not None
        await log_inferred_window_event(session, befund)
        await session.commit()

    async with maker() as session:
        zeile = (
            await session.execute(
                text(
                    "SELECT layer, setpoint_in, setpoint_out, details "
                    "FROM event_log WHERE room_id = :r AND layer = :l"
                ),
                {"r": zimmer.room_id, "l": EventLogLayer.INFERRED_WINDOW_OBSERVATION.value},
            )
        ).first()
    assert zeile is not None
    details = zeile.details
    assert isinstance(details, dict)
    assert details["ventil_von"] == 10
    assert details["ventil_bis"] == 70
    assert "ventil=10->70" in details["detail"]
    # **Passiv**: Eingang und Ausgang sind derselbe Wert. Eine Zeile mit
    # einem anderen Ausgang waere eine Steuerentscheidung.
    assert zeile.setpoint_in == zeile.setpoint_out


async def test_der_detektor_schreibt_keinen_befehl(
    zimmer: Aufbau, setup_engine: AsyncEngine
) -> None:
    """Schritt 2 bleibt passiv (AE-47).

    Kein ``ControlCommand``, kein Sollwert, keine Schicht in der
    Pipeline. „Inferenz darf beobachten, aber nicht steuern, bevor sie
    sich produktiv bewaehrt hat."
    """
    await _melde(
        setup_engine,
        zimmer,
        [(20, "22.0", 10), (2, "20.0", 70)],
    )
    maker = async_sessionmaker(setup_engine, expire_on_commit=False)
    async with maker() as session:
        vorher = int(
            await session.scalar(
                text("SELECT count(*) FROM control_command WHERE device_id = :d"),
                {"d": zimmer.dev_id},
            )
            or 0
        )
        befund = await detect_inferred_window(session, zimmer.room_id, JETZT)
        assert befund is not None
        nachher = int(
            await session.scalar(
                text("SELECT count(*) FROM control_command WHERE device_id = :d"),
                {"d": zimmer.dev_id},
            )
            or 0
        )
    assert nachher == vorher
