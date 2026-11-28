"""Der Aufraeum-Helfer selbst, gegen die Datenbank (27.11.2026).

**Warum ein Test fuer einen Test-Helfer.** ``purge_test_data_by_prefix``
ist der Boden, auf dem zwoelf Dateien stehen (Paragraph 5.39). Liefert er
nicht, merkt es niemand dort, wo er aufgerufen wird -- sondern irgendwann
in einer **anderen** Datei, die eine hausweite Zahl abfragt.

Genau das ist passiert. Der Helfer loeschte die Messwerte der Geraete und
dann die **Zimmer**, im Vertrauen darauf, dass der Cascade von ``room``
die Geraete mitnimmt. Das gilt aber nur fuer Geraete **mit** Heizzone;
eines ohne Zuordnung haengt an keinem Zimmer. Gemessen am 27.11.2026 in
der lokalen Test-Datenbank: **50 Geraete ohne Etikett, davon 49 ohne
Heizzone**, aus drei Gesamtlaeufen -- und davon 16 aus einer Datei, die
den Helfer korrekt aufruft.

Aufgefallen ist es an ``test_funkempfang``: ``lies_funkempfang`` zaehlt
die Meldungen des **ganzen Hauses** im Zehn-Minuten-Fenster, und die
Reste haben zweimal mitgezaehlt. In CI blieb alles gruen, dort ist die
Datenbank frisch.

Diese Datei prueft die drei Zusicherungen, auf die sich die Aufrufer
verlassen -- und die erste ist die, die gefehlt hat.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from heizung.models.device import Device
from heizung.models.enums import DeviceKind, DeviceVendor, HeatingZoneKind
from heizung.models.heating_zone import HeatingZone
from heizung.models.room import Room
from heizung.models.room_type import RoomType
from heizung.models.sensor_reading import SensorReading
from tests.conftest import purge_test_data_by_prefix

TEST_DB_URL = os.environ.get("TEST_DATABASE_URL")
SKIP_REASON = "TEST_DATABASE_URL nicht gesetzt"

pytestmark = pytest.mark.skipif(not TEST_DB_URL, reason=SKIP_REASON)

#: Eigene Praefixe, damit dieser Test niemandem ins Geschirr faehrt.
PREFIX = "putz"
GERAETE_MUSTER = "cafe0042%"
#: Ein Geraet, das der Helfer **nicht** anfassen darf.
FREMD_EUI = "fe1dfe1d00000001"


@pytest_asyncio.fixture
async def maker() -> AsyncIterator[Any]:
    assert TEST_DB_URL
    engine = create_async_engine(TEST_DB_URL)
    try:
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        async with async_sessionmaker(engine, expire_on_commit=False)() as putz:
            await purge_test_data_by_prefix(putz, PREFIX, dev_eui_pattern=GERAETE_MUSTER)
            await putz.execute(text("DELETE FROM device WHERE dev_eui = :e"), {"e": FREMD_EUI})
            await putz.commit()
        await engine.dispose()


async def _zaehle(session: AsyncSession, sql: str, werte: dict[str, Any]) -> int:
    return int(await session.scalar(text(sql), werte) or 0)


async def test_der_helfer_loescht_ein_geraet_ohne_zone(maker: Any) -> None:
    """**Die Zusicherung, die gefehlt hat.**

    Ein Geraet ohne Heizzone haengt an keinem Zimmer. Der Cascade von
    ``room`` erreicht es nicht, und bis zum 27.11.2026 hat der Helfer
    sich allein darauf verlassen. In Tests ist das kein Sonderfall,
    sondern der Normalfall: wer nur den Funkweg prueft, braucht kein
    Zimmer.
    """
    eui = f"cafe0042{uuid.uuid4().hex[:8]}"
    async with maker() as session:
        session.add(
            Device(
                dev_eui=eui,
                kind=DeviceKind.THERMOSTAT,
                vendor=DeviceVendor.MCLIMATE,
                model="vicki",
            )
        )
        await session.commit()

    async with maker() as session:
        assert (
            await _zaehle(session, "SELECT count(*) FROM device WHERE dev_eui = :e", {"e": eui})
            == 1
        )
        assert (
            await _zaehle(
                session,
                "SELECT count(*) FROM device WHERE dev_eui = :e AND heating_zone_id IS NULL",
                {"e": eui},
            )
            == 1
        ), "der Aufbau hat dem Geraet eine Zone gegeben -- dann prueft dieser Test nichts"

    async with maker() as session:
        await purge_test_data_by_prefix(session, PREFIX, dev_eui_pattern=GERAETE_MUSTER)

    async with maker() as session:
        assert (
            await _zaehle(session, "SELECT count(*) FROM device WHERE dev_eui = :e", {"e": eui})
            == 0
        ), "das Geraet ohne Zone ist liegen geblieben -- genau der Befund vom 27.11.2026"


async def test_der_helfer_nimmt_messwerte_und_zimmer_mit(maker: Any) -> None:
    """Der Bestandsteil der Zusicherung, mit Zimmer und Zone.

    Steht hier, weil die Korrektur am Helfer ihn haette brechen koennen:
    die Geraete jetzt **vorab** zu loeschen, waehrend ihre Zone noch
    steht, ist nur dann richtig, wenn die Messwerte vorher weg sind.
    """
    short = uuid.uuid4().hex[:6]
    eui = f"cafe0042{uuid.uuid4().hex[:8]}"
    async with maker() as session:
        rt = RoomType(name=f"{PREFIX}-rt-{short}", is_bookable=False)
        session.add(rt)
        await session.flush()
        room = Room(number=f"{PREFIX}-{short}", room_type_id=rt.id)
        session.add(room)
        await session.flush()
        zone = HeatingZone(room_id=room.id, kind=HeatingZoneKind.BEDROOM, name="bedroom")
        session.add(zone)
        await session.flush()
        geraet = Device(
            dev_eui=eui,
            kind=DeviceKind.THERMOSTAT,
            vendor=DeviceVendor.MCLIMATE,
            model="vicki",
            heating_zone_id=zone.id,
        )
        session.add(geraet)
        await session.flush()
        session.add(
            SensorReading(
                device_id=geraet.id,
                time=datetime.now(tz=UTC),
                temperature=Decimal("21.0"),
            )
        )
        await session.commit()
        room_id = room.id

    async with maker() as session:
        await purge_test_data_by_prefix(session, PREFIX, dev_eui_pattern=GERAETE_MUSTER)

    async with maker() as session:
        assert (
            await _zaehle(session, "SELECT count(*) FROM device WHERE dev_eui = :e", {"e": eui})
            == 0
        )
        assert (
            await _zaehle(session, "SELECT count(*) FROM room WHERE id = :r", {"r": room_id}) == 0
        )
        assert (
            await _zaehle(
                session,
                "SELECT count(*) FROM room_type WHERE name = :n",
                {"n": f"{PREFIX}-rt-{short}"},
            )
            == 0
        )


async def test_der_helfer_laesst_fremde_geraete_stehen(maker: Any) -> None:
    """**Die Gegenprobe, und ohne sie waere der Helfer gefaehrlich.**

    Er laeuft gegen dieselbe Datenbank, in der andere Dateien gerade
    ihren Aufbau haben. Ein ``DELETE FROM device`` ohne Muster waere
    bequem und wuerde die Nachbarn abraeumen -- derselbe Fehler eine
    Ebene tiefer.

    **Es stehen zwei Geraete im Aufbau, und das ist Absicht.** Die erste
    Fassung dieses Tests legte nur das fremde an. Damit war
    ``devices_to_purge`` leer, der ganze Muster-Zweig des Helfers wurde
    uebersprungen, und die Mutationsprobe „loesche alle Geraete" blieb
    **gruen** -- ein Test, der seinen Gegenstand nicht erreicht
    (Paragraph 5.55). Gefunden hat ihn genau diese Probe.
    """
    eigen = f"cafe0042{uuid.uuid4().hex[:8]}"
    async with maker() as session:
        session.add_all(
            [
                Device(
                    dev_eui=FREMD_EUI,
                    kind=DeviceKind.THERMOSTAT,
                    vendor=DeviceVendor.MCLIMATE,
                    model="vicki",
                ),
                Device(
                    dev_eui=eigen,
                    kind=DeviceKind.THERMOSTAT,
                    vendor=DeviceVendor.MCLIMATE,
                    model="vicki",
                ),
            ]
        )
        await session.commit()

    async with maker() as session:
        await purge_test_data_by_prefix(session, PREFIX, dev_eui_pattern=GERAETE_MUSTER)

    async with maker() as session:
        assert (
            await _zaehle(session, "SELECT count(*) FROM device WHERE dev_eui = :e", {"e": eigen})
            == 0
        ), "das eigene Geraet ist liegen geblieben -- dann prueft die Gegenprobe nichts"
        assert (
            await _zaehle(
                session, "SELECT count(*) FROM device WHERE dev_eui = :e", {"e": FREMD_EUI}
            )
            == 1
        ), "der Helfer hat ein Geraet geloescht, das nicht auf sein Muster passt"


async def test_ohne_muster_bleibt_das_geraet_liegen(maker: Any) -> None:
    """**Der Cascade nimmt Geraete gar nicht mit -- gemessen, nicht gelesen.**

    Der Docstring des Helfers behauptete bis zum 27.11.2026, der Cascade
    von ``room`` raeume „HeatingZone und Device". Die Haelfte davon ist
    falsch:

        fk_device_heating_zone | device | heating_zone | n

    ``n`` ist ``ON DELETE SET NULL``. Ein geloeschtes Zimmer nimmt seine
    Zonen mit, und die Geraete **verlieren ihre Zuordnung** -- sie bleiben
    stehen, ohne Zone. Das ist die Quelle der 49 zonenlosen Geraete: nicht
    Geraete, die nie eine Zone hatten, sondern Geraete, deren Zone
    weggeloescht wurde.

    Dieser Test haelt das Verhalten fest, statt es zu wuenschen. Solange
    der Fremdschluessel ``SET NULL`` ist, ist ``dev_eui_pattern`` die
    **einzige** Stelle, an der Geraete verschwinden -- wer den Helfer
    ohne Muster ruft, raeumt keine Geraete auf, und das muss er wissen.

    Wird der Fremdschluessel eines Tages auf ``CASCADE`` gestellt, faellt
    dieser Test. Das ist dann die richtige Nachricht und nicht ein
    Mangel: der Docstring des Helfers gehoert in demselben Schritt
    nachgezogen.
    """
    short = uuid.uuid4().hex[:6]
    eui = f"cafe0042{uuid.uuid4().hex[:8]}"
    async with maker() as session:
        rt = RoomType(name=f"{PREFIX}-rt-{short}", is_bookable=False)
        session.add(rt)
        await session.flush()
        room = Room(number=f"{PREFIX}-{short}", room_type_id=rt.id)
        session.add(room)
        await session.flush()
        zone = HeatingZone(room_id=room.id, kind=HeatingZoneKind.BEDROOM, name="bedroom")
        session.add(zone)
        await session.flush()
        session.add(
            Device(
                dev_eui=eui,
                kind=DeviceKind.THERMOSTAT,
                vendor=DeviceVendor.MCLIMATE,
                model="vicki",
                heating_zone_id=zone.id,
            )
        )
        await session.commit()
        zone_id = zone.id

    async with maker() as session:
        await purge_test_data_by_prefix(session, PREFIX)

    async with maker() as session:
        assert (
            await _zaehle(
                session, "SELECT count(*) FROM heating_zone WHERE id = :z", {"z": zone_id}
            )
            == 0
        ), "die Zone haette mit dem Zimmer verschwinden muessen"
        assert (
            await _zaehle(
                session,
                "SELECT count(*) FROM device WHERE dev_eui = :e AND heating_zone_id IS NULL",
                {"e": eui},
            )
            == 1
        ), (
            "das Geraet ist weg oder hat noch eine Zone -- dann ist der Fremdschluessel "
            "nicht mehr ON DELETE SET NULL, und der Docstring des Helfers gehoert nachgezogen"
        )
