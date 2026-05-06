"""Sprint 9.9 T4 - REST-API-Tests fuer Manual-Override.

Nutzt ``httpx.AsyncClient`` mit ``ASGITransport`` gegen die echte App
und die in CI hochgefahrene Test-DB (``DATABASE_URL`` env). Skip lokal,
wenn ``DATABASE_URL`` nicht gesetzt ist.

Kein dependency_override fuer ``get_session`` - die App nutzt ihre
echte ``SessionLocal``, die via ``DATABASE_URL`` auf die Test-DB
zeigt. Setup-Daten werden ueber dieselbe Engine angelegt und am
Ende per Teardown wieder entfernt.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
import pytest
import pytest_asyncio
from httpx import ASGITransport
from sqlalchemy import text

from heizung.db import SessionLocal
from heizung.main import app
from heizung.models.occupancy import Occupancy
from heizung.models.room import Room
from heizung.models.room_type import RoomType

DATABASE_URL_PRESENT = bool(os.environ.get("DATABASE_URL"))
SKIP_REASON = "DATABASE_URL nicht gesetzt - API-Tests brauchen Test-DB"


@pytest_asyncio.fixture
async def http_client() -> AsyncIterator[httpx.AsyncClient]:
    if not DATABASE_URL_PRESENT:
        pytest.skip(SKIP_REASON)
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest_asyncio.fixture
async def room_id() -> AsyncIterator[int]:
    """Legt RoomType + Room an, raeumt am Ende auf (manual_override + room +
    room_type per direktem DELETE)."""
    if not DATABASE_URL_PRESENT:
        pytest.skip(SKIP_REASON)

    suffix = datetime.now(tz=UTC).strftime("%H%M%S%f")
    async with SessionLocal() as session:
        rt = RoomType(name=f"t9-9-api-{suffix}")
        session.add(rt)
        await session.flush()
        room = Room(number=f"t9-9-api-{suffix}", room_type_id=rt.id)
        session.add(room)
        await session.commit()
        rid, rt_id = room.id, rt.id

    yield rid

    async with SessionLocal() as session:
        await session.execute(
            text("DELETE FROM manual_override WHERE room_id = :r"), {"r": rid}
        )
        await session.execute(text("DELETE FROM room WHERE id = :r"), {"r": rid})
        await session.execute(text("DELETE FROM room_type WHERE id = :r"), {"r": rt_id})
        await session.commit()


@pytest_asyncio.fixture
async def room_with_occupancy(room_id: int) -> AsyncIterator[int]:
    """Erweiterter Setup: ein Raum mit aktiver Belegung in der Zukunft.
    Notwendig fuer ``frontend_checkout``-Override-Tests."""
    async with SessionLocal() as session:
        occ = Occupancy(
            room_id=room_id,
            check_in=datetime.now(tz=UTC) + timedelta(hours=1),
            check_out=datetime.now(tz=UTC) + timedelta(days=2),
        )
        session.add(occ)
        await session.commit()
        occ_id = occ.id

    yield room_id

    async with SessionLocal() as session:
        await session.execute(text("DELETE FROM occupancy WHERE id = :i"), {"i": occ_id})
        await session.commit()


# ---------------------------------------------------------------------------
# POST /rooms/{room_id}/overrides
# ---------------------------------------------------------------------------


async def test_post_frontend_4h_returns_201(http_client: httpx.AsyncClient, room_id: int) -> None:
    before = datetime.now(tz=UTC)
    resp = await http_client.post(
        f"/api/v1/rooms/{room_id}/overrides",
        json={"setpoint": "21.5", "source": "frontend_4h", "reason": "API-Test"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["room_id"] == room_id
    assert body["source"] == "frontend_4h"
    assert Decimal(body["setpoint"]) == Decimal("21.5")
    expires = datetime.fromisoformat(body["expires_at"])
    delta = expires - before
    # 4h, mit Toleranz fuer Roundtrip + 7-Tage-Cap-Sanity
    assert timedelta(hours=3, minutes=55) < delta < timedelta(hours=4, minutes=5)


async def test_post_frontend_checkout_without_occupancy_returns_422(
    http_client: httpx.AsyncClient, room_id: int
) -> None:
    resp = await http_client.post(
        f"/api/v1/rooms/{room_id}/overrides",
        json={"setpoint": "22.0", "source": "frontend_checkout"},
    )
    assert resp.status_code == 422, resp.text


async def test_post_setpoint_above_max_returns_422(
    http_client: httpx.AsyncClient, room_id: int
) -> None:
    resp = await http_client.post(
        f"/api/v1/rooms/{room_id}/overrides",
        json={"setpoint": "35.0", "source": "frontend_4h"},
    )
    assert resp.status_code == 422, resp.text


async def test_post_source_device_returns_422(http_client: httpx.AsyncClient, room_id: int) -> None:
    """``device`` ist im Frontend-Schema bewusst nicht erlaubt - Drehring-
    Overrides erzeugt der ``device_adapter`` (T5) intern."""
    resp = await http_client.post(
        f"/api/v1/rooms/{room_id}/overrides",
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
    # Ein Override anlegen + revoken
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

    # GET History soll den revokierten Eintrag enthalten
    list_resp = await http_client.get(f"/api/v1/rooms/{room_id}/overrides")
    assert list_resp.status_code == 200
    items = list_resp.json()
    assert len(items) >= 1
    assert any(item["id"] == override_id and item["revoked_at"] is not None for item in items)


# ---------------------------------------------------------------------------
# DELETE /overrides/{override_id}
# ---------------------------------------------------------------------------


async def test_delete_sets_revoked_then_409_on_double_revoke(
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
