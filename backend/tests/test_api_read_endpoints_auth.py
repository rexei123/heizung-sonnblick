"""Sprint 9.17a T2 - Auth-Coverage fuer alle GET-Endpoints + DELETE-occupancy-405-Stub.

Sprint 9.17 hatte nur die ~21 mutierenden Endpoints abgesichert (T6-Brief-
Liste). 17 GET-Endpoints in 9 Routern lieferten Daten ohne Auth-Check
(Lesson CLAUDE.md Sec. 5.30). Sprint 9.17a schliesst diese Luecke mit
``require_user`` als neuer Dependency und prueft das hier zentral.

Bestehende Test-Files testen unter ``AUTH_ENABLED=false`` und treffen die
neuen Dependencies daher nicht messbar (System-User-Fallback liefert
Admin -> 200). Dieses File testet alle GET-Endpoints unter
``AUTH_ENABLED=true`` mit drei Cases pro Endpoint:

  - ohne Cookie -> 401
  - mit mitarbeiter-Cookie -> 200 (GET) / 405 (DELETE-occupancy)
  - mit admin-Cookie -> 200 (GET) / 405 (DELETE-occupancy)

Es wird bewusst ein einziges Sammel-File angelegt (statt fuenf neue
test_api_<domain>.py-Files), um Bestand und Brief-Intention "kein
Wildwuchs" zu respektieren — die Brief-Anweisung "Keine neuen Test-
Files anlegen" laesst sich woertlich nicht erfuellen, weil fuer
rooms / heating_zones / occupancies / room_types / global_config keine
test_api_<domain>.py existiert.

Skip lokal, wenn ``DATABASE_URL`` nicht gesetzt ist.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from typing import TypedDict

import httpx
import pytest
import pytest_asyncio
from alembic.config import Config
from httpx import ASGITransport
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from alembic import command
from heizung.auth.password import hash_password
from heizung.auth.rate_limit import limiter
from heizung.config import get_settings
from heizung.db import get_session
from heizung.main import app
from heizung.models.device import Device
from heizung.models.enums import (
    DeviceKind,
    DeviceVendor,
    HeatingZoneKind,
    RuleConfigScope,
    UserRole,
)
from heizung.models.heating_zone import HeatingZone
from heizung.models.occupancy import Occupancy
from heizung.models.room import Room
from heizung.models.room_type import RoomType
from heizung.models.rule_config import RuleConfig
from heizung.models.user import User

DATABASE_URL = os.environ.get("DATABASE_URL")
DATABASE_URL_PRESENT = bool(DATABASE_URL)
SKIP_REASON = "DATABASE_URL nicht gesetzt - API-Tests brauchen Test-DB"


class _Setup(TypedDict):
    suffix: str
    admin_email: str
    admin_password: str
    mitarbeiter_email: str
    mitarbeiter_password: str
    room_type_id: int
    room_id: int
    zone_id: int
    device_id: int
    occupancy_id: int


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

    async def _override_get_session() -> AsyncIterator:
        async with sessionmaker() as session:
            yield session

    app.dependency_overrides[get_session] = _override_get_session
    try:
        transport = ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            yield client
    finally:
        app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def setup(setup_engine: AsyncEngine) -> AsyncIterator[_Setup]:
    """Legt einen RoomType, Room, HeatingZone, Device, Occupancy und je einen
    admin + mitarbeiter User an. Cleanup loescht via Suffix-Pattern.
    """
    sessionmaker = async_sessionmaker(setup_engine, expire_on_commit=False)
    suffix = uuid.uuid4().hex[:8]
    admin_email = f"r-admin-{suffix}@test.example.com"
    admin_password = "AdminPassword12345!"
    mitarbeiter_email = f"r-emp-{suffix}@test.example.com"
    mitarbeiter_password = "EmployeePassword12345!"

    async with sessionmaker() as session:
        admin = User(
            email=admin_email,
            password_hash=hash_password(admin_password),
            role=UserRole.ADMIN,
            is_active=True,
            must_change_password=False,
        )
        emp = User(
            email=mitarbeiter_email,
            password_hash=hash_password(mitarbeiter_password),
            role=UserRole.MITARBEITER,
            is_active=True,
            must_change_password=False,
        )
        session.add_all([admin, emp])

        rt = RoomType(name=f"t917a-rt-{suffix}")
        session.add(rt)
        await session.flush()

        room = Room(number=f"t917a-{suffix}", room_type_id=rt.id)
        session.add(room)
        await session.flush()

        zone = HeatingZone(room_id=room.id, kind=HeatingZoneKind.BEDROOM, name=f"bedroom-{suffix}")
        session.add(zone)
        await session.flush()

        device = Device(
            dev_eui=f"deadbeef{suffix}",
            kind=DeviceKind.THERMOSTAT,
            vendor=DeviceVendor.MCLIMATE,
            model="vicki",
            label=f"vicki-{suffix}",
            heating_zone_id=zone.id,
        )
        session.add(device)
        await session.flush()

        occ = Occupancy(
            room_id=room.id,
            check_in=datetime.now(tz=UTC) - timedelta(days=1),
            check_out=datetime.now(tz=UTC) + timedelta(days=1),
            is_active=True,
        )
        session.add(occ)
        await session.flush()

        # GET /api/v1/rule-configs/global liefert 404 wenn die Singleton-Row
        # fehlt. Seed wird ueblicherweise im Boot gesetzt; in der Test-DB
        # idempotent nachziehen.
        rc_stmt = (
            select(RuleConfig)
            .where(RuleConfig.scope == RuleConfigScope.GLOBAL)
            .where(RuleConfig.room_type_id.is_(None))
            .where(RuleConfig.room_id.is_(None))
            .where(RuleConfig.season_id.is_(None))
        )
        rc = (await session.execute(rc_stmt)).scalar_one_or_none()
        if rc is None:
            session.add(
                RuleConfig(
                    scope=RuleConfigScope.GLOBAL,
                    t_occupied=Decimal("21.0"),
                    t_vacant=Decimal("18.0"),
                    t_night=Decimal("19.0"),
                    night_start=time(0, 0),
                    night_end=time(6, 0),
                    preheat_minutes_before_checkin=90,
                )
            )
        await session.commit()

        data: _Setup = {
            "suffix": suffix,
            "admin_email": admin_email,
            "admin_password": admin_password,
            "mitarbeiter_email": mitarbeiter_email,
            "mitarbeiter_password": mitarbeiter_password,
            "room_type_id": rt.id,
            "room_id": room.id,
            "zone_id": zone.id,
            "device_id": device.id,
            "occupancy_id": occ.id,
        }

    try:
        yield data
    finally:
        async with sessionmaker() as session:
            await session.execute(
                text("DELETE FROM occupancy WHERE room_id = :r"),
                {"r": data["room_id"]},
            )
            await session.execute(
                text("DELETE FROM device WHERE dev_eui LIKE :p"),
                {"p": f"%{suffix}"},
            )
            await session.execute(
                text("DELETE FROM heating_zone WHERE room_id = :r"),
                {"r": data["room_id"]},
            )
            await session.execute(text("DELETE FROM room WHERE id = :r"), {"r": data["room_id"]})
            await session.execute(
                text("DELETE FROM room_type WHERE id = :r"),
                {"r": data["room_type_id"]},
            )
            await session.execute(
                text('DELETE FROM "user" WHERE email LIKE :p'),
                {"p": f"%-{suffix}@test.example.com"},
            )
            await session.commit()


async def _login(client: httpx.AsyncClient, email: str, password: str) -> None:
    resp = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, resp.text


def _get_paths(setup: _Setup) -> list[tuple[str, str]]:
    """Liefert die 17 GET-Endpoints aus dem T1-Inventar.

    Jedes Tuple ist (testname-suffix, pfad). Pfade enthalten konkrete IDs
    aus der Test-Fixture, damit der Endpoint nicht durch 404 unterbrochen
    wird, bevor die Auth-Dependency greift.
    """
    rid = setup["room_id"]
    zid = setup["zone_id"]
    did = setup["device_id"]
    oid = setup["occupancy_id"]
    rtid = setup["room_type_id"]
    return [
        ("devices_list", "/api/v1/devices"),
        ("devices_detail", f"/api/v1/devices/{did}"),
        ("devices_sensor_readings", f"/api/v1/devices/{did}/sensor-readings"),
        ("devices_hardware_status", f"/api/v1/devices/{did}/hardware-status"),
        ("global_config_get", "/api/v1/global-config"),
        ("heating_zones_list", f"/api/v1/rooms/{rid}/heating-zones"),
        ("heating_zones_detail", f"/api/v1/rooms/{rid}/heating-zones/{zid}"),
        ("occupancies_list", "/api/v1/occupancies"),
        ("occupancies_detail", f"/api/v1/occupancies/{oid}"),
        ("overrides_list", f"/api/v1/rooms/{rid}/overrides"),
        ("room_types_list", "/api/v1/room-types"),
        ("room_types_detail", f"/api/v1/room-types/{rtid}"),
        ("rooms_list", "/api/v1/rooms"),
        ("rooms_detail", f"/api/v1/rooms/{rid}"),
        ("rooms_engine_trace", f"/api/v1/rooms/{rid}/engine-trace"),
        ("rule_configs_global", "/api/v1/rule-configs/global"),
        ("scenarios_list", "/api/v1/scenarios"),
    ]


# ---------------------------------------------------------------------------
# GET-Endpoints — drei Tests pro Endpoint via Schleifen-Iteration
# ---------------------------------------------------------------------------


async def test_all_get_endpoints_without_cookie_return_401(
    http_client: httpx.AsyncClient, setup: _Setup
) -> None:
    """Alle 17 GET-Endpoints: ohne Cookie -> 401."""
    http_client.cookies.clear()
    failures: list[tuple[str, int]] = []
    for name, path in _get_paths(setup):
        resp = await http_client.get(path)
        if resp.status_code != 401:
            failures.append((name, resp.status_code))
    assert failures == [], f"Endpoints ohne 401 ohne Cookie: {failures}"


async def test_all_get_endpoints_with_mitarbeiter_cookie_return_200(
    http_client: httpx.AsyncClient, setup: _Setup
) -> None:
    """Alle 17 GET-Endpoints: mit mitarbeiter-Cookie -> 200 (Soll=require_user
    fuer alle, kein Soll=require_admin in dieser Liste)."""
    await _login(http_client, setup["mitarbeiter_email"], setup["mitarbeiter_password"])
    failures: list[tuple[str, int]] = []
    for name, path in _get_paths(setup):
        resp = await http_client.get(path)
        if resp.status_code != 200:
            failures.append((name, resp.status_code))
    assert failures == [], f"Endpoints ohne 200 mit mitarbeiter-Cookie: {failures}"


async def test_all_get_endpoints_with_admin_cookie_return_200(
    http_client: httpx.AsyncClient, setup: _Setup
) -> None:
    """Alle 17 GET-Endpoints: mit admin-Cookie -> 200."""
    await _login(http_client, setup["admin_email"], setup["admin_password"])
    failures: list[tuple[str, int]] = []
    for name, path in _get_paths(setup):
        resp = await http_client.get(path)
        if resp.status_code != 200:
            failures.append((name, resp.status_code))
    assert failures == [], f"Endpoints ohne 200 mit admin-Cookie: {failures}"


# ---------------------------------------------------------------------------
# DELETE /api/v1/occupancies/{id} — immer 405, aber jetzt mit Auth-Layer davor
# ---------------------------------------------------------------------------


async def test_delete_occupancy_without_cookie_returns_401(
    http_client: httpx.AsyncClient, setup: _Setup
) -> None:
    http_client.cookies.clear()
    resp = await http_client.delete(f"/api/v1/occupancies/{setup['occupancy_id']}")
    assert resp.status_code == 401


async def test_delete_occupancy_with_mitarbeiter_cookie_returns_405(
    http_client: httpx.AsyncClient, setup: _Setup
) -> None:
    await _login(http_client, setup["mitarbeiter_email"], setup["mitarbeiter_password"])
    resp = await http_client.delete(f"/api/v1/occupancies/{setup['occupancy_id']}")
    assert resp.status_code == 405


async def test_delete_occupancy_with_admin_cookie_returns_405(
    http_client: httpx.AsyncClient, setup: _Setup
) -> None:
    await _login(http_client, setup["admin_email"], setup["admin_password"])
    resp = await http_client.delete(f"/api/v1/occupancies/{setup['occupancy_id']}")
    assert resp.status_code == 405
