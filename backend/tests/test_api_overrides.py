"""Sprint 9.9 T4 - REST-API-Tests fuer Manual-Override.

httpx.AsyncClient mit ASGITransport gegen die echte App. Setup-Daten
ueber eine SEPARATE async engine (eigener Pool) - so kollidieren die
asyncpg-Connections der Setup-Sessions nicht mit denen, die der
Endpoint via App-eigenem ``SessionLocal`` zieht.

Migration via ``alembic.command.upgrade`` in ``asyncio.to_thread``,
weil alembic env.py intern ``asyncio.run`` aufruft - das wuerde im
laufenden pytest-asyncio-Loop ``loop already running`` werfen.

Skip lokal, wenn ``DATABASE_URL`` nicht gesetzt ist.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

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
from heizung.models.room import Room
from heizung.models.room_type import RoomType

DATABASE_URL = os.environ.get("DATABASE_URL")
DATABASE_URL_PRESENT = bool(DATABASE_URL)
SKIP_REASON = "DATABASE_URL nicht gesetzt - API-Tests brauchen Test-DB"


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
    """Async engine fuer Setup + dependency_override. Pro Test ein eigener
    Pool, alle Connections im aktuellen pytest-asyncio-Loop -> kein
    "another operation in progress" und kein "different loop"."""
    if not DATABASE_URL_PRESENT:
        pytest.skip(SKIP_REASON)
    engine = create_async_engine(DATABASE_URL or "")
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def http_client(setup_engine: AsyncEngine) -> AsyncIterator[httpx.AsyncClient]:
    """AsyncClient + dependency_override: App nutzt dieselbe engine wie das
    Test-Setup, damit beide Pools im gleichen Loop laufen."""
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
async def vacant_room_id(setup_engine: AsyncEngine) -> AsyncIterator[int]:
    """Test-Setup ohne Belegung -> VACANT.

    Sprint 12a T2: ``test_post_frontend_checkout_without_occupancy_returns_422``
    testet explizit das 422 bei fehlender Occupancy (API-Layer-Check vor
    ``service.create``). Default-Fixture ``room_id`` seedet eine Belegung;
    fuer diesen Fall dediziert ohne.
    """
    sessionmaker = async_sessionmaker(setup_engine, expire_on_commit=False)
    suffix = datetime.now(tz=UTC).strftime("%H%M%S%f")
    async with sessionmaker() as session:
        # Prefix ``t12-v-`` = 6 chars, suffix 12 chars -> 18 chars (VARCHAR(20)).
        rt = RoomType(name=f"t12-v-{suffix}")
        session.add(rt)
        await session.flush()
        room = Room(number=f"t12-v-{suffix}", room_type_id=rt.id)
        session.add(room)
        await session.commit()
        rid, rt_id = room.id, rt.id

    try:
        yield rid
    finally:
        async with sessionmaker() as session:
            await session.execute(
                text("DELETE FROM manual_override WHERE room_id = :r"),
                {"r": rid},
            )
            await session.execute(text("DELETE FROM room WHERE id = :r"), {"r": rid})
            await session.execute(text("DELETE FROM room_type WHERE id = :r"), {"r": rt_id})
            await session.commit()


@pytest_asyncio.fixture
async def room_id(setup_engine: AsyncEngine) -> AsyncIterator[int]:
    """Test-Setup mit aktiver Belegung -> OCCUPIED-Status.

    Sprint 12a T2 (AE-58): ``override_service.create`` verlangt OCCUPIED
    (Domain-Invariante „Overrides existieren nur in belegten Zimmern").
    Bestehende API-Tests testen Override-CRUD-Pfade — eine aktive Belegung
    ist der realistische Setup-Default. Test-Bodies/Assertions unveraendert.
    """
    sessionmaker = async_sessionmaker(setup_engine, expire_on_commit=False)
    # ``room.number`` ist VARCHAR(20). Kompaktes prefix + 12-stelliges suffix
    # passt sicher rein (4 + 12 = 16 chars).
    suffix = datetime.now(tz=UTC).strftime("%H%M%S%f")
    async with sessionmaker() as session:
        rt = RoomType(name=f"t99api-{suffix}")
        session.add(rt)
        await session.flush()
        room = Room(number=f"t99-{suffix}", room_type_id=rt.id)
        session.add(room)
        await session.flush()
        from heizung.models.occupancy import Occupancy

        now = datetime.now(tz=UTC)
        occ = Occupancy(
            room_id=room.id,
            check_in=now - timedelta(hours=2),
            check_out=now + timedelta(days=2),
            is_active=True,
        )
        session.add(occ)
        await session.commit()
        rid, rt_id = room.id, rt.id

    try:
        yield rid
    finally:
        async with sessionmaker() as session:
            await session.execute(
                text("DELETE FROM manual_override WHERE room_id = :r"),
                {"r": rid},
            )
            await session.execute(text("DELETE FROM occupancy WHERE room_id = :r"), {"r": rid})
            await session.execute(text("DELETE FROM room WHERE id = :r"), {"r": rid})
            await session.execute(text("DELETE FROM room_type WHERE id = :r"), {"r": rt_id})
            await session.commit()


# ---------------------------------------------------------------------------
# POST /rooms/{room_id}/overrides
# ---------------------------------------------------------------------------


async def test_post_frontend_4h_returns_201(http_client: httpx.AsyncClient, room_id: int) -> None:
    before = datetime.now(tz=UTC)
    resp = await http_client.post(
        f"/api/v1/rooms/{room_id}/overrides",
        json={"setpoint": "22", "source": "frontend_4h", "reason": "API-Test"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["room_id"] == room_id
    assert body["source"] == "frontend_4h"
    assert Decimal(body["setpoint"]) == Decimal("22")
    expires = datetime.fromisoformat(body["expires_at"])
    delta = expires - before
    assert timedelta(hours=3, minutes=55) < delta < timedelta(hours=4, minutes=5)


async def test_post_frontend_checkout_without_occupancy_returns_422(
    http_client: httpx.AsyncClient, vacant_room_id: int
) -> None:
    # Sprint 12a T2: explizit VACANT-Fixture, weil Test 422 bei fehlender
    # Occupancy testet (API-Layer-Check fuer FRONTEND_CHECKOUT).
    resp = await http_client.post(
        f"/api/v1/rooms/{vacant_room_id}/overrides",
        json={"setpoint": "22.0", "source": "frontend_checkout"},
    )
    assert resp.status_code == 422, resp.text


async def test_post_setpoint_above_max_returns_422(http_client: httpx.AsyncClient) -> None:
    resp = await http_client.post(
        "/api/v1/rooms/1/overrides",
        json={"setpoint": "35.0", "source": "frontend_4h"},
    )
    assert resp.status_code == 422, resp.text


async def test_post_source_device_returns_422(http_client: httpx.AsyncClient) -> None:
    resp = await http_client.post(
        "/api/v1/rooms/1/overrides",
        json={"setpoint": "22.0", "source": "device"},
    )
    assert resp.status_code == 422, resp.text


async def test_post_unknown_room_returns_404(http_client: httpx.AsyncClient) -> None:
    resp = await http_client.post(
        "/api/v1/rooms/9999999/overrides",
        json={"setpoint": "22.0", "source": "frontend_4h"},
    )
    assert resp.status_code == 404, resp.text


# ---------------------------------------------------------------------------
# GET /rooms/{room_id}/overrides
# ---------------------------------------------------------------------------


async def test_get_history_includes_revoked(http_client: httpx.AsyncClient, room_id: int) -> None:
    create_resp = await http_client.post(
        f"/api/v1/rooms/{room_id}/overrides",
        json={"setpoint": "22.0", "source": "frontend_4h"},
    )
    assert create_resp.status_code == 201
    override_id = create_resp.json()["id"]
    revoke_resp = await http_client.request(
        "DELETE",
        f"/api/v1/overrides/{override_id}",
        json={"revoked_reason": "test cleanup"},
    )
    assert revoke_resp.status_code == 200

    list_resp = await http_client.get(f"/api/v1/rooms/{room_id}/overrides")
    assert list_resp.status_code == 200
    items = list_resp.json()
    assert len(items) >= 1
    assert any(item["id"] == override_id and item["revoked_at"] is not None for item in items)


# ---------------------------------------------------------------------------
# DELETE /overrides/{override_id}
# ---------------------------------------------------------------------------


async def test_delete_then_double_revoke_returns_409(
    http_client: httpx.AsyncClient, room_id: int
) -> None:
    create_resp = await http_client.post(
        f"/api/v1/rooms/{room_id}/overrides",
        json={"setpoint": "22.0", "source": "frontend_4h"},
    )
    override_id = create_resp.json()["id"]

    first = await http_client.request(
        "DELETE",
        f"/api/v1/overrides/{override_id}",
        json={"revoked_reason": "erstmal"},
    )
    assert first.status_code == 200, first.text
    assert first.json()["revoked_at"] is not None

    second = await http_client.request(
        "DELETE",
        f"/api/v1/overrides/{override_id}",
        json={"revoked_reason": "zweites mal"},
    )
    assert second.status_code == 409, second.text


async def test_delete_unknown_override_returns_404(http_client: httpx.AsyncClient) -> None:
    resp = await http_client.request("DELETE", "/api/v1/overrides/9999999")
    assert resp.status_code == 404, resp.text


# ---------------------------------------------------------------------------
# Sprint 9.9a Hotfix - Engine-Re-Eval-Trigger + Integer-Setpoint
# ---------------------------------------------------------------------------


async def test_post_triggers_evaluate_room(http_client: httpx.AsyncClient, room_id: int) -> None:
    """A1: POST muss ``evaluate_room.delay(room_id)`` triggern (analog
    zu occupancies, AE-07)."""
    with patch("heizung.api.v1.overrides._evaluate_room_task") as mock_task:
        resp = await http_client.post(
            f"/api/v1/rooms/{room_id}/overrides",
            json={"setpoint": "22", "source": "frontend_4h"},
        )
        assert resp.status_code == 201, resp.text
        mock_task.delay.assert_called_once_with(room_id)


async def test_delete_triggers_evaluate_room(http_client: httpx.AsyncClient, room_id: int) -> None:
    """A1: DELETE muss ebenfalls ``evaluate_room.delay`` triggern."""
    create_resp = await http_client.post(
        f"/api/v1/rooms/{room_id}/overrides",
        json={"setpoint": "22", "source": "frontend_4h"},
    )
    override_id = create_resp.json()["id"]

    with patch("heizung.api.v1.overrides._evaluate_room_task") as mock_task:
        resp = await http_client.request("DELETE", f"/api/v1/overrides/{override_id}")
        assert resp.status_code == 200, resp.text
        mock_task.delay.assert_called_once_with(room_id)


async def test_post_setpoint_with_half_step_returns_422(
    http_client: httpx.AsyncClient, room_id: int
) -> None:
    """A2: API akzeptiert nur ganze Grad - sonst Diskrepanz UI vs.
    Engine-Trace (rules.engine._quantize rundet auf int)."""
    resp = await http_client.post(
        f"/api/v1/rooms/{room_id}/overrides",
        json={"setpoint": "22.5", "source": "frontend_4h"},
    )
    assert resp.status_code == 422, resp.text
    assert "ganzen °C-Schritten" in resp.text


# ---------------------------------------------------------------------------
# Sprint 12 T4 (AE-52) — Window-Reject 409
# ---------------------------------------------------------------------------


async def _seed_zone_with_window_state(
    setup_engine: AsyncEngine, *, room_id: int, open_window: bool, suffix: str
) -> tuple[int, int]:
    """Setup-Helper: HeatingZone + healthy Device + frisches Reading mit
    angegebenem ``open_window``-Flag. Eigene Session ueber setup_engine
    (kein Reuse des http_client-Pools, weil parallel zur App-Eval).
    """
    from heizung.models.device import Device
    from heizung.models.enums import DeviceKind, DeviceVendor, HeatingZoneKind
    from heizung.models.heating_zone import HeatingZone
    from heizung.models.sensor_reading import SensorReading

    sessionmaker = async_sessionmaker(setup_engine, expire_on_commit=False)
    async with sessionmaker() as session:
        zone = HeatingZone(room_id=room_id, kind=HeatingZoneKind.BEDROOM, name=f"z-{suffix}")
        session.add(zone)
        await session.flush()
        device = Device(
            dev_eui=f"deadbeef{suffix[:8]}",
            kind=DeviceKind.THERMOSTAT,
            vendor=DeviceVendor.MCLIMATE,
            model="vicki",
            heating_zone_id=zone.id,
            health_state="healthy",
        )
        session.add(device)
        await session.flush()
        reading = SensorReading(
            time=datetime.now(tz=UTC) - timedelta(minutes=2),
            device_id=device.id,
            fcnt=1,
            temperature=Decimal("21.0"),
            open_window=open_window,
        )
        session.add(reading)
        await session.commit()
        return zone.id, device.id


async def test_post_returns_409_when_window_open(
    http_client: httpx.AsyncClient,
    setup_engine: AsyncEngine,
    room_id: int,
) -> None:
    """T4 (d): POST /override + Fenster offen -> HTTP 409 mit
    {detail: <str>, error_code: "OVERRIDE_REJECTED_WINDOW_OPEN", zones: [...]}.
    manual_override-Tabelle bleibt leer.

    B-Sprint13b2-7 (AE-59): top-level ``error_code`` + ``zones`` via
    OverrideError-Handler in ``heizung.main``.
    """
    suffix = datetime.now(tz=UTC).strftime("%H%M%S%f")
    zone_id, _device_id = await _seed_zone_with_window_state(
        setup_engine, room_id=room_id, open_window=True, suffix=suffix
    )

    resp = await http_client.post(
        f"/api/v1/rooms/{room_id}/overrides",
        json={"setpoint": "22", "source": "frontend_4h"},
    )
    assert resp.status_code == 409, resp.text
    body = resp.json()
    assert body["error_code"] == "OVERRIDE_REJECTED_WINDOW_OPEN"
    assert isinstance(body["detail"], str)
    assert isinstance(body["zones"], list)
    assert len(body["zones"]) == 1
    assert body["zones"][0]["zone_id"] == zone_id
    assert "reading_at" in body["zones"][0]

    # manual_override-Tabelle leer fuer diesen Raum:
    sessionmaker = async_sessionmaker(setup_engine, expire_on_commit=False)
    async with sessionmaker() as session:
        result = await session.execute(
            text("SELECT COUNT(*) FROM manual_override WHERE room_id = :r"),
            {"r": room_id},
        )
        count = result.scalar_one()
    assert count == 0


async def test_post_returns_201_when_window_closed(
    http_client: httpx.AsyncClient,
    setup_engine: AsyncEngine,
    room_id: int,
) -> None:
    """T4 (e): POST /override + alle Fenster zu -> 201 + Eintrag in DB."""
    suffix = datetime.now(tz=UTC).strftime("%H%M%S%f")
    await _seed_zone_with_window_state(
        setup_engine, room_id=room_id, open_window=False, suffix=suffix
    )

    resp = await http_client.post(
        f"/api/v1/rooms/{room_id}/overrides",
        json={"setpoint": "22", "source": "frontend_4h"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["room_id"] == room_id
    assert Decimal(body["setpoint"]) == Decimal("22")


# ---------------------------------------------------------------------------
# Sprint 12a T3 (AE-58) — Zone-Scope + room_not_occupied + invalid_zone
# ---------------------------------------------------------------------------


async def _seed_heating_zone(setup_engine: AsyncEngine, *, room_id: int, suffix: str) -> int:
    """Setup-Helper: nackte HeatingZone ohne Device/Reading. Fuer Zone-Scope-
    Tests die keinen Window-State brauchen.
    """
    from heizung.models.enums import HeatingZoneKind
    from heizung.models.heating_zone import HeatingZone

    sessionmaker = async_sessionmaker(setup_engine, expire_on_commit=False)
    async with sessionmaker() as session:
        zone = HeatingZone(room_id=room_id, kind=HeatingZoneKind.BEDROOM, name=f"z-{suffix}")
        session.add(zone)
        await session.commit()
        return zone.id


async def _seed_room_with_zone(
    setup_engine: AsyncEngine, *, suffix: str, with_occupancy: bool
) -> tuple[int, int, int]:
    """Setup-Helper: separater Raum + RoomType + Zone (+ optional Occupancy).
    Returns (room_id, room_type_id, zone_id). Aufruf raeumt selbst NICHT
    auf — Test ist verantwortlich (per finally-Block).
    """
    from heizung.models.enums import HeatingZoneKind
    from heizung.models.heating_zone import HeatingZone
    from heizung.models.occupancy import Occupancy

    sessionmaker = async_sessionmaker(setup_engine, expire_on_commit=False)
    async with sessionmaker() as session:
        rt = RoomType(name=f"t12-z-{suffix}")
        session.add(rt)
        await session.flush()
        room = Room(number=f"t12-z-{suffix}", room_type_id=rt.id)
        session.add(room)
        await session.flush()
        if with_occupancy:
            now = datetime.now(tz=UTC)
            occ = Occupancy(
                room_id=room.id,
                check_in=now - timedelta(hours=2),
                check_out=now + timedelta(days=2),
                is_active=True,
            )
            session.add(occ)
            await session.flush()
        zone = HeatingZone(room_id=room.id, kind=HeatingZoneKind.BEDROOM, name=f"z-{suffix}")
        session.add(zone)
        await session.commit()
        return room.id, rt.id, zone.id


async def _delete_room_cascade(setup_engine: AsyncEngine, *, room_id: int, rt_id: int) -> None:
    sessionmaker = async_sessionmaker(setup_engine, expire_on_commit=False)
    async with sessionmaker() as session:
        await session.execute(
            text("DELETE FROM manual_override WHERE room_id = :r"), {"r": room_id}
        )
        await session.execute(text("DELETE FROM room WHERE id = :r"), {"r": room_id})
        await session.execute(text("DELETE FROM room_type WHERE id = :r"), {"r": rt_id})
        await session.commit()


async def test_post_occupied_with_zone_id_returns_201(
    http_client: httpx.AsyncClient,
    setup_engine: AsyncEngine,
    room_id: int,
) -> None:
    """T3: zone_id im Body -> 201, Response + DB-Row enthalten heating_zone_id."""
    suffix = datetime.now(tz=UTC).strftime("%H%M%S%f")
    zone_id = await _seed_heating_zone(setup_engine, room_id=room_id, suffix=suffix)

    resp = await http_client.post(
        f"/api/v1/rooms/{room_id}/overrides",
        json={"setpoint": "22", "source": "frontend_4h", "heating_zone_id": zone_id},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["room_id"] == room_id
    assert body["heating_zone_id"] == zone_id

    sessionmaker = async_sessionmaker(setup_engine, expire_on_commit=False)
    async with sessionmaker() as session:
        row = await session.execute(
            text("SELECT heating_zone_id FROM manual_override WHERE id = :i"),
            {"i": body["id"]},
        )
        db_zone_id = row.scalar_one()
    assert db_zone_id == zone_id


async def test_post_occupied_without_zone_id_backward_compat(
    http_client: httpx.AsyncClient,
    setup_engine: AsyncEngine,
    room_id: int,
) -> None:
    """T3: ohne zone_id -> DB-Row hat heating_zone_id=NULL (Backward-Compat)."""
    resp = await http_client.post(
        f"/api/v1/rooms/{room_id}/overrides",
        json={"setpoint": "22", "source": "frontend_4h"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["heating_zone_id"] is None

    sessionmaker = async_sessionmaker(setup_engine, expire_on_commit=False)
    async with sessionmaker() as session:
        row = await session.execute(
            text("SELECT heating_zone_id FROM manual_override WHERE id = :i"),
            {"i": body["id"]},
        )
        db_zone_id = row.scalar_one()
    assert db_zone_id is None


async def test_post_vacant_returns_409_room_not_occupied(
    http_client: httpx.AsyncClient,
    vacant_room_id: int,
) -> None:
    """T3: POST in VACANT-Raum (frontend_4h, kein Occupancy-Pre-Check) -> 409
    mit ``{detail: <str>, error_code: "ROOM_NOT_OCCUPIED", room_id: X}``.

    B-Sprint13b2-7 (AE-59): top-level ``error_code`` via OverrideError-Handler.
    """
    resp = await http_client.post(
        f"/api/v1/rooms/{vacant_room_id}/overrides",
        json={"setpoint": "22", "source": "frontend_4h"},
    )
    assert resp.status_code == 409, resp.text
    body = resp.json()
    assert body["error_code"] == "ROOM_NOT_OCCUPIED"
    assert body["room_id"] == vacant_room_id


# ---------------------------------------------------------------------------
# Sprint 12c (AE-58) — Block-Gate vor OCCUPIED-Gate
# ---------------------------------------------------------------------------


async def test_create_returns_409_room_override_blocked(
    http_client: httpx.AsyncClient,
    setup_engine: AsyncEngine,
    room_id: int,
) -> None:
    """Sprint 12c: POST in geblocktes Zimmer (OCCUPIED + blocked=True) ->
    409 mit ``error_code=ROOM_OVERRIDE_BLOCKED``.

    B-Sprint13b2-7 (AE-59): top-level ``error_code`` via OverrideError-Handler.
    """
    sessionmaker = async_sessionmaker(setup_engine, expire_on_commit=False)
    async with sessionmaker() as session:
        room = await session.get(Room, room_id)
        assert room is not None
        room.guest_override_blocked = True
        await session.commit()

    resp = await http_client.post(
        f"/api/v1/rooms/{room_id}/overrides",
        json={"setpoint": "22", "source": "frontend_4h"},
    )
    assert resp.status_code == 409, resp.text
    body = resp.json()
    assert body["error_code"] == "ROOM_OVERRIDE_BLOCKED"
    assert body["room_id"] == room_id


async def test_create_block_takes_precedence_over_room_not_occupied(
    http_client: httpx.AsyncClient,
    setup_engine: AsyncEngine,
    vacant_room_id: int,
) -> None:
    """Sprint 12c (§5.51 Domain-Invariante): Block + VACANT ->
    ``ROOM_OVERRIDE_BLOCKED`` gewinnt, NICHT ``ROOM_NOT_OCCUPIED``.

    B-Sprint13b2-7 (AE-59): top-level ``error_code`` via OverrideError-Handler.
    """
    sessionmaker = async_sessionmaker(setup_engine, expire_on_commit=False)
    async with sessionmaker() as session:
        room = await session.get(Room, vacant_room_id)
        assert room is not None
        room.guest_override_blocked = True
        await session.commit()

    resp = await http_client.post(
        f"/api/v1/rooms/{vacant_room_id}/overrides",
        json={"setpoint": "22", "source": "frontend_4h"},
    )
    assert resp.status_code == 409, resp.text
    body = resp.json()
    assert body["error_code"] == "ROOM_OVERRIDE_BLOCKED"
    assert body["room_id"] == vacant_room_id


async def test_post_with_invalid_zone_id_returns_404(
    http_client: httpx.AsyncClient,
    setup_engine: AsyncEngine,
    room_id: int,
) -> None:
    """T3: zone_id zeigt auf Zone eines anderen Raums -> 404 INVALID_ZONE.

    B-Sprint13b2-7 (AE-59): top-level ``error_code`` via OverrideError-Handler.
    """
    suffix = datetime.now(tz=UTC).strftime("%H%M%S%f")
    other_room_id, other_rt_id, other_zone_id = await _seed_room_with_zone(
        setup_engine, suffix=suffix, with_occupancy=True
    )
    try:
        resp = await http_client.post(
            f"/api/v1/rooms/{room_id}/overrides",
            json={
                "setpoint": "22",
                "source": "frontend_4h",
                "heating_zone_id": other_zone_id,
            },
        )
        assert resp.status_code == 404, resp.text
        body = resp.json()
        assert body["error_code"] == "INVALID_ZONE"
        assert body["zone_id"] == other_zone_id
        assert body["room_id"] == room_id

        sessionmaker = async_sessionmaker(setup_engine, expire_on_commit=False)
        async with sessionmaker() as session:
            count = (
                await session.execute(
                    text("SELECT COUNT(*) FROM manual_override WHERE room_id = :r"),
                    {"r": room_id},
                )
            ).scalar_one()
        assert count == 0
    finally:
        await _delete_room_cascade(setup_engine, room_id=other_room_id, rt_id=other_rt_id)


async def test_get_with_zone_id_filters_correctly(
    http_client: httpx.AsyncClient,
    setup_engine: AsyncEngine,
    room_id: int,
) -> None:
    """T3: GET ?zone_id=X liefert Zone-Match + Room-Scope-Overrides.

    Setup: 1 Zone-Override (heating_zone_id=zone_id) + 1 Room-Override
    (heating_zone_id=NULL). GET ohne zone_id -> beide. GET mit zone_id
    -> beide, Zone-Match zuerst, dann Room-Scope.
    """
    suffix = datetime.now(tz=UTC).strftime("%H%M%S%f")
    zone_id = await _seed_heating_zone(setup_engine, room_id=room_id, suffix=suffix)

    # Room-Scope-Override
    resp_room = await http_client.post(
        f"/api/v1/rooms/{room_id}/overrides",
        json={"setpoint": "21", "source": "frontend_4h"},
    )
    assert resp_room.status_code == 201, resp_room.text
    room_override_id = resp_room.json()["id"]

    # Zone-Scope-Override
    resp_zone = await http_client.post(
        f"/api/v1/rooms/{room_id}/overrides",
        json={
            "setpoint": "23",
            "source": "frontend_4h",
            "heating_zone_id": zone_id,
        },
    )
    assert resp_zone.status_code == 201, resp_zone.text
    zone_override_id = resp_zone.json()["id"]

    # GET ohne zone_id -> alle (Backward-Compat, kein Filter, created_at DESC)
    resp_all = await http_client.get(f"/api/v1/rooms/{room_id}/overrides")
    assert resp_all.status_code == 200, resp_all.text
    ids_all = {item["id"] for item in resp_all.json()}
    assert ids_all == {room_override_id, zone_override_id}

    # GET mit zone_id -> Zone-Match zuerst, dann Room-Scope
    resp_zone_filter = await http_client.get(
        f"/api/v1/rooms/{room_id}/overrides", params={"zone_id": zone_id}
    )
    assert resp_zone_filter.status_code == 200, resp_zone_filter.text
    items = resp_zone_filter.json()
    assert len(items) == 2
    assert items[0]["id"] == zone_override_id
    assert items[0]["heating_zone_id"] == zone_id
    assert items[1]["id"] == room_override_id
    assert items[1]["heating_zone_id"] is None
