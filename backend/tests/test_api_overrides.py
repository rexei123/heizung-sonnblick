"""Sprint 9.9 T4 - REST-API-Tests fuer Manual-Override.

Synchroner ``TestClient`` (Repo-Pattern aus ``test_health.py``). Setup
und Cleanup laufen ueber eine eigene Sync-Engine, damit der App-eigene
asyncpg-Connection-Pool nicht mit den Test-Setup-Sessions kollidiert
("another operation is in progress").

CI-Annahme: ``DATABASE_URL`` zeigt auf eine leere Test-DB. Modul-Setup
fuehrt einmalig ``alembic upgrade head`` aus - andere Tests im Repo
(z.B. ``test_migrations_roundtrip``) laufen unabhaengig und im
alphabetischen Sort *nach* ``test_api_overrides``, deshalb darf dieses
Modul nicht voraussetzen, dass die DB schon migriert ist.

Skip lokal, wenn ``DATABASE_URL`` nicht gesetzt ist.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, text

from heizung.main import app

DATABASE_URL = os.environ.get("DATABASE_URL")
DATABASE_URL_PRESENT = bool(DATABASE_URL)
SKIP_REASON = "DATABASE_URL nicht gesetzt - API-Tests brauchen Test-DB"


def _sync_url() -> str:
    assert DATABASE_URL is not None
    return DATABASE_URL.replace("+asyncpg", "")


@pytest.fixture(scope="module", autouse=True)
def _migrate_db() -> None:
    """Stellt sicher, dass die Test-DB einmal pro Modul auf alembic head ist."""
    if not DATABASE_URL_PRESENT:
        return
    backend_root = Path(__file__).resolve().parents[1]
    cfg = Config(str(backend_root / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend_root / "alembic"))
    cfg.set_main_option("sqlalchemy.url", DATABASE_URL or "")
    command.upgrade(cfg, "head")


@pytest.fixture
def http_client() -> Iterator[TestClient]:
    if not DATABASE_URL_PRESENT:
        pytest.skip(SKIP_REASON)
    with TestClient(app) as client:
        yield client


@pytest.fixture
def room_id() -> Iterator[int]:
    """RoomType + Room ueber Sync-Engine, getrennter Pool vom App-Engine."""
    if not DATABASE_URL_PRESENT:
        pytest.skip(SKIP_REASON)

    engine = create_engine(_sync_url())
    suffix = datetime.now(tz=UTC).strftime("%H%M%S%f")

    with engine.begin() as conn:
        rt_id = conn.execute(
            text(
                "INSERT INTO room_type (name, default_t_occupied, default_t_vacant,"
                " default_t_night) VALUES (:n, 21.0, 18.0, 19.0) RETURNING id"
            ),
            {"n": f"t9-9-api-{suffix}"},
        ).scalar_one()
        rid = conn.execute(
            text(
                "INSERT INTO room (number, room_type_id, status)"
                " VALUES (:num, :rt, 'vacant') RETURNING id"
            ),
            {"num": f"t9-9-api-{suffix}", "rt": rt_id},
        ).scalar_one()

    try:
        yield int(rid)
    finally:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM manual_override WHERE room_id = :r"), {"r": rid})
            conn.execute(text("DELETE FROM occupancy WHERE room_id = :r"), {"r": rid})
            conn.execute(text("DELETE FROM room WHERE id = :r"), {"r": rid})
            conn.execute(text("DELETE FROM room_type WHERE id = :r"), {"r": rt_id})
        engine.dispose()


@pytest.fixture
def room_with_occupancy(room_id: int) -> int:
    """Erweiterter Setup: Raum mit aktiver Belegung. Cleanup faellt durch
    den ON-DELETE-CASCADE im ``room_id``-Teardown weg."""
    engine = create_engine(_sync_url())
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO occupancy (room_id, check_in, check_out, is_active)"
                " VALUES (:r, :ci, :co, true)"
            ),
            {
                "r": room_id,
                "ci": datetime.now(tz=UTC) + timedelta(hours=1),
                "co": datetime.now(tz=UTC) + timedelta(days=2),
            },
        )
    engine.dispose()
    return room_id


# ---------------------------------------------------------------------------
# POST /rooms/{room_id}/overrides
# ---------------------------------------------------------------------------


def test_post_frontend_4h_returns_201(http_client: TestClient, room_id: int) -> None:
    before = datetime.now(tz=UTC)
    resp = http_client.post(
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
    assert timedelta(hours=3, minutes=55) < delta < timedelta(hours=4, minutes=5)


def test_post_frontend_checkout_without_occupancy_returns_422(
    http_client: TestClient, room_id: int
) -> None:
    resp = http_client.post(
        f"/api/v1/rooms/{room_id}/overrides",
        json={"setpoint": "22.0", "source": "frontend_checkout"},
    )
    assert resp.status_code == 422, resp.text


def test_post_setpoint_above_max_returns_422(http_client: TestClient, room_id: int) -> None:
    resp = http_client.post(
        f"/api/v1/rooms/{room_id}/overrides",
        json={"setpoint": "35.0", "source": "frontend_4h"},
    )
    assert resp.status_code == 422, resp.text


def test_post_source_device_returns_422(http_client: TestClient, room_id: int) -> None:
    resp = http_client.post(
        f"/api/v1/rooms/{room_id}/overrides",
        json={"setpoint": "22.0", "source": "device"},
    )
    assert resp.status_code == 422, resp.text


def test_post_unknown_room_returns_404(http_client: TestClient) -> None:
    resp = http_client.post(
        "/api/v1/rooms/9999999/overrides",
        json={"setpoint": "22.0", "source": "frontend_4h"},
    )
    assert resp.status_code == 404, resp.text


# ---------------------------------------------------------------------------
# GET /rooms/{room_id}/overrides
# ---------------------------------------------------------------------------


def test_get_history_includes_revoked(http_client: TestClient, room_id: int) -> None:
    create_resp = http_client.post(
        f"/api/v1/rooms/{room_id}/overrides",
        json={"setpoint": "22.0", "source": "frontend_4h"},
    )
    assert create_resp.status_code == 201
    override_id = create_resp.json()["id"]
    revoke_resp = http_client.request(
        "DELETE",
        f"/api/v1/overrides/{override_id}",
        json={"revoked_reason": "test cleanup"},
    )
    assert revoke_resp.status_code == 200

    list_resp = http_client.get(f"/api/v1/rooms/{room_id}/overrides")
    assert list_resp.status_code == 200
    items = list_resp.json()
    assert len(items) >= 1
    assert any(item["id"] == override_id and item["revoked_at"] is not None for item in items)


# ---------------------------------------------------------------------------
# DELETE /overrides/{override_id}
# ---------------------------------------------------------------------------


def test_delete_then_double_revoke_returns_409(http_client: TestClient, room_id: int) -> None:
    create_resp = http_client.post(
        f"/api/v1/rooms/{room_id}/overrides",
        json={"setpoint": "22.0", "source": "frontend_4h"},
    )
    override_id = create_resp.json()["id"]

    first = http_client.request(
        "DELETE",
        f"/api/v1/overrides/{override_id}",
        json={"revoked_reason": "erstmal"},
    )
    assert first.status_code == 200, first.text
    assert first.json()["revoked_at"] is not None

    second = http_client.request(
        "DELETE",
        f"/api/v1/overrides/{override_id}",
        json={"revoked_reason": "zweites mal"},
    )
    assert second.status_code == 409, second.text


def test_delete_unknown_override_returns_404(http_client: TestClient) -> None:
    resp = http_client.request("DELETE", "/api/v1/overrides/9999999")
    assert resp.status_code == 404, resp.text
