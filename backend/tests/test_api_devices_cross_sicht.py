"""Sprint 14a T3 — Cross-Sicht-UI: enriched DeviceRead (D2).

Endpoints unter Test:
- GET /api/v1/devices            Liste mit Nested-Zuordnung + active_override
                                 + latest_reading
- GET /api/v1/devices/{id}       Detail mit denselben Feldern + hardware_number
- GET /api/v1/devices/pool       Pool-Device: heating_zone = null

Folgt der DB-Skip-Konvention von ``test_api_devices_lifecycle``. Skip lokal,
wenn ``DATABASE_URL`` nicht gesetzt ist (§5.50: lokal mit Postgres laufen
lassen, nicht nur skippen).
"""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from alembic.config import Config
from httpx import ASGITransport
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from alembic import command
from heizung.db import get_session
from heizung.main import app
from heizung.models.device import Device
from heizung.models.enums import (
    DeviceKind,
    DeviceVendor,
    HeatingZoneKind,
    OverrideSource,
    RoomStatus,
)
from heizung.models.heating_zone import HeatingZone
from heizung.models.manual_override import ManualOverride
from heizung.models.room import Room
from heizung.models.room_type import RoomType
from heizung.models.sensor_reading import SensorReading

DATABASE_URL = os.environ.get("DATABASE_URL")
DATABASE_URL_PRESENT = bool(DATABASE_URL)
SKIP_REASON = "DATABASE_URL nicht gesetzt - API-Tests brauchen Test-DB"

HARDWARE_NUMBER = "MDC5419731K6UF"


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


@pytest_asyncio.fixture
async def setup(setup_engine: AsyncEngine) -> AsyncIterator[dict[str, int | str]]:
    """RoomType + OCCUPIED-Room + Zone + 1 zugewiesenes Device (mit
    hardware_number) + 1 Pool-Device. Kein Override, kein Reading initial —
    die Tests fuegen sie bei Bedarf ein.
    """
    sessionmaker = async_sessionmaker(setup_engine, expire_on_commit=False)
    suffix = uuid.uuid4().hex[:8]
    async with sessionmaker() as session:
        rt = RoomType(name=f"t14a-rt-{suffix}")
        session.add(rt)
        await session.flush()
        room = Room(number=f"t14a-{suffix}", room_type_id=rt.id, status=RoomStatus.OCCUPIED)
        session.add(room)
        await session.flush()
        zone = HeatingZone(
            room_id=room.id,
            kind=HeatingZoneKind.BEDROOM,
            name=f"bedroom-{suffix}",
            health_state="degraded",
        )
        session.add(zone)
        await session.flush()
        device = Device(
            dev_eui=f"cccc{suffix}cccc",
            kind=DeviceKind.THERMOSTAT,
            vendor=DeviceVendor.MCLIMATE,
            model="vicki",
            heating_zone_id=zone.id,
            health_state="healthy",
            hardware_number=f"{HARDWARE_NUMBER}-{suffix}",
        )
        pool_device = Device(
            dev_eui=f"dddd{suffix}dddd",
            kind=DeviceKind.THERMOSTAT,
            vendor=DeviceVendor.MCLIMATE,
            model="vicki",
            heating_zone_id=None,
            health_state="silent",
        )
        session.add_all([device, pool_device])
        await session.commit()
        data: dict[str, int | str] = {
            "suffix": suffix,
            "room_type_id": rt.id,
            "room_id": room.id,
            "zone_id": zone.id,
            "device_id": device.id,
            "pool_device_id": pool_device.id,
            "room_number": room.number,
            "room_type_name": rt.name,
            "zone_name": zone.name,
            "hardware_number": device.hardware_number or "",
        }

    try:
        yield data
    finally:
        async with sessionmaker() as session:
            await session.execute(
                text("DELETE FROM sensor_reading WHERE device_id IN (:d, :p)"),
                {"d": data["device_id"], "p": data["pool_device_id"]},
            )
            await session.execute(
                text("DELETE FROM manual_override WHERE room_id = :r"),
                {"r": data["room_id"]},
            )
            await session.execute(
                text("DELETE FROM device WHERE dev_eui LIKE :pat"),
                {"pat": f"%{suffix}%"},
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
            await session.commit()


def _find_device(body: list[dict], device_id: int) -> dict:
    match = [d for d in body if d["id"] == device_id]
    assert match, f"device {device_id} nicht in Listen-Response"
    return match[0]


# ---------------------------------------------------------------------------
# Nested-Zuordnung (D2/D6)
# ---------------------------------------------------------------------------


async def test_list_includes_nested_zone_room_room_type(
    http_client: httpx.AsyncClient, setup: dict[str, int | str]
) -> None:
    resp = await http_client.get("/api/v1/devices?limit=1000")
    assert resp.status_code == 200, resp.text
    dev = _find_device(resp.json(), int(setup["device_id"]))

    assert dev["heating_zone"] is not None
    assert dev["heating_zone"]["name"] == setup["zone_name"]
    assert dev["heating_zone"]["health_state"] == "degraded"
    assert dev["heating_zone"]["room"]["number"] == setup["room_number"]
    assert dev["heating_zone"]["room"]["room_type"]["name"] == setup["room_type_name"]


async def test_detail_includes_hardware_number_and_zone(
    http_client: httpx.AsyncClient, setup: dict[str, int | str]
) -> None:
    resp = await http_client.get(f"/api/v1/devices/{setup['device_id']}")
    assert resp.status_code == 200, resp.text
    dev = resp.json()
    assert dev["hardware_number"] == setup["hardware_number"]
    assert dev["heating_zone"]["room"]["number"] == setup["room_number"]


# ---------------------------------------------------------------------------
# active_override (D2, AE-61 read-only)
# ---------------------------------------------------------------------------


async def test_active_override_null_then_populated(
    http_client: httpx.AsyncClient,
    setup: dict[str, int | str],
    setup_engine: AsyncEngine,
) -> None:
    # 1. ohne Override -> null
    resp = await http_client.get(f"/api/v1/devices/{setup['device_id']}")
    assert resp.json()["active_override"] is None, resp.text

    # 2. aktiven Room-Scope-Override anlegen (direkter Insert, Read-Pfad-Test)
    sessionmaker = async_sessionmaker(setup_engine, expire_on_commit=False)
    async with sessionmaker() as session:
        session.add(
            ManualOverride(
                room_id=int(setup["room_id"]),
                heating_zone_id=None,
                setpoint=Decimal("21.5"),
                source=OverrideSource.FRONTEND_4H,
                expires_at=datetime.now(tz=UTC) + timedelta(hours=4),
            )
        )
        await session.commit()

    resp = await http_client.get(f"/api/v1/devices/{setup['device_id']}")
    ovr = resp.json()["active_override"]
    assert ovr is not None, resp.text
    assert ovr["source"] == "frontend_4h"
    assert ovr["setpoint_celsius"] == 21.5
    assert ovr["expires_at"] is not None


# ---------------------------------------------------------------------------
# latest_reading (D2/D5)
# ---------------------------------------------------------------------------


async def test_latest_reading_with_valve_position(
    http_client: httpx.AsyncClient,
    setup: dict[str, int | str],
    setup_engine: AsyncEngine,
) -> None:
    sessionmaker = async_sessionmaker(setup_engine, expire_on_commit=False)
    async with sessionmaker() as session:
        session.add(
            SensorReading(
                time=datetime.now(tz=UTC),
                device_id=int(setup["device_id"]),
                fcnt=1,
                temperature=Decimal("21.0"),
                setpoint=Decimal("21.0"),
                valve_position=42,
                battery_percent=80,
                rssi_dbm=-90,
                open_window=False,
                attached_backplate=True,
            )
        )
        await session.commit()

    resp = await http_client.get(f"/api/v1/devices/{setup['device_id']}")
    latest = resp.json()["latest_reading"]
    assert latest is not None, resp.text
    assert latest["valve_position"] == 42
    assert latest["open_window"] is False
    assert latest["attached_backplate"] is True
    # Sprint 14b: temperature (Decimal->float) + battery_percent additiv.
    assert latest["temperature"] == 21.0
    assert latest["battery_percent"] == 80


# ---------------------------------------------------------------------------
# battery_state (Sprint 15d, AE-65) — orthogonale Health-Achse
# ---------------------------------------------------------------------------


async def test_battery_state_warn_without_touching_health_state(
    http_client: httpx.AsyncClient,
    setup: dict[str, int | str],
    setup_engine: AsyncEngine,
) -> None:
    """Gerät mit pct=15 erscheint als battery_state="warn" (Schwelle 20),
    während health_state unveraendert "healthy" bleibt (Regression: Batterie
    ist eine eigene Achse, faltet NICHT in offline/implausible).
    """
    sessionmaker = async_sessionmaker(setup_engine, expire_on_commit=False)
    async with sessionmaker() as session:
        session.add(
            SensorReading(
                time=datetime.now(tz=UTC),
                device_id=int(setup["device_id"]),
                fcnt=1,
                temperature=Decimal("21.0"),
                battery_percent=15,
                open_window=False,
            )
        )
        await session.commit()

    resp = await http_client.get(f"/api/v1/devices/{setup['device_id']}")
    dev = resp.json()
    assert dev["battery_state"] == "warn", dev
    assert dev["health_state"] == "healthy", "Batterie-Achse darf health_state nicht aendern"
    assert dev["latest_reading"]["battery_percent"] == 15


async def test_battery_state_kritisch_below_ten(
    http_client: httpx.AsyncClient,
    setup: dict[str, int | str],
    setup_engine: AsyncEngine,
) -> None:
    """pct=5 -> battery_state="kritisch" (absolute Schwelle 10)."""
    sessionmaker = async_sessionmaker(setup_engine, expire_on_commit=False)
    async with sessionmaker() as session:
        session.add(
            SensorReading(
                time=datetime.now(tz=UTC),
                device_id=int(setup["device_id"]),
                fcnt=2,
                battery_percent=5,
                open_window=False,
            )
        )
        await session.commit()

    resp = await http_client.get(f"/api/v1/devices/{setup['device_id']}")
    assert resp.json()["battery_state"] == "kritisch", resp.text


async def test_battery_state_unbekannt_without_reading(
    http_client: httpx.AsyncClient, setup: dict[str, int | str]
) -> None:
    """Pool-Device ohne Reading -> battery_state="unbekannt"."""
    resp = await http_client.get(f"/api/v1/devices/{setup['pool_device_id']}")
    assert resp.status_code == 200, resp.text
    assert resp.json()["battery_state"] == "unbekannt"


# ---------------------------------------------------------------------------
# Pool-Device + Lifecycle-Filter
# ---------------------------------------------------------------------------


async def test_pool_device_has_null_zone_and_override(
    http_client: httpx.AsyncClient, setup: dict[str, int | str]
) -> None:
    resp = await http_client.get(f"/api/v1/devices/{setup['pool_device_id']}")
    assert resp.status_code == 200, resp.text
    dev = resp.json()
    assert dev["heating_zone"] is None
    assert dev["active_override"] is None


async def test_retired_device_excluded_from_default_list(
    http_client: httpx.AsyncClient,
    setup: dict[str, int | str],
    setup_engine: AsyncEngine,
) -> None:
    # Pool-Device retiren -> darf in Default-Liste nicht mehr erscheinen.
    sessionmaker = async_sessionmaker(setup_engine, expire_on_commit=False)
    async with sessionmaker() as session:
        await session.execute(
            text("UPDATE device SET retired_at = NOW(), retired_reason = 'test_14a' WHERE id = :i"),
            {"i": setup["pool_device_id"]},
        )
        await session.commit()

    resp = await http_client.get("/api/v1/devices?limit=1000")
    ids = {d["id"] for d in resp.json()}
    assert setup["pool_device_id"] not in ids

    resp_incl = await http_client.get("/api/v1/devices?include_retired=true&limit=1000")
    ids_incl = {d["id"] for d in resp_incl.json()}
    assert setup["pool_device_id"] in ids_incl
