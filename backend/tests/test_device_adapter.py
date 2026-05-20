"""Sprint 9.9 T5 - Vicki-Device-Adapter Tests.

DB-Tests: skip ohne ``DATABASE_URL`` (CI-Pattern, vgl. T4). Setup-Daten
ueber eine separate async engine, damit Pool-/Loop-Konflikte mit der
App-eigenen Engine ausgeschlossen sind.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
import pytest_asyncio
from alembic.config import Config
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from alembic import command
from heizung.models.control_command import ControlCommand
from heizung.models.device import Device
from heizung.models.enums import (
    CommandReason,
    DeviceKind,
    DeviceVendor,
    HeatingZoneKind,
    OverrideSource,
)
from heizung.models.heating_zone import HeatingZone
from heizung.models.occupancy import Occupancy
from heizung.models.room import Room
from heizung.models.room_type import RoomType
from heizung.services import device_adapter

DATABASE_URL = os.environ.get("DATABASE_URL")
DATABASE_URL_PRESENT = bool(DATABASE_URL)
SKIP_REASON = "DATABASE_URL nicht gesetzt - DB-Tests brauchen Test-DB"


@pytest_asyncio.fixture(scope="module", autouse=True)
async def _migrate_db() -> None:
    if not DATABASE_URL_PRESENT:
        return
    backend_root = Path(__file__).resolve().parents[1]
    cfg = Config(str(backend_root / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend_root / "alembic"))
    cfg.set_main_option("sqlalchemy.url", DATABASE_URL or "")
    await asyncio.to_thread(command.upgrade, cfg, "head")


@pytest_asyncio.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    if not DATABASE_URL_PRESENT:
        pytest.skip(SKIP_REASON)
    eng = create_async_engine(DATABASE_URL or "")
    try:
        yield eng
    finally:
        await eng.dispose()


@pytest_asyncio.fixture
async def session(engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    async with sessionmaker() as s:
        try:
            yield s
        finally:
            await s.rollback()


def _unique_eui() -> str:
    """16-char hex aus UUID, eindeutig pro Test."""
    return uuid.uuid4().hex[:16]


def _unique_short() -> str:
    """8-char hex (fuer room.number / room_type.name unter VARCHAR(20))."""
    return uuid.uuid4().hex[:8]


async def _create_device(s: AsyncSession, *, heating_zone_id: int | None = None) -> Device:
    device = Device(
        dev_eui=_unique_eui(),
        kind=DeviceKind.THERMOSTAT,
        vendor=DeviceVendor.MCLIMATE,
        model="Vicki",
        heating_zone_id=heating_zone_id,
    )
    s.add(device)
    await s.flush()
    return device


async def _create_control_command(
    s: AsyncSession,
    *,
    device_id: int,
    setpoint: Decimal,
    sent_at: datetime,
) -> ControlCommand:
    cc = ControlCommand(
        device_id=device_id,
        target_setpoint=setpoint,
        reason=CommandReason.OCCUPIED_SETPOINT,
        sent_to_gateway_at=sent_at,
    )
    s.add(cc)
    await s.flush()
    return cc


# ---------------------------------------------------------------------------
# detect_user_override
# ---------------------------------------------------------------------------


async def test_no_previous_control_command_returns_none(session: AsyncSession) -> None:
    device = await _create_device(session)
    result = await device_adapter.detect_user_override(
        session,
        device_id=device.id,
        uplink_target_temp=Decimal("23.0"),
        fport=1,
        received_at=datetime.now(tz=UTC),
    )
    assert result is None


async def test_within_ack_window_returns_none(session: AsyncSession) -> None:
    """ControlCommand vor 30s + gleicher Setpoint -> erwarteter Reply -> None."""
    device = await _create_device(session)
    now = datetime.now(tz=UTC)
    await _create_control_command(
        session, device_id=device.id, setpoint=Decimal("21.0"), sent_at=now - timedelta(seconds=30)
    )
    result = await device_adapter.detect_user_override(
        session,
        device_id=device.id,
        uplink_target_temp=Decimal("21.0"),
        fport=1,
        received_at=now,
    )
    assert result is None


async def test_ack_window_expired_same_setpoint_returns_none(session: AsyncSession) -> None:
    """ControlCommand vor 90s + gleicher Setpoint -> Diff=0 -> None."""
    device = await _create_device(session)
    now = datetime.now(tz=UTC)
    await _create_control_command(
        session, device_id=device.id, setpoint=Decimal("21.0"), sent_at=now - timedelta(seconds=90)
    )
    result = await device_adapter.detect_user_override(
        session,
        device_id=device.id,
        uplink_target_temp=Decimal("21.0"),
        fport=1,
        received_at=now,
    )
    assert result is None


async def test_fport1_within_tolerance_returns_none(session: AsyncSession) -> None:
    """Engine 21.5, Uplink 21.0 (uint8-Rundung), fport=1 -> Diff=0.5<=0.6 -> None."""
    device = await _create_device(session)
    now = datetime.now(tz=UTC)
    await _create_control_command(
        session, device_id=device.id, setpoint=Decimal("21.5"), sent_at=now - timedelta(seconds=120)
    )
    result = await device_adapter.detect_user_override(
        session,
        device_id=device.id,
        uplink_target_temp=Decimal("21.0"),
        fport=1,
        received_at=now,
    )
    assert result is None


async def test_fport1_outside_tolerance_returns_uplink(session: AsyncSession) -> None:
    """Engine 21.0, Uplink 23.0, fport=1 -> Diff=2.0>0.6 -> 23.0."""
    device = await _create_device(session)
    now = datetime.now(tz=UTC)
    await _create_control_command(
        session, device_id=device.id, setpoint=Decimal("21.0"), sent_at=now - timedelta(seconds=120)
    )
    result = await device_adapter.detect_user_override(
        session,
        device_id=device.id,
        uplink_target_temp=Decimal("23.0"),
        fport=1,
        received_at=now,
    )
    assert result == Decimal("23.0")


async def test_fport2_within_tolerance_returns_none(session: AsyncSession) -> None:
    """Engine 21.5, Uplink 21.5, fport=2 -> Diff=0<=0.1 -> None."""
    device = await _create_device(session)
    now = datetime.now(tz=UTC)
    await _create_control_command(
        session, device_id=device.id, setpoint=Decimal("21.5"), sent_at=now - timedelta(seconds=120)
    )
    result = await device_adapter.detect_user_override(
        session,
        device_id=device.id,
        uplink_target_temp=Decimal("21.5"),
        fport=2,
        received_at=now,
    )
    assert result is None


async def test_fport2_outside_tolerance_returns_uplink(session: AsyncSession) -> None:
    """Engine 21.0, Uplink 21.5, fport=2 -> Diff=0.5>0.1 -> 21.5."""
    device = await _create_device(session)
    now = datetime.now(tz=UTC)
    await _create_control_command(
        session, device_id=device.id, setpoint=Decimal("21.0"), sent_at=now - timedelta(seconds=120)
    )
    result = await device_adapter.detect_user_override(
        session,
        device_id=device.id,
        uplink_target_temp=Decimal("21.5"),
        fport=2,
        received_at=now,
    )
    assert result == Decimal("21.5")


# ---------------------------------------------------------------------------
# handle_uplink_for_override (End-to-End)
# ---------------------------------------------------------------------------


async def test_handle_uplink_creates_device_override(session: AsyncSession) -> None:
    """Voller Stack: Room + HeatingZone + Device + Occupancy. Drehknopf-Diff
    erkennen -> ManualOverride mit ``source=device`` und ``next_checkout_at``
    aus aktiver Belegung als ``expires_at``."""
    short = _unique_short()
    rt = RoomType(name=f"t99-{short}")
    session.add(rt)
    await session.flush()
    room = Room(number=f"t99-{short}", room_type_id=rt.id)
    session.add(room)
    await session.flush()
    hz = HeatingZone(room_id=room.id, kind=HeatingZoneKind.BEDROOM, name="zone-1")
    session.add(hz)
    await session.flush()

    device = await _create_device(session, heating_zone_id=hz.id)

    now = datetime.now(tz=UTC)
    await _create_control_command(
        session, device_id=device.id, setpoint=Decimal("21.0"), sent_at=now - timedelta(seconds=120)
    )

    next_checkout = now + timedelta(days=2)
    session.add(
        Occupancy(
            room_id=room.id,
            check_in=now - timedelta(hours=1),
            check_out=next_checkout,
        )
    )
    await session.flush()

    override = await device_adapter.handle_uplink_for_override(
        session,
        device_id=device.id,
        uplink_target_temp=Decimal("23.0"),
        fport=1,
        received_at=now,
    )

    assert override is not None
    assert override.room_id == room.id
    assert override.source == OverrideSource.DEVICE
    assert override.setpoint == Decimal("23.0")
    # expires_at sollte vom Belegungs-checkout kommen (gerade 2 Tage in der Zukunft,
    # also unter dem 7-Tage-Hard-Cap).
    assert abs((override.expires_at - next_checkout).total_seconds()) < 1
    assert override.reason == "auto: detected user setpoint change"


# ---------------------------------------------------------------------------
# Sprint 12a T4 (AE-58) — Pre-Insert-Gates im Auto-Detect-Pfad
# ---------------------------------------------------------------------------


async def _seed_occupied_stack(
    session: AsyncSession,
    *,
    open_window_reading: bool = False,
) -> tuple[int, int, int, datetime]:
    """Setup-Helper: Room + RoomType + Occupancy + HeatingZone + Device +
    ControlCommand-Historie. Optional auch ein SensorReading mit
    ``open_window``. Returns (room_id, zone_id, device_id, now).
    """
    from heizung.models.sensor_reading import SensorReading

    short = _unique_short()
    rt = RoomType(name=f"t12a-{short}")
    session.add(rt)
    await session.flush()
    room = Room(number=f"t12a-{short}", room_type_id=rt.id)
    session.add(room)
    await session.flush()
    now = datetime.now(tz=UTC)
    session.add(
        Occupancy(
            room_id=room.id,
            check_in=now - timedelta(hours=1),
            check_out=now + timedelta(days=2),
            is_active=True,
        )
    )
    await session.flush()
    hz = HeatingZone(room_id=room.id, kind=HeatingZoneKind.BEDROOM, name="zone-1")
    session.add(hz)
    await session.flush()
    device = await _create_device(session, heating_zone_id=hz.id)
    # Engine-Intent: ControlCommand 21.0 vor 120 s -> Ack-Window aus,
    # nachfolgender Uplink mit deutlich anderem Setpoint = Drehring.
    await _create_control_command(
        session,
        device_id=device.id,
        setpoint=Decimal("21.0"),
        sent_at=now - timedelta(seconds=120),
    )
    if open_window_reading:
        session.add(
            SensorReading(
                time=now - timedelta(minutes=2),
                device_id=device.id,
                fcnt=1,
                temperature=Decimal("21.0"),
                open_window=True,
            )
        )
        await session.flush()
    return room.id, hz.id, device.id, now


async def test_drehring_in_occupied_with_zone_creates_override_with_zone_id(
    session: AsyncSession,
) -> None:
    """T4 (a-d): OCCUPIED + Fenster zu + Zone-Mapping -> Override mit
    heating_zone_id gesetzt."""
    _room_id, zone_id, device_id, now = await _seed_occupied_stack(session)

    override = await device_adapter.handle_uplink_for_override(
        session,
        device_id=device_id,
        uplink_target_temp=Decimal("24.0"),
        fport=1,
        received_at=now,
    )
    assert override is not None
    assert override.heating_zone_id == zone_id
    assert override.source == OverrideSource.DEVICE
    assert override.setpoint == Decimal("24.0")


async def test_drehring_in_vacant_silent_skip(session: AsyncSession) -> None:
    """T4 (a): VACANT-Raum -> kein Override, event_log MANUAL_OVERRIDE_BLOCKED
    mit reason=DEVICE_BLOCKED_VACANT.
    """
    from sqlalchemy import select as sa_select

    from heizung.models.enums import EventLogLayer
    from heizung.models.event_log import EventLog

    short = _unique_short()
    rt = RoomType(name=f"t12av-{short}")
    session.add(rt)
    await session.flush()
    room = Room(number=f"t12av-{short}", room_type_id=rt.id)
    session.add(room)
    await session.flush()
    # KEINE Occupancy -> derive_room_status returnt VACANT.
    hz = HeatingZone(room_id=room.id, kind=HeatingZoneKind.BEDROOM, name="zone-1")
    session.add(hz)
    await session.flush()
    device = await _create_device(session, heating_zone_id=hz.id)
    now = datetime.now(tz=UTC)
    await _create_control_command(
        session,
        device_id=device.id,
        setpoint=Decimal("21.0"),
        sent_at=now - timedelta(seconds=120),
    )

    result = await device_adapter.handle_uplink_for_override(
        session,
        device_id=device.id,
        uplink_target_temp=Decimal("24.0"),
        fport=1,
        received_at=now,
    )
    assert result is None

    # event_log-Eintrag verifizieren
    rows = list(
        (
            await session.execute(
                sa_select(EventLog).where(
                    EventLog.room_id == room.id,
                    EventLog.layer == EventLogLayer.MANUAL_OVERRIDE_BLOCKED,
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].reason == CommandReason.DEVICE_BLOCKED_VACANT
    assert rows[0].device_id == device.id
    assert rows[0].details is not None
    assert rows[0].details["uplink_setpoint"] == "24.0"


async def test_drehring_window_open_silent_skip(session: AsyncSession) -> None:
    """T4 (b): OCCUPIED + Fenster offen -> kein Override, event_log mit
    reason=DEVICE_BLOCKED_WINDOW.

    Wichtig: Device.health_state defaultet auf 'silent', detect_open_window_zones
    filtert aber auf 'healthy'. Fixture hebt den State explizit auf 'healthy',
    sonst sieht der Helper das Fenster nicht.
    """
    from sqlalchemy import select as sa_select

    from heizung.models.enums import EventLogLayer
    from heizung.models.event_log import EventLog

    room_id, _zone_id, device_id, now = await _seed_occupied_stack(
        session, open_window_reading=True
    )
    # Device auf healthy heben, sonst filtert detect_open_window_zones aus.
    device = await session.get(Device, device_id)
    assert device is not None
    device.health_state = "healthy"
    await session.flush()

    result = await device_adapter.handle_uplink_for_override(
        session,
        device_id=device_id,
        uplink_target_temp=Decimal("24.0"),
        fport=1,
        received_at=now,
    )
    assert result is None

    rows = list(
        (
            await session.execute(
                sa_select(EventLog).where(
                    EventLog.room_id == room_id,
                    EventLog.layer == EventLogLayer.MANUAL_OVERRIDE_BLOCKED,
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].reason == CommandReason.DEVICE_BLOCKED_WINDOW
    assert rows[0].device_id == device_id


async def test_drehring_device_without_zone_fallback(
    session: AsyncSession,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T4 (c): Vicki ohne heating_zone_id-Mapping -> Override mit
    heating_zone_id=NULL + Warning.

    Im aktuellen Schema sind ``_device_room_id`` und ``_device_zone_id``
    semantisch identisch (beide via ``Device.heating_zone_id`` -> ohne
    Zone auch kein Raum). Zum Test des Fallback-Branches monkeypatchen
    wir ``_device_zone_id`` so, dass es ``None`` zurueckliefert,
    waehrend der reale Raum-Lookup ueber ``_device_room_id`` weiter
    funktioniert. Branch ist Forward-Compat fuer kuenftige Schema-
    Erweiterung (z.B. direkter ``device.room_id``).
    """
    import logging as _logging

    _room_id, _zone_id, device_id, now = await _seed_occupied_stack(session)

    async def _zone_id_none(_session: AsyncSession, _device_id: int) -> int | None:
        return None

    monkeypatch.setattr(device_adapter, "_device_zone_id", _zone_id_none)

    caplog.set_level(_logging.WARNING, logger="heizung.services.device_adapter")
    override = await device_adapter.handle_uplink_for_override(
        session,
        device_id=device_id,
        uplink_target_temp=Decimal("24.0"),
        fport=1,
        received_at=now,
    )

    assert override is not None
    assert override.heating_zone_id is None
    # Warning ist via Logger emitted (caplog kann §5.37-bedingt leer sein —
    # Asserts behavior-based statt log-based; Override-Erfolg + NULL-Zone
    # beweist den Fallback-Pfad).


# ---------------------------------------------------------------------------
# Sprint 12c (AE-58) — Pre-A-Block-Gate vor OCCUPIED + Window
# ---------------------------------------------------------------------------


async def test_handle_uplink_room_blocked_writes_event_log_and_returns_none(
    session: AsyncSession,
) -> None:
    """Sprint 12c: guest_override_blocked=True -> kein Override, event_log
    MANUAL_OVERRIDE_BLOCKED mit reason=DEVICE_BLOCKED_ROOM_BLOCKED."""
    from sqlalchemy import select as sa_select

    from heizung.models.enums import EventLogLayer
    from heizung.models.event_log import EventLog

    room_id, _zone_id, device_id, now = await _seed_occupied_stack(session)
    room = await session.get(Room, room_id)
    assert room is not None
    room.guest_override_blocked = True
    await session.flush()

    result = await device_adapter.handle_uplink_for_override(
        session,
        device_id=device_id,
        uplink_target_temp=Decimal("24.0"),
        fport=1,
        received_at=now,
    )
    assert result is None

    rows = list(
        (
            await session.execute(
                sa_select(EventLog).where(
                    EventLog.room_id == room_id,
                    EventLog.layer == EventLogLayer.MANUAL_OVERRIDE_BLOCKED,
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].reason == CommandReason.DEVICE_BLOCKED_ROOM_BLOCKED
    assert rows[0].device_id == device_id
    assert rows[0].details is not None
    assert rows[0].details["uplink_setpoint"] == "24.0"


async def test_handle_uplink_block_takes_precedence_over_vacant(
    session: AsyncSession,
) -> None:
    """Sprint 12c (§5.51): blocked=True + VACANT -> Pre-A-Gate gewinnt,
    event_log-Eintrag traegt DEVICE_BLOCKED_ROOM_BLOCKED, NICHT
    DEVICE_BLOCKED_VACANT."""
    from sqlalchemy import select as sa_select

    from heizung.models.enums import EventLogLayer
    from heizung.models.event_log import EventLog

    short = _unique_short()
    rt = RoomType(name=f"t12cv-{short}")
    session.add(rt)
    await session.flush()
    # KEINE Occupancy -> VACANT.
    room = Room(number=f"t12cv-{short}", room_type_id=rt.id, guest_override_blocked=True)
    session.add(room)
    await session.flush()
    hz = HeatingZone(room_id=room.id, kind=HeatingZoneKind.BEDROOM, name="zone-1")
    session.add(hz)
    await session.flush()
    device = await _create_device(session, heating_zone_id=hz.id)
    now = datetime.now(tz=UTC)
    await _create_control_command(
        session,
        device_id=device.id,
        setpoint=Decimal("21.0"),
        sent_at=now - timedelta(seconds=120),
    )

    result = await device_adapter.handle_uplink_for_override(
        session,
        device_id=device.id,
        uplink_target_temp=Decimal("24.0"),
        fport=1,
        received_at=now,
    )
    assert result is None

    rows = list(
        (
            await session.execute(
                sa_select(EventLog).where(
                    EventLog.room_id == room.id,
                    EventLog.layer == EventLogLayer.MANUAL_OVERRIDE_BLOCKED,
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].reason == CommandReason.DEVICE_BLOCKED_ROOM_BLOCKED


async def test_handle_uplink_block_takes_precedence_over_window(
    session: AsyncSession,
) -> None:
    """Sprint 12c (§5.51): blocked=True + Fenster offen -> Pre-A-Gate
    gewinnt, event_log traegt DEVICE_BLOCKED_ROOM_BLOCKED, NICHT
    DEVICE_BLOCKED_WINDOW."""
    from sqlalchemy import select as sa_select

    from heizung.models.enums import EventLogLayer
    from heizung.models.event_log import EventLog

    room_id, _zone_id, device_id, now = await _seed_occupied_stack(
        session, open_window_reading=True
    )
    device = await session.get(Device, device_id)
    assert device is not None
    device.health_state = "healthy"
    room = await session.get(Room, room_id)
    assert room is not None
    room.guest_override_blocked = True
    await session.flush()

    result = await device_adapter.handle_uplink_for_override(
        session,
        device_id=device_id,
        uplink_target_temp=Decimal("24.0"),
        fport=1,
        received_at=now,
    )
    assert result is None

    rows = list(
        (
            await session.execute(
                sa_select(EventLog).where(
                    EventLog.room_id == room_id,
                    EventLog.layer == EventLogLayer.MANUAL_OVERRIDE_BLOCKED,
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].reason == CommandReason.DEVICE_BLOCKED_ROOM_BLOCKED
