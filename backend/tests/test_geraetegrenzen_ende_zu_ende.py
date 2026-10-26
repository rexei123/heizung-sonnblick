"""Vom MQTT-Uplink bis „Am Geraet": die Grenzen gehen den ganzen Weg (T1b).

**Warum dieser Test und nicht die vorhandenen.** Es gab schon drei:

* der Codec-Spiegel prueft die **Bytes** (``test_codec_mirror``),
* der Dienst-Test prueft die **Abfrage** (``test_geraetegrenzen``),
* der e2e-Test im Frontend prueft die **Anzeige**.

Alle drei waren gruen, waehrend in der Anlage nichts ankam. Der Fehler
lag zwischen ihnen: ``decodeUplink`` routete ``0x15`` nicht an den
Reply-Zweig, und der Subscriber bekam ``{command: 21}``.

Das ist Paragraph 5.83 — drei Zusicherungen, jede auf ihrer Ebene
richtig, und keine auf der Ebene, die zaehlt. Dieser Test geht die
**Kette** und laesst genau diese Luecke nicht mehr zu:

    Codec-Ausgabe -> Subscriber-Handler -> sensor_reading
                  -> ist_grenzen_je_geraet -> „15–25 °C, bestaetigt"

Was er **nicht** tut: MQTT sprechen. Die Zeile, die MQTT von
``_handle_temp_range_report`` trennt, ist das Routing im Subscriber, und
dafuer gibt es den Reply-Typ-Test. Hier beginnt die Kette an der Stelle,
an der der Codec sie uebergibt — mit genau dem ``object``-Block, den der
echte Codec aus dem Live-Frame erzeugt.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from heizung.models.device import Device
from heizung.models.enums import DeviceKind, DeviceVendor, HeatingZoneKind
from heizung.models.heating_zone import HeatingZone
from heizung.models.room import Room
from heizung.models.room_type import RoomType
from heizung.models.sensor_reading import SensorReading
from heizung.services import mqtt_subscriber
from heizung.services.geraetegrenzen import Grenzen, ist_grenzen_je_geraet

DATABASE_URL = os.environ.get("DATABASE_URL")
SKIP_REASON = "DATABASE_URL nicht gesetzt - der Ende-zu-Ende-Test braucht Test-DB"

#: Der ``object``-Block, den der echte Codec aus dem Live-Frame des
#: Betreibers erzeugt (Geraet 70b3d52dd303337d, 26.10.2026 09:44:51,
#: fCnt 3897, ``data = "FQ8ZgRKbfNnZEfAw"`` = ``15 0F 19 | 81 …``).
#:
#: **Abgenommen vom Codec-Lauf, nicht erfunden** — der JS-Test in
#: ``infra/chirpstack/tests/test_codec_decode_uplink.py`` fuehrt dieselben
#: Bytes durch ``decodeUplink`` und belegt diese Felder. Hier steht die
#: Ausgabe, damit die Kette ohne Node prueefbar bleibt; die Herkunft
#: steht dabei, weil ein Erwartungswert ohne Herkunft nur eine
#: Momentaufnahme ist (Paragraph 5.79).
CODEC_AUSGABE = {
    "report_type": "temp_range_reply",
    "command": 21,
    "temp_range_min": 15,
    "temp_range_max": 25,
    # Der angehaengte Keep-alive — er gehoert dazu, weil der Frame ihn
    # traegt. Dass der Subscriber ihn fuer einen Reply nicht als Messung
    # speichert, ist eine andere Entscheidung (siehe Modul-Kopf des
    # Subscribers).
    "temperature": 22.35,
    "target_temperature": 18,
    "battery_voltage": 3.5,
    "valve_openness": 0,
    "attachedBackplate": True,
    "childLock": False,
}


@pytest_asyncio.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    if not DATABASE_URL:
        pytest.skip(SKIP_REASON)
    engine: AsyncEngine = create_async_engine(DATABASE_URL)
    try:
        sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
        async with sessionmaker() as session:
            yield session
    finally:
        await engine.dispose()


async def _lege_geraet_an(session: AsyncSession) -> tuple[Device, HeatingZone, Room, RoomType]:
    suffix = uuid.uuid4().hex[:8]
    rt = RoomType(name=f"t1b-{suffix}", min_temp_celsius=15, max_temp_celsius=25)
    session.add(rt)
    await session.flush()
    room = Room(number=f"t1b-{suffix}", room_type_id=rt.id)
    session.add(room)
    await session.flush()
    zone = HeatingZone(room_id=room.id, kind=HeatingZoneKind.BEDROOM, name="Schlafzimmer")
    session.add(zone)
    await session.flush()
    geraet = Device(
        dev_eui=f"ee00{suffix}ee00",
        label=f"t1b-{suffix}",
        kind=DeviceKind.THERMOSTAT,
        vendor=DeviceVendor.MCLIMATE,
        model="vicki",
        heating_zone_id=zone.id,
    )
    session.add(geraet)
    await session.commit()
    return geraet, zone, room, rt


async def _raeum_auf(
    session: AsyncSession, geraet: Device, zone: HeatingZone, room: Room, rt: RoomType
) -> None:
    await session.execute(text("DELETE FROM sensor_reading WHERE device_id = :i"), {"i": geraet.id})
    await session.execute(text("DELETE FROM device WHERE id = :i"), {"i": geraet.id})
    await session.execute(text("DELETE FROM heating_zone WHERE id = :i"), {"i": zone.id})
    await session.execute(text("DELETE FROM room WHERE id = :i"), {"i": room.id})
    await session.execute(text("DELETE FROM room_type WHERE id = :i"), {"i": rt.id})
    await session.commit()


def _uplink(dev_eui: str, obj: dict[str, object]) -> mqtt_subscriber.ChirpStackUplink:
    return mqtt_subscriber.ChirpStackUplink.model_validate(
        {
            "deviceInfo": {"devEui": dev_eui},
            "fCnt": 3897,
            "fPort": 2,
            "time": datetime.now(tz=UTC).isoformat(),
            "object": obj,
            "data": "FQ8ZgRKbfNnZEfAw",
        }
    )


async def test_codec_ausgabe_landet_als_grenzen_am_geraet(db_session: AsyncSession) -> None:
    """Die ganze Kette, in der Reihenfolge, in der sie im Betrieb laeuft."""
    geraet, zone, room, rt = await _lege_geraet_an(db_session)
    try:
        # 1. Der Subscriber verarbeitet den Frame.
        await mqtt_subscriber._handle_temp_range_report(_uplink(geraet.dev_eui, CODEC_AUSGABE))

        # 2. Es liegt eine Zeile mit den Grenzen.
        zeilen = list(
            (
                await db_session.execute(
                    select(SensorReading)
                    .where(SensorReading.device_id == geraet.id)
                    .where(SensorReading.temp_range_min.is_not(None))
                )
            )
            .scalars()
            .all()
        )
        assert len(zeilen) == 1, "die 0x15-Antwort hat keine Zeile erzeugt"
        assert (zeilen[0].temp_range_min, zeilen[0].temp_range_max) == (15, 25)

        # 3. Und die Abfrage, die die Geraeteseite benutzt, findet sie.
        befund = (await ist_grenzen_je_geraet(db_session, [geraet.id]))[geraet.id]
        assert befund is not None, "die Geraeteseite wuerde „nicht bestaetigt“ zeigen"
        assert befund.grenzen == Grenzen(15, 25)
        assert befund.gemeldet_um is not None
    finally:
        await _raeum_auf(db_session, geraet, zone, room, rt)


async def test_der_reply_typ_ist_im_subscriber_bekannt() -> None:
    """Ohne diesen Eintrag laeuft der Frame in den Keepalive-Pfad.

    Dann legt ``_persist_uplink`` fuer eine Befehlsantwort eine
    ``sensor_reading``-Zeile aus lauter NULL an, und
    ``_handle_temp_range_report`` wird nie gerufen. Der Eintrag ist also
    die Weiche, nicht Zierde.
    """
    assert mqtt_subscriber.TEMP_RANGE_REPORT_TYPE in mqtt_subscriber.REPLY_REPORT_TYPES
    assert CODEC_AUSGABE["report_type"] == mqtt_subscriber.TEMP_RANGE_REPORT_TYPE


async def test_keepalive_ohne_grenzen_erzeugt_keine_zeile(db_session: AsyncSession) -> None:
    """Ein normaler Keep-alive darf die Grenzen nicht ueberschreiben.

    Er fuehrt die Felder nicht; ihn als „keine Grenzen" zu speichern
    waere derselbe Fehler, der bei ``child_lock`` schon einmal gemacht
    wurde (24c) — und die Anzeige sprang auf „nicht bestaetigt", obwohl
    die Antwort vorlag.
    """
    geraet, zone, room, rt = await _lege_geraet_an(db_session)
    try:
        ohne = {k: v for k, v in CODEC_AUSGABE.items() if not k.startswith("temp_range")}
        ohne["report_type"] = "periodic"
        await mqtt_subscriber._handle_temp_range_report(_uplink(geraet.dev_eui, ohne))

        anzahl = await db_session.scalar(
            text("SELECT count(*) FROM sensor_reading WHERE device_id = :i"), {"i": geraet.id}
        )
        assert anzahl == 0, "ein Keep-alive hat eine Grenzen-Zeile erzeugt"
    finally:
        await _raeum_auf(db_session, geraet, zone, room, rt)


async def test_unbrauchbare_werte_werden_nicht_gespeichert(db_session: AsyncSession) -> None:
    """Ein Reply mit kaputten Feldern erzeugt keine Zeile, sondern eine Warnung.

    Lieber „nicht bestaetigt" als eine Grenze, die es nicht gibt: die
    Anzeige sagt dann, dass noch keine Antwort kam, und das ist wahr.
    """
    geraet, zone, room, rt = await _lege_geraet_an(db_session)
    try:
        kaputt = dict(CODEC_AUSGABE)
        kaputt["temp_range_min"] = "fuenfzehn"
        await mqtt_subscriber._handle_temp_range_report(_uplink(geraet.dev_eui, kaputt))

        anzahl = await db_session.scalar(
            text("SELECT count(*) FROM sensor_reading WHERE device_id = :i"), {"i": geraet.id}
        )
        assert anzahl == 0
    finally:
        await _raeum_auf(db_session, geraet, zone, room, rt)
