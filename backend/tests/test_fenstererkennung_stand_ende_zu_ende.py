"""Vom ``0x46``-Uplink bis in die Datenbank: der Stand wird ablegbar.

**Der Anlass, 05.11.2026.** Auf die Frage „ist die Fenstererkennung auf
den Vickis ueberhaupt aktiv?" gab es im ganzen System keine Antwort.
``control_command`` fuehrt nur Sollwerte, ``business_audit`` keine
passende Aktion, und ``sensor_reading`` bekam keine Zeile, weil
``open_window_status_reply`` in ``REPLY_REPORT_TYPES`` steht. Geblieben
war eine Protokollzeile in einem Container, dessen Protokoll **18
Stunden** zurueckreichte.

Dieser Test geht die Kette, die das behebt:

    Codec-Ausgabe -> _handle_open_window_status_report -> sensor_reading

**Woher die Eingabe kommt, und was daran nicht echt ist.** Der
``object``-Block in ``vicki-ow-status-reply.json`` ist die Ausgabe des
**echten Codecs** (``infra/chirpstack/codecs/mclimate-vicki.js``,
``decodeUplink``) fuer die Bytes

    46 01 02 0F | 81 12 9B 7C D9 D9 11 F0 30

also Reply plus angehaengter Keepalive, in der Form des Live-Frames vom
26.10.2026. **Die Bytes selbst sind konstruiert, nicht gemessen** — es
ist in diesem Haus noch nie eine ``0x46``-Antwort eingegangen (0 Zeilen
in ``sensor_reading``, 0 Treffer im Protokoll, Befund 05.11.2026). Genau
deshalb gibt es diesen PR. Der Umschlag folgt
``vicki-temp-range-reply-107.json``.

**Warum die Eingabe aus einer Datei kommt und nicht aus einem Literal.**
Das ist die Lehre von ``test_geraetegrenzen_ende_zu_ende``: dort stand
``"temp_range_min": 15`` als ``int`` im Test, im Betrieb kommt ``15.0``
an, und die Pruefung lautete ``isinstance(..., int)``. Der Test war
gruen, die Anlage verwarf die Antwort. JSON unterscheidet 10 und 10.0
nicht — die Datei schreibt die Nachkommastelle deshalb ausdruecklich, und
der Codec-Lauf oben belegt, welche Felder Zahlen sind.

**Mutationsproben** (von Hand, 05.11.2026):

* ``_als_ganze_zahl(roh_dauer)`` gegen ein
  ``isinstance(roh_dauer, int)``-Gate getauscht -> **zwei** Tests fallen
  (``..._landet_als_stand_am_geraet`` und
  ``..._wird_als_aus_gespeichert``), beide mit „hat keine Zeile
  erzeugt". Das ist genau der Fehler, der bei 0x15 vier Tage gekostet
  hat — und er faellt hier doppelt auf, weil die Dauer in **beiden**
  schreibenden Tests durch dieselbe Pruefung geht.
* Die Delta-Spannenpruefung durch ``or False`` ersetzt ->
  ``test_unplausible_parameter_erzeugen_keine_zeile`` faellt.
* ``ow_detection_enabled=roh_enabled`` gegen ``=True`` getauscht ->
  ``test_ausgeschaltete_erkennung_wird_als_aus_gespeichert`` faellt. Das
  ist die Probe, die zaehlt: „aus" ist der erwartete Befund, und ein
  Schreibpfad, der immer ``True`` ablegt, waere schlimmer als keiner.
"""

from __future__ import annotations

import json
import os
import pathlib
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal
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

from heizung import db as db_modul
from heizung.models.device import Device
from heizung.models.enums import DeviceKind, DeviceVendor, HeatingZoneKind
from heizung.models.heating_zone import HeatingZone
from heizung.models.room import Room
from heizung.models.room_type import RoomType
from heizung.models.sensor_reading import SensorReading
from heizung.services import downlink_adapter, mqtt_subscriber

DATABASE_URL = os.environ.get("DATABASE_URL")
SKIP_REASON = "DATABASE_URL nicht gesetzt - der Ende-zu-Ende-Test braucht Test-DB"

UPLINK_DATEI = (
    pathlib.Path(__file__).resolve().parents[2]
    / "infra"
    / "chirpstack"
    / "test-uplinks"
    / "vicki-ow-status-reply.json"
)


def _lade_uplink() -> dict[str, Any]:
    return json.loads(UPLINK_DATEI.read_text(encoding="utf-8"))  # type: ignore[no-any-return]


@pytest_asyncio.fixture(autouse=True)
async def _frischer_pool() -> AsyncIterator[None]:
    """Vor jedem Test den **globalen** Pool leeren (§5.14).

    **Der Anlass, 05.11.2026, und er hat zwanzig Minuten gekostet.** Der
    Handler schreibt ueber ``heizung.db.SessionLocal``, also den globalen
    Pool. ``pytest-asyncio`` gibt jedem Test einen **eigenen**
    Event-Loop; asyncpg-Verbindungen haengen am Loop, in dem sie
    entstanden sind. Der zweite Test, der etwas schreibt, bekommt damit
    eine Verbindung aus dem geschlossenen Loop des ersten:

        RuntimeError: Event loop is closed

    Und weil der Schreibpfad seine Fehler defensiv faengt
    (``except Exception: logger.exception(...)``, dieselbe Haltung wie bei
    0x15 und beim FW-Bericht), **kam der Fehler nie an**. Das Symptom war
    „die 0x46-Antwort hat keine Zeile erzeugt" — also ein Befund am
    Zielort statt eines Fehlschlags am Tatort. Genau der Nachtrag zu
    §5.14, und die Protokollzeile war zusaetzlich unsichtbar, weil die
    ``heizung.*``-Logger im Testlauf nicht propagieren (§5.37).

    **Warum das im Praezedenzfall nicht aufgefallen ist.**
    ``test_geraetegrenzen_ende_zu_ende`` hat 16 Tests, aber nur **einer**
    erreicht den DB-Schreibpfad — die uebrigen steigen vorher aus
    (Keepalive ohne Felder, unplausible Werte). Die Falle braucht **zwei**
    schreibende Tests in einer Datei, und diese Datei ist die erste, die
    das tut. Wer dort einen zweiten schreibenden Test ergaenzt, laeuft
    hinein.

    **Warum testseitig und nicht am Produktionscode.** Der Pool ist im
    Betrieb richtig: ein Prozess, ein Loop. Die Eigenart gehoert dem
    Pruefstand, also wird sie dort behoben (vgl. §5.14, wo der
    Produktionsfix ``worker_process_init`` war — derselbe Gedanke, andere
    Grenze).

    **Backlog:** das gehoert als Helfer in ``tests/conftest.py``, damit
    die naechste Datei es nicht neu lernen muss. Hier bewusst lokal
    gelassen, weil ein gemeinsamer Helfer alle DB-Tests beruehrt und
    nicht in diesen PR gehoert (§5.1).
    """
    await db_modul.engine.dispose()
    yield
    await db_modul.engine.dispose()


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
    # schema_constraint: room.number max 20, device.dev_eui max 16 (§5.49)
    suffix = uuid.uuid4().hex[:8]
    rt = RoomType(name=f"ow38-{suffix}", min_temp_celsius=15, max_temp_celsius=25)
    session.add(rt)
    await session.flush()
    room = Room(number=f"ow38-{suffix}", room_type_id=rt.id)
    session.add(room)
    await session.flush()
    zone = HeatingZone(room_id=room.id, kind=HeatingZoneKind.BEDROOM, name="Schlafzimmer")
    session.add(zone)
    await session.flush()
    geraet = Device(
        dev_eui=f"ee38{suffix}ee38",
        label=f"ow38-{suffix}",
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
    """Die Uplink-JSON, nur mit unserem Test-Geraet und jetzt."""
    rohling = _lade_uplink()
    rohling["deviceInfo"]["devEui"] = dev_eui
    rohling["time"] = datetime.now(tz=UTC).isoformat()
    if obj is not None:
        rohling["object"] = obj
    return mqtt_subscriber.ChirpStackUplink.model_validate(rohling)


async def _stand_zeilen(session: AsyncSession, device_id: int) -> list[SensorReading]:
    return list(
        (
            await session.execute(
                select(SensorReading)
                .where(SensorReading.device_id == device_id)
                .where(SensorReading.ow_detection_enabled.is_not(None))
            )
        )
        .scalars()
        .all()
    )


async def test_codec_ausgabe_landet_als_stand_am_geraet(db_session: AsyncSession) -> None:
    """Die ganze Kette, in der Reihenfolge, in der sie im Betrieb laeuft."""
    geraet, zone, room, rt = await _lege_geraet_an(db_session)
    try:
        await mqtt_subscriber._handle_open_window_status_report(_uplink(geraet.dev_eui))

        zeilen = await _stand_zeilen(db_session, geraet.id)
        assert len(zeilen) == 1, "die 0x46-Antwort hat keine Zeile erzeugt"
        zeile = zeilen[0]
        assert zeile.ow_detection_enabled is True
        assert zeile.ow_detection_duration_min == 10
        assert zeile.ow_detection_delta_c == Decimal("1.5")
        # Der Zeitpunkt ist die Bestaetigung — ohne ihn ist die Zeile als
        # Antwort auf „seit wann" wertlos.
        assert zeile.time is not None
    finally:
        await _raeum_auf(db_session, geraet, zone, room, rt)


async def test_ausgeschaltete_erkennung_wird_als_aus_gespeichert(db_session: AsyncSession) -> None:
    """``enabled = false`` ist der erwartete Befund und muss ankommen.

    Das ist nicht der Nebenfall, sondern der wahrscheinliche: die
    Werksvorgabe ist **aus**, und am 05.11.2026 sprach alles dafuer, dass
    kein Geraet im Haus je ein ``0x45`` bekommen hat. Ein Schreibpfad,
    der nur ``True`` ablegen kann, wuerde die Frage genau dann nicht
    beantworten, wenn sie gestellt wird.
    """
    geraet, zone, room, rt = await _lege_geraet_an(db_session)
    try:
        aus = _lade_uplink()["object"]
        aus["open_window_detection_enabled"] = False
        await mqtt_subscriber._handle_open_window_status_report(_uplink(geraet.dev_eui, aus))

        zeilen = await _stand_zeilen(db_session, geraet.id)
        assert len(zeilen) == 1, "die 0x46-Antwort mit enabled=false hat keine Zeile erzeugt"
        assert zeilen[0].ow_detection_enabled is False
    finally:
        await _raeum_auf(db_session, geraet, zone, room, rt)


async def test_keepalive_ohne_stand_erzeugt_keine_zeile(db_session: AsyncSession) -> None:
    """Ein normaler Keep-alive darf den Stand nicht ueberschreiben.

    Er sagt darueber nichts. Wuerde er eine Zeile mit ``False`` anlegen,
    waere die juengste Zeile, die das Feld fuehrt, eine Erfindung — und
    die Anzeige wuerde „aus" behaupten, wo „unbekannt" richtig ist.
    """
    geraet, zone, room, rt = await _lege_geraet_an(db_session)
    try:
        ohne = _lade_uplink()["object"]
        for feld in (
            "report_type",
            "command",
            "open_window_detection_enabled",
            "open_window_detection_duration_min",
            "open_window_detection_delta_c",
        ):
            ohne.pop(feld, None)
        await mqtt_subscriber._handle_open_window_status_report(_uplink(geraet.dev_eui, ohne))

        assert await _stand_zeilen(db_session, geraet.id) == []
    finally:
        await _raeum_auf(db_session, geraet, zone, room, rt)


async def test_unplausible_parameter_erzeugen_keine_zeile(db_session: AsyncSession) -> None:
    """Lieber „nicht bestaetigt" als ein Parameter, den es nicht gibt.

    Die Spannen stehen im Downlink-Adapter und werden hier **nicht** als
    Zahlen wiederholt: eine zweite Wahrheit darueber, was das Geraet
    annimmt, liefe beim ersten Nachjustieren auseinander.
    """
    geraet, zone, room, rt = await _lege_geraet_an(db_session)
    try:
        for feld, wert in (
            ("open_window_detection_delta_c", float(downlink_adapter.OW_DELTA_MAX_C) + 0.1),
            ("open_window_detection_duration_min", downlink_adapter.OW_DURATION_MIN_MAX + 5),
            # Keine Vielfache-von-5-Dauer: der Codec rechnet Byte * 5,
            # ein anderer Wert kann also nicht von dort kommen.
            ("open_window_detection_duration_min", 7.0),
        ):
            kaputt = _lade_uplink()["object"]
            kaputt[feld] = wert
            await mqtt_subscriber._handle_open_window_status_report(_uplink(geraet.dev_eui, kaputt))
            assert await _stand_zeilen(db_session, geraet.id) == [], (
                f"{feld}={wert} haette verworfen werden muessen"
            )
    finally:
        await _raeum_auf(db_session, geraet, zone, room, rt)


async def test_der_reply_typ_ist_im_subscriber_bekannt() -> None:
    """Ohne diesen Eintrag laeuft der Frame in den Keepalive-Pfad.

    Dann legt ``_persist_uplink`` fuer eine Befehlsantwort eine Zeile aus
    lauter NULL an, und ``_handle_open_window_status_report`` wird nie
    gerufen. Der Eintrag ist die Weiche, nicht Zierde.
    """
    assert "open_window_status_reply" in mqtt_subscriber.REPLY_REPORT_TYPES
    assert _lade_uplink()["object"]["report_type"] == "open_window_status_reply"


async def test_stand_und_zustand_sind_verschiedene_spalten() -> None:
    """``ow_detection_enabled`` ist nicht ``open_window``.

    Der Frame traegt beides: die Erkennung ist **an** (``enabled =
    true``) und gerade ist **kein** Fenster offen (``openWindow =
    false``). Wer die Spalten verwechselt, liest aus lauter
    ``open_window = false`` den Befund „es wurde nie gelueftet" statt
    „die Erkennung war aus" — die Verwechslung, die am 05.11.2026
    offenstand.
    """
    obj = _lade_uplink()["object"]
    assert obj["open_window_detection_enabled"] is True
    assert obj["openWindow"] is False
    # Und der Handler schreibt genau eine der beiden Spalten.
    assert hasattr(SensorReading, "ow_detection_enabled")
    assert hasattr(SensorReading, "open_window")
