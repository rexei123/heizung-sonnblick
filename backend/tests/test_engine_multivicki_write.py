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

from heizung.models.business_audit import BusinessAudit
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
from heizung.models.manual_override import ManualOverride
from heizung.models.room import Room
from heizung.models.room_type import RoomType
from heizung.models.sensor_reading import SensorReading
from heizung.services import alert_throttle, engine_abgleich
from heizung.services.downlink_adapter import DownlinkError
from heizung.tasks.engine_tasks import (
    AUDIT_ABGLEICH_ERSCHOEPFT,
    _dispatch_downlinks_per_zone,
)
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


# ---------------------------------------------------------------------------
# Sprint 20f (T3) — Engine-Abgleich im Dispatch
# ---------------------------------------------------------------------------
#
# **Der Befund.** Die Hysterese vergleicht den neuen Sollwert mit dem **letzten
# selbst gesendeten**, nicht mit dem, den das Geraet meldet. Hat die Engine
# zuletzt 18 geschickt und will wieder 18, ist ``delta = 0`` und sie schweigt —
# unabhaengig davon, was am Geraet steht. Die Geraete **048** und **057**
# standen deshalb am 05.10.2026 nach einer Montage-Drehung auf 20 °C, waehrend
# der Engine-Soll 18 °C war und kein Override existierte. Korrigiert wurde per
# Hand ueber die Queue.
#
# Die Engine kannte ihren eigenen Willen, aber nicht den Zustand des Geraets.


async def _insert_reading(
    session: AsyncSession,
    *,
    device_id: int,
    setpoint_c: int | None,
    age: timedelta = timedelta(minutes=2),
) -> SensorReading:
    """Gemeldetes Reading — die Groesse, die der Abgleich liest.

    ``setpoint_c=None`` legt eine Zeile **ohne** Sollwert an. Das ist der Fall,
    den es wirklich gibt: ein Frame, den der Codec nicht vollstaendig
    dekodieren konnte (vor Sprint 20f T1 jeder ``0x28``-Frame). Eine solche
    Zeile darf **keine** Abweichung belegen.
    """
    reading = SensorReading(
        time=datetime.now(tz=UTC) - age,
        device_id=device_id,
        setpoint=None if setpoint_c is None else Decimal(setpoint_c),
    )
    session.add(reading)
    await session.flush()
    return reading


class _FakeRedis:
    """In-Memory-Redis fuer die Drosselung des Abgleichs."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    def set(
        self,
        key: str,
        value: str,
        *,
        nx: bool = False,
        ex: int | None = None,  # noqa: ARG002
    ) -> bool | None:
        if nx and key in self.store:
            return None
        self.store[key] = value
        return True

    def get(self, key: str) -> str | None:
        return self.store.get(key)

    def incr(self, key: str) -> int:
        neu = int(self.store.get(key, "0")) + 1
        self.store[key] = str(neu)
        return neu

    def expire(self, key: str, ttl: int) -> bool:  # noqa: ARG002
        return True

    def delete(self, key: str) -> int:
        return 1 if self.store.pop(key, None) is not None else 0


@pytest.fixture
def abgleich_redis(monkeypatch: pytest.MonkeyPatch) -> _FakeRedis:
    """Faelscht Redis fuer ``engine_abgleich`` **und** ``alert_throttle``.

    Beide muessen gefaelscht werden: der Abgleich drosselt ueber
    ``engine_abgleich``, und die Meldung "Versuche erschoepft" drosselt sich
    zusaetzlich ueber ``alert_throttle``. Ein echter Redis waere hier eine
    zweite Abhaengigkeit fuer einen Test, der ueber Downlinks urteilt.
    """
    client = _FakeRedis()
    monkeypatch.setattr(engine_abgleich.redis_client, "get_redis_client", lambda: client)
    monkeypatch.setattr(alert_throttle.redis_client, "get_redis_client", lambda: client)
    return client


@pytest.mark.asyncio
async def test_abgleich_sendet_wenn_das_geraet_abweicht(
    db_session: AsyncSession,
    mock_send_setpoint: tuple[list[tuple[str, int]], dict[str, BaseException]],
    abgleich_redis: _FakeRedis,
) -> None:
    """**Die Regressions-Wand fuer 048/057.**

    Die Engine hat zuletzt 18 geschickt und will wieder 18 — die Hysterese
    sagt also "nichts zu tun". Das Geraet meldet aber 20. Ohne den Abgleich
    bleibt es dort, bis sich der Engine-Soll aendert; das waren bei 048 und
    057 mehrere Tage, und behoben hat es ein Mensch per Queue.
    """
    recorded, _ = mock_send_setpoint
    room, _ = await _make_room(db_session, marker="a1")
    _zone, devices = await _make_zone_with_devices(
        db_session,
        room=room,
        zone_name="Schlafzimmer",
        device_health_states=["healthy"],
    )
    dev = devices[0]
    await _insert_prior_cc(db_session, device_id=dev.id, setpoint_c=18)
    await _insert_reading(db_session, device_id=dev.id, setpoint_c=20)

    per_dev, _per_zone = await _dispatch_downlinks_per_zone(
        session=db_session,
        room_id=room.id,
        target_setpoint_c=18,
        base_reason=CommandReason.VACANT_SETPOINT,
        eval_id=uuid.uuid4(),
    )

    assert recorded == [(dev.dev_eui, 18)]
    assert per_dev[0]["status"] == "sent"
    assert "engine_abgleich" in per_dev[0]["hysteresis_reason"]


@pytest.mark.asyncio
async def test_abgleich_schweigt_bei_aktivem_override(
    db_session: AsyncSession,
    mock_send_setpoint: tuple[list[tuple[str, int]], dict[str, BaseException]],
    abgleich_redis: _FakeRedis,
) -> None:
    """**Der wichtigste Test dieser Datei.**

    Ein Gast-Override ist genau der Fall, in dem das Geraet absichtlich
    abweicht. Wuerde der Abgleich hier senden, ueberschriebe er den
    Gastwunsch — und zwar alle 30 Minuten, dauerhaft, waehrend der Gast im
    Zimmer ist. Das waere aus einer Nachbesserung ein Defekt geworden.

    Deshalb ist "kein aktiver Override" im Code keine Nebenbedingung, sondern
    eine der drei Hauptbedingungen.
    """
    recorded, _ = mock_send_setpoint
    room, _ = await _make_room(db_session, marker="a2")
    zone, devices = await _make_zone_with_devices(
        db_session,
        room=room,
        zone_name="Schlafzimmer",
        device_health_states=["healthy"],
    )
    dev = devices[0]
    await _insert_prior_cc(db_session, device_id=dev.id, setpoint_c=18)
    await _insert_reading(db_session, device_id=dev.id, setpoint_c=25)
    # Der Gast hat gedreht — Override auf 25, zonen-scoped.
    override = ManualOverride(
        room_id=room.id,
        heating_zone_id=zone.id,
        setpoint=Decimal("25.0"),
        source=OverrideSource.DEVICE_MANUAL,
        expires_at=datetime.now(tz=UTC) + timedelta(hours=4),
    )
    db_session.add(override)
    await db_session.flush()

    per_dev, _per_zone = await _dispatch_downlinks_per_zone(
        session=db_session,
        room_id=room.id,
        target_setpoint_c=18,
        base_reason=CommandReason.VACANT_SETPOINT,
        eval_id=uuid.uuid4(),
    )

    assert recorded == []
    assert per_dev[0]["status"] == "skipped_hysteresis"
    assert "engine_abgleich" not in per_dev[0]["hysteresis_reason"]


@pytest.mark.asyncio
async def test_abgleich_sendet_hoechstens_einmal_je_fenster(
    db_session: AsyncSession,
    mock_send_setpoint: tuple[list[tuple[str, int]], dict[str, BaseException]],
    abgleich_redis: _FakeRedis,
) -> None:
    """Zweiter Tick im Fenster: kein zweiter Downlink.

    Der Engine-Tick laeuft **jede Minute**. Ohne diese Grenze waere der
    Abgleich ein Downlink pro Minute, solange das Geraet nicht folgt — und
    jeder davon eine Motorbewegung (§0 S4).
    """
    recorded, _ = mock_send_setpoint
    room, _ = await _make_room(db_session, marker="a3")
    _zone, devices = await _make_zone_with_devices(
        db_session,
        room=room,
        zone_name="Schlafzimmer",
        device_health_states=["healthy"],
    )
    dev = devices[0]
    await _insert_prior_cc(db_session, device_id=dev.id, setpoint_c=18)
    await _insert_reading(db_session, device_id=dev.id, setpoint_c=20)

    for _ in range(3):
        await _dispatch_downlinks_per_zone(
            session=db_session,
            room_id=room.id,
            target_setpoint_c=18,
            base_reason=CommandReason.VACANT_SETPOINT,
            eval_id=uuid.uuid4(),
        )

    assert recorded == [(dev.dev_eui, 18)], "drei Ticks, genau ein Downlink"


@pytest.mark.asyncio
async def test_abgleich_gibt_nach_drei_versuchen_auf_und_meldet(
    db_session: AsyncSession,
    mock_send_setpoint: tuple[list[tuple[str, int]], dict[str, BaseException]],
    abgleich_redis: _FakeRedis,
) -> None:
    """Nach ``MAX_VERSUCHE`` kein vierter Downlink — und ein Audit-Eintrag.

    Das Aufgeben darf nicht stillschweigend passieren. Ein Geraet, das
    dauerhaft einen anderen Wert haelt als die Engine will, heizt ein Zimmer
    falsch — und niemand sieht es, weil die Oberflaeche den Engine-Soll
    anzeigt und nicht den Geraete-Wert (§5.76).

    Die Sperre wird zwischen den Durchlaeufen von Hand entfernt; das ist der
    Zeitablauf, den der Test nicht abwarten soll.
    """
    recorded, _ = mock_send_setpoint
    room, _ = await _make_room(db_session, marker="a4")
    _zone, devices = await _make_zone_with_devices(
        db_session,
        room=room,
        zone_name="Schlafzimmer",
        device_health_states=["healthy"],
    )
    dev = devices[0]
    await _insert_prior_cc(db_session, device_id=dev.id, setpoint_c=18)
    await _insert_reading(db_session, device_id=dev.id, setpoint_c=20)

    # Vier Fenster: drei Versuche plus einer, der nicht mehr gesendet wird.
    for _ in range(4):
        abgleich_redis.store.pop(engine_abgleich._drossel_key(dev.dev_eui), None)
        await _dispatch_downlinks_per_zone(
            session=db_session,
            room_id=room.id,
            target_setpoint_c=18,
            base_reason=CommandReason.VACANT_SETPOINT,
            eval_id=uuid.uuid4(),
        )

    assert len(recorded) == engine_abgleich.MAX_VERSUCHE

    audits = (
        (
            await db_session.execute(
                select(BusinessAudit).where(
                    BusinessAudit.action == AUDIT_ABGLEICH_ERSCHOEPFT,
                    BusinessAudit.target_id == dev.id,
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(audits) == 1, "einmal melden, nicht bei jedem Tick"
    assert audits[0].new_value["gemeldeter_sollwert"] == 20
    assert audits[0].new_value["engine_sollwert"] == 18


@pytest.mark.asyncio
async def test_abgleich_schweigt_wenn_das_geraet_den_soll_meldet(
    db_session: AsyncSession,
    mock_send_setpoint: tuple[list[tuple[str, int]], dict[str, BaseException]],
    abgleich_redis: _FakeRedis,
) -> None:
    """Uebereinstimmung heisst Ruhe — und der Zaehler wird zurueckgesetzt.

    Die Gegenprobe zum ersten Test. Ohne sie koennte der Abgleich bei jedem
    Tick senden, weil die Bedingung falsch herum stuende, und niemand wuerde
    es an einer einzelnen Zeile merken.
    """
    recorded, _ = mock_send_setpoint
    room, _ = await _make_room(db_session, marker="a5")
    _zone, devices = await _make_zone_with_devices(
        db_session,
        room=room,
        zone_name="Schlafzimmer",
        device_health_states=["healthy"],
    )
    dev = devices[0]
    await _insert_prior_cc(db_session, device_id=dev.id, setpoint_c=18)
    await _insert_reading(db_session, device_id=dev.id, setpoint_c=18)
    # Verbrauchte Versuche aus einem frueheren Fall.
    engine_abgleich.versuch_gezaehlt(dev.dev_eui)
    engine_abgleich.versuch_gezaehlt(dev.dev_eui)

    await _dispatch_downlinks_per_zone(
        session=db_session,
        room_id=room.id,
        target_setpoint_c=18,
        base_reason=CommandReason.VACANT_SETPOINT,
        eval_id=uuid.uuid4(),
    )

    assert recorded == []
    assert engine_abgleich.versuche(dev.dev_eui) == 0


@pytest.mark.asyncio
async def test_reading_ohne_sollwert_belegt_keine_abweichung(
    db_session: AsyncSession,
    mock_send_setpoint: tuple[list[tuple[str, int]], dict[str, BaseException]],
    abgleich_redis: _FakeRedis,
) -> None:
    """Eine Zeile ohne ``setpoint`` ist keine Aussage.

    Genau solche Zeilen entstanden vor Sprint 20f T1 aus jedem
    ``0x28``-Frame: der Codec brach ab, und der Subscriber schrieb eine Zeile,
    in der alles ``NULL`` war. Wuerde der Abgleich ``NULL`` als Abweichung
    lesen, haette er genau an den Geraeten gesendet, an denen eine
    Handverstellung stattfand — alle 30 Minuten, gegen den Gast.

    Dieselbe Drei-Zustands-Regel wie bei ``attached_backplate`` und
    ``calibration_failed``: NULL ist weder Ja noch Nein.
    """
    recorded, _ = mock_send_setpoint
    room, _ = await _make_room(db_session, marker="a6")
    _zone, devices = await _make_zone_with_devices(
        db_session,
        room=room,
        zone_name="Schlafzimmer",
        device_health_states=["healthy"],
    )
    dev = devices[0]
    await _insert_prior_cc(db_session, device_id=dev.id, setpoint_c=18)
    await _insert_reading(db_session, device_id=dev.id, setpoint_c=None)

    await _dispatch_downlinks_per_zone(
        session=db_session,
        room_id=room.id,
        target_setpoint_c=18,
        base_reason=CommandReason.VACANT_SETPOINT,
        eval_id=uuid.uuid4(),
    )

    assert recorded == []
