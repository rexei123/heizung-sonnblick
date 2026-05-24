"""Sprint 13b.1 T6 - API-Endpoints fuer Device-Lifecycle (AE-57).

Endpoints unter Test:
- GET  /api/v1/devices/pool                  Reserve-Pool-Liste
- POST /api/v1/devices/{id}/replace/from-pool   Atomarer Pool-Tausch
- POST /api/v1/devices/{id}/retire            Stilllegung ohne Ersatz
- GET  /api/v1/devices                       Default-Filter retired_at IS NULL,
                                              ``?include_retired=true``-Param.

Folgt der DB-Skip-Konvention von ``test_api_device_zone``. Skip lokal,
wenn ``DATABASE_URL`` nicht gesetzt ist.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
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
from heizung.models.enums import DeviceKind, DeviceVendor, HeatingZoneKind
from heizung.models.heating_zone import HeatingZone
from heizung.models.room import Room
from heizung.models.room_type import RoomType

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
    """RoomType + Room + Zone + 1 zugewiesenes Device + 1 Pool-Device.

    Cleanup loescht in FK-sicherer Reihenfolge: business_audit (target_id
    Pattern), device (suffix), heating_zone, room, room_type.
    """
    sessionmaker = async_sessionmaker(setup_engine, expire_on_commit=False)
    suffix = uuid.uuid4().hex[:8]
    async with sessionmaker() as session:
        rt = RoomType(name=f"t13b1-rt-{suffix}")
        session.add(rt)
        await session.flush()
        room = Room(number=f"t13b1-{suffix}", room_type_id=rt.id)
        session.add(room)
        await session.flush()
        zone = HeatingZone(
            room_id=room.id,
            kind=HeatingZoneKind.BEDROOM,
            name=f"bedroom-{suffix}",
        )
        session.add(zone)
        await session.flush()
        old_device = Device(
            dev_eui=f"aaaa{suffix}aaaa",
            kind=DeviceKind.THERMOSTAT,
            vendor=DeviceVendor.MCLIMATE,
            model="vicki",
            heating_zone_id=zone.id,
            health_state="healthy",
        )
        pool_device = Device(
            dev_eui=f"bbbb{suffix}bbbb",
            kind=DeviceKind.THERMOSTAT,
            vendor=DeviceVendor.MCLIMATE,
            model="vicki",
            heating_zone_id=None,
            health_state="healthy",
        )
        session.add_all([old_device, pool_device])
        await session.commit()
        data: dict[str, int | str] = {
            "suffix": suffix,
            "room_type_id": rt.id,
            "room_id": room.id,
            "zone_id": zone.id,
            "old_device_id": old_device.id,
            "pool_device_id": pool_device.id,
            "old_dev_eui": old_device.dev_eui,
            "pool_dev_eui": pool_device.dev_eui,
        }

    try:
        yield data
    finally:
        async with sessionmaker() as session:
            await session.execute(
                text(
                    "DELETE FROM business_audit WHERE target_type = 'device' "
                    "AND target_id IN (:o, :p)"
                ),
                {"o": data["old_device_id"], "p": data["pool_device_id"]},
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


# ---------------------------------------------------------------------------
# GET /api/v1/devices/pool
# ---------------------------------------------------------------------------


async def test_get_pool_happy_lists_pool_device(
    http_client: httpx.AsyncClient, setup: dict[str, int | str]
) -> None:
    resp = await http_client.get("/api/v1/devices/pool")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    pool_ids = {d["id"] for d in body}
    assert setup["pool_device_id"] in pool_ids
    assert setup["old_device_id"] not in pool_ids


async def test_get_pool_401_when_auth_enabled(
    monkeypatch: pytest.MonkeyPatch,
    http_client: httpx.AsyncClient,
    setup: dict[str, int | str],
) -> None:
    monkeypatch.setenv("AUTH_ENABLED", "true")
    from heizung.config import get_settings

    get_settings.cache_clear()
    try:
        resp = await http_client.get("/api/v1/devices/pool")
        assert resp.status_code == 401
    finally:
        get_settings.cache_clear()


# ---------------------------------------------------------------------------
# POST /api/v1/devices/{id}/replace/from-pool
# ---------------------------------------------------------------------------


async def test_replace_from_pool_happy(
    http_client: httpx.AsyncClient,
    setup_engine: AsyncEngine,
    setup: dict[str, int | str],
) -> None:
    resp = await http_client.post(
        f"/api/v1/devices/{setup['old_device_id']}/replace/from-pool",
        json={"new_pool_device_id": setup["pool_device_id"]},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["id"] == setup["old_device_id"]
    assert body["retired_at"] is not None
    assert body["retired_reason"] == "replaced_by_pool"
    assert body["replaced_by_device_id"] == setup["pool_device_id"]
    assert body["heating_zone_id"] is None

    # Pool-Device sitzt jetzt in der alten Zone.
    sessionmaker = async_sessionmaker(setup_engine, expire_on_commit=False)
    async with sessionmaker() as s:
        pool = await s.get(Device, setup["pool_device_id"])
        assert pool is not None
        assert pool.heating_zone_id == setup["zone_id"]


async def test_replace_from_pool_401(
    monkeypatch: pytest.MonkeyPatch,
    http_client: httpx.AsyncClient,
    setup: dict[str, int | str],
) -> None:
    monkeypatch.setenv("AUTH_ENABLED", "true")
    from heizung.config import get_settings

    get_settings.cache_clear()
    try:
        resp = await http_client.post(
            f"/api/v1/devices/{setup['old_device_id']}/replace/from-pool",
            json={"new_pool_device_id": setup["pool_device_id"]},
        )
        assert resp.status_code == 401
    finally:
        get_settings.cache_clear()


async def test_replace_from_pool_404_unknown_old(
    http_client: httpx.AsyncClient, setup: dict[str, int | str]
) -> None:
    resp = await http_client.post(
        "/api/v1/devices/999999999/replace/from-pool",
        json={"new_pool_device_id": setup["pool_device_id"]},
    )
    assert resp.status_code == 404
    body = resp.json()
    assert "old_device_id" in body["detail"]
    # B-Sprint13b2-4 (AE-59): error_code-Diskriminator pflicht.
    assert body["error_code"] == "DEVICE_NOT_FOUND"


async def test_replace_from_pool_409_new_not_in_pool(
    http_client: httpx.AsyncClient, setup: dict[str, int | str]
) -> None:
    # old_device_id ist in Zone -> nicht im Pool -> PoolDeviceUnavailable
    # (Self-Swap-Block hier nicht, weil old != new als ID).
    resp = await http_client.post(
        f"/api/v1/devices/{setup['pool_device_id']}/replace/from-pool",
        json={"new_pool_device_id": setup["old_device_id"]},
    )
    # pool_device ist im Pool und versucht, old_device als new zu nutzen.
    # Gate 2 raised DeviceStateError, weil pool_device.heating_zone_id IS NULL
    # (kein aktiv-zugewiesener Tausch).
    assert resp.status_code == 409
    # B-Sprint13b2-4 (AE-59): error_code-Diskriminator pflicht.
    assert resp.json()["error_code"] == "DEVICE_STATE_ERROR"


async def test_replace_from_pool_409_self_replacement_forbidden(
    http_client: httpx.AsyncClient,
    setup: dict[str, int | str],
) -> None:
    """B-Sprint13b2-4 (AE-59): old_id == new_id -> SELF_REPLACEMENT_FORBIDDEN.

    Vor dem T1-Refactor warf ``device_service.replace_device`` einen inline-
    ``ValueError`` fuer diesen Pfad. Der Endpoint-Handler hat den generisch
    via ``except ValueError`` in 409 uebersetzt, aber kein dedizierter Code
    war im Body. Mit der neuen ``SelfReplacementError(LifecycleError)``-
    Klasse + App-weitem Exception-Handler ist der Pfad jetzt explizit
    diskriminierbar.
    """
    resp = await http_client.post(
        f"/api/v1/devices/{setup['old_device_id']}/replace/from-pool",
        json={"new_pool_device_id": setup["old_device_id"]},
    )
    assert resp.status_code == 409
    body = resp.json()
    assert body["error_code"] == "SELF_REPLACEMENT_FORBIDDEN"
    assert "Selbst-Tausch" in body["detail"]


async def test_replace_from_pool_409_pool_unavailable_direct(
    http_client: httpx.AsyncClient,
    setup_engine: AsyncEngine,
    setup: dict[str, int | str],
) -> None:
    """B-Sprint13b2-4 (AE-59): POOL_DEVICE_UNAVAILABLE-Diskriminator-Test.

    Pool-Device direkt aus dem Pool nehmen (zone_id setzen), Replace-
    Versuch trifft Gate 3 (Pre-Check ``new.heating_zone_id IS NOT NULL``)
    und liefert ``PoolDeviceUnavailable``. Bestandstest
    ``test_replace_from_pool_409_new_not_in_pool`` trifft eine andere
    409-Variante (DeviceStateError fuer alt-Pool-Device); dieser Test
    deckt den dedizierten Pool-Subtype.
    """
    sessionmaker = async_sessionmaker(setup_engine, expire_on_commit=False)
    async with sessionmaker() as s:
        pool = await s.get(Device, setup["pool_device_id"])
        assert pool is not None
        pool.heating_zone_id = setup["zone_id"]
        await s.commit()

    resp = await http_client.post(
        f"/api/v1/devices/{setup['old_device_id']}/replace/from-pool",
        json={"new_pool_device_id": setup["pool_device_id"]},
    )
    assert resp.status_code == 409
    body = resp.json()
    assert body["error_code"] == "POOL_DEVICE_UNAVAILABLE"
    assert "nicht im Pool" in body["detail"]


# ---------------------------------------------------------------------------
# POST /api/v1/devices/{id}/retire
# ---------------------------------------------------------------------------


async def test_retire_happy(
    http_client: httpx.AsyncClient,
    setup_engine: AsyncEngine,
    setup: dict[str, int | str],
) -> None:
    resp = await http_client.post(
        f"/api/v1/devices/{setup['old_device_id']}/retire",
        json={"reason": "battery_dead"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["id"] == setup["old_device_id"]
    assert body["retired_at"] is not None
    assert body["retired_reason"] == "battery_dead"
    # heating_zone_id BLEIBT (Historie-Anker).
    assert body["heating_zone_id"] == setup["zone_id"]


async def test_retire_401(
    monkeypatch: pytest.MonkeyPatch,
    http_client: httpx.AsyncClient,
    setup: dict[str, int | str],
) -> None:
    monkeypatch.setenv("AUTH_ENABLED", "true")
    from heizung.config import get_settings

    get_settings.cache_clear()
    try:
        resp = await http_client.post(
            f"/api/v1/devices/{setup['old_device_id']}/retire",
            json={"reason": "battery_dead"},
        )
        assert resp.status_code == 401
    finally:
        get_settings.cache_clear()


async def test_retire_404_unknown(
    http_client: httpx.AsyncClient, setup: dict[str, int | str]
) -> None:
    resp = await http_client.post(
        "/api/v1/devices/999999999/retire",
        json={"reason": "unknown_device"},
    )
    assert resp.status_code == 404
    # B-Sprint13b2-4 (AE-59): error_code-Diskriminator pflicht.
    assert resp.json()["error_code"] == "DEVICE_NOT_FOUND"


async def test_retire_409_already_retired(
    http_client: httpx.AsyncClient,
    setup_engine: AsyncEngine,
    setup: dict[str, int | str],
) -> None:
    # Erst retiren.
    resp1 = await http_client.post(
        f"/api/v1/devices/{setup['old_device_id']}/retire",
        json={"reason": "first_retire"},
    )
    assert resp1.status_code == 200, resp1.text
    # Zweiter Versuch -> 409.
    resp2 = await http_client.post(
        f"/api/v1/devices/{setup['old_device_id']}/retire",
        json={"reason": "duplicate_retire"},
    )
    assert resp2.status_code == 409
    body = resp2.json()
    assert "bereits retired" in body["detail"]
    # B-Sprint13b2-4 (AE-59): error_code-Diskriminator pflicht.
    assert body["error_code"] == "DEVICE_STATE_ERROR"


# ---------------------------------------------------------------------------
# GET /api/v1/devices (Default-Filter retired_at IS NULL)
# ---------------------------------------------------------------------------


async def test_list_devices_default_excludes_retired(
    http_client: httpx.AsyncClient,
    setup_engine: AsyncEngine,
    setup: dict[str, int | str],
) -> None:
    # Old-Device retiren via direkter ORM-Modifikation.
    sessionmaker = async_sessionmaker(setup_engine, expire_on_commit=False)
    async with sessionmaker() as s:
        dev = await s.get(Device, setup["old_device_id"])
        assert dev is not None
        dev.retired_at = datetime.now(tz=UTC)
        dev.retired_reason = "test_list_filter"
        await s.commit()

    resp = await http_client.get("/api/v1/devices?limit=1000")
    assert resp.status_code == 200
    ids = {d["id"] for d in resp.json()}
    assert setup["pool_device_id"] in ids
    assert setup["old_device_id"] not in ids, (
        "retired Device darf bei Default (include_retired=false) NICHT in der Liste sein."
    )


async def test_list_devices_include_retired_shows_retired(
    http_client: httpx.AsyncClient,
    setup_engine: AsyncEngine,
    setup: dict[str, int | str],
) -> None:
    sessionmaker = async_sessionmaker(setup_engine, expire_on_commit=False)
    async with sessionmaker() as s:
        dev = await s.get(Device, setup["old_device_id"])
        assert dev is not None
        dev.retired_at = datetime.now(tz=UTC)
        dev.retired_reason = "test_include_retired"
        await s.commit()

    resp = await http_client.get("/api/v1/devices?limit=1000&include_retired=true")
    assert resp.status_code == 200
    ids = {d["id"] for d in resp.json()}
    assert setup["pool_device_id"] in ids
    assert setup["old_device_id"] in ids, (
        "include_retired=true muss retired Device ZURUECK in der Liste haben."
    )
