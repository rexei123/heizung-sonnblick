"""Sprint 9.10 T2 — Engine Layer 4 (Window-Detection) Integrations-Tests.

Prueft, dass ``layer_window_open`` korrekt zwischen Layer 3 (Manual)
und Layer 5 (Clamp) eingehaengt ist und dass:
- ein frisches Reading mit ``open_window=True`` Layer 4 aktiviert,
- veraltete Readings ignoriert werden,
- mehrere Zonen korrekt aufgelistet werden,
- ``occupancy_state`` aus ``room.status`` abgeleitet wird.

DB-Tests skippen ohne ``TEST_DATABASE_URL``.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from heizung.models.device import Device
from heizung.models.enums import (
    CommandReason,
    DeviceKind,
    DeviceVendor,
    EventLogLayer,
    HeatingZoneKind,
    OverrideSource,
    RoomStatus,
)
from heizung.models.heating_zone import HeatingZone
from heizung.models.manual_override import ManualOverride
from heizung.models.room import Room
from heizung.models.room_type import RoomType
from heizung.models.sensor_reading import SensorReading
from heizung.rules.engine import (
    MIN_SETPOINT_C,
    WINDOW_STALE_THRESHOLD_MIN,
    LayerStep,
    evaluate_room,
)

TEST_DB_URL = os.environ.get("TEST_DATABASE_URL")
SKIP_REASON = "TEST_DATABASE_URL nicht gesetzt - DB-Tests brauchen Postgres"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


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
async def setup_room(db_session: AsyncSession) -> AsyncIterator[dict[str, int]]:
    """Raum + 1 Zone + 1 Device. Default-Status vacant -> Layer 1 = 18 degC.

    Suffix per UUID-Hex: room.number ist String(20), dev_eui String(16) —
    8 Hex-Zeichen reichen fuer Test-Eindeutigkeit innerhalb der Session.
    """
    suffix = uuid.uuid4().hex[:8]
    rt = RoomType(name=f"l4-rt-{suffix}")
    db_session.add(rt)
    await db_session.flush()

    room = Room(number=f"l4-{suffix}", room_type_id=rt.id)
    db_session.add(room)
    await db_session.flush()

    zone = HeatingZone(
        room_id=room.id,
        kind=HeatingZoneKind.BEDROOM,
        name="bedroom",
    )
    db_session.add(zone)
    await db_session.flush()

    device = Device(
        dev_eui=f"deadbeef{suffix}",
        kind=DeviceKind.THERMOSTAT,
        vendor=DeviceVendor.MCLIMATE,
        model="vicki",
        heating_zone_id=zone.id,
        # Sprint 11 T3: Layer 4 aggregiert nur ueber healthy Devices.
        health_state="healthy",
    )
    db_session.add(device)
    await db_session.flush()

    yield {"room_id": room.id, "zone_id": zone.id, "device_id": device.id}


def _layer4(result_layers: tuple[LayerStep, ...]) -> LayerStep:
    matches = [layer for layer in result_layers if layer.layer == EventLogLayer.WINDOW_SAFETY]
    assert len(matches) == 1, f"erwarte genau 1 Layer-4-Eintrag, gefunden {len(matches)}"
    return matches[0]


def _layer5(result_layers: tuple[LayerStep, ...]) -> LayerStep:
    matches = [layer for layer in result_layers if layer.layer == EventLogLayer.HARD_CLAMP]
    assert len(matches) == 1, f"erwarte genau 1 Layer-5-Eintrag, gefunden {len(matches)}"
    return matches[0]


async def _add_reading(
    session: AsyncSession,
    *,
    device_id: int,
    open_window: bool | None,
    age_min: int,
) -> None:
    reading = SensorReading(
        time=datetime.now(tz=UTC) - timedelta(minutes=age_min),
        device_id=device_id,
        fcnt=1,
        temperature=Decimal("21.0"),
        open_window=open_window,
    )
    session.add(reading)
    await session.flush()


# ---------------------------------------------------------------------------
# Test 1 — Fresh open_window=True -> Layer 4 aktiv, Setpoint = MIN_SETPOINT_C
# ---------------------------------------------------------------------------


async def test_layer4_active_when_window_open_fresh(
    db_session: AsyncSession, setup_room: dict[str, int]
) -> None:
    await _add_reading(db_session, device_id=setup_room["device_id"], open_window=True, age_min=5)

    result = await evaluate_room(db_session, setup_room["room_id"])
    assert result is not None
    layer4 = _layer4(result.layers)
    assert layer4.setpoint_c == MIN_SETPOINT_C
    assert layer4.reason == CommandReason.WINDOW_OPEN
    assert layer4.extras is not None
    assert len(layer4.extras["open_zones"]) == 1
    assert layer4.extras["open_zones"][0]["zone_id"] == setup_room["zone_id"]
    # Layer 5 darf MIN_SETPOINT_C nicht unter sich pressen.
    assert result.setpoint_c == MIN_SETPOINT_C


# ---------------------------------------------------------------------------
# Test 2 — open_window=False -> passthrough, kein Eingriff
# ---------------------------------------------------------------------------


async def test_layer4_passthrough_when_window_closed(
    db_session: AsyncSession, setup_room: dict[str, int]
) -> None:
    await _add_reading(db_session, device_id=setup_room["device_id"], open_window=False, age_min=5)

    result = await evaluate_room(db_session, setup_room["room_id"])
    assert result is not None
    layer4 = _layer4(result.layers)
    # vacant default = 18 degC, Layer 4 reicht 18 unveraendert durch.
    assert layer4.setpoint_c == 18
    assert layer4.reason == CommandReason.VACANT_SETPOINT
    assert layer4.detail == "no_open_window"
    assert layer4.extras is not None
    assert layer4.extras["open_zones"] == []
    assert result.setpoint_c == 18


# ---------------------------------------------------------------------------
# Test 3 — Reading > 30 Min alt -> stale, Layer 4 ignoriert (passthrough)
# ---------------------------------------------------------------------------


async def test_layer4_stale_reading_is_ignored(
    db_session: AsyncSession, setup_room: dict[str, int]
) -> None:
    await _add_reading(
        db_session,
        device_id=setup_room["device_id"],
        open_window=True,  # waere AKTIV wenn frisch
        age_min=WINDOW_STALE_THRESHOLD_MIN + 5,
    )

    result = await evaluate_room(db_session, setup_room["room_id"])
    assert result is not None
    layer4 = _layer4(result.layers)
    assert layer4.setpoint_c == 18
    assert layer4.detail == "stale_reading"
    assert layer4.extras is not None
    assert layer4.extras["open_zones"] == []


# ---------------------------------------------------------------------------
# Test 4 — Kein Reading vorhanden -> passthrough mit detail "no_readings"
# ---------------------------------------------------------------------------


async def test_layer4_no_readings_is_passthrough(
    db_session: AsyncSession, setup_room: dict[str, int]
) -> None:
    result = await evaluate_room(db_session, setup_room["room_id"])
    assert result is not None
    layer4 = _layer4(result.layers)
    assert layer4.setpoint_c == 18
    assert layer4.detail == "no_readings"


# ---------------------------------------------------------------------------
# Test 5 — Mehrere Zonen, eine offen -> open_zones listet nur die offene
# ---------------------------------------------------------------------------


async def test_layer4_only_open_zones_listed(
    db_session: AsyncSession, setup_room: dict[str, int]
) -> None:
    suffix2 = uuid.uuid4().hex[:8]
    # Zweite Zone + Device im selben Raum, Fenster ZU.
    zone2 = HeatingZone(
        room_id=setup_room["room_id"],
        kind=HeatingZoneKind.BATHROOM,
        name="bathroom",
    )
    db_session.add(zone2)
    await db_session.flush()
    device2 = Device(
        dev_eui=f"cafef00d{suffix2}",
        kind=DeviceKind.THERMOSTAT,
        vendor=DeviceVendor.MCLIMATE,
        model="vicki",
        heating_zone_id=zone2.id,
        # Sprint 11 T3: Layer 4 aggregiert nur ueber healthy Devices.
        health_state="healthy",
    )
    db_session.add(device2)
    await db_session.flush()

    # Zone 1 = Fenster offen, Zone 2 = Fenster zu.
    await _add_reading(db_session, device_id=setup_room["device_id"], open_window=True, age_min=2)
    await _add_reading(db_session, device_id=device2.id, open_window=False, age_min=2)

    result = await evaluate_room(db_session, setup_room["room_id"])
    assert result is not None
    layer4 = _layer4(result.layers)
    assert layer4.setpoint_c == MIN_SETPOINT_C
    assert layer4.extras is not None
    open_ids = [z["zone_id"] for z in layer4.extras["open_zones"]]
    assert open_ids == [setup_room["zone_id"]], "nur die OFFENE Zone darf gelistet sein"


# ---------------------------------------------------------------------------
# Test 6 — occupancy_state spiegelt room.status (occupied vs vacant)
# ---------------------------------------------------------------------------


async def test_layer4_occupancy_state_reflects_room_status(
    db_session: AsyncSession, setup_room: dict[str, int]
) -> None:
    """Sprint 12 T3 (AE-52) erweitert: ``occupancy_state`` in extras
    spiegelt nicht nur ``room.status``, sondern entscheidet auch den
    Setpoint bei Fenster offen. Test prueft Setpoint UND
    setpoint_source pro Pfad (§5.20-Drift-Vermeidung: kein semantisch
    verwaister Test, der nur einen Marker prueft waehrend das
    Verhalten daran haengt).
    """
    await _add_reading(db_session, device_id=setup_room["device_id"], open_window=True, age_min=2)

    # 6a: vacant + open -> Frostschutz (MIN_SETPOINT_C=10)
    result = await evaluate_room(db_session, setup_room["room_id"])
    assert result is not None
    layer4 = _layer4(result.layers)
    assert layer4.extras is not None
    assert layer4.extras["occupancy_state"] == "vacant"
    assert layer4.setpoint_c == MIN_SETPOINT_C
    assert layer4.extras["setpoint_source"] == "frost_protection"

    # 6b: occupied + open -> default_t_vacant Setback (18 degC default)
    room = await db_session.get(Room, setup_room["room_id"])
    assert room is not None
    room.status = RoomStatus.OCCUPIED
    await db_session.flush()

    result2 = await evaluate_room(db_session, setup_room["room_id"])
    assert result2 is not None
    layer4_b = _layer4(result2.layers)
    assert layer4_b.extras is not None
    assert layer4_b.extras["occupancy_state"] == "occupied"
    assert layer4_b.setpoint_c == 18
    assert layer4_b.extras["setpoint_source"] == "default_t_vacant"


# ---------------------------------------------------------------------------
# Test 7 — open_window=NULL (alter Codec) wird wie False behandelt
# ---------------------------------------------------------------------------


async def test_layer4_null_open_window_is_treated_as_closed(
    db_session: AsyncSession, setup_room: dict[str, int]
) -> None:
    await _add_reading(db_session, device_id=setup_room["device_id"], open_window=None, age_min=2)
    result = await evaluate_room(db_session, setup_room["room_id"])
    assert result is not None
    layer4 = _layer4(result.layers)
    assert layer4.setpoint_c == 18
    assert layer4.detail == "no_open_window"


# ---------------------------------------------------------------------------
# Sprint 12 T3 (AE-52) — room_status entscheidet Setpoint bei Fenster offen
# ---------------------------------------------------------------------------


async def test_layer4_closed_occupied_passthrough(
    db_session: AsyncSession, setup_room: dict[str, int]
) -> None:
    """T3 (b): Fenster zu + OCCUPIED -> Pass-Through, kein Eingriff.

    Layer 4 reicht prev_setpoint (= OCCUPIED-Base 21 degC default) und
    prev_reason unveraendert durch. setpoint_source ist NICHT gesetzt
    (kein open_zones-Pfad), occupancy_state == "occupied".
    """
    room = await db_session.get(Room, setup_room["room_id"])
    assert room is not None
    room.status = RoomStatus.OCCUPIED
    await db_session.flush()

    await _add_reading(db_session, device_id=setup_room["device_id"], open_window=False, age_min=2)
    result = await evaluate_room(db_session, setup_room["room_id"])
    assert result is not None
    layer4 = _layer4(result.layers)
    # OCCUPIED-Base = default_t_occupied = 21 degC. Layer 4 = Pass-Through.
    assert layer4.setpoint_c == 21
    assert layer4.reason == CommandReason.OCCUPIED_SETPOINT
    assert layer4.detail == "no_open_window"
    assert layer4.extras is not None
    assert layer4.extras["open_zones"] == []
    assert layer4.extras["occupancy_state"] == "occupied"
    # Setback-Pfad nicht durchlaufen -> kein setpoint_source-Eintrag.
    assert "setpoint_source" not in layer4.extras


async def test_layer4_open_occupied_setback_to_default_t_vacant(
    db_session: AsyncSession, setup_room: dict[str, int]
) -> None:
    """T3 (d): Fenster offen + OCCUPIED -> Setpoint=default_t_vacant
    (AE-52 Setback, NICHT 10 degC Frostschutz). reason bleibt WINDOW_OPEN,
    detail-Prefix differenziert.
    """
    room = await db_session.get(Room, setup_room["room_id"])
    assert room is not None
    room.status = RoomStatus.OCCUPIED
    await db_session.flush()

    await _add_reading(db_session, device_id=setup_room["device_id"], open_window=True, age_min=2)
    result = await evaluate_room(db_session, setup_room["room_id"])
    assert result is not None
    layer4 = _layer4(result.layers)
    # default_t_vacant = 18 degC im RoomType-Default (D2-Fix:
    # NICHT free_target_c, das Feld existiert nicht).
    assert layer4.setpoint_c == 18
    assert layer4.reason == CommandReason.WINDOW_OPEN
    assert layer4.detail is not None
    assert layer4.detail.startswith("window_open_room_occupied_setback ")
    assert "open_zones=" in layer4.detail
    assert layer4.extras is not None
    assert layer4.extras["setpoint_source"] == "default_t_vacant"
    assert layer4.extras["occupancy_state"] == "occupied"
    assert layer4.extras["override_overridden_by_window_open"] is False
    # Layer 5 Clamp laesst 18 unveraendert (innerhalb [MIN, MAX]).
    assert result.setpoint_c == 18


async def test_layer4_open_occupied_masks_active_manual_override(
    db_session: AsyncSession, setup_room: dict[str, int]
) -> None:
    """T3 (e): Fenster offen + OCCUPIED + aktiver Manual-Override
    -> Layer 4 ueberschreibt den Override mit default_t_vacant.

    Verifiziert die Override-Maskierungs-Logik aus AE-52 (Gast lernt
    "Drehen am Vicki bringt nichts"). Marker im Layer-4-detail und
    extras["override_overridden_by_window_open"] = True. Der Override
    selbst bleibt in der Datenbank — Layer 3 Trace zeigt ihn als aktiv,
    Layer 4 dokumentiert die Maskierung.
    """
    room = await db_session.get(Room, setup_room["room_id"])
    assert room is not None
    room.status = RoomStatus.OCCUPIED
    await db_session.flush()

    # Aktiver Manual-Override (setpoint 24 — Gast hat hochgedreht)
    now = datetime.now(tz=UTC)
    override = ManualOverride(
        room_id=setup_room["room_id"],
        setpoint=Decimal("24.0"),
        source=OverrideSource.DEVICE,
        expires_at=now + timedelta(hours=4),
    )
    db_session.add(override)
    await db_session.flush()

    await _add_reading(db_session, device_id=setup_room["device_id"], open_window=True, age_min=2)

    result = await evaluate_room(db_session, setup_room["room_id"])
    assert result is not None

    # Layer 3 muss den Override gesehen haben — prev_reason fuer Layer 4
    # ist CommandReason.MANUAL.
    layer3 = next(layer for layer in result.layers if layer.layer == EventLogLayer.MANUAL_OVERRIDE)
    assert layer3.setpoint_c == 24
    assert layer3.reason == CommandReason.MANUAL

    # Layer 4 ueberschreibt: setpoint = default_t_vacant, NICHT 24 (Override)
    # und NICHT 10 (Frost — das waere VACANT-Pfad).
    layer4 = _layer4(result.layers)
    assert layer4.setpoint_c == 18
    assert layer4.reason == CommandReason.WINDOW_OPEN
    assert layer4.detail is not None
    assert layer4.detail.startswith(
        "override_overridden_by_window_open window_open_room_occupied_setback "
    )
    assert layer4.extras is not None
    assert layer4.extras["override_overridden_by_window_open"] is True
    assert layer4.extras["setpoint_source"] == "default_t_vacant"

    # Finale Engine-Entscheidung -> 18 degC, Override-Setpoint 24 hat keinen Effekt.
    assert result.setpoint_c == 18
