"""Tests fuer services/device_service.py (Sprint 13b.1 T3 + T5, AE-57).

Lifecycle-Lese-Helper (T3):
- get_active_devices_for_zone: Happy, leer, retired-Filter
- get_pool_devices: Happy, leer, retired-Filter

Tausch-Service (T5):
- replace_device: Happy, Race, Self-Swap, old-retired, old-no-zone,
  new-not-in-pool, old-not-found, new-not-found, audit-row-verify
- retire_device: Happy, already-retired, not-found, audit-row-verify

DB-Tests skippen ohne TEST_DATABASE_URL. uuid-Suffix fuer Test-
Eindeutigkeit (§5.18, §5.59).
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from heizung.models.device import Device
from heizung.models.enums import DeviceKind, DeviceVendor, HeatingZoneKind
from heizung.models.heating_zone import HeatingZone
from heizung.models.room import Room
from heizung.models.room_type import RoomType
from heizung.services.device_service import (
    get_active_devices_for_zone,
    get_pool_devices,
)

TEST_DB_URL = os.environ.get("TEST_DATABASE_URL")
SKIP_REASON = "TEST_DATABASE_URL nicht gesetzt - DB-Tests brauchen Postgres"


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


async def _make_zone(session: AsyncSession) -> int:
    """Test-Helper: RoomType + Room + HeatingZone, gibt zone.id zurueck."""
    suffix = uuid.uuid4().hex[:8]
    rt = RoomType(name=f"ds-rt-{suffix}")
    session.add(rt)
    await session.flush()
    room = Room(number=f"ds-{suffix}", room_type_id=rt.id)
    session.add(room)
    await session.flush()
    zone = HeatingZone(
        room_id=room.id,
        kind=HeatingZoneKind.BEDROOM,
        name=f"z-{suffix}",
    )
    session.add(zone)
    await session.flush()
    assert zone.id is not None
    return zone.id


def _make_device(
    *,
    zone_id: int | None,
    suffix: str | None = None,
    retired: bool = False,
) -> Device:
    """Test-Helper: Device-Konstruktion mit explizitem Lifecycle-State."""
    if suffix is None:
        suffix = uuid.uuid4().hex[:8]
    device = Device(
        dev_eui=f"deadbeef{suffix}",
        kind=DeviceKind.THERMOSTAT,
        vendor=DeviceVendor.MCLIMATE,
        model="vicki",
        heating_zone_id=zone_id,
        health_state="healthy",
    )
    if retired:
        device.retired_at = datetime.now(tz=UTC)
        device.retired_reason = "test_fixture"
    return device


@pytest.mark.skipif(not TEST_DB_URL, reason=SKIP_REASON)
async def test_get_active_devices_for_zone_happy(db_session: AsyncSession) -> None:
    """Zone mit zwei aktiven Devices -> beide werden gefunden."""
    zone_id = await _make_zone(db_session)
    dev_a = _make_device(zone_id=zone_id)
    dev_b = _make_device(zone_id=zone_id)
    db_session.add_all([dev_a, dev_b])
    await db_session.flush()

    result = await get_active_devices_for_zone(db_session, zone_id)

    assert len(result) == 2
    assert {d.id for d in result} == {dev_a.id, dev_b.id}


@pytest.mark.skipif(not TEST_DB_URL, reason=SKIP_REASON)
async def test_get_active_devices_for_zone_empty(db_session: AsyncSession) -> None:
    """Zone ohne Devices -> leere Liste, kein Error."""
    zone_id = await _make_zone(db_session)

    result = await get_active_devices_for_zone(db_session, zone_id)

    assert result == []


@pytest.mark.skipif(not TEST_DB_URL, reason=SKIP_REASON)
async def test_get_active_devices_for_zone_ignores_retired(
    db_session: AsyncSession,
) -> None:
    """Zone mit 1 aktivem + 1 retired Device -> nur aktives im Result."""
    zone_id = await _make_zone(db_session)
    active = _make_device(zone_id=zone_id)
    retired = _make_device(zone_id=zone_id, retired=True)
    db_session.add_all([active, retired])
    await db_session.flush()

    result = await get_active_devices_for_zone(db_session, zone_id)

    assert len(result) == 1, (
        f"erwarte 1 aktives Device, gefunden {len(result)} (retired-Filter greift nicht?)"
    )
    assert result[0].id == active.id
    assert result[0].retired_at is None


@pytest.mark.skipif(not TEST_DB_URL, reason=SKIP_REASON)
async def test_get_pool_devices_happy(db_session: AsyncSession) -> None:
    """Zwei Pool-Devices (heating_zone_id=NULL) -> beide werden gefunden."""
    pool_a = _make_device(zone_id=None)
    pool_b = _make_device(zone_id=None)
    db_session.add_all([pool_a, pool_b])
    await db_session.flush()

    result = await get_pool_devices(db_session)

    pool_ids = {d.id for d in result}
    assert pool_a.id in pool_ids
    assert pool_b.id in pool_ids


@pytest.mark.skipif(not TEST_DB_URL, reason=SKIP_REASON)
async def test_get_pool_devices_empty(db_session: AsyncSession) -> None:
    """Keine Pool-Devices in der Session -> leere Liste oder bestehende
    Pool-Devices nicht im Result.

    Hinweis: Test-DB kann Pool-Devices aus anderen Tests enthalten;
    Assertion ist conservativ: gerade angelegtes Active-Device darf
    NICHT in get_pool_devices() auftauchen.
    """
    zone_id = await _make_zone(db_session)
    active = _make_device(zone_id=zone_id)
    db_session.add(active)
    await db_session.flush()

    result = await get_pool_devices(db_session)

    active_ids = {d.id for d in result}
    assert active.id not in active_ids, (
        f"aktives Device mit heating_zone_id={zone_id} darf NICHT in "
        f"Pool sein (heating_zone_id-Filter greift nicht?)"
    )


@pytest.mark.skipif(not TEST_DB_URL, reason=SKIP_REASON)
async def test_get_pool_devices_ignores_retired_pool(
    db_session: AsyncSession,
) -> None:
    """Retired Pool-Device (heating_zone_id=NULL, retired_at=NOW) -> NICHT im Result."""
    active_pool = _make_device(zone_id=None)
    retired_pool = _make_device(zone_id=None, retired=True)
    db_session.add_all([active_pool, retired_pool])
    await db_session.flush()

    result = await get_pool_devices(db_session)

    pool_ids = {d.id for d in result}
    assert active_pool.id in pool_ids
    assert retired_pool.id not in pool_ids, (
        f"retired Pool-Device {retired_pool.id} darf NICHT im Result sein "
        f"(retired-Filter greift nicht?)"
    )


# ---------------------------------------------------------------------------
# T5: replace_device + retire_device
# ---------------------------------------------------------------------------


async def _make_zone(session: AsyncSession) -> int:
    """T5-Helper: RoomType + Room + Zone -> zone_id. Cleanup-Tracking
    ueber globale Liste ``_T5_CREATED_IDS`` fuer den Race-Test.
    """
    suffix = uuid.uuid4().hex[:8]
    rt = RoomType(name=f"t5-rt-{suffix}")
    session.add(rt)
    await session.flush()
    room = Room(number=f"t5-{suffix}", room_type_id=rt.id)
    session.add(room)
    await session.flush()
    zone = HeatingZone(
        room_id=room.id,
        kind=HeatingZoneKind.BEDROOM,
        name=f"z-{suffix}",
    )
    session.add(zone)
    await session.flush()
    assert zone.id is not None
    _T5_CREATED_IDS["rt"].append(rt.id)
    _T5_CREATED_IDS["room"].append(room.id)
    _T5_CREATED_IDS["zone"].append(zone.id)
    return zone.id


# Pro-Test-Tracking fuer Race-Test-Cleanup. Da Race-Test commited, koennen
# wir nicht auf db_session-Rollback verlassen.
_T5_CREATED_IDS: dict[str, list[int]] = {"rt": [], "room": [], "zone": []}


async def _fetch_audit_row(
    session: AsyncSession, *, action: str, target_id: int
) -> dict[str, object]:
    """Helper: laed die juengste BusinessAudit-Row fuer action+target_id."""
    from sqlalchemy import desc
    from sqlalchemy import select as sa_select

    from heizung.models.business_audit import BusinessAudit

    stmt = (
        sa_select(BusinessAudit)
        .where(BusinessAudit.action == action)
        .where(BusinessAudit.target_id == target_id)
        .order_by(desc(BusinessAudit.id))
        .limit(1)
    )
    row = (await session.execute(stmt)).scalar_one()
    return {
        "action": row.action,
        "target_type": row.target_type,
        "target_id": row.target_id,
        "user_id": row.user_id,
        "old_value": row.old_value,
        "new_value": row.new_value,
    }


@pytest.mark.skipif(not TEST_DB_URL, reason=SKIP_REASON)
async def test_replace_device_happy(db_session: AsyncSession) -> None:
    """Happy-Path: alter Vicki in Zone, neuer Vicki im Pool, atomarer Tausch."""
    from heizung.services.device_service import replace_device

    zone_id = await _make_zone(db_session)
    old = _make_device(zone_id=zone_id)
    new = _make_device(zone_id=None)
    db_session.add_all([old, new])
    await db_session.flush()

    result = await replace_device(
        db_session,
        old_device_id=old.id,
        new_pool_device_id=new.id,
        user_id=None,
    )

    # Return: das retired old-Device.
    assert result.id == old.id
    assert result.retired_at is not None
    assert result.retired_reason == "replaced_by_pool"
    assert result.replaced_by_device_id == new.id
    assert result.heating_zone_id is None

    # New device sitzt nun in der Zone.
    await db_session.refresh(new)
    assert new.heating_zone_id == zone_id
    assert new.retired_at is None


@pytest.mark.skipif(not TEST_DB_URL, reason=SKIP_REASON)
async def test_replace_device_writes_audit(db_session: AsyncSession) -> None:
    """BusinessAudit DEVICE_REPLACED: target_id=old, new_value mit
    new_device_id + heating_zone_id + replaced_at_iso."""
    from heizung.services.device_service import replace_device

    zone_id = await _make_zone(db_session)
    old = _make_device(zone_id=zone_id)
    new = _make_device(zone_id=None)
    db_session.add_all([old, new])
    await db_session.flush()

    await replace_device(
        db_session,
        old_device_id=old.id,
        new_pool_device_id=new.id,
        user_id=None,
    )

    audit = await _fetch_audit_row(db_session, action="DEVICE_REPLACED", target_id=old.id)
    assert audit["target_type"] == "device"
    assert audit["target_id"] == old.id
    # FK auf user verlangt echten User; Tests nutzen System-Trigger-
    # Pattern (user_id=None erlaubt). Audit-Inhalt-Check unten.
    assert audit["user_id"] is None
    nv = audit["new_value"]
    assert isinstance(nv, dict)
    assert nv["new_device_id"] == new.id
    assert nv["heating_zone_id"] == zone_id
    assert "replaced_at_iso" in nv


@pytest.mark.skipif(not TEST_DB_URL, reason=SKIP_REASON)
async def test_replace_device_self_swap_raises(db_session: AsyncSession) -> None:
    """old_id == new_id -> SelfReplacementError vor DB-Touch.

    B-Sprint13b2-4 (AE-59): vor T1 warf der Service einen
    inline-``ValueError``; ab T1 ist es eine eigene
    ``SelfReplacementError(LifecycleError)``-Subklasse mit
    ``error_code = "SELF_REPLACEMENT_FORBIDDEN"``. Da LifecycleError
    direkt von Exception erbt (NICHT mehr ValueError-Subklasse),
    musste der Test von ``pytest.raises(ValueError, ...)`` auf
    ``pytest.raises(SelfReplacementError, ...)`` umgestellt werden.
    """
    from heizung.services.device_service import replace_device
    from heizung.services.exceptions import SelfReplacementError

    zone_id = await _make_zone(db_session)
    dev = _make_device(zone_id=zone_id)
    db_session.add(dev)
    await db_session.flush()

    with pytest.raises(SelfReplacementError, match="Selbst-Tausch"):
        await replace_device(
            db_session,
            old_device_id=dev.id,
            new_pool_device_id=dev.id,
        )


@pytest.mark.skipif(not TEST_DB_URL, reason=SKIP_REASON)
async def test_replace_device_old_already_retired(db_session: AsyncSession) -> None:
    """old.retired_at gesetzt -> DeviceStateError."""
    from heizung.services.device_service import DeviceStateError, replace_device

    zone_id = await _make_zone(db_session)
    old = _make_device(zone_id=zone_id, retired=True)
    new = _make_device(zone_id=None)
    db_session.add_all([old, new])
    await db_session.flush()

    with pytest.raises(DeviceStateError, match="bereits retired"):
        await replace_device(
            db_session,
            old_device_id=old.id,
            new_pool_device_id=new.id,
        )


@pytest.mark.skipif(not TEST_DB_URL, reason=SKIP_REASON)
async def test_replace_device_old_no_zone(db_session: AsyncSession) -> None:
    """old.heating_zone_id IS NULL (Pool-Device) -> DeviceStateError."""
    from heizung.services.device_service import DeviceStateError, replace_device

    old_pool = _make_device(zone_id=None)
    new_pool = _make_device(zone_id=None)
    db_session.add_all([old_pool, new_pool])
    await db_session.flush()

    with pytest.raises(DeviceStateError, match="nicht zugewiesen"):
        await replace_device(
            db_session,
            old_device_id=old_pool.id,
            new_pool_device_id=new_pool.id,
        )


@pytest.mark.skipif(not TEST_DB_URL, reason=SKIP_REASON)
async def test_replace_device_new_not_in_pool(db_session: AsyncSession) -> None:
    """new.heating_zone_id IS NOT NULL (schon zugewiesen) -> PoolDeviceUnavailable."""
    from heizung.services.device_service import (
        PoolDeviceUnavailable,
        replace_device,
    )

    zone_id_a = await _make_zone(db_session)
    zone_id_b = await _make_zone(db_session)
    old = _make_device(zone_id=zone_id_a)
    new_busy = _make_device(zone_id=zone_id_b)  # nicht im Pool
    db_session.add_all([old, new_busy])
    await db_session.flush()

    with pytest.raises(PoolDeviceUnavailable, match="nicht im Pool"):
        await replace_device(
            db_session,
            old_device_id=old.id,
            new_pool_device_id=new_busy.id,
        )


@pytest.mark.skipif(not TEST_DB_URL, reason=SKIP_REASON)
async def test_replace_device_old_not_found(db_session: AsyncSession) -> None:
    """Unbekannte old_id -> DeviceNotFound."""
    from heizung.services.device_service import DeviceNotFound, replace_device

    new = _make_device(zone_id=None)
    db_session.add(new)
    await db_session.flush()

    with pytest.raises(DeviceNotFound, match="old_device_id"):
        await replace_device(
            db_session,
            old_device_id=999_999_999,
            new_pool_device_id=new.id,
        )


@pytest.mark.skipif(not TEST_DB_URL, reason=SKIP_REASON)
async def test_replace_device_new_not_found(db_session: AsyncSession) -> None:
    """Unbekannte new_id -> DeviceNotFound."""
    from heizung.services.device_service import DeviceNotFound, replace_device

    zone_id = await _make_zone(db_session)
    old = _make_device(zone_id=zone_id)
    db_session.add(old)
    await db_session.flush()

    with pytest.raises(DeviceNotFound, match="new_pool_device_id"):
        await replace_device(
            db_session,
            old_device_id=old.id,
            new_pool_device_id=999_999_999,
        )


@pytest.mark.skipif(not TEST_DB_URL, reason=SKIP_REASON)
async def test_replace_device_race_two_sessions(
    db_session: AsyncSession,
) -> None:
    """Race-Test: zwei Sessions racing auf denselben Pool-Vicki.
    Eine gewinnt mit Success, die andere bekommt PoolDeviceUnavailable
    (race-safe UPDATE-Rowcount-Check, nicht nur Pre-Gate-Read).

    Setup: 2 zugewiesene Old-Devices + 1 Pool-Device. Beide replace_device
    targeten denselben Pool-Vicki. asyncio.gather schedule beide auf zwei
    eigene Sessions (eigene Connections -> echte DB-Race).
    """
    from heizung.services.device_service import (
        PoolDeviceUnavailable,
        replace_device,
    )

    # Setup in db_session committen, damit beide Race-Sessions die Rows
    # an der DB sehen koennen (rollback macht Setup im Race-Sessions
    # unsichtbar).
    zone_id_a = await _make_zone(db_session)
    zone_id_b = await _make_zone(db_session)
    old_a = _make_device(zone_id=zone_id_a)
    old_b = _make_device(zone_id=zone_id_b)
    pool = _make_device(zone_id=None)
    db_session.add_all([old_a, old_b, pool])
    await db_session.flush()
    await db_session.commit()

    captured_ids = (old_a.id, old_b.id, pool.id)

    # Zwei eigene Sessions/Connections -> echte DB-Race.
    engine = create_async_engine(TEST_DB_URL)
    sm = async_sessionmaker(engine, expire_on_commit=False)

    import asyncio

    async def _do_replace(old_id: int) -> tuple[str, object]:
        async with sm() as s:
            try:
                await replace_device(
                    s,
                    old_device_id=old_id,
                    new_pool_device_id=captured_ids[2],
                )
                await s.commit()
                return ("ok", old_id)
            except PoolDeviceUnavailable as exc:
                await s.rollback()
                return ("unavailable", str(exc))

    try:
        results = await asyncio.gather(
            _do_replace(captured_ids[0]),
            _do_replace(captured_ids[1]),
        )
    finally:
        # Cleanup: alle Test-Rows in FK-sicherer Reihenfolge entfernen,
        # damit Folge-Tests nicht von committed Setup-Rows verschmutzt
        # werden. Reihenfolge: business_audit -> device -> heating_zone
        # -> room -> room_type.
        async with sm() as cleanup:
            from sqlalchemy import delete as sa_delete

            from heizung.models.business_audit import BusinessAudit
            from heizung.models.heating_zone import HeatingZone as Hz
            from heizung.models.room import Room as Rm
            from heizung.models.room_type import RoomType as Rt

            await cleanup.execute(
                sa_delete(BusinessAudit).where(BusinessAudit.target_id.in_(captured_ids))
            )
            await cleanup.execute(sa_delete(Device).where(Device.id.in_(captured_ids)))
            await cleanup.execute(sa_delete(Hz).where(Hz.id.in_(_T5_CREATED_IDS["zone"])))
            await cleanup.execute(sa_delete(Rm).where(Rm.id.in_(_T5_CREATED_IDS["room"])))
            await cleanup.execute(sa_delete(Rt).where(Rt.id.in_(_T5_CREATED_IDS["rt"])))
            await cleanup.commit()
        await engine.dispose()
        # Tracking-List zuruecksetzen fuer Folge-Tests.
        _T5_CREATED_IDS["rt"].clear()
        _T5_CREATED_IDS["room"].clear()
        _T5_CREATED_IDS["zone"].clear()

    statuses = sorted(r[0] for r in results)
    assert statuses == ["ok", "unavailable"], (
        f"Race-Outcome muss genau 1 ok + 1 unavailable sein, war {statuses!r}"
    )


@pytest.mark.skipif(not TEST_DB_URL, reason=SKIP_REASON)
async def test_retire_device_happy(db_session: AsyncSession) -> None:
    """Happy-Path: aktives Device retiren mit reason."""
    from heizung.services.device_service import retire_device

    zone_id = await _make_zone(db_session)
    dev = _make_device(zone_id=zone_id)
    db_session.add(dev)
    await db_session.flush()

    result = await retire_device(
        db_session,
        device_id=dev.id,
        reason="battery_dead",
        user_id=None,
    )

    assert result.retired_at is not None
    assert result.retired_reason == "battery_dead"
    # heating_zone_id BLEIBT (Historie-Anker).
    assert result.heating_zone_id == zone_id


@pytest.mark.skipif(not TEST_DB_URL, reason=SKIP_REASON)
async def test_retire_device_writes_audit(db_session: AsyncSession) -> None:
    """BusinessAudit DEVICE_RETIRED: target_id=device, new_value mit reason."""
    from heizung.services.device_service import retire_device

    zone_id = await _make_zone(db_session)
    dev = _make_device(zone_id=zone_id)
    db_session.add(dev)
    await db_session.flush()

    await retire_device(
        db_session,
        device_id=dev.id,
        reason="hardware_swap",
        user_id=None,
    )

    audit = await _fetch_audit_row(db_session, action="DEVICE_RETIRED", target_id=dev.id)
    assert audit["target_type"] == "device"
    assert audit["target_id"] == dev.id
    assert audit["user_id"] is None
    nv = audit["new_value"]
    assert isinstance(nv, dict)
    assert nv["reason"] == "hardware_swap"
    assert "retired_at_iso" in nv


@pytest.mark.skipif(not TEST_DB_URL, reason=SKIP_REASON)
async def test_retire_device_already_retired(db_session: AsyncSession) -> None:
    """device bereits retired -> DeviceStateError."""
    from heizung.services.device_service import DeviceStateError, retire_device

    zone_id = await _make_zone(db_session)
    dev = _make_device(zone_id=zone_id, retired=True)
    db_session.add(dev)
    await db_session.flush()

    with pytest.raises(DeviceStateError, match="bereits retired"):
        await retire_device(
            db_session,
            device_id=dev.id,
            reason="duplicate",
        )


@pytest.mark.skipif(not TEST_DB_URL, reason=SKIP_REASON)
async def test_retire_device_not_found(db_session: AsyncSession) -> None:
    """Unbekannte device_id -> DeviceNotFound."""
    from heizung.services.device_service import DeviceNotFound, retire_device

    with pytest.raises(DeviceNotFound, match="device_id"):
        await retire_device(
            db_session,
            device_id=999_999_999,
            reason="ghost",
        )
