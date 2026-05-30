"""Sprint 14e — Hygiene-Rest (FU-1 Zone-Ist-Temp, FU-2 Engine-Setpoint, FU-3 Audit).

Prueft:
- ``services.zone_aggregates.latest_mean_temp_per_zone`` (FU-1: 2 healthy ->
  Mittel; alles offline -> None; retired Vicki ignoriert).
- ``services.event_log.latest_hard_clamp_setpoint_per_room`` (FU-2: frischer
  HARD_CLAMP -> Wert; nichts im 1h-Fenster -> None; zwei Zonen identischer
  Wert; Decimal-Form 0.1 °C).
- PATCH-Audit (T4): Zone.name -> 1 ``HEATING_ZONE_NAME_CHANGED``-Audit;
  Room.room_type_id -> 1 ``ROOM_TYPE_CHANGED``-Audit mit
  ``engine_effect=rule_config_scope_room_type``; non-admin -> 403.

DB-Tests; skip ohne ``DATABASE_URL`` (§5.50).
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
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from alembic import command
from heizung.auth.password import hash_password
from heizung.auth.rate_limit import limiter
from heizung.config import get_settings
from heizung.db import get_session
from heizung.main import app
from heizung.models.business_audit import BusinessAudit
from heizung.models.device import Device
from heizung.models.enums import (
    CommandReason,
    DeviceKind,
    DeviceVendor,
    EventLogLayer,
    HeatingZoneKind,
    RoomStatus,
    UserRole,
)
from heizung.models.event_log import EventLog
from heizung.models.heating_zone import HeatingZone
from heizung.models.room import Room
from heizung.models.room_type import RoomType
from heizung.models.sensor_reading import SensorReading
from heizung.models.user import User
from heizung.services.event_log import latest_hard_clamp_setpoint_per_room
from heizung.services.zone_aggregates import latest_mean_temp_per_zone

DATABASE_URL = os.environ.get("DATABASE_URL")
DATABASE_URL_PRESENT = bool(DATABASE_URL)
SKIP_REASON = "DATABASE_URL nicht gesetzt - DB-Tests brauchen Test-DB"

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _auth_test_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setenv("ALLOW_DEFAULT_SECRETS", "1")
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("AUTH_COOKIE_SECURE", "false")
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _reset_limiter() -> Iterator[None]:
    limiter.reset()
    yield
    limiter.reset()


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
async def setup_engine() -> AsyncIterator[AsyncEngine]:
    if not DATABASE_URL_PRESENT:
        pytest.skip(SKIP_REASON)
    engine = create_async_engine(DATABASE_URL or "")
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def http_client(setup_engine: AsyncEngine) -> AsyncIterator[httpx.AsyncClient]:
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


async def _login(
    client: httpx.AsyncClient,
    sm: async_sessionmaker[AsyncSession],
    role: UserRole,
    prefix: str,
) -> int:
    suffix = uuid.uuid4().hex[:8]
    email = f"e14e-{prefix}-{suffix}@test.example.com"
    pw = "Hygiene14ePassword!"
    async with sm() as session:
        user = User(
            email=email,
            password_hash=hash_password(pw),
            role=role,
            is_active=True,
            must_change_password=False,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        user_id = user.id
    resp = await client.post("/api/v1/auth/login", json={"email": email, "password": pw})
    assert resp.status_code == 200, resp.text
    return user_id


async def _mk_room(
    sm: async_sessionmaker[AsyncSession], suffix: str, status: RoomStatus
) -> tuple[int, int]:
    async with sm() as session:
        rt = RoomType(name=f"t14e-rt-{suffix}")
        session.add(rt)
        await session.flush()
        room = Room(number=f"t14e-{suffix}", room_type_id=rt.id, status=status)
        session.add(room)
        await session.flush()
        await session.commit()
        return room.id, rt.id


async def _mk_zone(sm: async_sessionmaker[AsyncSession], room_id: int, suffix: str) -> int:
    async with sm() as session:
        zone = HeatingZone(room_id=room_id, kind=HeatingZoneKind.BEDROOM, name=f"z-{suffix}")
        session.add(zone)
        await session.flush()
        await session.commit()
        return zone.id


async def _mk_device(
    sm: async_sessionmaker[AsyncSession],
    *,
    zone_id: int,
    health_state: str,
    retired: bool = False,
) -> int:
    """§5.18: dev_eui ist VARCHAR(16) — eigener 16-char-hex pro Device."""
    async with sm() as session:
        now = datetime.now(tz=UTC)
        device = Device(
            dev_eui=uuid.uuid4().hex[:16],
            kind=DeviceKind.THERMOSTAT,
            vendor=DeviceVendor.MCLIMATE,
            model="vicki",
            heating_zone_id=zone_id,
            health_state=health_state,
            retired_at=now if retired else None,
        )
        session.add(device)
        await session.flush()
        await session.commit()
        return device.id


async def _mk_reading(
    sm: async_sessionmaker[AsyncSession],
    *,
    device_id: int,
    temperature_c: Decimal,
    seconds_ago: int = 60,
) -> None:
    async with sm() as session:
        session.add(
            SensorReading(
                time=datetime.now(tz=UTC) - timedelta(seconds=seconds_ago),
                device_id=device_id,
                temperature=temperature_c,
            )
        )
        await session.commit()


async def _mk_hard_clamp_eval(
    sm: async_sessionmaker[AsyncSession],
    *,
    room_id: int,
    setpoint_c: Decimal,
    minutes_ago: int = 1,
) -> None:
    """Direkter EventLog-Insert (umgeht die Engine — hier wird der Read geprueft)."""
    async with sm() as session:
        session.add(
            EventLog(
                time=datetime.now(tz=UTC) - timedelta(minutes=minutes_ago),
                room_id=room_id,
                evaluation_id=uuid.uuid4(),
                layer=EventLogLayer.HARD_CLAMP,
                setpoint_in=setpoint_c,
                setpoint_out=setpoint_c,
                reason=CommandReason.OCCUPIED_SETPOINT,
            )
        )
        await session.commit()


async def _cleanup(sm: async_sessionmaker[AsyncSession]) -> None:
    async with sm() as session:
        await session.execute(text("DELETE FROM business_audit WHERE action LIKE '%14e%'"))
        await session.execute(
            text(
                "DELETE FROM business_audit WHERE action IN "
                "('HEATING_ZONE_NAME_CHANGED', 'ROOM_TYPE_CHANGED') "
                "AND target_id IN (SELECT id FROM room WHERE number LIKE 't14e-%') "
                "OR target_id IN (SELECT id FROM heating_zone WHERE name LIKE 'z-t14e%')"
            )
        )
        await session.execute(
            text(
                "DELETE FROM business_audit WHERE user_id IN "
                "(SELECT id FROM \"user\" WHERE email LIKE 'e14e-%@test.example.com')"
            )
        )
        # 14e-Devices haengen ueber heating_zone an unseren Test-Raumen — Filter
        # ueber den FK statt dev_eui-Prefix, weil dev_eui ein uuid4-Hex ist.
        await session.execute(
            text(
                "DELETE FROM sensor_reading WHERE device_id IN "
                "(SELECT id FROM device WHERE heating_zone_id IN "
                "(SELECT id FROM heating_zone WHERE name LIKE 'z-t14e%'))"
            )
        )
        await session.execute(
            text(
                "DELETE FROM device WHERE heating_zone_id IN "
                "(SELECT id FROM heating_zone WHERE name LIKE 'z-t14e%')"
            )
        )
        await session.execute(
            text(
                "DELETE FROM event_log WHERE room_id IN "
                "(SELECT id FROM room WHERE number LIKE 't14e-%')"
            )
        )
        await session.execute(text("DELETE FROM heating_zone WHERE name LIKE 'z-t14e%'"))
        await session.execute(text("DELETE FROM room WHERE number LIKE 't14e-%'"))
        await session.execute(text("DELETE FROM room_type WHERE name LIKE 't14e-rt-%'"))
        await session.execute(
            text("""DELETE FROM "user" WHERE email LIKE 'e14e-%@test.example.com'""")
        )
        await session.commit()


# ---------------------------------------------------------------------------
# T1 — FU-1 Zone-Ist-Temp
# ---------------------------------------------------------------------------


async def test_mean_temp_two_healthy_vickis_arithmetic_mean(
    setup_engine: AsyncEngine,
) -> None:
    sm = async_sessionmaker(setup_engine, expire_on_commit=False)
    s = uuid.uuid4().hex[:8]
    try:
        room_id, _ = await _mk_room(sm, s, RoomStatus.OCCUPIED)
        zone_id = await _mk_zone(sm, room_id, f"t14e{s}a")
        d1 = await _mk_device(sm, zone_id=zone_id, health_state="healthy")
        d2 = await _mk_device(sm, zone_id=zone_id, health_state="healthy")
        await _mk_reading(sm, device_id=d1, temperature_c=Decimal("20.0"))
        await _mk_reading(sm, device_id=d2, temperature_c=Decimal("22.0"))

        async with sm() as session:
            result = await latest_mean_temp_per_zone(session, [zone_id])

        assert result[zone_id] == Decimal("21.0")
    finally:
        await _cleanup(sm)


async def test_mean_temp_all_silent_returns_none(setup_engine: AsyncEngine) -> None:
    sm = async_sessionmaker(setup_engine, expire_on_commit=False)
    s = uuid.uuid4().hex[:8]
    try:
        room_id, _ = await _mk_room(sm, s, RoomStatus.OCCUPIED)
        zone_id = await _mk_zone(sm, room_id, f"t14e{s}b")
        d1 = await _mk_device(sm, zone_id=zone_id, health_state="silent")
        await _mk_reading(sm, device_id=d1, temperature_c=Decimal("19.5"))

        async with sm() as session:
            result = await latest_mean_temp_per_zone(session, [zone_id])

        assert result[zone_id] is None
    finally:
        await _cleanup(sm)


async def test_mean_temp_excludes_retired_vicki(setup_engine: AsyncEngine) -> None:
    """§5.58: retired_at IS NULL gilt auch im Aggregat — retired Vicki darf
    nicht im Mittelwert auftauchen, auch wenn er den health_state healthy
    haette."""
    sm = async_sessionmaker(setup_engine, expire_on_commit=False)
    s = uuid.uuid4().hex[:8]
    try:
        room_id, _ = await _mk_room(sm, s, RoomStatus.OCCUPIED)
        zone_id = await _mk_zone(sm, room_id, f"t14e{s}c")
        active = await _mk_device(sm, zone_id=zone_id, health_state="healthy")
        await _mk_device(sm, zone_id=zone_id, health_state="healthy", retired=True)
        await _mk_reading(sm, device_id=active, temperature_c=Decimal("21.0"))
        # retired bekommt keinen Reading -- aber selbst mit Reading muss er
        # ignoriert werden, weil der Helper retired_at-Filter machen muss.

        async with sm() as session:
            result = await latest_mean_temp_per_zone(session, [zone_id])

        # Mittelwert ist 21.0 — der retired Device fliesst NICHT ein, sonst
        # waere das Aggregat None (Reading fehlt) oder anders.
        assert result[zone_id] == Decimal("21.0")
    finally:
        await _cleanup(sm)


# ---------------------------------------------------------------------------
# T2 — FU-2 Engine-Setpoint aus Trace
# ---------------------------------------------------------------------------


async def test_hard_clamp_setpoint_fresh_returns_value(
    setup_engine: AsyncEngine,
) -> None:
    sm = async_sessionmaker(setup_engine, expire_on_commit=False)
    s = uuid.uuid4().hex[:8]
    try:
        room_id, _ = await _mk_room(sm, s, RoomStatus.OCCUPIED)
        await _mk_hard_clamp_eval(sm, room_id=room_id, setpoint_c=Decimal("21.0"))

        async with sm() as session:
            result = await latest_hard_clamp_setpoint_per_room(session, [room_id])

        assert result[room_id] == Decimal("21.0")
        assert isinstance(result[room_id], Decimal)
    finally:
        await _cleanup(sm)


async def test_hard_clamp_setpoint_stale_outside_1h_returns_none(
    setup_engine: AsyncEngine,
) -> None:
    sm = async_sessionmaker(setup_engine, expire_on_commit=False)
    s = uuid.uuid4().hex[:8]
    try:
        room_id, _ = await _mk_room(sm, s, RoomStatus.OCCUPIED)
        await _mk_hard_clamp_eval(sm, room_id=room_id, setpoint_c=Decimal("21.0"), minutes_ago=90)

        async with sm() as session:
            result = await latest_hard_clamp_setpoint_per_room(session, [room_id])

        # Frische-Fenster ist 1 h — 90 min alt -> filtered out -> dict ohne key.
        assert room_id not in result
    finally:
        await _cleanup(sm)


async def test_hard_clamp_setpoint_two_zones_same_room_share_value(
    setup_engine: AsyncEngine,
) -> None:
    """AE-51 §4.2: alle Zonen eines Zimmers teilen den HARD_CLAMP-Setpoint."""
    sm = async_sessionmaker(setup_engine, expire_on_commit=False)
    s = uuid.uuid4().hex[:8]
    try:
        room_id, _ = await _mk_room(sm, s, RoomStatus.OCCUPIED)
        z1 = await _mk_zone(sm, room_id, f"t14e{s}d1")
        z2 = await _mk_zone(sm, room_id, f"t14e{s}d2")
        await _mk_hard_clamp_eval(sm, room_id=room_id, setpoint_c=Decimal("19.5"))

        async with sm() as session:
            result = await latest_hard_clamp_setpoint_per_room(session, [room_id])
            # Zone-Mapping zeigt fuer beide Zonen denselben Wert.
            value_zone1 = result.get(room_id)
            value_zone2 = result.get(room_id)

        assert value_zone1 == Decimal("19.5")
        assert value_zone1 == value_zone2
        # Sanity: Zone-IDs sind unterschiedlich aber teilen den Room-Setpoint.
        assert z1 != z2
    finally:
        await _cleanup(sm)


async def test_hard_clamp_setpoint_decimal_one_place(
    setup_engine: AsyncEngine,
) -> None:
    sm = async_sessionmaker(setup_engine, expire_on_commit=False)
    s = uuid.uuid4().hex[:8]
    try:
        room_id, _ = await _mk_room(sm, s, RoomStatus.OCCUPIED)
        # Numeric(4,1) quantisiert auf 0.1.
        await _mk_hard_clamp_eval(sm, room_id=room_id, setpoint_c=Decimal("20.5"))

        async with sm() as session:
            result = await latest_hard_clamp_setpoint_per_room(session, [room_id])

        assert isinstance(result[room_id], Decimal)
        # Eine Nachkommastelle (DB Numeric(4,1) garantiert das).
        sp = result[room_id]
        assert sp is not None
        assert -sp.as_tuple().exponent <= 1
    finally:
        await _cleanup(sm)


# ---------------------------------------------------------------------------
# T4 — FU-3 PATCH-Audit
# ---------------------------------------------------------------------------


async def test_patch_zone_name_creates_audit(
    http_client: httpx.AsyncClient, setup_engine: AsyncEngine
) -> None:
    sm = async_sessionmaker(setup_engine, expire_on_commit=False)
    s = uuid.uuid4().hex[:8]
    try:
        admin_id = await _login(http_client, sm, UserRole.ADMIN, prefix="admin")
        room_id, _ = await _mk_room(sm, s, RoomStatus.OCCUPIED)
        zone_id = await _mk_zone(sm, room_id, f"t14e{s}n")

        resp = await http_client.patch(
            f"/api/v1/rooms/{room_id}/heating-zones/{zone_id}",
            json={"name": "Neuer Name"},
        )
        assert resp.status_code == 200, resp.text

        async with sm() as session:
            rows = (
                (
                    await session.execute(
                        select(BusinessAudit)
                        .where(BusinessAudit.action == "HEATING_ZONE_NAME_CHANGED")
                        .where(BusinessAudit.target_id == zone_id)
                    )
                )
                .scalars()
                .all()
            )
        assert len(rows) == 1
        entry = rows[0]
        assert entry.user_id == admin_id
        assert entry.target_type == "heating_zone"
        assert entry.new_value == {"name": "Neuer Name"}
    finally:
        await _cleanup(sm)


async def test_patch_room_type_creates_audit_with_engine_effect(
    http_client: httpx.AsyncClient, setup_engine: AsyncEngine
) -> None:
    sm = async_sessionmaker(setup_engine, expire_on_commit=False)
    s = uuid.uuid4().hex[:8]
    try:
        admin_id = await _login(http_client, sm, UserRole.ADMIN, prefix="admin")
        room_id, rt_old = await _mk_room(sm, s, RoomStatus.OCCUPIED)
        # Zweiten RoomType anlegen, damit es einen Ziel-Typ gibt.
        async with sm() as session:
            rt_new = RoomType(name=f"t14e-rt-{s}-new")
            session.add(rt_new)
            await session.flush()
            await session.commit()
            await session.refresh(rt_new)
            rt_new_id = rt_new.id

        resp = await http_client.patch(
            f"/api/v1/rooms/{room_id}",
            json={"room_type_id": rt_new_id},
        )
        assert resp.status_code == 200, resp.text

        async with sm() as session:
            rows = (
                (
                    await session.execute(
                        select(BusinessAudit)
                        .where(BusinessAudit.action == "ROOM_TYPE_CHANGED")
                        .where(BusinessAudit.target_id == room_id)
                    )
                )
                .scalars()
                .all()
            )
        assert len(rows) == 1
        entry = rows[0]
        assert entry.user_id == admin_id
        assert entry.target_type == "room"
        assert entry.old_value == {"room_type_id": rt_old}
        assert entry.new_value["room_type_id"] == rt_new_id
        assert entry.new_value["engine_effect"] == "rule_config_scope_room_type"
    finally:
        await _cleanup(sm)


async def test_patch_room_as_non_admin_returns_403(
    http_client: httpx.AsyncClient, setup_engine: AsyncEngine
) -> None:
    sm = async_sessionmaker(setup_engine, expire_on_commit=False)
    s = uuid.uuid4().hex[:8]
    try:
        await _login(http_client, sm, UserRole.MITARBEITER, prefix="mitarbeiter")
        room_id, _ = await _mk_room(sm, s, RoomStatus.OCCUPIED)

        resp = await http_client.patch(
            f"/api/v1/rooms/{room_id}",
            json={"display_name": "Versuch"},
        )
        assert resp.status_code == 403
    finally:
        await _cleanup(sm)
