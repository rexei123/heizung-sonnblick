"""Sprint 12 — E2E Verbund-Tests fuer Multi-Vicki + Fenster + Override-Reject.

Sammelt die T5-Verhaltens-Verbund-Tests. Statt sie auf 4 Bestands-Test-
Dateien zu verteilen, liegen sie hier zusammen — Hardware-Pfad-Review
ueberblickbar in einem File.

Szenarien:

- A: 2-Zonen-Room (je 1 Vicki), Fenster zu, kein Override, OCCUPIED
     -> beide Zonen identischer Setpoint, downlink_per_device 2x sent.
- B: 2-Zonen-Room, Fenster in einer Zone offen, VACANT
     -> beide Zonen 10 degC (Frostschutz), setpoint_source frost_protection.
- C: 2-Zonen-Room, Fenster in einer Zone offen, OCCUPIED
     -> beide Zonen default_t_vacant (18), setpoint_source default_t_vacant.
- D: 1-Zone-3-Vicki, 1 Vicki silent, Fenster zu, OCCUPIED
     -> 2 Downlinks (nur healthy), count_skipped=0, count_failed=0.
- E: Aktiver Override + Fenster geht auf zwischen Tick 1 und Tick 2
     -> Tick 1: Setpoint 22 (Override aktiv); Tick 2: Setpoint 18
        (Layer 4 ueberschreibt, override_overridden_by_window_open-Marker
        in extras + detail-Prefix). Override-Tabellen-Eintrag bleibt.
- F: POST /override + Fenster offen -> 409, Tabelle leer.
- G: POST /override + alle Vickis silent + open_window-Reading
     -> 201, Override persistiert (Symmetrie zu Layer 4: unhealthy zaehlt
        nicht, Helper liefert leere Liste).

A-E nutzen direkten Aufruf von ``engine_tasks._evaluate_room_async``
(Engine-Tick), F-G httpx + FastAPI-App.

Mocking ``send_setpoint`` via ``monkeypatch.setattr`` — keine echten
MQTT-Calls.

Cleanup via ``purge_test_data_by_prefix`` aus T0-Helper plus expliziter
Device-Purge fuer dev_eui-Pattern (T0-Helper raeumt Rooms+RoomTypes,
Devices werden durch Room->HeatingZone-CASCADE auf SET NULL georphant
und brauchen separates Cleanup). Alle DB-Tests skippen ohne
``TEST_DATABASE_URL``.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from alembic.config import Config
from httpx import ASGITransport
from sqlalchemy import delete as sa_delete
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from alembic import command
from heizung.config import get_settings
from heizung.db import get_session
from heizung.main import app
from heizung.models.control_command import ControlCommand
from heizung.models.device import Device
from heizung.models.enums import (
    CommandReason,
    DeviceKind,
    DeviceVendor,
    EventLogLayer,
    HeatingZoneKind,
    OverrideSource,
    RoomStatus,
)
from heizung.models.event_log import EventLog
from heizung.models.heating_zone import HeatingZone
from heizung.models.manual_override import ManualOverride
from heizung.models.room import Room
from heizung.models.room_type import RoomType
from heizung.models.sensor_reading import SensorReading
from heizung.tasks import engine_tasks
from tests.conftest import purge_test_data_by_prefix

TEST_DB_URL = os.environ.get("TEST_DATABASE_URL")
SKIP_REASON = "TEST_DATABASE_URL nicht gesetzt — Sprint-12-E2E braucht Postgres"
PREFIX = "t12e2e"
DEV_EUI_PATTERN = "deadbeef%"


# ---------------------------------------------------------------------------
# Module-scoped Migration + Admin-Insert (parallel zu conftest._ensure_test_admin,
# das DATABASE_URL liest; hier benutzen wir TEST_DATABASE_URL)
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture(scope="module", autouse=True)
async def _migrate_and_seed_admin() -> AsyncIterator[None]:
    if not TEST_DB_URL:
        yield
        return
    backend_root = Path(__file__).resolve().parents[1]
    cfg = Config(str(backend_root / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend_root / "alembic"))
    cfg.set_main_option("sqlalchemy.url", TEST_DB_URL)
    await asyncio.to_thread(command.upgrade, cfg, "head")

    from heizung.models.enums import UserRole
    from heizung.models.user import User

    engine = create_async_engine(TEST_DB_URL)
    sm = async_sessionmaker(engine, expire_on_commit=False)
    async with sm() as session:
        existing = (
            await session.execute(select(User).where(User.role == UserRole.ADMIN).limit(1))
        ).scalar_one_or_none()
        if existing is None:
            session.add(
                User(
                    email="test-admin-sprint12@local",
                    password_hash="test-hash-not-used",
                    role=UserRole.ADMIN,
                    is_active=True,
                    must_change_password=False,
                )
            )
            await session.commit()
    await engine.dispose()
    yield


# ---------------------------------------------------------------------------
# Engine-Tick-Fixtures (Szenarien A-E)
# ---------------------------------------------------------------------------


async def _purge_orphan_devices(session: AsyncSession) -> None:
    """Loescht Test-Devices nach dev_eui-Pattern + ihre ControlCommands.

    Ergaenzt ``purge_test_data_by_prefix`` aus T0: Room->HeatingZone-CASCADE
    setzt Device.heating_zone_id auf NULL (FK ondelete=SET NULL), Devices
    bleiben orphan. Diese explizit purge — sonst akkumulieren bei mehreren
    Test-Runs. ControlCommand cascade-deletes via Device-FK.
    """
    devices = list(
        (await session.execute(select(Device.id).where(Device.dev_eui.like(DEV_EUI_PATTERN))))
        .scalars()
        .all()
    )
    if devices:
        await session.execute(
            sa_delete(ControlCommand).where(ControlCommand.device_id.in_(devices))
        )
        await session.execute(sa_delete(SensorReading).where(SensorReading.device_id.in_(devices)))
        await session.execute(sa_delete(Device).where(Device.id.in_(devices)))
    await session.commit()


@pytest_asyncio.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    if not TEST_DB_URL:
        pytest.skip(SKIP_REASON)
    engine = create_async_engine(TEST_DB_URL)
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    async with sessionmaker() as session:
        await purge_test_data_by_prefix(session, PREFIX, dev_eui_pattern=DEV_EUI_PATTERN)
        await _purge_orphan_devices(session)
        try:
            yield session
        finally:
            await session.rollback()
            await purge_test_data_by_prefix(session, PREFIX, dev_eui_pattern=DEV_EUI_PATTERN)
            await _purge_orphan_devices(session)
    await engine.dispose()


@pytest.fixture
def pin_database_url(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """``DATABASE_URL`` auf ``TEST_DATABASE_URL`` pinnen, damit
    ``_task_session`` in ``engine_tasks._evaluate_room_async`` dieselbe DB
    sieht wie der Test-Setup. ``cache_clear`` am Ende.
    """
    if not TEST_DB_URL:
        pytest.skip(SKIP_REASON)
    monkeypatch.setenv("DATABASE_URL", TEST_DB_URL)
    get_settings.cache_clear()
    try:
        yield None
    finally:
        get_settings.cache_clear()


@pytest.fixture
def mock_send_setpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> list[tuple[str, int]]:
    """Mockt ``send_setpoint`` in ``engine_tasks``. Sammelt Aufrufe als
    ``(dev_eui, setpoint_c)``. Reihenfolge nicht deterministisch wegen
    asyncio.gather. Default-Mock returnt einen fake topic-String, wirft
    keine Exception.
    """
    recorded: list[tuple[str, int]] = []

    async def _mock(dev_eui: str, setpoint_c: int) -> str:
        recorded.append((dev_eui, setpoint_c))
        return f"application/x/device/{dev_eui}/command/down"

    monkeypatch.setattr("heizung.tasks.engine_tasks.send_setpoint", _mock)
    return recorded


# ---------------------------------------------------------------------------
# Setup-Helper
# ---------------------------------------------------------------------------


async def _make_room(
    session: AsyncSession,
    *,
    suffix: str,
    status: RoomStatus,
    default_t_vacant: Decimal = Decimal("18.0"),
    default_t_occupied: Decimal = Decimal("21.0"),
) -> tuple[int, int]:
    rt = RoomType(
        name=f"{PREFIX}-rt-{suffix}",
        default_t_occupied=default_t_occupied,
        default_t_vacant=default_t_vacant,
    )
    session.add(rt)
    await session.flush()
    room = Room(number=f"{PREFIX}-{suffix}", room_type_id=rt.id, status=status)
    session.add(room)
    await session.flush()
    return room.id, rt.id


async def _make_zone(
    session: AsyncSession,
    *,
    room_id: int,
    kind: HeatingZoneKind,
    name: str,
) -> int:
    zone = HeatingZone(room_id=room_id, kind=kind, name=name)
    session.add(zone)
    await session.flush()
    return zone.id


async def _make_device(
    session: AsyncSession,
    *,
    zone_id: int,
    health_state: str = "healthy",
    is_active: bool = True,
) -> tuple[int, str]:
    dev_eui = f"deadbeef{uuid.uuid4().hex[:8]}"
    device = Device(
        dev_eui=dev_eui,
        kind=DeviceKind.THERMOSTAT,
        vendor=DeviceVendor.MCLIMATE,
        model="vicki",
        heating_zone_id=zone_id,
        is_active=is_active,
        health_state=health_state,
    )
    session.add(device)
    await session.flush()
    return device.id, dev_eui


async def _add_reading(
    session: AsyncSession,
    *,
    device_id: int,
    open_window: bool,
    age_min: int = 2,
    fcnt: int = 1,
    temperature: Decimal = Decimal("21.0"),
) -> None:
    reading = SensorReading(
        time=datetime.now(tz=UTC) - timedelta(minutes=age_min),
        device_id=device_id,
        fcnt=fcnt,
        temperature=temperature,
        open_window=open_window,
    )
    session.add(reading)
    await session.flush()


async def _get_clamp_eventlog_latest(session: AsyncSession, room_id: int) -> EventLog:
    """Liefert die juengste HARD_CLAMP-EventLog-Row. Enthaelt
    downlink_per_device + downlink_zone_status (T2-Sub-Trace).
    """
    stmt = (
        select(EventLog)
        .where(EventLog.room_id == room_id)
        .where(EventLog.layer == EventLogLayer.HARD_CLAMP)
        .order_by(EventLog.time.desc())
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one()


async def _get_window_safety_eventlog_latest(session: AsyncSession, room_id: int) -> EventLog:
    """Liefert die juengste WINDOW_SAFETY-EventLog-Row."""
    stmt = (
        select(EventLog)
        .where(EventLog.room_id == room_id)
        .where(EventLog.layer == EventLogLayer.WINDOW_SAFETY)
        .order_by(EventLog.time.desc())
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one()


# ---------------------------------------------------------------------------
# Szenario A — 2-Zonen-Room, Fenster zu, OCCUPIED, kein Override
# ---------------------------------------------------------------------------


async def test_e2e_a_two_zones_occupied_closed_no_override(
    db_session: AsyncSession,
    mock_send_setpoint: list[tuple[str, int]],
    pin_database_url: None,
) -> None:
    suffix = uuid.uuid4().hex[:8]
    room_id, _rt_id = await _make_room(db_session, suffix=suffix, status=RoomStatus.OCCUPIED)
    zone_bed = await _make_zone(
        db_session, room_id=room_id, kind=HeatingZoneKind.BEDROOM, name="bedroom"
    )
    zone_bath = await _make_zone(
        db_session, room_id=room_id, kind=HeatingZoneKind.BATHROOM, name="bath"
    )
    dev_bed_id, dev_bed_eui = await _make_device(db_session, zone_id=zone_bed)
    dev_bath_id, dev_bath_eui = await _make_device(db_session, zone_id=zone_bath)
    await _add_reading(db_session, device_id=dev_bed_id, open_window=False)
    await _add_reading(db_session, device_id=dev_bath_id, open_window=False, fcnt=2)
    await db_session.commit()

    result = await engine_tasks._evaluate_room_async(room_id)

    # Room-Decision: OCCUPIED -> default_t_occupied=21
    assert result["setpoint_c"] == 21
    assert len(mock_send_setpoint) == 2
    assert {call[0] for call in mock_send_setpoint} == {dev_bed_eui, dev_bath_eui}
    assert all(call[1] == 21 for call in mock_send_setpoint)

    # CLAMP-EventLog mit Sub-Trace
    clamp = await _get_clamp_eventlog_latest(db_session, room_id)
    assert clamp.details is not None
    per_dev = clamp.details["downlink_per_device"]
    per_zone = clamp.details["downlink_zone_status"]
    assert len(per_dev) == 2
    assert all(e["status"] == "sent" for e in per_dev)
    assert {e["zone_id"] for e in per_dev} == {zone_bed, zone_bath}
    assert len(per_zone) == 2
    assert all(z["count_sent"] == 1 and z["count_failed"] == 0 for z in per_zone)

    # ControlCommand-Rows persistent
    ccs = list(
        (
            await db_session.execute(
                select(ControlCommand).where(
                    ControlCommand.device_id.in_([dev_bed_id, dev_bath_id])
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(ccs) == 2
    assert all(cc.sent_to_gateway_at is not None for cc in ccs)
    assert all(cc.target_setpoint == Decimal("21") for cc in ccs)


# ---------------------------------------------------------------------------
# Szenario B — 2-Zonen-Room, Fenster in Zone offen, VACANT
# ---------------------------------------------------------------------------


async def test_e2e_b_window_open_vacant_frost(
    db_session: AsyncSession,
    mock_send_setpoint: list[tuple[str, int]],
    pin_database_url: None,
) -> None:
    suffix = uuid.uuid4().hex[:8]
    room_id, _rt_id = await _make_room(db_session, suffix=suffix, status=RoomStatus.VACANT)
    zone_bed = await _make_zone(
        db_session, room_id=room_id, kind=HeatingZoneKind.BEDROOM, name="bedroom"
    )
    zone_bath = await _make_zone(
        db_session, room_id=room_id, kind=HeatingZoneKind.BATHROOM, name="bath"
    )
    dev_bed_id, _dev_bed_eui = await _make_device(db_session, zone_id=zone_bed)
    dev_bath_id, _dev_bath_eui = await _make_device(db_session, zone_id=zone_bath)
    # Zone 1 Fenster offen, Zone 2 zu
    await _add_reading(db_session, device_id=dev_bed_id, open_window=True)
    await _add_reading(db_session, device_id=dev_bath_id, open_window=False, fcnt=2)
    await db_session.commit()

    result = await engine_tasks._evaluate_room_async(room_id)

    # Layer 4 zieht VACANT+open -> Frostschutz=10
    assert result["setpoint_c"] == 10
    assert len(mock_send_setpoint) == 2
    assert all(call[1] == 10 for call in mock_send_setpoint)

    window_row = await _get_window_safety_eventlog_latest(db_session, room_id)
    assert window_row.reason == CommandReason.WINDOW_OPEN
    assert window_row.details is not None
    assert window_row.details["setpoint_source"] == "frost_protection"
    assert window_row.details["occupancy_state"] == "vacant"
    assert window_row.details["override_overridden_by_window_open"] is False
    assert window_row.details["detail"] is not None
    assert window_row.details["detail"].startswith("window_open_room_free_frost_protection ")


# ---------------------------------------------------------------------------
# Szenario C — 2-Zonen-Room, Fenster offen, OCCUPIED -> default_t_vacant
# ---------------------------------------------------------------------------


async def test_e2e_c_window_open_occupied_setback(
    db_session: AsyncSession,
    mock_send_setpoint: list[tuple[str, int]],
    pin_database_url: None,
) -> None:
    suffix = uuid.uuid4().hex[:8]
    room_id, _rt_id = await _make_room(
        db_session,
        suffix=suffix,
        status=RoomStatus.OCCUPIED,
        default_t_vacant=Decimal("18.0"),
    )
    zone_bed = await _make_zone(
        db_session, room_id=room_id, kind=HeatingZoneKind.BEDROOM, name="bedroom"
    )
    zone_bath = await _make_zone(
        db_session, room_id=room_id, kind=HeatingZoneKind.BATHROOM, name="bath"
    )
    dev_bed_id, _ = await _make_device(db_session, zone_id=zone_bed)
    dev_bath_id, _ = await _make_device(db_session, zone_id=zone_bath)
    await _add_reading(db_session, device_id=dev_bed_id, open_window=True)
    await _add_reading(db_session, device_id=dev_bath_id, open_window=False, fcnt=2)
    await db_session.commit()

    result = await engine_tasks._evaluate_room_async(room_id)

    # Layer 4 zieht OCCUPIED+open -> default_t_vacant=18
    assert result["setpoint_c"] == 18
    assert len(mock_send_setpoint) == 2
    assert all(call[1] == 18 for call in mock_send_setpoint)

    window_row = await _get_window_safety_eventlog_latest(db_session, room_id)
    assert window_row.details is not None
    assert window_row.details["setpoint_source"] == "default_t_vacant"
    assert window_row.details["occupancy_state"] == "occupied"
    assert window_row.details["detail"] is not None
    assert window_row.details["detail"].startswith("window_open_room_occupied_setback ")


# ---------------------------------------------------------------------------
# Szenario D — 1-Zone-3-Vicki, 1 silent, Fenster zu, OCCUPIED
# ---------------------------------------------------------------------------


async def test_e2e_d_one_silent_vicki_skipped(
    db_session: AsyncSession,
    mock_send_setpoint: list[tuple[str, int]],
    pin_database_url: None,
) -> None:
    suffix = uuid.uuid4().hex[:8]
    room_id, _rt_id = await _make_room(db_session, suffix=suffix, status=RoomStatus.OCCUPIED)
    zone_id = await _make_zone(
        db_session, room_id=room_id, kind=HeatingZoneKind.BEDROOM, name="bedroom"
    )
    dev1_id, dev1_eui = await _make_device(db_session, zone_id=zone_id, health_state="healthy")
    dev2_id, dev2_eui = await _make_device(db_session, zone_id=zone_id, health_state="healthy")
    dev3_id, dev3_eui = await _make_device(db_session, zone_id=zone_id, health_state="silent")
    # Fenster zu fuer alle (silent zaehlt nicht in Layer-4-Aggregat)
    await _add_reading(db_session, device_id=dev1_id, open_window=False, fcnt=1)
    await _add_reading(db_session, device_id=dev2_id, open_window=False, fcnt=2)
    await _add_reading(db_session, device_id=dev3_id, open_window=False, fcnt=3)
    await db_session.commit()

    result = await engine_tasks._evaluate_room_async(room_id)

    # OCCUPIED -> 21 degC, Fenster zu, kein Override
    assert result["setpoint_c"] == 21
    # Nur 2 Downlinks (silent ausgefiltert):
    assert len(mock_send_setpoint) == 2
    sent_euis = {call[0] for call in mock_send_setpoint}
    assert sent_euis == {dev1_eui, dev2_eui}
    assert dev3_eui not in sent_euis

    clamp = await _get_clamp_eventlog_latest(db_session, room_id)
    assert clamp.details is not None
    per_zone = clamp.details["downlink_zone_status"]
    assert len(per_zone) == 1
    assert per_zone[0]["count_sent"] == 2
    assert per_zone[0]["count_failed"] == 0
    assert per_zone[0]["count_skipped"] == 0  # silent waren in _get_zone_devices ausgefiltert
    assert per_zone[0]["all_failed"] is False


# ---------------------------------------------------------------------------
# Szenario E — Aktiver Override + Fenster geht auf zwischen Tick 1 und Tick 2
# ---------------------------------------------------------------------------


async def test_e2e_e_override_masked_by_window_between_ticks(
    db_session: AsyncSession,
    mock_send_setpoint: list[tuple[str, int]],
    pin_database_url: None,
) -> None:
    suffix = uuid.uuid4().hex[:8]
    room_id, _rt_id = await _make_room(
        db_session,
        suffix=suffix,
        status=RoomStatus.OCCUPIED,
        default_t_vacant=Decimal("18.0"),
    )
    zone_id = await _make_zone(
        db_session, room_id=room_id, kind=HeatingZoneKind.BEDROOM, name="bedroom"
    )
    dev_id, _dev_eui = await _make_device(db_session, zone_id=zone_id)

    # Aktiver Override mit Setpoint 22 (Gast hat hochgedreht)
    override = ManualOverride(
        room_id=room_id,
        setpoint=Decimal("22.0"),
        source=OverrideSource.DEVICE,
        expires_at=datetime.now(tz=UTC) + timedelta(hours=4),
    )
    db_session.add(override)
    await db_session.flush()

    # Reading 1: Fenster zu
    await _add_reading(db_session, device_id=dev_id, open_window=False, fcnt=1, age_min=3)
    await db_session.commit()

    # Tick 1: Override aktiv, Fenster zu -> Setpoint 22
    result1 = await engine_tasks._evaluate_room_async(room_id)
    assert result1["setpoint_c"] == 22
    assert len(mock_send_setpoint) == 1
    assert mock_send_setpoint[0][1] == 22

    # Reading 2: Fenster geht auf (juenger als Reading 1 -> DISTINCT-ON
    # waehlt dieses)
    await _add_reading(db_session, device_id=dev_id, open_window=True, fcnt=2, age_min=1)
    await db_session.commit()

    # Tick 2: Override noch da, Fenster offen, OCCUPIED -> Setpoint 18
    # (Layer 4 ueberschreibt)
    mock_send_setpoint.clear()
    result2 = await engine_tasks._evaluate_room_async(room_id)
    assert result2["setpoint_c"] == 18
    assert len(mock_send_setpoint) == 1
    assert mock_send_setpoint[0][1] == 18

    # Override-Tabellen-Eintrag bleibt
    refreshed_override = await db_session.get(ManualOverride, override.id)
    assert refreshed_override is not None
    assert refreshed_override.revoked_at is None
    assert refreshed_override.setpoint == Decimal("22.0")

    # Layer-4-Row (Tick 2) mit Override-Maskierungs-Markern (T3-Konvention:
    # BEIDE — extras-Key UND detail-Prefix)
    window_row = await _get_window_safety_eventlog_latest(db_session, room_id)
    assert window_row.reason == CommandReason.WINDOW_OPEN
    assert window_row.details is not None
    assert window_row.details["override_overridden_by_window_open"] is True
    assert window_row.details["setpoint_source"] == "default_t_vacant"
    assert window_row.details["detail"] is not None
    assert window_row.details["detail"].startswith(
        "override_overridden_by_window_open window_open_room_occupied_setback "
    )


# ---------------------------------------------------------------------------
# HTTP-Fixtures fuer Szenarien F + G
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def setup_engine() -> AsyncIterator[AsyncEngine]:
    """Async-Engine fuer Setup + dependency_override. Pro Test ein eigener
    Pool, alle Connections im aktuellen pytest-asyncio-Loop (Pattern aus
    test_api_overrides.py).
    """
    if not TEST_DB_URL:
        pytest.skip(SKIP_REASON)
    engine = create_async_engine(TEST_DB_URL)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def http_client(setup_engine: AsyncEngine) -> AsyncIterator[httpx.AsyncClient]:
    """AsyncClient mit dependency_override fuer get_session. Setup + App
    teilen sich denselben Engine-Pool im selben Loop.
    """
    sessionmaker = async_sessionmaker(setup_engine, expire_on_commit=False)

    async def _override_get_session() -> AsyncIterator[AsyncSession]:
        async with sessionmaker() as session:
            yield session

    app.dependency_overrides[get_session] = _override_get_session
    try:
        transport = ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            yield client
    finally:
        app.dependency_overrides.clear()


async def _seed_room_zone_device_reading(
    setup_engine: AsyncEngine,
    *,
    suffix: str,
    open_window: bool,
    device_health_state: str = "healthy",
) -> tuple[int, int]:
    """Setup-Helper fuer F/G: Room + aktive Belegung + 1 Zone + 1 Device + Reading.

    Sprint 12a T2 (AE-58): F/G testen POST-Override-Pfade. Override-Service
    verlangt OCCUPIED — daher aktive Occupancy ab now-2h bis now+2d. Eigene
    Session via setup_engine, commit am Ende.
    """
    from heizung.models.occupancy import Occupancy

    sessionmaker = async_sessionmaker(setup_engine, expire_on_commit=False)
    async with sessionmaker() as session:
        rt = RoomType(name=f"{PREFIX}-rt-{suffix}")
        session.add(rt)
        await session.flush()
        room = Room(number=f"{PREFIX}-{suffix}", room_type_id=rt.id)
        session.add(room)
        await session.flush()
        now = datetime.now(tz=UTC)
        occ = Occupancy(
            room_id=room.id,
            check_in=now - timedelta(hours=2),
            check_out=now + timedelta(days=2),
            is_active=True,
        )
        session.add(occ)
        await session.flush()
        zone = HeatingZone(room_id=room.id, kind=HeatingZoneKind.BEDROOM, name="bedroom")
        session.add(zone)
        await session.flush()
        device = Device(
            dev_eui=f"deadbeef{suffix[:8]}",
            kind=DeviceKind.THERMOSTAT,
            vendor=DeviceVendor.MCLIMATE,
            model="vicki",
            heating_zone_id=zone.id,
            health_state=device_health_state,
        )
        session.add(device)
        await session.flush()
        reading = SensorReading(
            time=datetime.now(tz=UTC) - timedelta(minutes=2),
            device_id=device.id,
            fcnt=1,
            temperature=Decimal("21.0"),
            open_window=open_window,
        )
        session.add(reading)
        await session.commit()
        return room.id, zone.id


async def _cleanup_room_after_http(setup_engine: AsyncEngine) -> None:
    sessionmaker = async_sessionmaker(setup_engine, expire_on_commit=False)
    async with sessionmaker() as session:
        await purge_test_data_by_prefix(session, PREFIX, dev_eui_pattern=DEV_EUI_PATTERN)
        await _purge_orphan_devices(session)


# ---------------------------------------------------------------------------
# Szenario F — POST /override + Fenster offen -> 409
# ---------------------------------------------------------------------------


async def test_e2e_f_post_override_window_open_returns_409(
    http_client: httpx.AsyncClient,
    setup_engine: AsyncEngine,
) -> None:
    suffix = uuid.uuid4().hex[:8]
    try:
        room_id, zone_id = await _seed_room_zone_device_reading(
            setup_engine, suffix=suffix, open_window=True
        )

        resp = await http_client.post(
            f"/api/v1/rooms/{room_id}/overrides",
            json={"setpoint": "22", "source": "frontend_4h"},
        )
        assert resp.status_code == 409, resp.text
        body = resp.json()
        assert body["detail"]["error"] == "override_rejected_window_open"
        zones = body["detail"]["zones"]
        assert isinstance(zones, list)
        assert len(zones) == 1
        assert zones[0]["zone_id"] == zone_id
        assert "reading_at" in zones[0]

        # ManualOverride-Tabelle leer fuer diesen Raum
        sessionmaker = async_sessionmaker(setup_engine, expire_on_commit=False)
        async with sessionmaker() as session:
            result = await session.execute(
                text("SELECT COUNT(*) FROM manual_override WHERE room_id = :r"),
                {"r": room_id},
            )
            count = result.scalar_one()
        assert count == 0
    finally:
        await _cleanup_room_after_http(setup_engine)


# ---------------------------------------------------------------------------
# Szenario G — Alle Vickis silent + open_window-Reading -> 201
# ---------------------------------------------------------------------------


async def test_e2e_g_post_override_all_silent_window_open_returns_201(
    http_client: httpx.AsyncClient,
    setup_engine: AsyncEngine,
) -> None:
    """Symmetrie zu Layer 4: ``detect_open_window_zones`` filtert auf
    ``health_state='healthy'``. Wenn alle Devices der Zone silent sind,
    liefert der Helper leere Liste -> Override-Service rejected NICHT,
    Override wird angelegt. Begruendung in T4 Drift D14.
    """
    suffix = uuid.uuid4().hex[:8]
    try:
        room_id, _zone_id = await _seed_room_zone_device_reading(
            setup_engine, suffix=suffix, open_window=True, device_health_state="silent"
        )

        resp = await http_client.post(
            f"/api/v1/rooms/{room_id}/overrides",
            json={"setpoint": "22", "source": "frontend_4h"},
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["room_id"] == room_id
        assert Decimal(body["setpoint"]) == Decimal("22")
    finally:
        await _cleanup_room_after_http(setup_engine)
