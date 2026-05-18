"""Sprint 11 T4 — Engine-Failure-Hardening + Health-Mutation Tests (AE-54).

Verifiziert, dass ``_evaluate_room_async`` einen aeusseren ``try/except
Exception`` hat, der bei einem beliebigen Crash innerhalb der Eval
(Layer-Funktion, DB, unerwartete Exception) den Task sauber abschliesst,
ALLE HeatingZones des Raums auf ``health_state='degraded'`` setzt und
KEIN Re-Raise produziert (kein Celery-Retry-Backlog bei dauerhaft
kaputter Zone).

Phase-0.5-Befund: Engine ist heute Room-zentrisch — HeatingZone wird
nur als JOIN-Filter genutzt, nicht als Iterations-Granular. T4 verankert
deshalb die bestehende Per-Room-Isolation strukturell (Celery-Task-
Boundary + neuer Top-Level-Wrap) und mutiert ALLE Zonen des Raums.
HeatingZone-Iteration kommt mit Sprint 12 (AE-51 §4.2 Schreib-Pfad).

DB-Tests skippen ohne ``TEST_DATABASE_URL``.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator, Iterator
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from heizung.config import get_settings
from heizung.models.control_command import ControlCommand
from heizung.models.device import Device
from heizung.models.enums import DeviceKind, DeviceVendor, HeatingZoneKind
from heizung.models.event_log import EventLog
from heizung.models.heating_zone import HeatingZone
from heizung.models.room import Room
from heizung.models.room_type import RoomType
from heizung.tasks import engine_tasks

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


@pytest.fixture
def pin_database_url(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """``DATABASE_URL`` auf ``TEST_DATABASE_URL`` pinnen, damit
    ``_task_session`` aus ``engine_tasks`` und der Test dieselbe DB sehen
    (Pattern aus ``test_engine_trace_consistency.py``). ``cache_clear``
    am Ende, damit der naechste Test ohne Pin frische Settings bekommt.
    """
    assert TEST_DB_URL is not None
    monkeypatch.setenv("DATABASE_URL", TEST_DB_URL)
    get_settings.cache_clear()
    try:
        yield None
    finally:
        get_settings.cache_clear()


@pytest.fixture
def track_downlinks(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, Any]]:
    """Patcht ``send_setpoint`` in ``engine_tasks`` zu einem Tracker —
    kein echter MQTT-Downlink, aber Aufrufe sind sichtbar.
    """
    calls: list[tuple[str, Any]] = []

    async def _track(dev_eui: str, setpoint_c: Any) -> None:
        calls.append((dev_eui, setpoint_c))

    monkeypatch.setattr(engine_tasks, "send_setpoint", _track)
    return calls


async def _create_room_with_zone_and_device(
    session: AsyncSession, *, suffix: str, zone_health: str = "healthy"
) -> tuple[int, int, int]:
    """Anlegt RoomType + Room + HeatingZone + Device. ``suffix`` 8 hex chars.

    Kein ``commit`` hier — Test entscheidet, wann committed wird (muss
    vor dem ``_evaluate_room_async``-Aufruf passieren, damit das
    separate ``_task_session()`` die Daten sieht).
    """
    rt = RoomType(name=f"t11t4-rt-{suffix}")
    session.add(rt)
    await session.flush()
    room = Room(number=f"t11t4-{suffix}", room_type_id=rt.id)
    session.add(room)
    await session.flush()
    zone = HeatingZone(
        room_id=room.id,
        kind=HeatingZoneKind.BEDROOM,
        name="bedroom",
        health_state=zone_health,
    )
    session.add(zone)
    await session.flush()
    device = Device(
        dev_eui=f"deadbeef{suffix}",
        kind=DeviceKind.THERMOSTAT,
        vendor=DeviceVendor.MCLIMATE,
        model="vicki",
        heating_zone_id=zone.id,
        health_state="healthy",
    )
    session.add(device)
    await session.flush()
    return room.id, zone.id, device.id


async def _cleanup_room_side_effects(
    session: AsyncSession, *, room_id: int, device_ids: list[int]
) -> None:
    """Loescht ``event_log`` + ``control_command``, die ein erfolgreicher
    ``_evaluate_room_async``-Lauf committed hat — Test-Session-Rollback
    raeumt committed Daten nicht weg (vgl. trace_consistency-Test).
    """
    for ev in (
        (await session.execute(select(EventLog).where(EventLog.room_id == room_id))).scalars().all()
    ):
        await session.delete(ev)
    if device_ids:
        for cc in (
            (
                await session.execute(
                    select(ControlCommand).where(ControlCommand.device_id.in_(device_ids))
                )
            )
            .scalars()
            .all()
        ):
            await session.delete(cc)
    await session.commit()


# ---------------------------------------------------------------------------
# Test 1 — Layer-Crash markiert Zone als degraded, kein Downlink, kein CC
# ---------------------------------------------------------------------------


async def test_room_with_synthetic_layer_exception_marks_zone_degraded(
    db_session: AsyncSession,
    pin_database_url: None,
    monkeypatch: pytest.MonkeyPatch,
    track_downlinks: list[tuple[str, Any]],
) -> None:
    suffix = uuid.uuid4().hex[:8]
    room_id, zone_id, device_id = await _create_room_with_zone_and_device(db_session, suffix=suffix)
    await db_session.commit()  # _task_session sieht den Raum

    async def _boom(session: Any, room_id: int) -> Any:
        raise RuntimeError("synthetic-layer-exception")

    monkeypatch.setattr(engine_tasks, "_engine_evaluate_room", _boom)

    result = await engine_tasks._evaluate_room_async(room_id)

    assert result == {"room_id": room_id, "status": "failed_marked_degraded"}

    # Re-fetch zone state — sichtbar erst nach expire, da der Helper in
    # einer anderen Session committed hat.
    db_session.expire_all()
    zone = await db_session.get(HeatingZone, zone_id)
    assert zone is not None
    assert zone.health_state == "degraded"

    # Verhaltens-Assert statt Logger-Assert (caplog + pytest-asyncio-Quirk
    # im Async-Call-Path — Audit-Log wird produktiv via
    # ``logger.exception("room_eval_failed", ...)`` in engine_tasks.py
    # geschrieben und ist im Container-Log grep-bar; statisch via
    # Code-Review verifizierbar).
    cmds = (
        (
            await db_session.execute(
                select(ControlCommand).where(ControlCommand.device_id == device_id)
            )
        )
        .scalars()
        .all()
    )
    assert cmds == [], "kein ControlCommand bei Crash"
    assert track_downlinks == [], "kein Downlink versucht bei Crash"

    # Audit-Trail: KEIN EventLog-Eintrag fuer diesen Raum (Eval-Pipeline
    # ist vor dem EventLog-Insert in engine_tasks.py:177ff gecrasht).
    event_logs = (
        (await db_session.execute(select(EventLog).where(EventLog.room_id == room_id)))
        .scalars()
        .all()
    )
    assert event_logs == [], "kein event_log-Eintrag bei Eval-Failure"


# ---------------------------------------------------------------------------
# Test 2 — Raum A crasht, Raum B evaluiert normal — Per-Room-Isolation
# ---------------------------------------------------------------------------


async def test_two_rooms_first_crashes_second_evaluates_normally(
    db_session: AsyncSession,
    pin_database_url: None,
    monkeypatch: pytest.MonkeyPatch,
    track_downlinks: list[tuple[str, Any]],
) -> None:
    suffix_a = uuid.uuid4().hex[:8]
    suffix_b = uuid.uuid4().hex[:8]
    room_a, zone_a, device_a = await _create_room_with_zone_and_device(db_session, suffix=suffix_a)
    room_b, zone_b, device_b = await _create_room_with_zone_and_device(db_session, suffix=suffix_b)
    await db_session.commit()

    original = engine_tasks._engine_evaluate_room

    async def _selective_boom(session: Any, room_id: int) -> Any:
        if room_id == room_a:
            raise RuntimeError("synthetic-room-a-crash")
        return await original(session, room_id)

    monkeypatch.setattr(engine_tasks, "_engine_evaluate_room", _selective_boom)

    result_a = await engine_tasks._evaluate_room_async(room_a)
    result_b = await engine_tasks._evaluate_room_async(room_b)

    assert result_a == {"room_id": room_a, "status": "failed_marked_degraded"}
    assert result_b.get("status") != "failed_marked_degraded", (
        "Raum B darf nicht durch Raum-A-Crash in den Fail-Pfad gezogen werden"
    )
    assert "evaluation_id" in result_b, "Raum B muss die normale Eval-Pipeline durchlaufen"

    db_session.expire_all()
    zone_a_obj = await db_session.get(HeatingZone, zone_a)
    zone_b_obj = await db_session.get(HeatingZone, zone_b)
    assert zone_a_obj is not None and zone_b_obj is not None
    assert zone_a_obj.health_state == "degraded", "Raum A: Zone -> degraded"
    assert zone_b_obj.health_state == "healthy", (
        "Raum B: Zone-Health bleibt unangetastet (kein implicit-healthy aus Eval)"
    )

    # Per-Room-Isolation der Side-Effects:
    # Raum A: kein ControlCommand fuer device_a (Crash vor Insert).
    cmds_a = (
        (
            await db_session.execute(
                select(ControlCommand).where(ControlCommand.device_id == device_a)
            )
        )
        .scalars()
        .all()
    )
    assert cmds_a == [], "Raum A: kein ControlCommand bei Crash"

    # Raum A: kein event_log-Eintrag.
    event_logs_a = (
        (await db_session.execute(select(EventLog).where(EventLog.room_id == room_a)))
        .scalars()
        .all()
    )
    assert event_logs_a == [], "Raum A: kein event_log bei Crash"

    # Raum B: ControlCommand wurde persistiert (Erfolgspfad lief durch).
    cmds_b = (
        (
            await db_session.execute(
                select(ControlCommand).where(ControlCommand.device_id == device_b)
            )
        )
        .scalars()
        .all()
    )
    assert len(cmds_b) >= 1, "Raum B: Erfolgspfad muss ControlCommand persistiert haben"

    # Raum B: Downlink wurde versucht (patched send_setpoint hat getrackt).
    assert any(eui.endswith(suffix_b) for eui, _ in track_downlinks), (
        "Raum B: send_setpoint muss fuer device_b aufgerufen worden sein"
    )

    # Aufraeumen: Raum-B-Eval hat event_log + control_command committed.
    await _cleanup_room_side_effects(db_session, room_id=room_b, device_ids=[device_b])


# ---------------------------------------------------------------------------
# Test 3 — Wiederholter Crash, Zone schon degraded: KEIN doppelter UPDATE
# ---------------------------------------------------------------------------


async def test_repeated_crash_same_room_no_double_write(
    db_session: AsyncSession,
    pin_database_url: None,
    monkeypatch: pytest.MonkeyPatch,
    track_downlinks: list[tuple[str, Any]],
) -> None:
    """Idempotenz-Check via SQLAlchemy ``before_update``-Event-Listener:
    HeatingZone war bereits ``degraded`` vor dem Aufruf, der Helper darf
    KEIN UPDATE auf die Tabelle emitten (Wert-Vergleich im Helper
    verhindert das Setter-Dirty-Marker-Pattern).

    Implementation: ``event.listen(HeatingZone, "before_update", cb)``
    aus ``sqlalchemy.event``. Der Callback feuert pro ORM-flushed UPDATE
    auf der HeatingZone-Tabelle, gefiltert auf unsere ``room_id``. Bei
    erfolgreicher Idempotenz im Helper bleibt der Counter == 0.
    """
    suffix = uuid.uuid4().hex[:8]
    room_id, zone_id, _ = await _create_room_with_zone_and_device(
        db_session, suffix=suffix, zone_health="degraded"
    )
    await db_session.commit()

    async def _boom(session: Any, room_id: int) -> Any:
        raise RuntimeError("synthetic-layer-exception")

    monkeypatch.setattr(engine_tasks, "_engine_evaluate_room", _boom)

    updates: list[int] = []

    def _track_update(_mapper: Any, _connection: Any, target: HeatingZone) -> None:
        # Nur Updates auf die Test-Zone zaehlen — andere parallele Test-Runs
        # haben andere room_ids und sollen den Counter nicht stoeren.
        if target.room_id == room_id:
            updates.append(target.id)

    event.listen(HeatingZone, "before_update", _track_update)
    try:
        result1 = await engine_tasks._evaluate_room_async(room_id)
        result2 = await engine_tasks._evaluate_room_async(room_id)
    finally:
        event.remove(HeatingZone, "before_update", _track_update)

    assert result1["status"] == "failed_marked_degraded"
    assert result2["status"] == "failed_marked_degraded"

    # Idempotenz: Zone war schon 'degraded' -> kein UPDATE in beiden Laeufen.
    assert updates == [], (
        f"erwarte 0 HeatingZone-UPDATEs bei bereits-degraded Zone, gefunden {len(updates)}"
    )

    db_session.expire_all()
    zone = await db_session.get(HeatingZone, zone_id)
    assert zone is not None
    assert zone.health_state == "degraded", "Zone bleibt degraded (kein Toggle)"


# ---------------------------------------------------------------------------
# Test 4 — Orphaned room_id: Helper laeuft sauber durch, kein FK-Crash
# ---------------------------------------------------------------------------


async def test_room_with_orphaned_room_id_does_not_crash(
    db_session: AsyncSession,
    pin_database_url: None,
    monkeypatch: pytest.MonkeyPatch,
    track_downlinks: list[tuple[str, Any]],
) -> None:
    """Patch zwingt einen Crash, der Raum existiert nicht.
    ``_mark_room_health_degraded`` muss als bewusste Eigenschaft eine
    leere zones-Liste verarbeiten ohne FK-Violation/IntegrityError.

    Verifikation des "kein FK-/IntegrityError"-Vertrags erfolgt
    implizit: wuerde der Helper bei orphan room_id eine Exception
    durchlassen, wuerde sie aus ``_evaluate_room_async`` heraus
    eskalieren (die Helper-Sektion ist ausserhalb des outer try)
    und der ``await``-Aufruf hier wuerfe — der Test wuerde an dieser
    Zeile sterben, nicht erst an einer spaeteren Assertion. Das
    erfolgreiche ``return``-Dict ist also das Bestehen des Kontrakts.
    """
    orphan_id = 10_000_000 + (uuid.uuid4().int % 1_000_000)
    existing = await db_session.get(Room, orphan_id)
    assert existing is None, "Vorbedingung: orphan_id darf nicht existieren"

    async def _boom(session: Any, room_id: int) -> Any:
        raise RuntimeError("synthetic-layer-exception")

    monkeypatch.setattr(engine_tasks, "_engine_evaluate_room", _boom)

    result = await engine_tasks._evaluate_room_async(orphan_id)

    assert result == {"room_id": orphan_id, "status": "failed_marked_degraded"}
