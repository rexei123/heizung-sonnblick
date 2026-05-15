"""Sprint 9.11a T4 - REST-API-Tests fuer Geraete-Zone-Zuordnung.

Folgt der DB-Skip-Konvention von ``test_api_overrides``: separate async
engine fuer Setup, dependency_override teilt diese engine mit der App.

Skip lokal, wenn ``DATABASE_URL`` nicht gesetzt ist. Lokal-Run gegen
echtes Postgres ist Pflicht (Lesson Sec. 5.19).
"""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncIterator
from datetime import datetime
from pathlib import Path
from typing import TypedDict
from unittest.mock import MagicMock

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
from heizung.models.enums import DeviceKind, DeviceVendor, HeatingZoneKind
from heizung.models.heating_zone import HeatingZone
from heizung.models.room import Room
from heizung.models.room_type import RoomType

DATABASE_URL = os.environ.get("DATABASE_URL")
DATABASE_URL_PRESENT = bool(DATABASE_URL)
SKIP_REASON = "DATABASE_URL nicht gesetzt - API-Tests brauchen Test-DB"


class _Setup(TypedDict):
    suffix: str
    room_type_id: int
    room_id: int
    zone_a_id: int
    zone_b_id: int


@pytest_asyncio.fixture(scope="module", autouse=True)
async def _migrate_db() -> None:
    """``alembic upgrade head`` im Thread, einmal pro Modul."""
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
async def setup(setup_engine: AsyncEngine) -> AsyncIterator[_Setup]:
    """Erzeugt RoomType + Room + zwei Zonen (BEDROOM/BATHROOM).

    Cleanup loescht zusaetzlich alle im Test angelegten Devices ueber den
    DevEUI-Suffix-Pattern. ``device.heating_zone_id`` hat ``ondelete=SET NULL``,
    also wuerden Devices ohne explizites Cleanup leakend zurueckbleiben.
    """
    sessionmaker = async_sessionmaker(setup_engine, expire_on_commit=False)
    suffix = uuid.uuid4().hex[:8]
    async with sessionmaker() as session:
        rt = RoomType(name=f"t911a-rt-{suffix}")
        session.add(rt)
        await session.flush()
        room = Room(number=f"t911a-{suffix}", room_type_id=rt.id)
        session.add(room)
        await session.flush()
        zone_a = HeatingZone(
            room_id=room.id, kind=HeatingZoneKind.BEDROOM, name=f"bedroom-{suffix}"
        )
        zone_b = HeatingZone(
            room_id=room.id, kind=HeatingZoneKind.BATHROOM, name=f"bathroom-{suffix}"
        )
        session.add_all([zone_a, zone_b])
        await session.commit()
        data: _Setup = {
            "suffix": suffix,
            "room_type_id": rt.id,
            "room_id": room.id,
            "zone_a_id": zone_a.id,
            "zone_b_id": zone_b.id,
        }

    try:
        yield data
    finally:
        async with sessionmaker() as session:
            await session.execute(
                text("DELETE FROM device WHERE dev_eui LIKE :pat"),
                {"pat": f"%{suffix}"},
            )
            await session.execute(
                text("DELETE FROM heating_zone WHERE room_id = :r"),
                {"r": data["room_id"]},
            )
            await session.execute(text("DELETE FROM room WHERE id = :r"), {"r": data["room_id"]})
            await session.execute(
                text("DELETE FROM room_type WHERE id = :r"), {"r": data["room_type_id"]}
            )
            await session.commit()


async def _create_device(
    engine: AsyncEngine, suffix: str, heating_zone_id: int | None
) -> tuple[int, str, datetime]:
    """Legt ein Vicki-Device an und liefert (device_id, dev_eui, updated_at)."""
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    async with sessionmaker() as session:
        # 8-stelliger Hex-Suffix laesst dev_eui exakt 16 Zeichen lang werden.
        device = Device(
            dev_eui=f"deadbeef{suffix}",
            kind=DeviceKind.THERMOSTAT,
            vendor=DeviceVendor.MCLIMATE,
            model="vicki",
            label=f"vicki-{suffix}",
            heating_zone_id=heating_zone_id,
        )
        session.add(device)
        await session.commit()
        await session.refresh(device)
        return device.id, device.dev_eui, device.updated_at


# ---------------------------------------------------------------------------
# PUT /api/v1/devices/{device_id}/heating-zone
# ---------------------------------------------------------------------------


async def test_assign_device_to_zone_when_unassigned(
    http_client: httpx.AsyncClient, setup_engine: AsyncEngine, setup: _Setup
) -> None:
    device_id, dev_eui, updated_before = await _create_device(setup_engine, setup["suffix"], None)

    resp = await http_client.put(
        f"/api/v1/devices/{device_id}/heating-zone",
        json={"heating_zone_id": setup["zone_a_id"]},
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["device_id"] == device_id
    assert body["dev_eui"] == dev_eui
    assert body["heating_zone_id"] == setup["zone_a_id"]
    assert datetime.fromisoformat(body["updated_at"]) > updated_before


async def test_assign_idempotent_when_already_assigned(
    http_client: httpx.AsyncClient, setup_engine: AsyncEngine, setup: _Setup
) -> None:
    device_id, _, updated_before = await _create_device(
        setup_engine, setup["suffix"], setup["zone_a_id"]
    )

    resp = await http_client.put(
        f"/api/v1/devices/{device_id}/heating-zone",
        json={"heating_zone_id": setup["zone_a_id"]},
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["heating_zone_id"] == setup["zone_a_id"]
    assert datetime.fromisoformat(body["updated_at"]) == updated_before


async def test_reassign_to_different_zone(
    http_client: httpx.AsyncClient, setup_engine: AsyncEngine, setup: _Setup
) -> None:
    device_id, _, updated_before = await _create_device(
        setup_engine, setup["suffix"], setup["zone_a_id"]
    )

    resp = await http_client.put(
        f"/api/v1/devices/{device_id}/heating-zone",
        json={"heating_zone_id": setup["zone_b_id"]},
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["heating_zone_id"] == setup["zone_b_id"]
    assert datetime.fromisoformat(body["updated_at"]) > updated_before


async def test_assign_returns_404_when_device_missing(
    http_client: httpx.AsyncClient, setup: _Setup
) -> None:
    resp = await http_client.put(
        "/api/v1/devices/99999/heating-zone",
        json={"heating_zone_id": setup["zone_a_id"]},
    )
    assert resp.status_code == 404, resp.text
    assert resp.json()["detail"] == "device_not_found"


async def test_assign_returns_404_when_zone_missing(
    http_client: httpx.AsyncClient, setup_engine: AsyncEngine, setup: _Setup
) -> None:
    device_id, _, _ = await _create_device(setup_engine, setup["suffix"], None)

    resp = await http_client.put(
        f"/api/v1/devices/{device_id}/heating-zone",
        json={"heating_zone_id": 99999},
    )
    assert resp.status_code == 404, resp.text
    assert resp.json()["detail"] == "heating_zone_not_found"


async def test_assign_returns_422_when_zone_id_zero(
    http_client: httpx.AsyncClient, setup_engine: AsyncEngine, setup: _Setup
) -> None:
    device_id, _, _ = await _create_device(setup_engine, setup["suffix"], None)

    resp = await http_client.put(
        f"/api/v1/devices/{device_id}/heating-zone",
        json={"heating_zone_id": 0},
    )
    assert resp.status_code == 422, resp.text


async def test_assign_returns_422_when_extra_field(
    http_client: httpx.AsyncClient, setup_engine: AsyncEngine, setup: _Setup
) -> None:
    device_id, _, _ = await _create_device(setup_engine, setup["suffix"], None)

    resp = await http_client.put(
        f"/api/v1/devices/{device_id}/heating-zone",
        json={"heating_zone_id": setup["zone_a_id"], "foo": "bar"},
    )
    assert resp.status_code == 422, resp.text


# ---------------------------------------------------------------------------
# DELETE /api/v1/devices/{device_id}/heating-zone
# ---------------------------------------------------------------------------


async def test_detach_device_with_zone(
    http_client: httpx.AsyncClient, setup_engine: AsyncEngine, setup: _Setup
) -> None:
    device_id, _, updated_before = await _create_device(
        setup_engine, setup["suffix"], setup["zone_a_id"]
    )

    resp = await http_client.delete(f"/api/v1/devices/{device_id}/heating-zone")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["heating_zone_id"] is None
    assert datetime.fromisoformat(body["updated_at"]) > updated_before


async def test_detach_idempotent_when_unassigned(
    http_client: httpx.AsyncClient, setup_engine: AsyncEngine, setup: _Setup
) -> None:
    device_id, _, updated_before = await _create_device(setup_engine, setup["suffix"], None)

    resp = await http_client.delete(f"/api/v1/devices/{device_id}/heating-zone")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["heating_zone_id"] is None
    assert datetime.fromisoformat(body["updated_at"]) == updated_before


async def test_detach_returns_404_when_device_missing(http_client: httpx.AsyncClient) -> None:
    resp = await http_client.delete("/api/v1/devices/99999/heating-zone")
    assert resp.status_code == 404, resp.text
    assert resp.json()["detail"] == "device_not_found"


# ---------------------------------------------------------------------------
# HF-9.13a-2: Engine-Tick-Trigger nach Zone-Aenderung (B-LT-2)
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_evaluate_room(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Ersetzt das im API-Modul importierte ``evaluate_room`` durch einen
    MagicMock. ``mock.delay`` wird dann automatisch zum Tracker.
    """
    mock = MagicMock()
    monkeypatch.setattr("heizung.api.v1.devices.evaluate_room", mock)
    return mock


async def test_assign_triggers_evaluate_room(
    http_client: httpx.AsyncClient,
    setup_engine: AsyncEngine,
    setup: _Setup,
    mock_evaluate_room: MagicMock,
) -> None:
    """PUT auf ein bisher unzugeordnetes Geraet triggert evaluate_room.delay
    fuer das Zimmer der gewaehlten Zone."""
    device_id, _, _ = await _create_device(setup_engine, setup["suffix"], None)

    resp = await http_client.put(
        f"/api/v1/devices/{device_id}/heating-zone",
        json={"heating_zone_id": setup["zone_a_id"]},
    )

    assert resp.status_code == 200, resp.text
    mock_evaluate_room.delay.assert_called_once_with(setup["room_id"])


async def test_detach_triggers_evaluate_room_for_previous_room(
    http_client: httpx.AsyncClient,
    setup_engine: AsyncEngine,
    setup: _Setup,
    mock_evaluate_room: MagicMock,
) -> None:
    """DELETE triggert evaluate_room.delay fuer das ALTE Zimmer (das jetzt
    ein Geraet weniger hat)."""
    device_id, _, _ = await _create_device(setup_engine, setup["suffix"], setup["zone_a_id"])

    resp = await http_client.delete(f"/api/v1/devices/{device_id}/heating-zone")

    assert resp.status_code == 200, resp.text
    mock_evaluate_room.delay.assert_called_once_with(setup["room_id"])


async def test_assign_idempotent_does_not_trigger_evaluate_room(
    http_client: httpx.AsyncClient,
    setup_engine: AsyncEngine,
    setup: _Setup,
    mock_evaluate_room: MagicMock,
) -> None:
    """PUT mit derselben heating_zone_id wie bereits gesetzt: Idempotenz-
    Shortcut greift VOR dem Trigger, evaluate_room.delay NICHT gerufen."""
    device_id, _, _ = await _create_device(setup_engine, setup["suffix"], setup["zone_a_id"])

    resp = await http_client.put(
        f"/api/v1/devices/{device_id}/heating-zone",
        json={"heating_zone_id": setup["zone_a_id"]},
    )

    assert resp.status_code == 200, resp.text
    mock_evaluate_room.delay.assert_not_called()


async def test_detach_idempotent_does_not_trigger_evaluate_room(
    http_client: httpx.AsyncClient,
    setup_engine: AsyncEngine,
    setup: _Setup,
    mock_evaluate_room: MagicMock,
) -> None:
    """DELETE auf ein bereits unzugeordnetes Geraet: Idempotenz-Shortcut
    greift, evaluate_room.delay NICHT gerufen."""
    device_id, _, _ = await _create_device(setup_engine, setup["suffix"], None)

    resp = await http_client.delete(f"/api/v1/devices/{device_id}/heating-zone")

    assert resp.status_code == 200, resp.text
    mock_evaluate_room.delay.assert_not_called()
