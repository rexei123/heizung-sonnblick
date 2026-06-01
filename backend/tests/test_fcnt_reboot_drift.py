"""Sprint 15c (AE-63) — fcnt-Reboot-Drift-Fix Tests.

Deckt:
- Reine Funktion ``is_reboot_frame`` (Diskriminator-Schwelle, Edge-Cases).
- ``_get_prior_fcnt`` DB-Lookup gegen ``sensor_reading`` (DB-Test).
- ``handle_uplink_for_override`` Reboot-Gate Integration (DB-Test):
  Reboot-Frame -> KEIN DEVICE-Override, Redis-Flag gesetzt, event_log
  ``REBOOT_RESYNC``.
- ``engine_tasks._dispatch_downlinks_per_zone`` Re-Sync-Consume (DB-Test):
  Flag gesetzt -> Hysterese-Bypass + forced Downlink mit ``reason=
  REBOOT_RESYNC``, Flag danach geloescht.
- Regression: echter Drehring (fcnt monoton, Setpoint != Engine-Soll) ->
  DEVICE-Override wie bisher (AE-45-Pfad unangetastet).
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
from sqlalchemy import select
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
    EventLogLayer,
    HeatingZoneKind,
    OverrideSource,
)
from heizung.models.event_log import EventLog
from heizung.models.heating_zone import HeatingZone
from heizung.models.manual_override import ManualOverride
from heizung.models.occupancy import Occupancy
from heizung.models.room import Room
from heizung.models.room_type import RoomType
from heizung.models.sensor_reading import SensorReading
from heizung.services import device_adapter, redis_client, resync_flag
from heizung.tasks import engine_tasks

DATABASE_URL = os.environ.get("DATABASE_URL")
DATABASE_URL_PRESENT = bool(DATABASE_URL)
SKIP_REASON = "DATABASE_URL nicht gesetzt - DB-Tests brauchen Test-DB"


# ---------------------------------------------------------------------------
# Pure-Function-Tests fuer is_reboot_frame (kein DB / Redis noetig)
# ---------------------------------------------------------------------------


def test_is_reboot_frame_classic_reset() -> None:
    """prior=4338, current=4 -> True (Reboot, current << threshold)."""
    assert device_adapter.is_reboot_frame(prior_fcnt=4338, current_fcnt=4) is True


def test_is_reboot_frame_out_of_order_not_below_threshold() -> None:
    """prior=4340, current=4339 -> False (current nicht < threshold)."""
    assert device_adapter.is_reboot_frame(prior_fcnt=4340, current_fcnt=4339) is False


def test_is_reboot_frame_no_prior() -> None:
    """prior=None -> False (kein Vorframe = nicht entscheidbar)."""
    assert device_adapter.is_reboot_frame(prior_fcnt=None, current_fcnt=3) is False


def test_is_reboot_frame_duplicate() -> None:
    """prior=4338, current=4338 -> False (Duplikat, nicht strikt < prior)."""
    assert device_adapter.is_reboot_frame(prior_fcnt=4338, current_fcnt=4338) is False


def test_is_reboot_frame_monotone_increase() -> None:
    """prior=5, current=8 -> False (Monoton, kein Reset)."""
    assert device_adapter.is_reboot_frame(prior_fcnt=5, current_fcnt=8) is False


def test_is_reboot_frame_threshold_boundary_inclusive() -> None:
    """prior=10, current=9 -> True (current=9 < threshold=10 UND < prior=10)."""
    assert device_adapter.is_reboot_frame(prior_fcnt=10, current_fcnt=9) is True


def test_is_reboot_frame_at_threshold() -> None:
    """prior=20, current=10 -> False (current=10 nicht < threshold=10)."""
    assert device_adapter.is_reboot_frame(prior_fcnt=20, current_fcnt=10) is False


def test_is_reboot_frame_current_zero() -> None:
    """prior=100, current=0 -> True (klassischer LoRaWAN-Cold-Boot)."""
    assert device_adapter.is_reboot_frame(prior_fcnt=100, current_fcnt=0) is True


# ---------------------------------------------------------------------------
# FakeRedis fuer resync_flag-Mock (sync, in-memory, mit getdel-Support)
# ---------------------------------------------------------------------------


class _FakeRedis:
    """In-Memory-Stand-in fuer ``redis.Redis``. Implementiert nur die
    Operationen, die ``resync_flag`` und Bestandstests nutzen: ``set``
    (mit ``nx``/``ex``), ``get``, ``getdel``, ``delete``, ``incr``,
    ``expire``, ``pipeline``. TTL wird ignoriert.
    """

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

    def getdel(self, key: str) -> str | None:
        return self.store.pop(key, None)

    def delete(self, key: str) -> int:
        if key in self.store:
            del self.store[key]
            return 1
        return 0


@pytest.fixture
def fake_redis(monkeypatch: pytest.MonkeyPatch) -> _FakeRedis:
    fake = _FakeRedis()
    monkeypatch.setattr(redis_client, "get_redis_client", lambda: fake)
    return fake


def test_resync_flag_mark_then_consume(fake_redis: _FakeRedis) -> None:
    """mark_pending -> consume gibt True zurueck und loescht den Key."""
    assert resync_flag.mark_pending("AABBCCDDEEFF0011") is True
    assert "resync_pending:aabbccddeeff0011" in fake_redis.store
    assert resync_flag.consume("AABBCCDDEEFF0011") is True
    assert "resync_pending:aabbccddeeff0011" not in fake_redis.store


def test_resync_flag_consume_when_not_set(fake_redis: _FakeRedis) -> None:
    """consume ohne vorheriges mark_pending -> False."""
    assert resync_flag.consume("aabbccddeeff0011") is False


def test_resync_flag_key_case_insensitive(fake_redis: _FakeRedis) -> None:
    """Key wird auf lowercase normalisiert (subscriber lowercased dev_eui)."""
    resync_flag.mark_pending("AABBCC")
    assert "resync_pending:aabbcc" in fake_redis.store
    assert resync_flag.consume("aabbcc") is True


# ---------------------------------------------------------------------------
# DB-Fixtures (Pattern aus test_device_adapter.py)
# ---------------------------------------------------------------------------


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
    return uuid.uuid4().hex[:16]


def _unique_short() -> str:
    return uuid.uuid4().hex[:8]


async def _seed_occupied_stack_with_reading_history(
    s: AsyncSession,
    *,
    prior_fcnt: int | None,
    last_engine_setpoint: Decimal = Decimal("21.0"),
) -> tuple[int, int, str, datetime]:
    """Setup: Room (OCCUPIED) + HeatingZone + Device (healthy) +
    ControlCommand (last engine setpoint, > Ack-Window alt) + optional
    eine SensorReading-Historie mit ``fcnt=prior_fcnt`` 5 Minuten zurueck.
    Returns (room_id, device_id, dev_eui, received_at).
    """
    short = _unique_short()
    rt = RoomType(name=f"15c-{short}")
    s.add(rt)
    await s.flush()
    room = Room(number=f"15c-{short}", room_type_id=rt.id)
    s.add(room)
    await s.flush()
    now = datetime.now(tz=UTC)
    s.add(
        Occupancy(
            room_id=room.id,
            check_in=now - timedelta(hours=1),
            check_out=now + timedelta(days=2),
            is_active=True,
        )
    )
    await s.flush()
    hz = HeatingZone(room_id=room.id, kind=HeatingZoneKind.BEDROOM, name="zone-1")
    s.add(hz)
    await s.flush()
    dev_eui = _unique_eui()
    device = Device(
        dev_eui=dev_eui,
        kind=DeviceKind.THERMOSTAT,
        vendor=DeviceVendor.MCLIMATE,
        model="Vicki",
        heating_zone_id=hz.id,
        health_state="healthy",
    )
    s.add(device)
    await s.flush()
    cc = ControlCommand(
        device_id=device.id,
        target_setpoint=last_engine_setpoint,
        reason=CommandReason.OCCUPIED_SETPOINT,
        sent_to_gateway_at=now - timedelta(seconds=120),
    )
    s.add(cc)
    await s.flush()
    if prior_fcnt is not None:
        s.add(
            SensorReading(
                time=now - timedelta(minutes=5),
                device_id=device.id,
                fcnt=prior_fcnt,
                temperature=Decimal("21.0"),
                setpoint=last_engine_setpoint,
            )
        )
        await s.flush()
    return room.id, device.id, dev_eui, now


# ---------------------------------------------------------------------------
# _get_prior_fcnt — DB-Lookup
# ---------------------------------------------------------------------------


async def test_get_prior_fcnt_returns_most_recent_before_received_at(
    session: AsyncSession,
) -> None:
    _room_id, device_id, _dev_eui, now = await _seed_occupied_stack_with_reading_history(
        session, prior_fcnt=4338
    )
    prior = await device_adapter._get_prior_fcnt(session, device_id, now)
    assert prior == 4338


async def test_get_prior_fcnt_returns_none_without_history(
    session: AsyncSession,
) -> None:
    _room_id, device_id, _dev_eui, now = await _seed_occupied_stack_with_reading_history(
        session, prior_fcnt=None
    )
    prior = await device_adapter._get_prior_fcnt(session, device_id, now)
    assert prior is None


async def test_get_prior_fcnt_excludes_current_frame(
    session: AsyncSession,
) -> None:
    """Filter time < received_at: ein bereits inserted Frame mit
    time == received_at wird NICHT als prior zurueckgeliefert."""
    _room_id, device_id, _dev_eui, now = await _seed_occupied_stack_with_reading_history(
        session, prior_fcnt=4338
    )
    # Aktuelles Frame schon committed (Periodic-Pfad)
    session.add(
        SensorReading(
            time=now,
            device_id=device_id,
            fcnt=4,
            temperature=Decimal("21.0"),
        )
    )
    await session.flush()
    prior = await device_adapter._get_prior_fcnt(session, device_id, now)
    assert prior == 4338, "muss prior 4338 liefern, nicht current 4"


# ---------------------------------------------------------------------------
# handle_uplink_for_override — Reboot-Gate Integration
# ---------------------------------------------------------------------------


async def test_reboot_frame_blocks_override_sets_flag_writes_event_log(
    session: AsyncSession,
    fake_redis: _FakeRedis,
) -> None:
    """Vicki sendet nach Reboot fcnt=4 (prior=4338), Uplink-Setpoint 24.0
    (Engine sent 21.0). Erwartet: KEIN ManualOverride, Redis-Flag gesetzt,
    EventLog-Eintrag mit Layer=REBOOT_RESYNC, Reason=REBOOT_RESYNC, fcnt-
    Uebergang in details.
    """
    room_id, device_id, dev_eui, now = await _seed_occupied_stack_with_reading_history(
        session, prior_fcnt=4338
    )

    result = await device_adapter.handle_uplink_for_override(
        session,
        device_id=device_id,
        uplink_target_temp=Decimal("24.0"),
        fport=1,
        received_at=now,
        dev_eui=dev_eui,
        current_fcnt=4,
    )

    assert result is None, "Reboot-Frame darf KEINEN DEVICE-Override erzeugen"

    # Redis-Flag verifizieren
    assert f"resync_pending:{dev_eui.lower()}" in fake_redis.store

    # EventLog verifizieren
    rows = (
        (
            await session.execute(
                select(EventLog).where(
                    EventLog.room_id == room_id,
                    EventLog.layer == EventLogLayer.REBOOT_RESYNC,
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1
    entry = rows[0]
    assert entry.reason == CommandReason.REBOOT_RESYNC
    assert entry.device_id == device_id
    assert entry.setpoint_in is None
    assert entry.setpoint_out is None
    assert entry.details is not None
    assert entry.details["prior_fcnt"] == 4338
    assert entry.details["current_fcnt"] == 4
    assert entry.details["uplink_setpoint"] == "24.0"
    assert entry.details["resync_flag_set"] is True

    # Keine ManualOverride-Row angelegt
    overrides = (
        (await session.execute(select(ManualOverride).where(ManualOverride.room_id == room_id)))
        .scalars()
        .all()
    )
    assert overrides == []


async def test_drehring_with_monotone_fcnt_creates_override_unchanged(
    session: AsyncSession,
    fake_redis: _FakeRedis,
) -> None:
    """Regression: echter Drehring (fcnt monoton hoch, Setpoint != Engine)
    -> DEVICE-Override wie bisher (AE-45-Pfad unangetastet)."""
    room_id, device_id, dev_eui, now = await _seed_occupied_stack_with_reading_history(
        session, prior_fcnt=4338
    )

    result = await device_adapter.handle_uplink_for_override(
        session,
        device_id=device_id,
        uplink_target_temp=Decimal("23.0"),
        fport=1,
        received_at=now,
        dev_eui=dev_eui,
        current_fcnt=4339,  # monoton hoch
    )

    assert result is not None
    assert result.source == OverrideSource.DEVICE
    assert result.setpoint == Decimal("23.0")
    assert result.room_id == room_id

    # KEIN Re-Sync-Flag bei echtem Drehring
    assert f"resync_pending:{dev_eui.lower()}" not in fake_redis.store


async def test_legacy_call_without_fcnt_skips_reboot_gate(
    session: AsyncSession,
    fake_redis: _FakeRedis,
) -> None:
    """Backward-Compat: Aufrufer ohne ``current_fcnt`` (Tests, Legacy)
    laeuft wie bisher, Reboot-Gate aktiviert sich nicht."""
    _room_id, device_id, _dev_eui, now = await _seed_occupied_stack_with_reading_history(
        session, prior_fcnt=4338
    )

    result = await device_adapter.handle_uplink_for_override(
        session,
        device_id=device_id,
        uplink_target_temp=Decimal("23.0"),
        fport=1,
        received_at=now,
        # KEIN dev_eui / current_fcnt
    )

    assert result is not None
    assert result.setpoint == Decimal("23.0")
    # Kein Flag, kein REBOOT_RESYNC-EventLog
    assert not any(k.startswith("resync_pending:") for k in fake_redis.store)


# ---------------------------------------------------------------------------
# engine_tasks._dispatch_downlinks_per_zone — Re-Sync-Consume
# ---------------------------------------------------------------------------


async def test_dispatch_resync_flag_bypasses_hysteresis(
    session: AsyncSession,
    fake_redis: _FakeRedis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Flag gesetzt + Hysterese wuerde skippen -> forced Downlink mit
    reason=REBOOT_RESYNC, Flag danach geloescht.
    """
    room_id, device_id, dev_eui, now = await _seed_occupied_stack_with_reading_history(
        session, prior_fcnt=None
    )
    # ControlCommand vor 2 Min, same Setpoint -> Hysterese wuerde skippen
    # (no delta, age < 6h heartbeat)
    cc = (
        (await session.execute(select(ControlCommand).where(ControlCommand.device_id == device_id)))
        .scalars()
        .one()
    )
    cc.target_setpoint = Decimal("21")
    cc.issued_at = now - timedelta(minutes=2)
    cc.sent_to_gateway_at = now - timedelta(minutes=2)
    await session.flush()
    await session.commit()  # damit _dispatch_downlinks_per_zone die sieht

    # Flag setzen
    resync_flag.mark_pending(dev_eui)
    assert f"resync_pending:{dev_eui.lower()}" in fake_redis.store

    # send_setpoint mocken (kein echter MQTT-Call)
    sent: list[tuple[str, int]] = []

    async def _fake_send(target_dev_eui: str, setpoint_c: int) -> None:
        sent.append((target_dev_eui, setpoint_c))

    monkeypatch.setattr(engine_tasks, "send_setpoint", _fake_send)

    eval_id = uuid.uuid4()
    per_device, per_zone = await engine_tasks._dispatch_downlinks_per_zone(
        session=session,
        room_id=room_id,
        target_setpoint_c=21,  # same as last engine setpoint -> hysterese-skip
        base_reason=CommandReason.OCCUPIED_SETPOINT,
        eval_id=eval_id,
    )

    # Downlink wurde forciert
    assert len(sent) == 1
    assert sent[0] == (dev_eui, 21)

    # per_device sollte sent zeigen, nicht skipped
    assert len(per_device) == 1
    assert per_device[0]["status"] == "sent"
    assert "reboot_resync" in per_device[0]["hysteresis_reason"]

    # Flag wurde konsumiert
    assert f"resync_pending:{dev_eui.lower()}" not in fake_redis.store

    # ControlCommand mit reason=REBOOT_RESYNC angelegt
    rows = (
        (
            await session.execute(
                select(ControlCommand).where(
                    ControlCommand.device_id == device_id,
                    ControlCommand.reason == CommandReason.REBOOT_RESYNC,
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].sent_to_gateway_at is not None


async def test_dispatch_no_flag_normal_hysteresis_skip(
    session: AsyncSession,
    fake_redis: _FakeRedis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Kein Flag + Hysterese skippt -> kein Downlink, Verhalten unveraendert."""
    room_id, device_id, _dev_eui, now = await _seed_occupied_stack_with_reading_history(
        session, prior_fcnt=None
    )
    cc = (
        (await session.execute(select(ControlCommand).where(ControlCommand.device_id == device_id)))
        .scalars()
        .one()
    )
    cc.target_setpoint = Decimal("21")
    cc.issued_at = now - timedelta(minutes=2)
    cc.sent_to_gateway_at = now - timedelta(minutes=2)
    await session.flush()
    await session.commit()

    sent: list[tuple[str, int]] = []

    async def _fake_send(target_dev_eui: str, setpoint_c: int) -> None:
        sent.append((target_dev_eui, setpoint_c))

    monkeypatch.setattr(engine_tasks, "send_setpoint", _fake_send)

    eval_id = uuid.uuid4()
    per_device, _per_zone = await engine_tasks._dispatch_downlinks_per_zone(
        session=session,
        room_id=room_id,
        target_setpoint_c=21,
        base_reason=CommandReason.OCCUPIED_SETPOINT,
        eval_id=eval_id,
    )

    assert sent == []
    assert len(per_device) == 1
    assert per_device[0]["status"] == "skipped_hysteresis"


async def test_dispatch_flag_consumed_on_normal_send(
    session: AsyncSession,
    fake_redis: _FakeRedis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Flag gesetzt + Hysterese sendet ohnehin (Delta) -> normaler Send
    mit ``reason=base_reason``, Flag wird trotzdem konsumiert (cleanup).
    """
    room_id, device_id, dev_eui, now = await _seed_occupied_stack_with_reading_history(
        session, prior_fcnt=None
    )
    cc = (
        (await session.execute(select(ControlCommand).where(ControlCommand.device_id == device_id)))
        .scalars()
        .one()
    )
    cc.target_setpoint = Decimal("19")  # alt 19, neu 21 -> Delta 2 >= 1
    cc.issued_at = now - timedelta(minutes=2)
    cc.sent_to_gateway_at = now - timedelta(minutes=2)
    await session.flush()
    await session.commit()

    resync_flag.mark_pending(dev_eui)

    sent: list[tuple[str, int]] = []

    async def _fake_send(target_dev_eui: str, setpoint_c: int) -> None:
        sent.append((target_dev_eui, setpoint_c))

    monkeypatch.setattr(engine_tasks, "send_setpoint", _fake_send)

    eval_id = uuid.uuid4()
    per_device, _per_zone = await engine_tasks._dispatch_downlinks_per_zone(
        session=session,
        room_id=room_id,
        target_setpoint_c=21,
        base_reason=CommandReason.OCCUPIED_SETPOINT,
        eval_id=eval_id,
    )

    assert sent == [(dev_eui, 21)]
    # Reason bleibt base_reason, NICHT REBOOT_RESYNC (Hysterese sendet
    # ohnehin, kein Bypass noetig)
    rows = (
        (
            await session.execute(
                select(ControlCommand)
                .where(ControlCommand.device_id == device_id)
                .where(ControlCommand.reason == CommandReason.OCCUPIED_SETPOINT)
                .where(ControlCommand.target_setpoint == Decimal("21"))
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1

    # Flag wurde konsumiert
    assert f"resync_pending:{dev_eui.lower()}" not in fake_redis.store
