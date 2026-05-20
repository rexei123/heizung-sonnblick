"""Sprint 9.9 T2 - override_service-Tests.

Pure-Function-Tests fuer ``compute_expires_at`` laufen ohne DB. Die
restlichen Tests nutzen ein async ``db_session``-Fixture und skippen,
wenn ``TEST_DATABASE_URL`` nicht gesetzt ist.

§5.51 Domain-Invariante (Sprint 12c, AE-58): Block-Check liegt VOR
OCCUPIED-Check. Ein Zimmer mit ``guest_override_blocked=True`` wirft
``RoomOverrideBlockedError`` unabhaengig vom Belegungs-Status — auch wenn
es VACANT, CLEANING oder BLOCKED ist. Die Sperre hat Vorrang vor dem
Sprint-12a-OCCUPIED-Gate.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from heizung.models.enums import OverrideSource, RoomStatus
from heizung.models.global_config import GlobalConfig
from heizung.models.manual_override import ManualOverride
from heizung.models.occupancy import Occupancy
from heizung.models.room import Room
from heizung.models.room_type import RoomType
from heizung.services import override_service

TEST_DB_URL = os.environ.get("TEST_DATABASE_URL")
SKIP_REASON = "TEST_DATABASE_URL nicht gesetzt - DB-Tests brauchen Postgres"


# ---------------------------------------------------------------------------
# Pure-Function-Tests fuer compute_expires_at (kein DB)
# ---------------------------------------------------------------------------


def test_compute_expires_at_frontend_4h() -> None:
    now = datetime(2026, 5, 6, 12, 0, tzinfo=UTC)
    result = override_service.compute_expires_at(OverrideSource.FRONTEND_4H, now)
    assert result == now + timedelta(hours=4)


def test_compute_expires_at_frontend_midnight_default_tz() -> None:
    """Default-Timezone Europe/Vienna. Mai = CEST (UTC+2). 23:59 lokal = 21:59 UTC."""
    now = datetime(2026, 5, 6, 12, 0, tzinfo=UTC)
    result = override_service.compute_expires_at(OverrideSource.FRONTEND_MIDNIGHT, now)
    expected = datetime(2026, 5, 6, 23, 59, tzinfo=ZoneInfo("Europe/Vienna"))
    assert result == expected.astimezone(UTC)


def test_compute_expires_at_frontend_midnight_with_hotel_config() -> None:
    """``hotel_config.timezone = 'UTC'`` -> 23:59 UTC heute."""
    now = datetime(2026, 5, 6, 12, 0, tzinfo=UTC)
    cfg = GlobalConfig(id=1, timezone="UTC")
    result = override_service.compute_expires_at(
        OverrideSource.FRONTEND_MIDNIGHT, now, hotel_config=cfg
    )
    assert result == datetime(2026, 5, 6, 23, 59, tzinfo=UTC)


def test_compute_expires_at_frontend_checkout_with_next() -> None:
    now = datetime(2026, 5, 6, 12, 0, tzinfo=UTC)
    next_co = datetime(2026, 5, 8, 11, 0, tzinfo=UTC)
    result = override_service.compute_expires_at(
        OverrideSource.FRONTEND_CHECKOUT, now, next_checkout_at=next_co
    )
    assert result == next_co


def test_compute_expires_at_device_with_next() -> None:
    now = datetime(2026, 5, 6, 12, 0, tzinfo=UTC)
    next_co = datetime(2026, 5, 8, 11, 0, tzinfo=UTC)
    result = override_service.compute_expires_at(
        OverrideSource.DEVICE, now, next_checkout_at=next_co
    )
    assert result == next_co


def test_compute_expires_at_caps_when_next_checkout_too_far() -> None:
    """Hard-Cap greift, auch wenn next_checkout in 10 Tagen liegt."""
    now = datetime(2026, 5, 6, 12, 0, tzinfo=UTC)
    next_co = now + timedelta(days=10)
    result = override_service.compute_expires_at(
        OverrideSource.FRONTEND_CHECKOUT, now, next_checkout_at=next_co
    )
    assert result == now + timedelta(days=7)


# Sprint 12a T2: Fallback-Pfad ``next_checkout_at=None`` ist tot (OCCUPIED-Gate).
# Defensive Pflicht: compute_expires_at raises bei FRONTEND_CHECKOUT/DEVICE +
# None — kein stiller 7d-Cap.
def test_compute_expires_at_frontend_checkout_without_next_raises() -> None:
    now = datetime(2026, 5, 6, 12, 0, tzinfo=UTC)
    with pytest.raises(ValueError, match="next_checkout_at darf nicht None sein"):
        override_service.compute_expires_at(OverrideSource.FRONTEND_CHECKOUT, now)


def test_compute_expires_at_device_without_next_raises() -> None:
    now = datetime(2026, 5, 6, 12, 0, tzinfo=UTC)
    with pytest.raises(ValueError, match="next_checkout_at darf nicht None sein"):
        override_service.compute_expires_at(OverrideSource.DEVICE, now)


def test_compute_expires_at_hard_max_caps_device() -> None:
    """Sprint 12a T2: HARD_MAX (7 Tage) gilt auch fuer DEVICE bei langem checkout."""
    now = datetime(2026, 5, 6, 12, 0, tzinfo=UTC)
    far_checkout = now + timedelta(days=14)
    result = override_service.compute_expires_at(
        OverrideSource.DEVICE, now, next_checkout_at=far_checkout
    )
    assert result == now + timedelta(days=7)


# ---------------------------------------------------------------------------
# DB-Tests (async fixture, skip ohne TEST_DATABASE_URL)
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
async def room_id(db_session: AsyncSession) -> AsyncIterator[int]:
    """RoomType + Room + aktive Belegung -> OCCUPIED.

    Sprint 12a T2 (AE-58): ``override_service.create`` verlangt
    OCCUPIED-Status. Test-Default ist eine aktive Belegung (check_in vor
    now, check_out > now+1d), damit alle Bestandstests ohne Logik-Aenderung
    durch das OCCUPIED-Gate kommen. ``derive_room_status`` liest aus
    aktiven Occupancies — kein expliziter ``room.status``-Set noetig.

    Aufraeumen via ``session.rollback`` (db_session-Fixture).
    """
    suffix = datetime.now(tz=UTC).strftime("%H%M%S%f")
    rt = RoomType(name=f"t9-9-svc-{suffix}")
    db_session.add(rt)
    await db_session.flush()
    room = Room(number=f"t9-9-{suffix}", room_type_id=rt.id)
    db_session.add(room)
    await db_session.flush()
    now = datetime.now(tz=UTC)
    occ = Occupancy(
        room_id=room.id,
        check_in=now - timedelta(hours=2),
        check_out=now + timedelta(days=2),
        is_active=True,
    )
    db_session.add(occ)
    await db_session.flush()
    yield room.id


@pytest_asyncio.fixture
async def vacant_room_id(db_session: AsyncSession) -> AsyncIterator[int]:
    """RoomType + Room ohne Belegung -> VACANT (Default-Status).

    Sprint 12a T2: dediziert fuer OCCUPIED-Gate-Negative-Test
    (``RoomNotOccupiedError``).
    """
    suffix = datetime.now(tz=UTC).strftime("%H%M%S%f")
    rt = RoomType(name=f"t12-vac-{suffix}")
    db_session.add(rt)
    await db_session.flush()
    # Prefix ``t12-v-`` ist 6 chars; mit 12-char strftime-Suffix = 18 chars
    # (innerhalb VARCHAR(20), §5.49).
    room = Room(number=f"t12-v-{suffix}", room_type_id=rt.id)
    db_session.add(room)
    await db_session.flush()
    yield room.id


async def test_create_quantizes_setpoint(db_session: AsyncSession, room_id: int) -> None:
    expires = datetime.now(tz=UTC) + timedelta(hours=4)
    o = await override_service.create(
        db_session,
        room_id=room_id,
        setpoint=Decimal("21.55"),
        source=OverrideSource.FRONTEND_4H,
        expires_at=expires,
    )
    assert o.setpoint == Decimal("21.6")


async def test_create_rejects_setpoint_below_min(db_session: AsyncSession, room_id: int) -> None:
    expires = datetime.now(tz=UTC) + timedelta(hours=4)
    with pytest.raises(ValueError):
        await override_service.create(
            db_session,
            room_id=room_id,
            setpoint=Decimal("4.9"),
            source=OverrideSource.FRONTEND_4H,
            expires_at=expires,
        )


async def test_create_rejects_setpoint_above_max(db_session: AsyncSession, room_id: int) -> None:
    expires = datetime.now(tz=UTC) + timedelta(hours=4)
    with pytest.raises(ValueError):
        await override_service.create(
            db_session,
            room_id=room_id,
            setpoint=Decimal("30.1"),
            source=OverrideSource.FRONTEND_4H,
            expires_at=expires,
        )


async def test_create_caps_long_expires_at(db_session: AsyncSession, room_id: int) -> None:
    """``expires_at > now+7d`` wird hart auf ``now+7d`` gecappt."""
    far_future = datetime.now(tz=UTC) + timedelta(days=30)
    o = await override_service.create(
        db_session,
        room_id=room_id,
        setpoint=Decimal("21.0"),
        source=OverrideSource.DEVICE,
        expires_at=far_future,
    )
    assert o.expires_at <= datetime.now(tz=UTC) + timedelta(days=7, seconds=1)


async def test_get_active_returns_only_non_revoked(db_session: AsyncSession, room_id: int) -> None:
    """Revokierter Override wird uebersprungen; aktiver gewinnt."""
    expires = datetime.now(tz=UTC) + timedelta(hours=4)
    revoked = await override_service.create(
        db_session,
        room_id=room_id,
        setpoint=Decimal("20.0"),
        source=OverrideSource.FRONTEND_4H,
        expires_at=expires,
    )
    await override_service.revoke(db_session, revoked.id, reason="test")
    active = await override_service.create(
        db_session,
        room_id=room_id,
        setpoint=Decimal("22.0"),
        source=OverrideSource.FRONTEND_4H,
        expires_at=expires,
    )
    found = await override_service.get_active(db_session, room_id)
    assert found is not None
    assert found.id == active.id
    assert found.setpoint == Decimal("22.0")


async def test_get_active_returns_none_if_all_revoked(
    db_session: AsyncSession, room_id: int
) -> None:
    expires = datetime.now(tz=UTC) + timedelta(hours=4)
    o = await override_service.create(
        db_session,
        room_id=room_id,
        setpoint=Decimal("21.0"),
        source=OverrideSource.FRONTEND_4H,
        expires_at=expires,
    )
    await override_service.revoke(db_session, o.id, reason="test")
    active = await override_service.get_active(db_session, room_id)
    assert active is None


async def test_get_active_returns_none_if_all_expired(
    db_session: AsyncSession, room_id: int
) -> None:
    """Override mit ``expires_at < now`` zaehlt nicht als aktiv."""
    past = datetime.now(tz=UTC) - timedelta(hours=1)
    o = ManualOverride(
        room_id=room_id,
        setpoint=Decimal("21.0"),
        source=OverrideSource.FRONTEND_4H,
        expires_at=past,
    )
    db_session.add(o)
    await db_session.flush()
    active = await override_service.get_active(db_session, room_id)
    assert active is None


async def test_revoke_double_raises(db_session: AsyncSession, room_id: int) -> None:
    expires = datetime.now(tz=UTC) + timedelta(hours=4)
    o = await override_service.create(
        db_session,
        room_id=room_id,
        setpoint=Decimal("21.0"),
        source=OverrideSource.FRONTEND_4H,
        expires_at=expires,
    )
    await override_service.revoke(db_session, o.id, reason="erstmal")
    with pytest.raises(ValueError):
        await override_service.revoke(db_session, o.id, reason="zweites mal")


async def test_revoke_all_active_overrides_revokes_device_and_frontend(
    db_session: AsyncSession, room_id: int
) -> None:
    """Sprint 12a T2 (AE-58): revoke_all_active_overrides revoked ALLE Quellen.

    Ersetzt ``revoke_device_overrides`` ersatzlos — neuer Vertrag: Check-out
    revoked DEVICE und FRONTEND_* in einem Aufruf.
    """
    expires = datetime.now(tz=UTC) + timedelta(hours=4)
    device = await override_service.create(
        db_session,
        room_id=room_id,
        setpoint=Decimal("23.0"),
        source=OverrideSource.DEVICE,
        expires_at=expires,
    )
    frontend = await override_service.create(
        db_session,
        room_id=room_id,
        setpoint=Decimal("21.0"),
        source=OverrideSource.FRONTEND_4H,
        expires_at=expires,
    )
    count = await override_service.revoke_all_active_overrides(db_session, room_id)
    assert count == 2
    await db_session.refresh(device)
    await db_session.refresh(frontend)
    assert device.revoked_at is not None
    assert frontend.revoked_at is not None
    assert device.revoked_reason == "auto: guest checked out"
    assert frontend.revoked_reason == "auto: guest checked out"


async def test_cleanup_expired_marks_only_expired(db_session: AsyncSession, room_id: int) -> None:
    past = datetime.now(tz=UTC) - timedelta(hours=2)
    future = datetime.now(tz=UTC) + timedelta(hours=4)
    expired = ManualOverride(
        room_id=room_id,
        setpoint=Decimal("20.0"),
        source=OverrideSource.FRONTEND_4H,
        expires_at=past,
    )
    active = ManualOverride(
        room_id=room_id,
        setpoint=Decimal("22.0"),
        source=OverrideSource.FRONTEND_4H,
        expires_at=future,
    )
    db_session.add_all([expired, active])
    await db_session.flush()

    count = await override_service.cleanup_expired(db_session)
    assert count == 1
    await db_session.refresh(expired)
    await db_session.refresh(active)
    assert expired.revoked_at is not None
    assert expired.revoked_reason == "auto: expired"
    assert active.revoked_at is None


# ---------------------------------------------------------------------------
# Sprint 12 T4 (AE-52) — Window-Reject in create()
# ---------------------------------------------------------------------------


async def _add_zone_with_device(
    session: AsyncSession, *, room_id: int, zone_name: str, dev_eui: str
) -> tuple[int, int]:
    """Setup-Helper: Eine HeatingZone + ein healthy Device im Raum."""
    from heizung.models.device import Device
    from heizung.models.enums import DeviceKind, DeviceVendor, HeatingZoneKind
    from heizung.models.heating_zone import HeatingZone

    zone = HeatingZone(room_id=room_id, kind=HeatingZoneKind.BEDROOM, name=zone_name)
    session.add(zone)
    await session.flush()
    device = Device(
        dev_eui=dev_eui,
        kind=DeviceKind.THERMOSTAT,
        vendor=DeviceVendor.MCLIMATE,
        model="vicki",
        heating_zone_id=zone.id,
        is_active=True,
        health_state="healthy",
    )
    session.add(device)
    await session.flush()
    return zone.id, device.id


async def _add_reading(
    session: AsyncSession, *, device_id: int, open_window: bool, age_min: int = 2
) -> None:
    """Setup-Helper: SensorReading mit ``open_window``-Flag + frischem Alter."""
    from heizung.models.sensor_reading import SensorReading

    reading = SensorReading(
        time=datetime.now(tz=UTC) - timedelta(minutes=age_min),
        device_id=device_id,
        fcnt=1,
        temperature=Decimal("21.0"),
        open_window=open_window,
    )
    session.add(reading)
    await session.flush()


async def test_create_rejects_when_window_open(db_session: AsyncSession, room_id: int) -> None:
    """T4 (a): create() + 1 Zone Fenster offen -> raises
    OverrideRejectedWindowOpenError, manual_override-Tabelle leer.
    """
    suffix = datetime.now(tz=UTC).strftime("%H%M%S%f")[-8:]
    zone_id, device_id = await _add_zone_with_device(
        db_session, room_id=room_id, zone_name="bedroom", dev_eui=f"deadbeef{suffix}"
    )
    await _add_reading(db_session, device_id=device_id, open_window=True)

    expires = datetime.now(tz=UTC) + timedelta(hours=4)
    with pytest.raises(override_service.OverrideRejectedWindowOpenError) as exc_info:
        await override_service.create(
            db_session,
            room_id=room_id,
            setpoint=Decimal("22.0"),
            source=OverrideSource.FRONTEND_4H,
            expires_at=expires,
        )
    # Exception fuehrt die offene Zone in zones:
    assert len(exc_info.value.zones) == 1
    assert exc_info.value.zones[0]["zone_id"] == zone_id
    assert "reading_at" in exc_info.value.zones[0]

    # manual_override-Tabelle bleibt leer fuer diesen Raum:
    from sqlalchemy import select

    rows = list(
        (await db_session.execute(select(ManualOverride).where(ManualOverride.room_id == room_id)))
        .scalars()
        .all()
    )
    assert rows == []


async def test_create_persists_when_window_closed(db_session: AsyncSession, room_id: int) -> None:
    """T4 (b): create() + Fenster zu -> Eintrag persistiert wie heute."""
    suffix = datetime.now(tz=UTC).strftime("%H%M%S%f")[-8:]
    _zone_id, device_id = await _add_zone_with_device(
        db_session, room_id=room_id, zone_name="bedroom", dev_eui=f"deadbeef{suffix}"
    )
    await _add_reading(db_session, device_id=device_id, open_window=False)

    expires = datetime.now(tz=UTC) + timedelta(hours=4)
    override = await override_service.create(
        db_session,
        room_id=room_id,
        setpoint=Decimal("22.0"),
        source=OverrideSource.FRONTEND_4H,
        expires_at=expires,
    )
    assert override.id is not None
    assert override.setpoint == Decimal("22.0")


async def test_create_rejects_when_one_of_two_zones_open(
    db_session: AsyncSession, room_id: int
) -> None:
    """T4 (c): create() + 2 Zonen, eine offen -> 409, leere Tabelle."""
    suffix = datetime.now(tz=UTC).strftime("%H%M%S%f")[-8:]
    zone1_id, device1_id = await _add_zone_with_device(
        db_session, room_id=room_id, zone_name="bedroom", dev_eui=f"deadbeef{suffix}"
    )
    suffix2 = datetime.now(tz=UTC).strftime("%H%M%S%f")[-8:]
    _zone2_id, device2_id = await _add_zone_with_device(
        db_session, room_id=room_id, zone_name="bath", dev_eui=f"cafef00d{suffix2}"
    )
    # Zone 1 offen, Zone 2 zu
    await _add_reading(db_session, device_id=device1_id, open_window=True)
    await _add_reading(db_session, device_id=device2_id, open_window=False)

    expires = datetime.now(tz=UTC) + timedelta(hours=4)
    with pytest.raises(override_service.OverrideRejectedWindowOpenError) as exc_info:
        await override_service.create(
            db_session,
            room_id=room_id,
            setpoint=Decimal("22.0"),
            source=OverrideSource.FRONTEND_4H,
            expires_at=expires,
        )
    # Nur die offene Zone (zone1) im Reject-Detail:
    zone_ids = [z["zone_id"] for z in exc_info.value.zones]
    assert zone_ids == [zone1_id]

    from sqlalchemy import select

    rows = list(
        (await db_session.execute(select(ManualOverride).where(ManualOverride.room_id == room_id)))
        .scalars()
        .all()
    )
    assert rows == []


# ---------------------------------------------------------------------------
# Sprint 12a T2 (AE-58) — OCCUPIED-Gate + Zone-Scope + Priority-Sort
# ---------------------------------------------------------------------------


async def test_create_raises_on_vacant_room(db_session: AsyncSession, vacant_room_id: int) -> None:
    """T2 (AE-58): VACANT-Raum -> RoomNotOccupiedError, kein DB-Insert."""
    expires = datetime.now(tz=UTC) + timedelta(hours=4)
    with pytest.raises(override_service.RoomNotOccupiedError) as exc_info:
        await override_service.create(
            db_session,
            room_id=vacant_room_id,
            setpoint=Decimal("22.0"),
            source=OverrideSource.FRONTEND_4H,
            expires_at=expires,
        )
    assert exc_info.value.room_id == vacant_room_id
    assert exc_info.value.status == RoomStatus.VACANT

    from sqlalchemy import select

    rows = list(
        (
            await db_session.execute(
                select(ManualOverride).where(ManualOverride.room_id == vacant_room_id)
            )
        )
        .scalars()
        .all()
    )
    assert rows == []


async def test_create_succeeds_on_occupied_room(db_session: AsyncSession, room_id: int) -> None:
    """T2 (AE-58): OCCUPIED-Raum (room_id-Fixture mit aktiver Belegung) -> Insert ok."""
    expires = datetime.now(tz=UTC) + timedelta(hours=4)
    override = await override_service.create(
        db_session,
        room_id=room_id,
        setpoint=Decimal("22.0"),
        source=OverrideSource.FRONTEND_4H,
        expires_at=expires,
    )
    assert override.id is not None
    assert override.heating_zone_id is None  # Backward-Compat: Default Room-Scope


async def test_get_active_priority_frontend_beats_device_same_timestamp(
    db_session: AsyncSession, room_id: int
) -> None:
    """T2: Bei gleichem created_at gewinnt FRONTEND_* vor DEVICE."""
    expires = datetime.now(tz=UTC) + timedelta(hours=4)
    await override_service.create(
        db_session,
        room_id=room_id,
        setpoint=Decimal("23.0"),
        source=OverrideSource.DEVICE,
        expires_at=expires,
    )
    frontend = await override_service.create(
        db_session,
        room_id=room_id,
        setpoint=Decimal("21.0"),
        source=OverrideSource.FRONTEND_4H,
        expires_at=expires,
    )
    active = await override_service.get_active(db_session, room_id)
    assert active is not None
    assert active.id == frontend.id
    assert active.source == OverrideSource.FRONTEND_4H


async def test_get_active_newest_wins_within_same_priority_class(
    db_session: AsyncSession, room_id: int
) -> None:
    """T2: Innerhalb gleicher Priority-Klasse (z.B. zwei DEVICE) gewinnt der neueste."""
    expires = datetime.now(tz=UTC) + timedelta(hours=4)
    older = await override_service.create(
        db_session,
        room_id=room_id,
        setpoint=Decimal("22.0"),
        source=OverrideSource.DEVICE,
        expires_at=expires,
    )
    # Manueller created_at-Vorlauf, weil zwei flushes in derselben TX in
    # Postgres denselben transaction_timestamp tragen.
    older.created_at = datetime.now(tz=UTC) - timedelta(minutes=5)
    await db_session.flush()

    newer = await override_service.create(
        db_session,
        room_id=room_id,
        setpoint=Decimal("24.0"),
        source=OverrideSource.DEVICE,
        expires_at=expires,
    )
    active = await override_service.get_active(db_session, room_id)
    assert active is not None
    assert active.id == newer.id


async def test_get_active_zone_match_beats_room_match(
    db_session: AsyncSession, room_id: int
) -> None:
    """T2: Lookup mit zone_id -> Zone-Override schlaegt Room-Override.

    Auch wenn der Room-Override eine staerkere Priority-Klasse hat
    (FRONTEND vs. DEVICE), gewinnt die Zone-Match-Klausel hierarchisch
    zuerst.
    """
    suffix = datetime.now(tz=UTC).strftime("%H%M%S%f")[-8:]
    zone_id, _device_id = await _add_zone_with_device(
        db_session, room_id=room_id, zone_name="bedroom", dev_eui=f"deadbeef{suffix}"
    )
    expires = datetime.now(tz=UTC) + timedelta(hours=4)
    zone_override = await override_service.create(
        db_session,
        room_id=room_id,
        setpoint=Decimal("23.0"),
        source=OverrideSource.DEVICE,
        expires_at=expires,
        heating_zone_id=zone_id,
    )
    await override_service.create(
        db_session,
        room_id=room_id,
        setpoint=Decimal("21.0"),
        source=OverrideSource.FRONTEND_4H,
        expires_at=expires,
    )

    active = await override_service.get_active(db_session, room_id, heating_zone_id=zone_id)
    assert active is not None
    assert active.id == zone_override.id


async def test_get_active_room_scope_only_when_lookup_without_zone_id(
    db_session: AsyncSession, room_id: int
) -> None:
    """T2: Lookup ohne zone_id -> Zone-Overrides sind unsichtbar (Backward-Compat).

    Engine-Layer-3-Aufrufer aus Sprint 9.9 ruft ``get_active(session, room_id)``
    ohne ``heating_zone_id`` und darf nur Room-Scope-Overrides sehen — sonst
    wuerden zone-spezifische Anlagen unbeabsichtigt auf den gesamten Raum
    wirken.
    """
    suffix = datetime.now(tz=UTC).strftime("%H%M%S%f")[-8:]
    zone_id, _device_id = await _add_zone_with_device(
        db_session, room_id=room_id, zone_name="bath", dev_eui=f"cafef00d{suffix}"
    )
    expires = datetime.now(tz=UTC) + timedelta(hours=4)
    await override_service.create(
        db_session,
        room_id=room_id,
        setpoint=Decimal("23.0"),
        source=OverrideSource.FRONTEND_4H,
        expires_at=expires,
        heating_zone_id=zone_id,
    )
    active_without_zone = await override_service.get_active(db_session, room_id)
    assert active_without_zone is None, (
        "Lookup ohne zone_id darf Zone-Override nicht sehen (Backward-Compat)"
    )
    active_with_zone = await override_service.get_active(
        db_session, room_id, heating_zone_id=zone_id
    )
    assert active_with_zone is not None


# ---------------------------------------------------------------------------
# Sprint 12c (AE-58) — Block-Gate vor OCCUPIED-Gate
# ---------------------------------------------------------------------------


async def test_create_raises_room_override_blocked_when_room_is_blocked(
    db_session: AsyncSession, room_id: int
) -> None:
    """Sprint 12c: ``guest_override_blocked=True`` -> RoomOverrideBlockedError,
    kein DB-Insert."""
    room = await db_session.get(Room, room_id)
    assert room is not None
    room.guest_override_blocked = True
    await db_session.flush()

    expires = datetime.now(tz=UTC) + timedelta(hours=4)
    with pytest.raises(override_service.RoomOverrideBlockedError) as exc_info:
        await override_service.create(
            db_session,
            room_id=room_id,
            setpoint=Decimal("22.0"),
            source=OverrideSource.FRONTEND_4H,
            expires_at=expires,
        )
    assert exc_info.value.room_id == room_id

    from sqlalchemy import select

    rows = list(
        (await db_session.execute(select(ManualOverride).where(ManualOverride.room_id == room_id)))
        .scalars()
        .all()
    )
    assert rows == []


async def test_create_block_check_runs_before_occupied_check(
    db_session: AsyncSession, vacant_room_id: int
) -> None:
    """Sprint 12c (§5.51 Domain-Invariante): Block-Gate hat Vorrang vor
    OCCUPIED-Gate. Auch wenn der Raum VACANT ist, wird bei
    ``guest_override_blocked=True`` zuerst ``RoomOverrideBlockedError`` geworfen
    — NICHT ``RoomNotOccupiedError``."""
    room = await db_session.get(Room, vacant_room_id)
    assert room is not None
    room.guest_override_blocked = True
    await db_session.flush()

    expires = datetime.now(tz=UTC) + timedelta(hours=4)
    with pytest.raises(override_service.RoomOverrideBlockedError) as exc_info:
        await override_service.create(
            db_session,
            room_id=vacant_room_id,
            setpoint=Decimal("22.0"),
            source=OverrideSource.FRONTEND_4H,
            expires_at=expires,
        )
    assert exc_info.value.room_id == vacant_room_id


async def test_create_allows_when_blocked_false(db_session: AsyncSession, room_id: int) -> None:
    """Sprint 12c: ``guest_override_blocked=False`` (Default) -> Override
    wird normal angelegt."""
    room = await db_session.get(Room, room_id)
    assert room is not None
    assert room.guest_override_blocked is False

    expires = datetime.now(tz=UTC) + timedelta(hours=4)
    override = await override_service.create(
        db_session,
        room_id=room_id,
        setpoint=Decimal("22.0"),
        source=OverrideSource.FRONTEND_4H,
        expires_at=expires,
    )
    assert override.id is not None
    assert override.setpoint == Decimal("22.0")
