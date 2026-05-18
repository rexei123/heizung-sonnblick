"""Sprint 11 T5 — Health-State-Compute-Task-Tests (AE-53).

Prueft ``_compute_health_state_async`` (Pure-Function-Aufruf, nicht der
Celery-Wrapper) gegen TimescaleDB. Pro Test:
- Fixture-Setup mit RoomType + Room + HeatingZone + Devices + ggf.
  SensorReading-Rows mit gezielten Timestamps.
- Aufruf von ``_compute_health_state_async()``.
- Verifikation device.health_state / heating_zone.health_state +
  Return-Dict (silent_transitions etc.).

Redis ist immer gemockt (autouse-fixture), Counter default 0 — Test 7
ueberschreibt den Mock fuer den Implausible-Pfad.

DB-Tests skippen ohne ``TEST_DATABASE_URL``.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock

import pytest
import pytest_asyncio
from sqlalchemy import delete as sa_delete
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from heizung.config import get_settings
from heizung.models.device import Device
from heizung.models.enums import DeviceKind, DeviceVendor, HeatingZoneKind
from heizung.models.heating_zone import HeatingZone
from heizung.models.room import Room
from heizung.models.room_type import RoomType
from heizung.models.sensor_reading import SensorReading
from heizung.services import redis_client
from heizung.tasks import health_tasks

TEST_DB_URL = os.environ.get("TEST_DATABASE_URL")
SKIP_REASON = "TEST_DATABASE_URL nicht gesetzt — DB-Tests brauchen Postgres"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    if not TEST_DB_URL:
        pytest.skip(SKIP_REASON)
    engine = create_async_engine(TEST_DB_URL)
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    async with sessionmaker() as session:
        try:
            yield session
        finally:
            await session.rollback()
    await engine.dispose()


async def _purge_t11t5(session: AsyncSession) -> None:
    """Loescht t11t5-*-Test-Daten + zugehoerige SensorReadings.

    Reihenfolge: SensorReading (FK device_id) -> Room (CASCADE-loescht
    HeatingZone+Device) -> RoomType. SensorReading-Filter via
    Device.dev_eui LIKE 'deadbeef%' (Test-Helper-Suffix); Produktive
    Vicki-dev_euis sind echte MAC-Adressen, keine "deadbeef..."-
    Pattern, also kein Konflikt zu erwarten.
    """
    devices_to_purge = list(
        (await session.execute(select(Device.id).where(Device.dev_eui.like("deadbeef%"))))
        .scalars()
        .all()
    )
    if devices_to_purge:
        await session.execute(
            sa_delete(SensorReading).where(SensorReading.device_id.in_(devices_to_purge))
        )
    # Rooms mit t11t5-Prefix loeschen — CASCADE raeumt HeatingZone+Device.
    rooms = list(
        (await session.execute(select(Room).where(Room.number.like("t11t5-%")))).scalars().all()
    )
    for room in rooms:
        await session.delete(room)
    # RoomTypes mit t11t5-Prefix.
    room_types = list(
        (await session.execute(select(RoomType).where(RoomType.name.like("t11t5-rt-%"))))
        .scalars()
        .all()
    )
    for rt in room_types:
        await session.delete(rt)
    await session.commit()


@pytest_asyncio.fixture(autouse=True)
async def _clean_t11t5_leftovers(db_session: AsyncSession) -> AsyncIterator[None]:
    """DB-Hygiene-Fixture: loescht t11t5-*-Reste vor + nach jedem Test.

    Sprint 11 T5 Lesson: DB-Tests gegen globalen Compute-Task brauchen
    Cleanup-Fixture (Strukturschutz) UND Assertion-Filter auf own_ids
    (Aussage-Haertung). Crash-Leftovers aus frueheren Runs (z.B. mit
    MissingGreenlet beim _cleanup-Aufruf) wuerden sonst die Per-Device-
    Compute-Logik Cross-Test stoeren — alte Devices mit stale Readings
    triggern silent-State und kontaminieren silent_transitions.
    """
    await _purge_t11t5(db_session)
    yield None
    await _purge_t11t5(db_session)


@pytest.fixture
def pin_database_url(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """``DATABASE_URL`` auf ``TEST_DATABASE_URL`` pinnen, damit
    ``_task_session`` aus ``engine_tasks`` und der Test dieselbe DB sehen.
    """
    assert TEST_DB_URL is not None
    monkeypatch.setenv("DATABASE_URL", TEST_DB_URL)
    get_settings.cache_clear()
    try:
        yield None
    finally:
        get_settings.cache_clear()


@pytest.fixture(autouse=True)
def fake_redis(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Default-Mock: ``get(...)`` -> ``None`` (Counter == 0).

    Tests, die die Implausible-Schwelle testen wollen, ueberschreiben
    ``fake.get.return_value`` (siehe Test 7).
    """
    fake = MagicMock()
    fake.get.return_value = None
    monkeypatch.setattr(redis_client, "get_redis_client", lambda: fake)
    return fake


async def _make_room_with_zone(session: AsyncSession, *, suffix: str) -> tuple[int, int]:
    """RoomType + Room + HeatingZone. Returns (room_id, zone_id)."""
    rt = RoomType(name=f"t11t5-rt-{suffix}")
    session.add(rt)
    await session.flush()
    room = Room(number=f"t11t5-{suffix}", room_type_id=rt.id)
    session.add(room)
    await session.flush()
    zone = HeatingZone(
        room_id=room.id,
        kind=HeatingZoneKind.BEDROOM,
        name="bedroom",
        health_state="silent",  # AE-53 Default; Compute soll auf real-state schreiben
    )
    session.add(zone)
    await session.flush()
    return room.id, zone.id


async def _add_device(
    session: AsyncSession,
    *,
    zone_id: int,
    dev_eui_suffix: str,
    initial_health_state: str = "silent",
) -> Device:
    """Device in der Zone anlegen. ``dev_eui`` = ``deadbeef{8-hex}``."""
    device = Device(
        dev_eui=f"deadbeef{dev_eui_suffix}",
        kind=DeviceKind.THERMOSTAT,
        vendor=DeviceVendor.MCLIMATE,
        model="vicki",
        heating_zone_id=zone_id,
        health_state=initial_health_state,
    )
    session.add(device)
    await session.flush()
    return device


async def _add_reading(
    session: AsyncSession,
    *,
    device_id: int,
    age: timedelta,
    temperature_c: Decimal | None,
    fcnt: int = 1,
) -> None:
    """SensorReading-Row mit (now - age) als time, temperatur wie angegeben."""
    reading = SensorReading(
        time=datetime.now(tz=UTC) - age,
        device_id=device_id,
        fcnt=fcnt,
        temperature=temperature_c,
    )
    session.add(reading)
    await session.flush()


async def _cleanup(session: AsyncSession, *, room_id: int, device_ids: list[int]) -> None:
    """Test-Daten nach committed Compute-Lauf manuell loeschen.

    Reihenfolge wichtig: SensorReading (FK auf Device) zuerst,
    dann Device, dann HeatingZone, dann Room, dann RoomType.
    Test-Session-Rollback raeumt commits nicht weg.
    """
    if device_ids:
        for sr in (
            (
                await session.execute(
                    select(SensorReading).where(SensorReading.device_id.in_(device_ids))
                )
            )
            .scalars()
            .all()
        ):
            await session.delete(sr)
    # Devices + Zone via FK-CASCADE-Delete am Room — Room loeschen reicht.
    room = await session.get(Room, room_id)
    if room is not None:
        rt_id = room.room_type_id
        await session.delete(room)
        rt = await session.get(RoomType, rt_id)
        if rt is not None:
            await session.delete(rt)
    await session.commit()


# ---------------------------------------------------------------------------
# Test 1 — Alle Devices frisch -> alle healthy, Zone healthy
# ---------------------------------------------------------------------------


async def test_all_devices_healthy_zone_becomes_healthy(
    db_session: AsyncSession,
    pin_database_url: None,
) -> None:
    suffix = uuid.uuid4().hex[:8]
    room_id, zone_id = await _make_room_with_zone(db_session, suffix=suffix)
    dev_a = await _add_device(db_session, zone_id=zone_id, dev_eui_suffix=uuid.uuid4().hex[:8])
    dev_b = await _add_device(db_session, zone_id=zone_id, dev_eui_suffix=uuid.uuid4().hex[:8])
    # IDs in lokale Vars VOR commit/expire — nach ``db_session.expire_all()``
    # wuerden ``dev_X.id``-Zugriffe lazy-loaden und unter dem async-Dialekt
    # ``MissingGreenlet`` werfen.
    dev_a_id = dev_a.id
    dev_b_id = dev_b.id
    await _add_reading(
        db_session, device_id=dev_a_id, age=timedelta(minutes=30), temperature_c=Decimal("20.0")
    )
    await _add_reading(
        db_session, device_id=dev_b_id, age=timedelta(minutes=30), temperature_c=Decimal("20.5")
    )
    await db_session.commit()

    try:
        result = await health_tasks._compute_health_state_async()

        own_ids = {dev_a_id, dev_b_id}
        my_transitions = [t for t in result["silent_transitions"] if t["device_id"] in own_ids]
        assert my_transitions == []

        db_session.expire_all()
        a = await db_session.get(Device, dev_a_id)
        b = await db_session.get(Device, dev_b_id)
        z = await db_session.get(HeatingZone, zone_id)
        assert a is not None and b is not None and z is not None
        assert a.health_state == "healthy"
        assert b.health_state == "healthy"
        assert z.health_state == "healthy"
    finally:
        await _cleanup(db_session, room_id=room_id, device_ids=[dev_a_id, dev_b_id])


# ---------------------------------------------------------------------------
# Test 2 — Mischung healthy/degraded/silent -> Zone degraded
# ---------------------------------------------------------------------------


async def test_mixed_states_zone_becomes_degraded(
    db_session: AsyncSession,
    pin_database_url: None,
) -> None:
    suffix = uuid.uuid4().hex[:8]
    room_id, zone_id = await _make_room_with_zone(db_session, suffix=suffix)
    dev_a = await _add_device(db_session, zone_id=zone_id, dev_eui_suffix=uuid.uuid4().hex[:8])
    dev_b = await _add_device(db_session, zone_id=zone_id, dev_eui_suffix=uuid.uuid4().hex[:8])
    dev_c = await _add_device(
        db_session,
        zone_id=zone_id,
        dev_eui_suffix=uuid.uuid4().hex[:8],
        initial_health_state="healthy",  # damit C-Uebergang zu silent ein transition ist
    )
    # IDs capturen VOR commit/expire (siehe Test 1 Begruendung).
    dev_a_id = dev_a.id
    dev_b_id = dev_b.id
    dev_c_id = dev_c.id
    await _add_reading(
        db_session, device_id=dev_a_id, age=timedelta(minutes=30), temperature_c=Decimal("20.0")
    )
    await _add_reading(
        db_session, device_id=dev_b_id, age=timedelta(hours=5), temperature_c=Decimal("20.0")
    )
    await _add_reading(
        db_session, device_id=dev_c_id, age=timedelta(hours=30), temperature_c=Decimal("20.0")
    )
    await db_session.commit()

    try:
        result = await health_tasks._compute_health_state_async()

        db_session.expire_all()
        a = await db_session.get(Device, dev_a_id)
        b = await db_session.get(Device, dev_b_id)
        c = await db_session.get(Device, dev_c_id)
        z = await db_session.get(HeatingZone, zone_id)
        assert a is not None and b is not None and c is not None and z is not None
        assert a.health_state == "healthy"
        assert b.health_state == "degraded"
        assert c.health_state == "silent"
        assert z.health_state == "degraded"

        # silent_transitions: nur C, weil A/B nicht silent + Vorzustand von A
        # ist silent (Default), und A geht zu healthy (nicht silent).
        own_ids = {dev_a_id, dev_b_id, dev_c_id}
        my_transitions = [t for t in result["silent_transitions"] if t["device_id"] in own_ids]
        assert len(my_transitions) == 1, f"erwarte 1 own transition (C), gefunden {my_transitions}"
        assert my_transitions[0]["device_id"] == dev_c_id
        assert my_transitions[0]["reason"] == "offline_24h"
    finally:
        await _cleanup(db_session, room_id=room_id, device_ids=[dev_a_id, dev_b_id, dev_c_id])


# ---------------------------------------------------------------------------
# Test 3 — Alle Devices offline >24h -> alle silent, Zone silent
# ---------------------------------------------------------------------------


async def test_all_silent_zone_becomes_silent(
    db_session: AsyncSession,
    pin_database_url: None,
) -> None:
    suffix = uuid.uuid4().hex[:8]
    room_id, zone_id = await _make_room_with_zone(db_session, suffix=suffix)
    dev_a = await _add_device(
        db_session,
        zone_id=zone_id,
        dev_eui_suffix=uuid.uuid4().hex[:8],
        initial_health_state="healthy",
    )
    dev_b = await _add_device(
        db_session,
        zone_id=zone_id,
        dev_eui_suffix=uuid.uuid4().hex[:8],
        initial_health_state="healthy",
    )
    # IDs capturen VOR commit/expire (siehe Test 1 Begruendung).
    dev_a_id = dev_a.id
    dev_b_id = dev_b.id
    await _add_reading(
        db_session, device_id=dev_a_id, age=timedelta(hours=48), temperature_c=Decimal("20.0")
    )
    await _add_reading(
        db_session, device_id=dev_b_id, age=timedelta(hours=48), temperature_c=Decimal("20.0")
    )
    await db_session.commit()

    try:
        result = await health_tasks._compute_health_state_async()

        db_session.expire_all()
        a = await db_session.get(Device, dev_a_id)
        b = await db_session.get(Device, dev_b_id)
        z = await db_session.get(HeatingZone, zone_id)
        assert a is not None and b is not None and z is not None
        assert a.health_state == "silent"
        assert b.health_state == "silent"
        assert z.health_state == "silent"

        own_ids = {dev_a_id, dev_b_id}
        my_transitions = [t for t in result["silent_transitions"] if t["device_id"] in own_ids]
        my_transition_ids = {t["device_id"] for t in my_transitions}
        assert my_transition_ids == own_ids, (
            f"erwarte beide own Devices in transitions, gefunden {my_transitions}"
        )
        assert all(t["reason"] == "offline_24h" for t in my_transitions)
    finally:
        await _cleanup(db_session, room_id=room_id, device_ids=[dev_a_id, dev_b_id])


# ---------------------------------------------------------------------------
# Test 4 — Outlier-Device wird suspicious, Zone degraded
# ---------------------------------------------------------------------------


async def test_outlier_device_becomes_suspicious(
    db_session: AsyncSession,
    pin_database_url: None,
) -> None:
    suffix = uuid.uuid4().hex[:8]
    room_id, zone_id = await _make_room_with_zone(db_session, suffix=suffix)
    dev_a = await _add_device(db_session, zone_id=zone_id, dev_eui_suffix=uuid.uuid4().hex[:8])
    dev_b = await _add_device(db_session, zone_id=zone_id, dev_eui_suffix=uuid.uuid4().hex[:8])
    dev_c = await _add_device(db_session, zone_id=zone_id, dev_eui_suffix=uuid.uuid4().hex[:8])
    # IDs capturen VOR commit/expire (siehe Test 1 Begruendung).
    dev_a_id = dev_a.id
    dev_b_id = dev_b.id
    dev_c_id = dev_c.id
    # A=20.0, B=20.5, C=28.5. Median(A,B) = 20.25, |28.5 - 20.25| = 8.25 > 7.0
    await _add_reading(
        db_session, device_id=dev_a_id, age=timedelta(minutes=10), temperature_c=Decimal("20.0")
    )
    await _add_reading(
        db_session, device_id=dev_b_id, age=timedelta(minutes=10), temperature_c=Decimal("20.5")
    )
    await _add_reading(
        db_session, device_id=dev_c_id, age=timedelta(minutes=10), temperature_c=Decimal("28.5")
    )
    await db_session.commit()

    try:
        result = await health_tasks._compute_health_state_async()

        own_ids = {dev_a_id, dev_b_id, dev_c_id}
        my_transitions = [t for t in result["silent_transitions"] if t["device_id"] in own_ids]
        assert my_transitions == []

        db_session.expire_all()
        a = await db_session.get(Device, dev_a_id)
        b = await db_session.get(Device, dev_b_id)
        c = await db_session.get(Device, dev_c_id)
        z = await db_session.get(HeatingZone, zone_id)
        assert a is not None and b is not None and c is not None and z is not None
        assert a.health_state == "healthy"
        assert b.health_state == "healthy"
        assert c.health_state == "suspicious"
        assert z.health_state == "degraded"  # weil 1 suspicious
    finally:
        await _cleanup(db_session, room_id=room_id, device_ids=[dev_a_id, dev_b_id, dev_c_id])


# ---------------------------------------------------------------------------
# Test 5 — Zone ohne Devices -> no_device
# ---------------------------------------------------------------------------


async def test_no_device_zone_becomes_no_device(
    db_session: AsyncSession,
    pin_database_url: None,
) -> None:
    suffix = uuid.uuid4().hex[:8]
    room_id, zone_id = await _make_room_with_zone(db_session, suffix=suffix)
    await db_session.commit()

    try:
        # silent_transitions-Assert gestrichen: Test 5 hat keine eigenen
        # Devices, kann also keinen own_ids-Filter machen. Andere Test-
        # Devices in der DB (auch bei intaktem Cleanup) waeren beobachtbar
        # in transitions. Kernaussage des Tests ist Zone -> no_device.
        await health_tasks._compute_health_state_async()

        db_session.expire_all()
        z = await db_session.get(HeatingZone, zone_id)
        assert z is not None
        assert z.health_state == "no_device"
    finally:
        await _cleanup(db_session, room_id=room_id, device_ids=[])


# ---------------------------------------------------------------------------
# Test 6 — Idempotenz: zweiter Lauf macht KEIN UPDATE
# ---------------------------------------------------------------------------


async def test_repeated_run_no_double_write(
    db_session: AsyncSession,
    pin_database_url: None,
) -> None:
    """Idempotenz-Check via SQLAlchemy ``before_update``-Event-Listener
    auf Device und HeatingZone. Beide Counter == 0 im zweiten Lauf
    (Wert-Vergleich in Phase 4/5 verhindert das Setter-Dirty-Pattern).
    """
    suffix = uuid.uuid4().hex[:8]
    room_id, zone_id = await _make_room_with_zone(db_session, suffix=suffix)
    dev = await _add_device(db_session, zone_id=zone_id, dev_eui_suffix=uuid.uuid4().hex[:8])
    # ID capturen VOR commit/expire (siehe Test 1 Begruendung). Auch im
    # ``_track_device``-Callback wird ``dev_id`` als int verglichen, damit
    # nach ``expire_all`` keine sync Attribut-Loads passieren.
    dev_id = dev.id
    await _add_reading(
        db_session, device_id=dev_id, age=timedelta(minutes=20), temperature_c=Decimal("20.0")
    )
    await db_session.commit()

    # Erster Lauf: kommt von 'silent' (Default) auf 'healthy'. Wir lassen ihn
    # ohne Listener laufen, damit nur der ZWEITE (idempotente) Lauf zaehlt.
    await health_tasks._compute_health_state_async()

    # Listener fuer den zweiten Lauf installieren.
    device_updates: list[int] = []
    zone_updates: list[int] = []

    def _track_device(_m: Any, _c: Any, target: Device) -> None:
        if target.id == dev_id:
            device_updates.append(target.id)

    def _track_zone(_m: Any, _c: Any, target: HeatingZone) -> None:
        if target.id == zone_id:
            zone_updates.append(target.id)

    event.listen(Device, "before_update", _track_device)
    event.listen(HeatingZone, "before_update", _track_zone)
    try:
        await health_tasks._compute_health_state_async()
    finally:
        event.remove(Device, "before_update", _track_device)
        event.remove(HeatingZone, "before_update", _track_zone)

    assert device_updates == [], (
        f"erwarte 0 Device-UPDATEs im 2. Lauf (Wert unveraendert), gefunden {device_updates}"
    )
    assert zone_updates == [], f"erwarte 0 HeatingZone-UPDATEs im 2. Lauf, gefunden {zone_updates}"

    db_session.expire_all()
    d = await db_session.get(Device, dev_id)
    z = await db_session.get(HeatingZone, zone_id)
    assert d is not None and z is not None
    assert d.health_state == "healthy"
    assert z.health_state == "healthy"

    await _cleanup(db_session, room_id=room_id, device_ids=[dev_id])


# ---------------------------------------------------------------------------
# Test 7 — Implausible-Counter >= 10 triggert silent (Stufe-3)
# ---------------------------------------------------------------------------


async def test_implausible_counter_threshold_triggers_silent(
    db_session: AsyncSession,
    pin_database_url: None,
    fake_redis: MagicMock,
) -> None:
    """Device hat frisches Reading (=> Basis-State healthy), aber Redis-
    Mock liefert ``b"15"`` (>= 10) -> Phase 3 ueberschreibt auf silent,
    silent_transitions enthaelt Device mit ``implausible_readings_24h``.
    """
    suffix = uuid.uuid4().hex[:8]
    room_id, zone_id = await _make_room_with_zone(db_session, suffix=suffix)
    dev = await _add_device(
        db_session,
        zone_id=zone_id,
        dev_eui_suffix=uuid.uuid4().hex[:8],
        initial_health_state="healthy",  # damit transition zu silent ein transition ist
    )
    # ID capturen VOR commit/expire (siehe Test 1 Begruendung).
    dev_id = dev.id
    await _add_reading(
        db_session, device_id=dev_id, age=timedelta(minutes=20), temperature_c=Decimal("20.0")
    )
    await db_session.commit()

    fake_redis.get.return_value = b"15"

    try:
        result = await health_tasks._compute_health_state_async()

        db_session.expire_all()
        d = await db_session.get(Device, dev_id)
        z = await db_session.get(HeatingZone, zone_id)
        assert d is not None and z is not None
        assert d.health_state == "silent", "Counter >= 10 muss Basis-State healthy ueberschreiben"
        assert z.health_state == "silent"

        own_ids = {dev_id}
        my_transitions = [t for t in result["silent_transitions"] if t["device_id"] in own_ids]
        assert len(my_transitions) == 1
        assert my_transitions[0]["device_id"] == dev_id
        assert my_transitions[0]["reason"] == "implausible_readings_24h"
    finally:
        await _cleanup(db_session, room_id=room_id, device_ids=[dev_id])
