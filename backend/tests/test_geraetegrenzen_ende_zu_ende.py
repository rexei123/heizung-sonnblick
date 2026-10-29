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

import json
import os
import pathlib
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

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

#: Die echte Uplink-JSON, in der Form, in der sie ueber MQTT ankommt.
#:
#: **Warum eine Datei und keine Konstante im Test** (Befund des
#: Betreibers, 26.10.2026 10:14:30). Die erste Fassung dieses Tests hatte
#: den ``object``-Block hier als Python-Literal mit ``"temp_range_min":
#: 15`` — also einem ``int``. Im Betrieb kommen die Zahlen als
#: **Gleitkommazahl** an (``15.0``), und die Pruefung im Subscriber
#: lautete ``isinstance(min_c, int)``. Der Test war gruen, die Anlage
#: verwarf die Antwort.
#:
#: Das ist Paragraph 5.79 woertlich: der Erwartungswert kam aus meiner
#: Vorstellung der Form, nicht aus einer Quelle. Jetzt kommt die Eingabe
#: aus einer Datei, die die Form **traegt** — JSON unterscheidet 15 und
#: 15.0 nicht, die Datei schreibt die Nachkommastelle deshalb
#: ausdruecklich.
#:
#: Herkunft der Datei: der ``object``-Block ist die Ausgabe des **echten
#: Codecs** fuer die Live-Bytes des Betreibers
#: (``data = "FQ8ZgRKbfNnZEfAw"``, Geraet 70b3d52dd303337d, fCnt 3897),
#: jede Zahl als Gleitkommazahl. Der Umschlag folgt
#: ``vicki-status-001.json``.
UPLINK_DATEI = (
    pathlib.Path(__file__).resolve().parents[2]
    / "infra"
    / "chirpstack"
    / "test-uplinks"
    / "vicki-temp-range-reply-107.json"
)


def _lade_uplink() -> dict[str, Any]:
    return json.loads(UPLINK_DATEI.read_text(encoding="utf-8"))  # type: ignore[no-any-return]


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


def _uplink(dev_eui: str, obj: dict[str, Any] | None = None) -> mqtt_subscriber.ChirpStackUplink:
    """Die echte Uplink-JSON, nur mit unserem Test-Geraet und jetzt.

    ``obj`` ersetzt den ``object``-Block, wenn ein Test eine Abwandlung
    braucht. Ohne Angabe kommt der Block aus der Datei — also die Form,
    die im Betrieb ankommt.
    """
    rohling = _lade_uplink()
    rohling["deviceInfo"]["devEui"] = dev_eui
    rohling["time"] = datetime.now(tz=UTC).isoformat()
    if obj is not None:
        rohling["object"] = obj
    return mqtt_subscriber.ChirpStackUplink.model_validate(rohling)


async def test_codec_ausgabe_landet_als_grenzen_am_geraet(db_session: AsyncSession) -> None:
    """Die ganze Kette, in der Reihenfolge, in der sie im Betrieb laeuft."""
    geraet, zone, room, rt = await _lege_geraet_an(db_session)
    try:
        # 1. Der Subscriber verarbeitet den Frame.
        await mqtt_subscriber._handle_temp_range_report(_uplink(geraet.dev_eui))

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
    assert _lade_uplink()["object"]["report_type"] == mqtt_subscriber.TEMP_RANGE_REPORT_TYPE


async def test_keepalive_ohne_grenzen_erzeugt_keine_zeile(db_session: AsyncSession) -> None:
    """Ein normaler Keep-alive darf die Grenzen nicht ueberschreiben.

    Er fuehrt die Felder nicht; ihn als „keine Grenzen" zu speichern
    waere derselbe Fehler, der bei ``child_lock`` schon einmal gemacht
    wurde (24c) — und die Anzeige sprang auf „nicht bestaetigt", obwohl
    die Antwort vorlag.
    """
    geraet, zone, room, rt = await _lege_geraet_an(db_session)
    try:
        ohne = {k: v for k, v in _lade_uplink()["object"].items() if not k.startswith("temp_range")}
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
        kaputt = dict(_lade_uplink()["object"])
        kaputt["temp_range_min"] = "fuenfzehn"
        await mqtt_subscriber._handle_temp_range_report(_uplink(geraet.dev_eui, kaputt))

        anzahl = await db_session.scalar(
            text("SELECT count(*) FROM sensor_reading WHERE device_id = :i"), {"i": geraet.id}
        )
        assert anzahl == 0
    finally:
        await _raeum_auf(db_session, geraet, zone, room, rt)


# ---------------------------------------------------------------------------
# Die Form der Zahlen (Befund des Betreibers, 26.10.2026 10:14:30)
# ---------------------------------------------------------------------------


def test_die_fixture_traegt_die_zahlen_als_gleitkomma() -> None:
    """Die Schranke gegen ein "Aufraeumen" dieser Datei.

    Wer ``15.0`` in der JSON zu ``15`` macht, macht den Test gruen und den
    Betrieb kaputt — genau diese Richtung ist am 26.10. passiert, nur
    umgekehrt: der Test hatte ``int``, die Anlage hatte ``float``, und der
    Test war gruen.

    JSON unterscheidet die beiden nicht; die Datei schreibt die
    Nachkommastelle deshalb ausdruecklich, und dieser Test haelt sie fest.
    """
    obj = _lade_uplink()["object"]
    for feld in ("temp_range_min", "temp_range_max"):
        assert isinstance(obj[feld], float), (
            f"{feld} ist {type(obj[feld]).__name__} statt float — die Fixture "
            "bildet die Form des Betriebs nicht mehr ab"
        )
    # Und die Werte selbst, aus dem Live-Frame.
    assert obj["temp_range_min"] == 15.0
    assert obj["temp_range_max"] == 25.0


@pytest.mark.parametrize(
    ("roh", "erwartet"),
    [
        (15, 15),  # int, wie der Codec ihn meint
        (15.0, 15),  # float, wie er ankommt — der Befund
        (-3.0, -3),  # negativ und ganzzahlig: zulaessige Zahl
        (0.0, 0),
        (15.5, None),  # echte Nachkommastelle: verwerfen, nicht runden
        (True, None),  # isinstance(True, int) ist wahr — trotzdem kein Messwert
        (False, None),
        ("15", None),
        (None, None),
    ],
)
def test_ganze_zahl_aus_dem_object_block(roh: object, erwartet: int | None) -> None:
    """Die Umrechnung selbst, mit allen Formen, die vorkommen koennen.

    ``15.5`` wird **verworfen und nicht gerundet**: das Geraet meldet
    ganze Grad, und eine Nachkommastelle heisst, dass die Annahme ueber
    das Format nicht stimmt. Dann ist Schweigen richtiger als eine Zahl,
    die plausibel aussieht.
    """
    assert mqtt_subscriber._als_ganze_zahl(roh) == erwartet


async def test_werte_ausserhalb_der_spanne_werden_verworfen(db_session: AsyncSession) -> None:
    """5..30 ist die Spanne des Geraets (Werk 5/30).

    Eine Antwort darueber hinaus heisst, dass die Bytes anders gemeint
    sind als angenommen — und dann ist "nicht bestaetigt" die wahre
    Aussage, nicht eine Grenze, die es nicht gibt.
    """
    geraet, zone, room, rt = await _lege_geraet_an(db_session)
    try:
        for min_c, max_c in ((3.0, 25.0), (15.0, 35.0), (25.0, 15.0), (20.0, 20.0)):
            obj = dict(_lade_uplink()["object"])
            obj["temp_range_min"] = min_c
            obj["temp_range_max"] = max_c
            await mqtt_subscriber._handle_temp_range_report(_uplink(geraet.dev_eui, obj))

        anzahl = await db_session.scalar(
            text("SELECT count(*) FROM sensor_reading WHERE device_id = :i"), {"i": geraet.id}
        )
        assert anzahl == 0, "eine unmoegliche Spanne wurde gespeichert"
    finally:
        await _raeum_auf(db_session, geraet, zone, room, rt)


def test_die_spanne_kommt_aus_dem_downlink_adapter() -> None:
    """Eine Zahl, eine Stelle.

    Die Spanne, die das Geraet annimmt, steht im Downlink-Adapter — dort
    prueft sie auch der Sende-Pfad. Zwei Zahlen fuer dieselbe
    Geraete-Eigenschaft liefen beim ersten Nachjustieren auseinander
    (Paragraph 5.53), und zwar stumm: beide Seiten saehen plausibel aus.
    """
    from heizung.services import downlink_adapter

    assert (downlink_adapter.TEMP_RANGE_MIN_C, downlink_adapter.TEMP_RANGE_MAX_C) == (5, 30)
