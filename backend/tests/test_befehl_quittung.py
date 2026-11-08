"""``acknowledged_at`` fuellen — reine Buchfuehrung (Sprint 25, T2).

**Der Befund.** Die Spalte existiert seit Sprint 9.2 und wurde **nie**
gesetzt. Jeder Befehl in der Datenbank sieht aus wie „nie angekommen",
auch die, die angekommen sind. Eine Spalte, die immer leer ist, ist keine
fehlende Information — sie ist eine falsche.

**Was hier geprueft wird, und was ausdruecklich nicht.** Dass die Spalte
sich fuellt, und dass sie den **richtigen** Befehl trifft. **Nicht**, dass
irgendetwas daran haengt: kein Tor, keine Wiederholung, keine Schwelle.
Der letzte Test dieser Datei haelt genau das fest — ein Fehler in der
Quittung darf den Messwert nicht aufhalten.

**Class A ist der Grund fuer den zweiten Test.** Ein Vicki holt den
Downlink erst im Fenster nach einem eigenen Uplink ab; die Bestaetigung
traegt dann die **uebernaechste** Meldung. Ein Test, der die Quittung
sofort erwartet, prueft eine Hardware, die es nicht gibt.

DB-Tests; skip ohne ``TEST_DATABASE_URL`` (Paragraph 5.50, lokal
gelaufen). ``_frischer_pool`` ist Pflicht und nicht Zierde — Begruendung
im Nachtrag zu Paragraph 5.14 und in
``test_fenstererkennung_stand_ende_zu_ende``: zwei schreibende Tests in
einer Datei laufen sonst in eine geschlossene Verbindung, und der Fehler
erscheint am **Zielort** statt am Tatort.
"""

from __future__ import annotations

import json
import os
import pathlib
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from heizung import db as db_modul
from heizung.models.control_command import ControlCommand
from heizung.models.device import Device
from heizung.models.enums import CommandReason, DeviceKind, DeviceVendor, HeatingZoneKind
from heizung.models.heating_zone import HeatingZone
from heizung.models.room import Room
from heizung.models.room_type import RoomType
from heizung.models.sensor_reading import SensorReading
from heizung.services import befehl_quittung, mqtt_subscriber

DATABASE_URL = os.environ.get("TEST_DATABASE_URL") or os.environ.get("DATABASE_URL")
SKIP_REASON = "TEST_DATABASE_URL nicht gesetzt - DB-Tests brauchen Postgres"

UPLINK_PERIODISCH = (
    pathlib.Path(__file__).resolve().parents[2]
    / "infra"
    / "chirpstack"
    / "test-uplinks"
    / "vicki-status-001.json"
)

JETZT = datetime(2026, 11, 8, 11, 0, tzinfo=UTC)

pytestmark = pytest.mark.asyncio


def _periodisch(dev_eui: str, *, setpoint: float, zeit: datetime) -> Any:
    """Ein Periodenbericht (``0x81``-Familie) mit gewaehltem Sollwert."""
    rohling = json.loads(UPLINK_PERIODISCH.read_text(encoding="utf-8"))
    rohling["deviceInfo"]["devEui"] = dev_eui
    rohling["time"] = zeit.isoformat()
    rohling["object"]["target_temperature"] = setpoint
    return mqtt_subscriber.ChirpStackUplink.model_validate(rohling)


def _setpoint_antwort(dev_eui: str, *, setpoint: float, zeit: datetime) -> Any:
    """Die ausdrueckliche Antwort auf ``0x51`` — Codec-Form von ``0x52``."""
    rohling = json.loads(UPLINK_PERIODISCH.read_text(encoding="utf-8"))
    rohling["deviceInfo"]["devEui"] = dev_eui
    rohling["time"] = zeit.isoformat()
    rohling["fPort"] = 2
    rohling["object"] = {
        "report_type": "setpoint_reply",
        "command": 0x52,
        "target_temperature": setpoint,
        "targetTemperature": setpoint,
        "acknowledged": True,
    }
    return mqtt_subscriber.ChirpStackUplink.model_validate(rohling)


@pytest_asyncio.fixture(autouse=True)
async def _frischer_pool() -> AsyncIterator[None]:
    """Vor jedem Test den globalen Pool leeren (Paragraph 5.14, Nachtrag)."""
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


# ---------------------------------------------------------------------------
# Aufbau
# ---------------------------------------------------------------------------


async def _lege_geraet_an(session: AsyncSession) -> tuple[Device, HeatingZone, Room, RoomType]:
    # schema_constraint: room.number max 20, device.dev_eui max 16 (Paragraph 5.49)
    suffix = uuid.uuid4().hex[:8]
    rt = RoomType(name=f"qu25-{suffix}", min_temp_celsius=15, max_temp_celsius=25)
    session.add(rt)
    await session.flush()
    room = Room(number=f"qu25-{suffix}", room_type_id=rt.id)
    session.add(room)
    await session.flush()
    zone = HeatingZone(room_id=room.id, kind=HeatingZoneKind.BEDROOM, name="Schlafzimmer")
    session.add(zone)
    await session.flush()
    geraet = Device(
        dev_eui=f"qu25{suffix}qu25"[:16].replace("q", "c").replace("u", "d"),
        label=f"qu25-{suffix}",
        kind=DeviceKind.THERMOSTAT,
        vendor=DeviceVendor.MCLIMATE,
        model="vicki",
        heating_zone_id=zone.id,
        health_state="healthy",
    )
    session.add(geraet)
    await session.commit()
    return geraet, zone, room, rt


async def _raeum_auf(
    session: AsyncSession, geraet: Device, zone: HeatingZone, room: Room, rt: RoomType
) -> None:
    await session.execute(
        text("DELETE FROM control_command WHERE device_id = :i"), {"i": geraet.id}
    )
    await session.execute(text("DELETE FROM sensor_reading WHERE device_id = :i"), {"i": geraet.id})
    await session.execute(text("DELETE FROM event_log WHERE room_id = :i"), {"i": room.id})
    await session.execute(text("DELETE FROM device WHERE id = :i"), {"i": geraet.id})
    await session.execute(text("DELETE FROM heating_zone WHERE id = :i"), {"i": zone.id})
    await session.execute(text("DELETE FROM room WHERE id = :i"), {"i": room.id})
    await session.execute(text("DELETE FROM room_type WHERE id = :i"), {"i": rt.id})
    await session.commit()


async def _befehl(
    session: AsyncSession,
    device_id: int,
    *,
    wert: int,
    gesendet_um: datetime | None,
) -> ControlCommand:
    cc = ControlCommand(
        issued_at=gesendet_um or JETZT,
        device_id=device_id,
        target_setpoint=Decimal(wert),
        reason=CommandReason.OCCUPIED_SETPOINT,
        sent_to_gateway_at=gesendet_um,
    )
    session.add(cc)
    await session.commit()
    return cc


# ---------------------------------------------------------------------------
# 1. Die Spalte fuellt sich
# ---------------------------------------------------------------------------


async def test_periodenbericht_quittiert_den_gesendeten_wert(db_session: AsyncSession) -> None:
    """Das Geraet meldet 21, gesendet war 21 -> ``acknowledged_at`` gesetzt.

    Der Zeitstempel ist die **Uplink-Zeit**, nicht die Serverzeit: sonst
    waere die Dauer zwischen Befehl und Quittung von der Laufzeit des
    Subscribers abhaengig (Paragraph 5.68-Familie — eine Zahl, die etwas
    anderes misst, als ihr Name sagt).
    """
    geraet, zone, room, rt = await _lege_geraet_an(db_session)
    try:
        cc = await _befehl(
            db_session, geraet.id, wert=21, gesendet_um=JETZT - timedelta(minutes=12)
        )
        uplink_zeit = JETZT

        quittiert = await befehl_quittung.quittiere(
            db_session,
            device_id=geraet.id,
            gemeldet_c=Decimal("21.0"),
            gemeldet_um=uplink_zeit,
        )
        await db_session.commit()

        assert quittiert == cc.id
        await db_session.refresh(cc)
        assert cc.acknowledged_at == uplink_zeit
    finally:
        await _raeum_auf(db_session, geraet, zone, room, rt)


async def test_der_vergleich_laeuft_als_zahl_nicht_als_zeichenkette(
    db_session: AsyncSession,
) -> None:
    """``21.00`` in der Datenbank und ``21.0`` vom Geraet sind derselbe Wert.

    Genau dieser Unterschied hat am 07.11.2026 die CI von #393 rot
    gemacht: die Spalte ist ``NUMERIC``, und ein Zeichenketten-Vergleich
    haette hier nie quittiert.
    """
    geraet, zone, room, rt = await _lege_geraet_an(db_session)
    try:
        cc = await _befehl(
            db_session, geraet.id, wert=21, gesendet_um=JETZT - timedelta(minutes=12)
        )
        for gemeldet in (Decimal("21"), Decimal("21.0"), Decimal("21.00")):
            cc.acknowledged_at = None
            await db_session.commit()
            assert (
                await befehl_quittung.quittiere(
                    db_session,
                    device_id=geraet.id,
                    gemeldet_c=gemeldet,
                    gemeldet_um=JETZT,
                )
                == cc.id
            ), f"{gemeldet} haette quittieren muessen"
            await db_session.commit()
    finally:
        await _raeum_auf(db_session, geraet, zone, room, rt)


# ---------------------------------------------------------------------------
# 2. Class A — die Bestaetigung kommt in der uebernaechsten Meldung
# ---------------------------------------------------------------------------


async def test_class_a_die_quittung_kommt_erst_in_der_uebernaechsten_meldung(
    db_session: AsyncSession,
) -> None:
    """Der Ablauf, wie ein Vicki ihn wirklich fährt.

    1. Befehl auf 21 geht um 11:00 hinaus.
    2. Der naechste Uplink (11:02) meldet noch **18** — das Geraet hat den
       Downlink in seinem Fenster abgeholt, aber noch nichts bestaetigt.
       **Keine Quittung**, und das ist der Kern dieses Tests: ein Uplink
       nach dem Befehl ist noch keine Bestaetigung.
    3. Der uebernaechste Uplink (11:12) meldet 21 -> Quittung, mit dessen
       Zeit.

    Ein Test, der die Quittung sofort erwartet, prueft eine Hardware, die
    es nicht gibt.
    """
    geraet, zone, room, rt = await _lege_geraet_an(db_session)
    try:
        cc = await _befehl(db_session, geraet.id, wert=21, gesendet_um=JETZT)

        # Schritt 2: der Uplink unmittelbar danach traegt den alten Wert.
        assert (
            await befehl_quittung.quittiere(
                db_session,
                device_id=geraet.id,
                gemeldet_c=Decimal("18.0"),
                gemeldet_um=JETZT + timedelta(minutes=2),
            )
            is None
        )
        await db_session.refresh(cc)
        assert cc.acknowledged_at is None, "ein Uplink mit dem alten Wert quittiert nichts"

        # Schritt 3: die uebernaechste Meldung traegt den gesendeten Wert.
        spaeter = JETZT + timedelta(minutes=12)
        assert (
            await befehl_quittung.quittiere(
                db_session,
                device_id=geraet.id,
                gemeldet_c=Decimal("21.0"),
                gemeldet_um=spaeter,
            )
            == cc.id
        )
        await db_session.commit()
        await db_session.refresh(cc)
        assert cc.acknowledged_at == spaeter
        # Die Dauer ist die Aussage dieses Feldes: zwoelf Minuten sind der
        # Normalfall bei Class A, nicht der Verdachtsfall.
        assert cc.acknowledged_at - cc.sent_to_gateway_at == timedelta(minutes=12)
    finally:
        await _raeum_auf(db_session, geraet, zone, room, rt)


# ---------------------------------------------------------------------------
# 3. Den richtigen Befehl treffen
# ---------------------------------------------------------------------------


async def test_ein_uplink_vor_dem_befehl_quittiert_ihn_nicht(db_session: AsyncSession) -> None:
    """Die Zeitgrenze, und sie ist nicht Kosmetik.

    Ohne ``sent_to_gateway_at <= gemeldet_um`` quittiert bei einem
    Downlink, der im selben Augenblick rausgeht, der Uplink **von
    vorher** — dieselbe Falle, die am 07.11.2026 im Ack-Fenster von
    ``device_adapter`` steckte.
    """
    geraet, zone, room, rt = await _lege_geraet_an(db_session)
    try:
        cc = await _befehl(db_session, geraet.id, wert=21, gesendet_um=JETZT)

        assert (
            await befehl_quittung.quittiere(
                db_session,
                device_id=geraet.id,
                gemeldet_c=Decimal("21.0"),
                gemeldet_um=JETZT - timedelta(seconds=30),
            )
            is None
        )
        await db_session.refresh(cc)
        assert cc.acknowledged_at is None
    finally:
        await _raeum_auf(db_session, geraet, zone, room, rt)


async def test_nur_der_juengste_offene_befehl_mit_diesem_wert(db_session: AsyncSession) -> None:
    """Zwei offene Befehle auf 21 -> der juengere wird quittiert.

    **Der aeltere bleibt offen, und das ist gewollt.** Er wurde vom
    juengeren ueberholt, und niemand hat ihn je einzeln bestaetigt. Das
    als „auch quittiert" zu schreiben waere eine Annahme statt einer
    Beobachtung (Festlegung des Betreibers, Brief T2).
    """
    geraet, zone, room, rt = await _lege_geraet_an(db_session)
    try:
        alt = await _befehl(db_session, geraet.id, wert=21, gesendet_um=JETZT - timedelta(hours=2))
        neu = await _befehl(
            db_session, geraet.id, wert=21, gesendet_um=JETZT - timedelta(minutes=12)
        )

        assert (
            await befehl_quittung.quittiere(
                db_session,
                device_id=geraet.id,
                gemeldet_c=Decimal("21.0"),
                gemeldet_um=JETZT,
            )
            == neu.id
        )
        await db_session.commit()
        await db_session.refresh(alt)
        await db_session.refresh(neu)
        assert neu.acknowledged_at == JETZT
        assert alt.acknowledged_at is None
    finally:
        await _raeum_auf(db_session, geraet, zone, room, rt)


async def test_ein_nicht_gesendeter_befehl_wird_nicht_quittiert(db_session: AsyncSession) -> None:
    """``sent_to_gateway_at IS NULL`` heisst: der Befehl hat das Haus nie verlassen.

    Ihn zu quittieren waere die Gegenrichtung des Befundes: eine Spalte,
    die etwas bestaetigt, was nie passiert ist.
    """
    geraet, zone, room, rt = await _lege_geraet_an(db_session)
    try:
        cc = await _befehl(db_session, geraet.id, wert=21, gesendet_um=None)

        assert (
            await befehl_quittung.quittiere(
                db_session,
                device_id=geraet.id,
                gemeldet_c=Decimal("21.0"),
                gemeldet_um=JETZT,
            )
            is None
        )
        await db_session.refresh(cc)
        assert cc.acknowledged_at is None
    finally:
        await _raeum_auf(db_session, geraet, zone, room, rt)


async def test_ein_schon_quittierter_befehl_wird_nicht_zweimal_gestempelt(
    db_session: AsyncSession,
) -> None:
    """Der zweite Uplink mit demselben Wert ruehrt den Zeitstempel nicht an.

    Sonst wanderte ``acknowledged_at`` mit jedem Periodenbericht nach
    vorn, und die Dauer zwischen Befehl und Bestaetigung — die einzige
    Aussage dieses Feldes — waere immer rund zehn Minuten, ganz gleich wie
    lange es wirklich gedauert hat.
    """
    geraet, zone, room, rt = await _lege_geraet_an(db_session)
    try:
        cc = await _befehl(
            db_session, geraet.id, wert=21, gesendet_um=JETZT - timedelta(minutes=12)
        )
        erste = JETZT
        await befehl_quittung.quittiere(
            db_session, device_id=geraet.id, gemeldet_c=Decimal("21.0"), gemeldet_um=erste
        )
        await db_session.commit()

        assert (
            await befehl_quittung.quittiere(
                db_session,
                device_id=geraet.id,
                gemeldet_c=Decimal("21.0"),
                gemeldet_um=JETZT + timedelta(minutes=10),
            )
            is None
        )
        await db_session.refresh(cc)
        assert cc.acknowledged_at == erste
    finally:
        await _raeum_auf(db_session, geraet, zone, room, rt)


# ---------------------------------------------------------------------------
# 4. Beide Uplink-Wege
# ---------------------------------------------------------------------------


async def test_der_keepalive_pfad_quittiert_ueber_den_subscriber(
    db_session: AsyncSession,
) -> None:
    """Ende zu Ende durch ``_persist_uplink``: der Periodenbericht quittiert."""
    geraet, zone, room, rt = await _lege_geraet_an(db_session)
    try:
        cc = await _befehl(
            db_session, geraet.id, wert=21, gesendet_um=JETZT - timedelta(minutes=12)
        )
        uplink_zeit = JETZT

        await mqtt_subscriber._persist_uplink(
            _periodisch(geraet.dev_eui, setpoint=21.0, zeit=uplink_zeit)
        )

        await db_session.refresh(cc)
        assert cc.acknowledged_at == uplink_zeit
    finally:
        await _raeum_auf(db_session, geraet, zone, room, rt)


async def test_die_setpoint_antwort_quittiert_ueber_den_reply_zweig(
    db_session: AsyncSession,
) -> None:
    """Die ``0x52``-Antwort ist die ausdrueckliche Bestaetigung.

    Sie laeuft nicht durch ``_persist_uplink`` — der Reply-Zweig
    ueberspringt den Reading-Insert —, deshalb braucht sie einen eigenen
    Aufruf. Ohne ihn waere genau der Frame unbeachtet, der am
    deutlichsten „angekommen" sagt.
    """
    geraet, zone, room, rt = await _lege_geraet_an(db_session)
    try:
        cc = await _befehl(db_session, geraet.id, wert=22, gesendet_um=JETZT - timedelta(minutes=5))
        uplink_zeit = JETZT

        await mqtt_subscriber._handle_setpoint_reply_quittung(
            _setpoint_antwort(geraet.dev_eui, setpoint=22.0, zeit=uplink_zeit)
        )

        await db_session.refresh(cc)
        assert cc.acknowledged_at == uplink_zeit
    finally:
        await _raeum_auf(db_session, geraet, zone, room, rt)


# ---------------------------------------------------------------------------
# 5. Kein Tor — der wichtigste Test dieser Datei
# ---------------------------------------------------------------------------


async def test_eine_gescheiterte_quittung_haelt_den_messwert_nicht_auf(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Die Quittung ist Buchfuehrung und darf nichts blockieren.

    **Der wichtigste Test hier.** Die Vorgabe lautet „kein Tor, keine
    Logik haengt daran" — dann darf eine kaputte Quittung auch den
    Messwert nicht verhindern, der gerade geschrieben wird. Ein verlorener
    Eintrag in einer Diagnose-Spalte kostet eine Protokollzeile; ein
    verlorener Messwert kostet die Regelung.
    """

    async def _kaputt(*args: object, **kwargs: object) -> int | None:
        raise SQLAlchemyError("Quittung absichtlich kaputt")

    monkeypatch.setattr(mqtt_subscriber.befehl_quittung, "quittiere", _kaputt)

    geraet, zone, room, rt = await _lege_geraet_an(db_session)
    try:
        uplink_zeit = JETZT
        await mqtt_subscriber._persist_uplink(
            _periodisch(geraet.dev_eui, setpoint=21.0, zeit=uplink_zeit)
        )

        zeilen = list(
            (
                await db_session.execute(
                    select(SensorReading).where(SensorReading.device_id == geraet.id)
                )
            )
            .scalars()
            .all()
        )
        assert len(zeilen) == 1, "der Messwert muss geschrieben sein, trotz kaputter Quittung"
        assert zeilen[0].setpoint == Decimal("21.0")
    finally:
        await _raeum_auf(db_session, geraet, zone, room, rt)


# ---------------------------------------------------------------------------
# 6. Die Verdrahtung im Reply-Zweig
# ---------------------------------------------------------------------------


def test_der_reply_zweig_ruft_die_quittung() -> None:
    """Pruefung der **Verdrahtung**, nicht des Verhaltens — und sie hat einen Anlass.

    Die Mutationsprobe „Aufruf im Reply-Zweig entfernt" ist am
    08.11.2026 **nicht aufgefallen**: der Test oben ruft
    ``_handle_setpoint_reply_quittung`` direkt auf und sagt deshalb
    nichts darueber, ob die Schleife ihn auch aufruft. Dieselbe Luecke
    haben die beiden aelteren Reply-Handler (``0x04``, ``0x46``) — nur
    hat dort nie jemand die Probe gemacht.

    ``_consume_loop`` ist der MQTT-Verbraucher und ohne Broker nicht
    aufrufbar; ihn fuer einen Test zu zerlegen waere ein Eingriff in den
    Eingangspfad und gehoert nicht in einen Buchfuehrungs-PR
    (Paragraph 5.1). Also wird gelesen, was dort steht.

    **Was dieser Test nicht kann:** er belegt die Reihenfolge nicht und
    nicht, dass der Zweig ueberhaupt erreicht wird. Er faellt genau dann,
    wenn jemand den Aufruf entfernt oder umbenennt — und das ist der Fall,
    den die Probe gefunden hat.
    """
    import inspect

    quelle = inspect.getsource(mqtt_subscriber._consume_loop)
    assert "_handle_setpoint_reply_quittung(uplink)" in quelle, (
        "Der Reply-Zweig ruft die Quittung nicht mehr auf. Dann bleibt der "
        "Frame unbeachtet, der am deutlichsten 'angekommen' sagt."
    )
