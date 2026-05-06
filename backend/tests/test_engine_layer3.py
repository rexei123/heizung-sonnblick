"""Sprint 9.9 T3 - Engine Layer 3 (Manual Override) Integrations-Tests.

Pruft, dass ``layer_manual_override`` in den ``evaluate_room``-Pipeline-
Stack zwischen Layer 2 und Layer 5 korrekt eingehaengt ist und dass
Engine-Trace-Eintrage die Override-Metadaten enthalten.

DB-Tests skippen ohne ``TEST_DATABASE_URL``.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from heizung.models.enums import EventLogLayer, OverrideSource
from heizung.models.room import Room
from heizung.models.room_type import RoomType
from heizung.rules.engine import LayerStep, evaluate_room
from heizung.services import override_service

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


@pytest_asyncio.fixture
async def room_id(db_session: AsyncSession) -> AsyncIterator[int]:
    """RoomType + Room. Default-Status vacant -> Layer 1 = t_vacant = 18 degC."""
    suffix = datetime.now(tz=UTC).strftime("%H%M%S%f")
    rt = RoomType(name=f"t9-9-l3-{suffix}")
    db_session.add(rt)
    await db_session.flush()
    room = Room(number=f"t9-9-l3-{suffix}", room_type_id=rt.id)
    db_session.add(room)
    await db_session.flush()
    yield room.id


def _layer3(result_layers: tuple[LayerStep, ...]) -> LayerStep:
    """Helper: extrahiert den MANUAL_OVERRIDE-LayerStep aus result.layers."""
    matches = [layer for layer in result_layers if layer.layer == EventLogLayer.MANUAL_OVERRIDE]
    assert len(matches) == 1, f"erwarte genau 1 Layer-3-Eintrag, gefunden {len(matches)}"
    return matches[0]


def _layer5(result_layers: tuple[LayerStep, ...]) -> LayerStep:
    matches = [layer for layer in result_layers if layer.layer == EventLogLayer.HARD_CLAMP]
    assert len(matches) == 1, f"erwarte genau 1 Layer-5-Eintrag, gefunden {len(matches)}"
    return matches[0]


# ---------------------------------------------------------------------------
# Test 1 - No-op: kein aktiver Override -> Setpoint = Layer-2-Output
# ---------------------------------------------------------------------------


async def test_layer3_no_op_passes_through(db_session: AsyncSession, room_id: int) -> None:
    result = await evaluate_room(db_session, room_id)
    assert result is not None
    # Default vacant -> 18 degC, Layer 5 in [5,30] = 18.
    assert result.setpoint_c == 18
    layer3 = _layer3(result.layers)
    assert layer3.setpoint_c == 18
    assert layer3.extras == {"source": None, "expires_at": None, "override_id": None}


# ---------------------------------------------------------------------------
# Test 2 - Override aktiv: Override-Setpoint ueberschreibt
# ---------------------------------------------------------------------------


async def test_layer3_active_override_wins(db_session: AsyncSession, room_id: int) -> None:
    expires = datetime.now(tz=UTC) + timedelta(hours=4)
    o = await override_service.create(
        db_session,
        room_id=room_id,
        setpoint=Decimal("23.0"),
        source=OverrideSource.DEVICE,
        expires_at=expires,
    )
    result = await evaluate_room(db_session, room_id)
    assert result is not None
    assert result.setpoint_c == 23
    layer3 = _layer3(result.layers)
    assert layer3.setpoint_c == 23
    assert layer3.extras is not None
    assert layer3.extras["source"] == "device"
    assert layer3.extras["override_id"] == o.id


# ---------------------------------------------------------------------------
# Test 3 - Trace: extras enthalten source + expires_at + override_id
# ---------------------------------------------------------------------------


async def test_layer3_trace_extras_complete(db_session: AsyncSession, room_id: int) -> None:
    expires = datetime.now(tz=UTC) + timedelta(hours=2)
    o = await override_service.create(
        db_session,
        room_id=room_id,
        setpoint=Decimal("22.0"),
        source=OverrideSource.FRONTEND_4H,
        expires_at=expires,
        reason="Live-QA",
    )
    result = await evaluate_room(db_session, room_id)
    assert result is not None
    layer3 = _layer3(result.layers)
    assert layer3.extras is not None
    assert layer3.extras["source"] == "frontend_4h"
    assert layer3.extras["expires_at"] == o.expires_at.isoformat()
    assert layer3.extras["override_id"] == o.id


# ---------------------------------------------------------------------------
# Test 4 - Layer-Reihenfolge: Layer 5 clampt auf room_type.max_temp_celsius
# ---------------------------------------------------------------------------


async def test_layer5_clamps_above_room_type_max(
    db_session: AsyncSession, room_id: int
) -> None:
    """``room_type.max_temp_celsius=22`` + Override 25 -> Layer 5 cappt auf 22."""
    room = await db_session.get(Room, room_id)
    assert room is not None
    room_type = await db_session.get(RoomType, room.room_type_id)
    assert room_type is not None
    room_type.max_temp_celsius = Decimal("22.0")
    await db_session.flush()

    expires = datetime.now(tz=UTC) + timedelta(hours=4)
    await override_service.create(
        db_session,
        room_id=room_id,
        setpoint=Decimal("25.0"),
        source=OverrideSource.DEVICE,
        expires_at=expires,
    )

    result = await evaluate_room(db_session, room_id)
    assert result is not None
    layer3 = _layer3(result.layers)
    layer5 = _layer5(result.layers)
    assert layer3.setpoint_c == 25, "Layer 3 muss den Override-Setpoint vor Clamp tragen"
    assert layer5.setpoint_c == 22, "Layer 5 muss auf room_type.max=22 cappen"
    assert result.setpoint_c == 22


# ---------------------------------------------------------------------------
# Test 5 - Revoked Override wird ignoriert
# ---------------------------------------------------------------------------


async def test_layer3_revoked_override_ignored(
    db_session: AsyncSession, room_id: int
) -> None:
    expires = datetime.now(tz=UTC) + timedelta(hours=4)
    o = await override_service.create(
        db_session,
        room_id=room_id,
        setpoint=Decimal("23.0"),
        source=OverrideSource.DEVICE,
        expires_at=expires,
    )
    await override_service.revoke(db_session, o.id, reason="test")

    result = await evaluate_room(db_session, room_id)
    assert result is not None
    layer3 = _layer3(result.layers)
    assert layer3.extras is not None
    assert layer3.extras["source"] is None, "Revoked Override darf Layer 3 nicht aktivieren"
    assert layer3.setpoint_c == 18, "Layer 3 reicht t_vacant=18 unveraendert durch"
    assert result.setpoint_c == 18
