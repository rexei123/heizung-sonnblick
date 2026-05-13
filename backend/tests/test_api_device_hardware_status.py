"""Sprint 9.13c TC3 - Tests fuer GET /api/v1/devices/{id}/hardware-status.

Folgt der DB-Skip-Konvention von ``test_api_device_zone``: separate async
engine fuer Setup, dependency_override teilt diese engine mit der App.

Skip lokal, wenn ``DATABASE_URL`` nicht gesetzt ist. Lokal-Run gegen
echtes Postgres ist Pflicht (Lesson §5.19).
"""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from alembic.config import Config
from httpx import ASGITransport
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from alembic import command
from heizung.db import get_session
from heizung.main import app
from heizung.models.device import Device
from heizung.models.enums import DeviceKind, DeviceVendor
from heizung.models.sensor_reading import SensorReading

DATABASE_URL = os.environ.get("DATABASE_URL")
DATABASE_URL_PRESENT = bool(DATABASE_URL)
SKIP_REASON = "DATABASE_URL nicht gesetzt - API-Tests brauchen Test-DB"


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
async def device(setup_engine: AsyncEngine) -> AsyncIterator[tuple[int, str]]:
    """Ein frisches Vicki-Device ohne Zone-Zuordnung. Cleanup loescht
    Device und alle zugehoerigen sensor_readings (Cascade haengt am
    composite PK, deshalb explizit per DELETE)."""
    sessionmaker = async_sessionmaker(setup_engine, expire_on_commit=False)
    suffix = uuid.uuid4().hex[:8]
    async with sessionmaker() as session:
        dev = Device(
            dev_eui=f"deadbeef{suffix}",
            kind=DeviceKind.THERMOSTAT,
            vendor=DeviceVendor.MCLIMATE,
            model="vicki",
            label=f"hw-{suffix}",
        )
        session.add(dev)
        await session.commit()
        await session.refresh(dev)
        device_id = dev.id
        dev_eui = dev.dev_eui

    try:
        yield (device_id, dev_eui)
    finally:
        async with sessionmaker() as session:
            await session.execute(
                text("DELETE FROM sensor_reading WHERE device_id = :d"),
                {"d": device_id},
            )
            await session.execute(
                text("DELETE FROM device WHERE id = :d"),
                {"d": device_id},
            )
            await session.commit()


async def _add_reading(
    engine: AsyncEngine,
    device_id: int,
    *,
    age_min: int,
    attached: bool | None,
    fcnt: int,
) -> datetime:
    """Fuegt ein sensor_reading bei ``now() - age_min`` ein und liefert
    den Zeitstempel zurueck (fuer last_seen-Assertions)."""
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    t = datetime.now(UTC) - timedelta(minutes=age_min)
    async with sessionmaker() as session:
        sr = SensorReading(
            time=t,
            device_id=device_id,
            fcnt=fcnt,
            attached_backplate=attached,
        )
        session.add(sr)
        await session.commit()
    return t


# ---------------------------------------------------------------------------
# Test 1 - active wenn juengster Frame attached_backplate=True
# ---------------------------------------------------------------------------


async def test_active_when_recent_true_frame(
    http_client: httpx.AsyncClient, setup_engine: AsyncEngine, device: tuple[int, str]
) -> None:
    device_id, _ = device
    t_true = await _add_reading(setup_engine, device_id, age_min=5, attached=True, fcnt=1)

    resp = await http_client.get(f"/api/v1/devices/{device_id}/hardware-status")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "active"
    assert body["last_seen"] is not None
    last_seen = datetime.fromisoformat(body["last_seen"])
    assert abs((last_seen - t_true).total_seconds()) < 1
    assert body["frames_in_window"] == 1
    assert body["window_minutes"] == 30


# ---------------------------------------------------------------------------
# Test 2 - inactive wenn alle Frames False
# ---------------------------------------------------------------------------


async def test_inactive_when_all_false(
    http_client: httpx.AsyncClient, setup_engine: AsyncEngine, device: tuple[int, str]
) -> None:
    device_id, _ = device
    await _add_reading(setup_engine, device_id, age_min=5, attached=False, fcnt=1)
    await _add_reading(setup_engine, device_id, age_min=15, attached=False, fcnt=2)

    resp = await http_client.get(f"/api/v1/devices/{device_id}/hardware-status")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "inactive"
    assert body["last_seen"] is None
    assert body["frames_in_window"] == 2
    assert body["window_minutes"] == 30


# ---------------------------------------------------------------------------
# Test 3 - inactive wenn keine Frames vorhanden
# ---------------------------------------------------------------------------


async def test_inactive_when_no_frames(
    http_client: httpx.AsyncClient, device: tuple[int, str]
) -> None:
    device_id, _ = device

    resp = await http_client.get(f"/api/v1/devices/{device_id}/hardware-status")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "inactive"
    assert body["last_seen"] is None
    assert body["frames_in_window"] == 0
    assert body["window_minutes"] == 30


# ---------------------------------------------------------------------------
# Test 4 - inactive wenn True-Frame ausserhalb 30-Min-Fenster
# ---------------------------------------------------------------------------


async def test_inactive_when_frame_outside_window(
    http_client: httpx.AsyncClient, setup_engine: AsyncEngine, device: tuple[int, str]
) -> None:
    device_id, _ = device
    await _add_reading(setup_engine, device_id, age_min=45, attached=True, fcnt=1)

    resp = await http_client.get(f"/api/v1/devices/{device_id}/hardware-status")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "inactive"
    assert body["last_seen"] is None
    assert body["frames_in_window"] == 0


# ---------------------------------------------------------------------------
# Test 5 - active bei mixed (True, False, True); last_seen = juengster True
# ---------------------------------------------------------------------------


async def test_active_when_mixed_with_recent_true(
    http_client: httpx.AsyncClient, setup_engine: AsyncEngine, device: tuple[int, str]
) -> None:
    device_id, _ = device
    # aelterer True, dann False, dann juengster True - alle im Fenster
    await _add_reading(setup_engine, device_id, age_min=20, attached=True, fcnt=1)
    await _add_reading(setup_engine, device_id, age_min=15, attached=False, fcnt=2)
    t_newer_true = await _add_reading(setup_engine, device_id, age_min=5, attached=True, fcnt=3)

    resp = await http_client.get(f"/api/v1/devices/{device_id}/hardware-status")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "active"
    assert body["last_seen"] is not None
    last_seen = datetime.fromisoformat(body["last_seen"])
    assert abs((last_seen - t_newer_true).total_seconds()) < 1
    assert body["frames_in_window"] == 3


# ---------------------------------------------------------------------------
# Test 6 - 404 wenn Device nicht existiert
# ---------------------------------------------------------------------------


async def test_404_when_device_missing(http_client: httpx.AsyncClient) -> None:
    resp = await http_client.get("/api/v1/devices/99999/hardware-status")

    assert resp.status_code == 404, resp.text
