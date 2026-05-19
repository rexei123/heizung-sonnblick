"""Sprint 12 T2 — Multi-Vicki Schreib-Pfad Tests (STRATEGIE §4.2, AE-51 P3).

Verifiziert ``_dispatch_downlinks_per_zone`` aus ``tasks/engine_tasks.py``:

- Per-Zone-Iteration, healthy-Filter (D3-Fix: NICHT mehr nur ``is_active``)
- Per-Vicki-Hysterese ueber ``_last_command_for_device`` (D5)
- Parallele Downlink-Submission via ``asyncio.gather`` (return_exceptions=True)
- Individuelles try/except pro Vicki, kein Rollback bei Teil-Erfolg (A2)
- Engine-Trace Sub-Trace als JSONB-Aggregat in ``per_device_results`` /
  ``per_zone_status`` (D7-Pattern: EventLog-PK erlaubt KEINE eigenen Rows
  pro Vicki, Aggregat statt PK-Migration)
- ``all_failed``-Marker pro Zone wenn ``count_sent==0 UND count_failed>0``

Mocking-Strategie: ``send_setpoint`` per ``monkeypatch.setattr`` auf eine
async-Coroutine umgeleitet — keine echten MQTT-Calls. Per-Test-Fixture
sammelt die Aufrufe (``recorded_calls``) und kann pro ``dev_eui`` eine
Exception werfen.

DB-Tests skippen ohne ``TEST_DATABASE_URL``.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from heizung.models.control_command import ControlCommand
from heizung.models.device import Device
from heizung.models.enums import CommandReason, DeviceKind, DeviceVendor, HeatingZoneKind
from heizung.models.heating_zone import HeatingZone
from heizung.models.room import Room
from heizung.models.room_type import RoomType
from heizung.services.downlink_adapter import DownlinkError
from heizung.tasks.engine_tasks import _dispatch_downlinks_per_zone
from tests.conftest import purge_test_data_by_prefix

TEST_DB_URL = os.environ.get("TEST_DATABASE_URL")
SKIP_REASON = "TEST_DATABASE_URL nicht gesetzt — DB-Tests brauchen Postgres"
# schema_constraint: Room.number = VARCHAR(20). Pattern f"{PREFIX}-{marker}-{4-hex}"
# = 3 + 1 + 2-4 + 1 + 4 = max 13 chars. PREFIX 3 chars statt 5 (war "t12t2"),
# 4-hex statt 8-hex — Sprint 12 T7 Fix nach VARCHAR(20)-CI-Failure (D18/§5.49).
PREFIX = "t12"
DEV_EUI_PATTERN = "deadbeef%"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    """Test-DB-Session mit Pre- und Post-Cleanup ueber Prefix-Pattern.

    Cleanup nutzt ``purge_test_data_by_prefix`` aus Sprint 12 T0
    (konftest.py-Helper). Pattern: Test-Daten mit Prefix ``t12t2-*``
    werden vor und nach jedem Test geloescht, damit Cross-Test-Leakage
    ausgeschlossen ist (§5.39).
    """
    if not TEST_DB_URL:
        pytest.skip(SKIP_REASON)
    engine = create_async_engine(TEST_DB_URL)
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    async with sessionmaker() as session:
        await purge_test_data_by_prefix(session, PREFIX, dev_eui_pattern=DEV_EUI_PATTERN)
        try:
            yield session
        finally:
            await session.rollback()
            await purge_test_data_by_prefix(session, PREFIX, dev_eui_pattern=DEV_EUI_PATTERN)
    await engine.dispose()


SendSetpointCallback = Callable[[str, int], Awaitable[str]]


@pytest.fixture
def mock_send_setpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[list[tuple[str, int]], dict[str, BaseException]]:
    """Mockt ``send_setpoint`` in ``engine_tasks``. Returnt
    ``(recorded_calls, exceptions_by_dev_eui)``:

    - ``recorded_calls`` sammelt ``(dev_eui, setpoint_c)`` jedes Aufrufs
      (asyncio.gather-parallel — Reihenfolge nicht garantiert)
    - ``exceptions_by_dev_eui`` ist per Test mutierbar: ``dict[dev_eui] =
      Exception()`` → der Mock wirft beim Aufruf mit diesem dev_eui die
      Exception. Sonst returnt er einen fake topic-String.
    """
    recorded_calls: list[tuple[str, int]] = []
    exceptions_by_dev_eui: dict[str, BaseException] = {}

    async def _mock(dev_eui: str, setpoint_c: int) -> str:
        recorded_calls.append((dev_eui, setpoint_c))
        if dev_eui in exceptions_by_dev_eui:
            raise exceptions_by_dev_eui[dev_eui]
        return f"application/x/device/{dev_eui}/command/down"

    monkeypatch.setattr("heizung.tasks.engine_tasks.send_setpoint", _mock)
    return recorded_calls, exceptions_by_dev_eui


# ---------------------------------------------------------------------------
# Setup-Helper
# ---------------------------------------------------------------------------


async def _make_room(
    session: AsyncSession,
    *,
    marker: str,
) -> tuple[Room, RoomType]:
    """Setzt einen frischen Room + RoomType auf.

    Sprint 12 T7 (D18 / §5.49): ``Room.number`` ist ``VARCHAR(20)``.
    Pattern ``f"{PREFIX}-{marker}-{4-hex}"`` mit ``PREFIX="t12"``
    (3 chars) und ``marker`` 2-4 chars + 4-hex-Suffix = max 13 chars
    total. ``marker`` muss pro Test eindeutig sein, damit
    Test-Daten-Cleanup ueber den Prefix funktioniert.

    ``RoomType.name`` ist ``VARCHAR(100)`` — kein Längen-Risiko.
    """
    short = uuid.uuid4().hex[:4]
    rt = RoomType(name=f"{PREFIX}-rt-{marker}-{short}")
    session.add(rt)
    await session.flush()

    room = Room(
        number=f"{PREFIX}-{marker}-{short}",
        room_type_id=rt.id,
    )
    session.add(room)
    await session.flush()
    return room, rt


async def _make_zone_with_devices(
    session: AsyncSession,
    *,
    room: Room,
    zone_name: str,
    kind: HeatingZoneKind = HeatingZoneKind.BEDROOM,
    device_health_states: list[str],
) -> tuple[HeatingZone, list[Device]]:
    """Zone + N Devices mit explizit gesetzten ``health_state``-Werten.

    Reihenfolge der zurueckgegebenen Device-Liste entspricht der
    Reihenfolge in ``device_health_states``.
    """
    zone = HeatingZone(
        room_id=room.id,
        kind=kind,
        name=zone_name,
    )
    session.add(zone)
    await session.flush()

    devices: list[Device] = []
    for idx, health in enumerate(device_health_states):
        dev_suffix = uuid.uuid4().hex[:8]
        dev = Device(
            dev_eui=f"deadbeef{dev_suffix}",
            kind=DeviceKind.THERMOSTAT,
            vendor=DeviceVendor.MCLIMATE,
            model="vicki",
            label=f"{zone_name}-vicki-{idx}",
            heating_zone_id=zone.id,
            is_active=True,
            health_state=health,
        )
        session.add(dev)
        devices.append(dev)
    await session.flush()
    return zone, devices


async def _insert_prior_cc(
    session: AsyncSession,
    *,
    device_id: int,
    setpoint_c: int,
    age: timedelta = timedelta(minutes=5),
) -> ControlCommand:
    """Vorgaenger-ControlCommand fuer Hysterese-Test. ``age`` < 6h damit
    Heartbeat-Pfad nicht greift.
    """
    issued_at = datetime.now(tz=UTC) - age
    cc = ControlCommand(
        device_id=device_id,
        target_setpoint=Decimal(setpoint_c),
        reason=CommandReason.VACANT_SETPOINT,
        issued_at=issued_at,
        sent_to_gateway_at=issued_at,
    )
    session.add(cc)
    await session.flush()
    return cc


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_zone_3_vicki_all_healthy_3_downlinks(
    db_session: AsyncSession,
    mock_send_setpoint: tuple[list[tuple[str, int]], dict[str, BaseException]],
) -> None:
    """1-Zone-3-Vicki, alle healthy, kein Vorgaenger-CC → 3 Downlinks parallel."""
    recorded, _ = mock_send_setpoint
    room, _ = await _make_room(db_session, marker="ah")
    zone, devices = await _make_zone_with_devices(
        db_session,
        room=room,
        zone_name="Schlafzimmer",
        device_health_states=["healthy", "healthy", "healthy"],
    )

    per_dev, per_zone = await _dispatch_downlinks_per_zone(
        session=db_session,
        room_id=room.id,
        target_setpoint_c=21,
        base_reason=CommandReason.OCCUPIED_SETPOINT,
        eval_id=uuid.uuid4(),
    )

    assert len(recorded) == 3
    assert all(call[1] == 21 for call in recorded)
    assert {call[0] for call in recorded} == {d.dev_eui for d in devices}

    assert len(per_dev) == 3
    assert all(entry["status"] == "sent" for entry in per_dev)
    assert all(entry["zone_id"] == zone.id for entry in per_dev)

    assert len(per_zone) == 1
    assert per_zone[0] == {
        "zone_id": zone.id,
        "count_sent": 3,
        "count_failed": 0,
        "count_skipped": 0,
        "all_failed": False,
    }

    # ControlCommand-Rows persistent (sent_to_gateway_at != NULL)
    ccs = list(
        (
            await db_session.execute(
                select(ControlCommand).where(ControlCommand.device_id.in_([d.id for d in devices]))
            )
        )
        .scalars()
        .all()
    )
    assert len(ccs) == 3
    assert all(cc.sent_to_gateway_at is not None for cc in ccs)


@pytest.mark.asyncio
async def test_zone_3_vicki_2_healthy_1_silent_2_downlinks(
    db_session: AsyncSession,
    mock_send_setpoint: tuple[list[tuple[str, int]], dict[str, BaseException]],
) -> None:
    """1-Zone-3-Vicki, 1 silent → 2 Downlinks. Silent-Vicki wird NICHT
    angesteuert (kein ControlCommand-Row, kein per_device_results-Eintrag).
    """
    recorded, _ = mock_send_setpoint
    room, _ = await _make_room(db_session, marker="hs")
    zone, devices = await _make_zone_with_devices(
        db_session,
        room=room,
        zone_name="Schlafzimmer",
        device_health_states=["healthy", "healthy", "silent"],
    )
    silent_dev = devices[2]

    per_dev, per_zone = await _dispatch_downlinks_per_zone(
        session=db_session,
        room_id=room.id,
        target_setpoint_c=21,
        base_reason=CommandReason.OCCUPIED_SETPOINT,
        eval_id=uuid.uuid4(),
    )

    assert len(recorded) == 2
    assert silent_dev.dev_eui not in {call[0] for call in recorded}

    # per_dev hat NUR Eintraege fuer angesteuerte Vickis (silent ausgefiltert
    # vor dem Loop in _get_zone_devices)
    assert len(per_dev) == 2
    assert all(entry["status"] == "sent" for entry in per_dev)

    assert per_zone[0] == {
        "zone_id": zone.id,
        "count_sent": 2,
        "count_failed": 0,
        "count_skipped": 0,
        "all_failed": False,
    }


@pytest.mark.asyncio
async def test_zone_3_vicki_1_in_hysteresis_band_2_downlinks(
    db_session: AsyncSession,
    mock_send_setpoint: tuple[list[tuple[str, int]], dict[str, BaseException]],
) -> None:
    """1-Zone-3-Vicki, alle healthy, 1 Vicki hat letzten Setpoint=21 (gleich
    Ziel-Setpoint, Delta=0 < HYSTERESIS_C=1) → 2 Downlinks. Vicki #3 wird
    per Hysterese skipped (status=skipped_hysteresis, KEINE ControlCommand-
    Row).
    """
    recorded, _ = mock_send_setpoint
    room, _ = await _make_room(db_session, marker="h1")
    zone, devices = await _make_zone_with_devices(
        db_session,
        room=room,
        zone_name="Schlafzimmer",
        device_health_states=["healthy", "healthy", "healthy"],
    )
    # Vicki #3 hat schon Setpoint 21 (vor 5 Min) → Hysterese skip
    await _insert_prior_cc(db_session, device_id=devices[2].id, setpoint_c=21)
    skipped_dev = devices[2]

    per_dev, per_zone = await _dispatch_downlinks_per_zone(
        session=db_session,
        room_id=room.id,
        target_setpoint_c=21,
        base_reason=CommandReason.OCCUPIED_SETPOINT,
        eval_id=uuid.uuid4(),
    )

    assert len(recorded) == 2
    assert skipped_dev.dev_eui not in {call[0] for call in recorded}

    assert len(per_dev) == 3  # 2 sent + 1 skipped
    skipped_entries = [e for e in per_dev if e["status"] == "skipped_hysteresis"]
    sent_entries = [e for e in per_dev if e["status"] == "sent"]
    assert len(skipped_entries) == 1
    assert skipped_entries[0]["device_id"] == skipped_dev.id
    assert "hysteresis" in skipped_entries[0]["hysteresis_reason"]
    assert len(sent_entries) == 2

    assert per_zone[0] == {
        "zone_id": zone.id,
        "count_sent": 2,
        "count_failed": 0,
        "count_skipped": 1,
        "all_failed": False,
    }


@pytest.mark.asyncio
async def test_zone_3_vicki_all_in_hysteresis_band_0_downlinks(
    db_session: AsyncSession,
    mock_send_setpoint: tuple[list[tuple[str, int]], dict[str, BaseException]],
) -> None:
    """1-Zone-3-Vicki, alle healthy, alle haben letzten Setpoint=21 (=
    Ziel-Setpoint) → 0 Downlinks, all_hysteresis_skipped-Detail im
    per_zone_status.
    """
    recorded, _ = mock_send_setpoint
    room, _ = await _make_room(db_session, marker="ha")
    zone, devices = await _make_zone_with_devices(
        db_session,
        room=room,
        zone_name="Schlafzimmer",
        device_health_states=["healthy", "healthy", "healthy"],
    )
    for dev in devices:
        await _insert_prior_cc(db_session, device_id=dev.id, setpoint_c=21)

    per_dev, per_zone = await _dispatch_downlinks_per_zone(
        session=db_session,
        room_id=room.id,
        target_setpoint_c=21,
        base_reason=CommandReason.OCCUPIED_SETPOINT,
        eval_id=uuid.uuid4(),
    )

    assert len(recorded) == 0
    assert len(per_dev) == 3
    assert all(e["status"] == "skipped_hysteresis" for e in per_dev)

    assert per_zone[0]["zone_id"] == zone.id
    assert per_zone[0]["count_sent"] == 0
    assert per_zone[0]["count_failed"] == 0
    assert per_zone[0]["count_skipped"] == 3
    assert per_zone[0]["all_failed"] is False
    assert per_zone[0]["detail"] == "all_hysteresis_skipped"


@pytest.mark.asyncio
async def test_zone_3_vicki_1_exception_2_sent_1_failed(
    db_session: AsyncSession,
    mock_send_setpoint: tuple[list[tuple[str, int]], dict[str, BaseException]],
) -> None:
    """1-Zone-3-Vicki, alle healthy, send_setpoint wirft fuer 1 Vicki eine
    Exception → 2 ControlCommand mit sent_to_gateway_at != NULL,
    1 ControlCommand mit sent_to_gateway_at == NULL, per_device_results
    zeigt 2x ``sent`` + 1x ``failed`` mit error-Feld.
    """
    recorded, exceptions = mock_send_setpoint
    room, _ = await _make_room(db_session, marker="e1")
    zone, devices = await _make_zone_with_devices(
        db_session,
        room=room,
        zone_name="Schlafzimmer",
        device_health_states=["healthy", "healthy", "healthy"],
    )
    failing_dev = devices[1]
    exceptions[failing_dev.dev_eui] = DownlinkError("test-mqtt-broker-unreachable")

    per_dev, per_zone = await _dispatch_downlinks_per_zone(
        session=db_session,
        room_id=room.id,
        target_setpoint_c=21,
        base_reason=CommandReason.OCCUPIED_SETPOINT,
        eval_id=uuid.uuid4(),
    )

    assert len(recorded) == 3  # alle 3 wurden versucht
    failed_entries = [e for e in per_dev if e["status"] == "failed"]
    sent_entries = [e for e in per_dev if e["status"] == "sent"]
    assert len(failed_entries) == 1
    assert failed_entries[0]["device_id"] == failing_dev.id
    assert "DownlinkError" in failed_entries[0]["error"]
    assert "test-mqtt-broker-unreachable" in failed_entries[0]["error"]
    assert len(sent_entries) == 2

    assert per_zone[0]["zone_id"] == zone.id
    assert per_zone[0]["count_sent"] == 2
    assert per_zone[0]["count_failed"] == 1
    assert per_zone[0]["all_failed"] is False

    # ControlCommand-Persistenz: 3 Rows, davon 2 sent, 1 failed (NULL)
    ccs = list(
        (
            await db_session.execute(
                select(ControlCommand).where(ControlCommand.device_id.in_([d.id for d in devices]))
            )
        )
        .scalars()
        .all()
    )
    assert len(ccs) == 3
    sent_ccs = [cc for cc in ccs if cc.sent_to_gateway_at is not None]
    failed_ccs = [cc for cc in ccs if cc.sent_to_gateway_at is None]
    assert len(sent_ccs) == 2
    assert len(failed_ccs) == 1
    assert failed_ccs[0].device_id == failing_dev.id


@pytest.mark.asyncio
async def test_2_zone_room_1_vicki_each_2_downlinks_same_setpoint(
    db_session: AsyncSession,
    mock_send_setpoint: tuple[list[tuple[str, int]], dict[str, BaseException]],
) -> None:
    """2-Zonen-Room (Schlafzimmer + Bad, je 1 Vicki), beide healthy →
    2 Downlinks mit demselben Setpoint, per_zone_status hat 2 Eintraege
    beide success.
    """
    recorded, _ = mock_send_setpoint
    room, _ = await _make_room(db_session, marker="2z")
    zone_bed, devs_bed = await _make_zone_with_devices(
        db_session,
        room=room,
        zone_name="Schlafzimmer",
        kind=HeatingZoneKind.BEDROOM,
        device_health_states=["healthy"],
    )
    zone_bath, devs_bath = await _make_zone_with_devices(
        db_session,
        room=room,
        zone_name="Bad",
        kind=HeatingZoneKind.BATHROOM,
        device_health_states=["healthy"],
    )

    per_dev, per_zone = await _dispatch_downlinks_per_zone(
        session=db_session,
        room_id=room.id,
        target_setpoint_c=20,
        base_reason=CommandReason.OCCUPIED_SETPOINT,
        eval_id=uuid.uuid4(),
    )

    assert len(recorded) == 2
    assert all(call[1] == 20 for call in recorded)
    assert {call[0] for call in recorded} == {devs_bed[0].dev_eui, devs_bath[0].dev_eui}

    assert len(per_dev) == 2
    assert all(e["status"] == "sent" for e in per_dev)
    zone_ids_in_per_dev = {e["zone_id"] for e in per_dev}
    assert zone_ids_in_per_dev == {zone_bed.id, zone_bath.id}

    assert len(per_zone) == 2
    by_zone = {z["zone_id"]: z for z in per_zone}
    assert by_zone[zone_bed.id]["count_sent"] == 1
    assert by_zone[zone_bath.id]["count_sent"] == 1
    assert all(z["count_failed"] == 0 for z in per_zone)


@pytest.mark.asyncio
async def test_zone_3_vicki_all_fail_all_failed_marker(
    db_session: AsyncSession,
    mock_send_setpoint: tuple[list[tuple[str, int]], dict[str, BaseException]],
) -> None:
    """1-Zone-3-Vicki, alle healthy, send_setpoint wirft fuer alle 3
    Exception → per_zone_status[zone].all_failed=True, alle 3
    ControlCommand-Rows ohne sent_to_gateway_at.
    """
    recorded, exceptions = mock_send_setpoint
    room, _ = await _make_room(db_session, marker="af")
    zone, devices = await _make_zone_with_devices(
        db_session,
        room=room,
        zone_name="Schlafzimmer",
        device_health_states=["healthy", "healthy", "healthy"],
    )
    for dev in devices:
        exceptions[dev.dev_eui] = DownlinkError(f"fail-{dev.id}")

    per_dev, per_zone = await _dispatch_downlinks_per_zone(
        session=db_session,
        room_id=room.id,
        target_setpoint_c=21,
        base_reason=CommandReason.OCCUPIED_SETPOINT,
        eval_id=uuid.uuid4(),
    )

    assert len(recorded) == 3
    assert all(e["status"] == "failed" for e in per_dev)

    assert per_zone[0]["zone_id"] == zone.id
    assert per_zone[0]["count_sent"] == 0
    assert per_zone[0]["count_failed"] == 3
    assert per_zone[0]["all_failed"] is True

    ccs = list(
        (
            await db_session.execute(
                select(ControlCommand).where(ControlCommand.device_id.in_([d.id for d in devices]))
            )
        )
        .scalars()
        .all()
    )
    assert len(ccs) == 3
    assert all(cc.sent_to_gateway_at is None for cc in ccs)
