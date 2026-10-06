"""Sprint 9.9 T6 - PMS Auto-Revoke Tests.

DB-Tests: skip ohne ``DATABASE_URL`` (CI-Pattern, vgl. T4/T5).
"""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
import pytest_asyncio
from alembic.config import Config
from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from alembic import command
from heizung.models.business_audit import BusinessAudit
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
from heizung.models.occupancy import Occupancy
from heizung.models.room import Room
from heizung.models.room_type import RoomType
from heizung.services.override_pms_hook import auto_revoke_on_checkout

DATABASE_URL = os.environ.get("DATABASE_URL")
DATABASE_URL_PRESENT = bool(DATABASE_URL)
SKIP_REASON = "DATABASE_URL nicht gesetzt - DB-Tests brauchen Test-DB"


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
async def engine() -> AsyncIterator[AsyncEngine]:
    if not DATABASE_URL_PRESENT:
        pytest.skip(SKIP_REASON)
    eng = create_async_engine(DATABASE_URL or "")
    try:
        yield eng
    finally:
        await eng.dispose()


@pytest_asyncio.fixture
async def session(engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    async with sessionmaker() as s:
        try:
            yield s
        finally:
            await s.rollback()


def _short() -> str:
    return uuid.uuid4().hex[:8]


def _eui() -> str:
    return uuid.uuid4().hex[:16]


async def _seed_room_with_device(s: AsyncSession) -> tuple[int, int]:
    """Legt RoomType + Room + HeatingZone + Device an, returns (room_id, device_id)."""
    short = _short()
    rt = RoomType(name=f"t99-{short}")
    s.add(rt)
    await s.flush()
    room = Room(number=f"t99-{short}", room_type_id=rt.id, status=RoomStatus.OCCUPIED)
    s.add(room)
    await s.flush()
    hz = HeatingZone(room_id=room.id, kind=HeatingZoneKind.BEDROOM, name="zone-1")
    s.add(hz)
    await s.flush()
    device = Device(
        dev_eui=_eui(),
        kind=DeviceKind.THERMOSTAT,
        vendor=DeviceVendor.MCLIMATE,
        model="Vicki",
        heating_zone_id=hz.id,
    )
    s.add(device)
    await s.flush()
    return room.id, device.id


async def _add_device_override(s: AsyncSession, room_id: int, expires: datetime) -> ManualOverride:
    o = ManualOverride(
        room_id=room_id,
        setpoint=Decimal("23.0"),
        source=OverrideSource.DEVICE,
        expires_at=expires,
    )
    s.add(o)
    await s.flush()
    return o


# ---------------------------------------------------------------------------
# 5 Tests
# ---------------------------------------------------------------------------


async def test_occupied_to_vacant_no_followup_revokes(session: AsyncSession) -> None:
    now = datetime.now(tz=UTC)
    room_id, _ = await _seed_room_with_device(session)
    override = await _add_device_override(session, room_id, now + timedelta(days=2))

    revoked = await auto_revoke_on_checkout(
        session,
        room_id,
        previous_status=RoomStatus.OCCUPIED,
        new_status=RoomStatus.VACANT,
        now=now,
    )
    assert revoked == 1
    await session.refresh(override)
    assert override.revoked_at is not None
    assert override.revoked_reason == "auto_revoke_on_checkout"


async def test_occupied_to_vacant_mit_folgegast_in_2h_revoked_trotzdem(
    session: AsyncSession,
) -> None:
    """**Umgedreht in Sprint 20f (T5).** Ein Folgegast schuetzt nichts mehr.

    Bis hierher unterblieb der Widerruf, wenn innerhalb von vier Stunden ein
    Folgegast erwartet wurde (``CHECKOUT_GRACE_WINDOW``). Die fachliche Regel
    des Hotels ist eindeutig: **ein Override endet mit jeder Abreise, ohne
    Ausnahme.**

    Der Override gehoert dem Gast, der gegangen ist. Ob der naechste in zwei
    oder in zwanzig Stunden kommt, aendert daran nichts — er bekommt ein
    Zimmer auf den globalen Einstellungen, nicht die Wunschtemperatur seines
    Vorgaengers.

    Dieser Test hiess vorher ``..._does_not_revoke`` und sicherte das
    Gegenteil zu. Er ist nicht geloescht, sondern umgedreht: wer die alte
    Zusicherung sucht, findet hier die Begruendung, warum sie nicht mehr
    gilt.
    """
    now = datetime.now(tz=UTC)
    room_id, _ = await _seed_room_with_device(session)
    override = await _add_device_override(session, room_id, now + timedelta(days=2))
    # Folgegast in 2 Stunden — ohne Wirkung auf den Widerruf.
    session.add(
        Occupancy(
            room_id=room_id,
            check_in=now + timedelta(hours=2),
            check_out=now + timedelta(days=3),
        )
    )
    await session.flush()

    revoked = await auto_revoke_on_checkout(
        session,
        room_id,
        previous_status=RoomStatus.OCCUPIED,
        new_status=RoomStatus.VACANT,
        now=now,
    )
    assert revoked == 1
    await session.refresh(override)
    assert override.revoked_at is not None
    assert override.revoked_reason == "auto_revoke_on_checkout"


async def test_vacant_to_occupied_does_not_revoke(session: AsyncSession) -> None:
    now = datetime.now(tz=UTC)
    room_id, _ = await _seed_room_with_device(session)
    override = await _add_device_override(session, room_id, now + timedelta(days=2))

    revoked = await auto_revoke_on_checkout(
        session,
        room_id,
        previous_status=RoomStatus.VACANT,
        new_status=RoomStatus.OCCUPIED,
        now=now,
    )
    assert revoked == 0
    await session.refresh(override)
    assert override.revoked_at is None


async def test_occupied_to_cleaning_does_not_revoke(session: AsyncSession) -> None:
    """Nur ``OCCUPIED -> VACANT`` triggert — **unveraendert in Sprint 20f**.

    Der Auftrag zu T5 sah zunaechst vor, auch ``OCCUPIED -> CLEANING`` zu
    widerrufen. Die Vorab-Analyse hat gezeigt, dass dieser Wechsel diesen
    Hook gar nicht erreicht: ``CLEANING`` wird **nie automatisch** gesetzt
    (``derive_room_status`` kennt den Wert nicht, ``sync_room_status``
    schuetzt ihn sogar), sondern ausschliesslich von einem Admin ueber
    ``PATCH /rooms/{id}`` — und dieser Pfad ruft ``auto_revoke_on_checkout``
    nicht auf.

    Der Hotelier hat daraufhin entschieden: ``CLEANING`` wird im Haus nicht
    genutzt, also kein zweiter Aufrufpunkt (§0 S6 — die einfachere Variante
    reicht, solange niemand den Zustand setzt). Wer ``CLEANING`` spaeter
    einfuehrt, findet die Luecke hier beschrieben.
    """
    now = datetime.now(tz=UTC)
    room_id, _ = await _seed_room_with_device(session)
    override = await _add_device_override(session, room_id, now + timedelta(days=2))

    revoked = await auto_revoke_on_checkout(
        session,
        room_id,
        previous_status=RoomStatus.OCCUPIED,
        new_status=RoomStatus.CLEANING,
        now=now,
    )
    assert revoked == 0
    await session.refresh(override)
    assert override.revoked_at is None


async def test_occupied_to_vacant_no_overrides_returns_zero(session: AsyncSession) -> None:
    """Trigger-Bedingung erfuellt, aber kein device-Override aktiv -> 0,
    kein Fehler."""
    now = datetime.now(tz=UTC)
    room_id, _ = await _seed_room_with_device(session)

    revoked = await auto_revoke_on_checkout(
        session,
        room_id,
        previous_status=RoomStatus.OCCUPIED,
        new_status=RoomStatus.VACANT,
        now=now,
    )
    assert revoked == 0


# ---------------------------------------------------------------------------
# Sprint 12a T6 (AE-58) — revoke_all_active_overrides Verifikation
# ---------------------------------------------------------------------------


async def test_checkout_revoked_alle_override_quellen(session: AsyncSession) -> None:
    """T6: DEVICE + FRONTEND_* gemischt aktiv -> beide revoked beim Check-out.

    Sprint 12a T2 hat ``revoke_device_overrides`` durch
    ``revoke_all_active_overrides`` ersetzt. Vorher blieben FRONTEND-
    Overrides ueber den Check-out hinaus aktiv, jetzt wird der komplette
    Stack revokiert (AE-58: neue Belegung startet sauber auf globalen
    Einstellungen).
    """
    now = datetime.now(tz=UTC)
    room_id, _ = await _seed_room_with_device(session)
    expires = now + timedelta(days=2)

    device_override = ManualOverride(
        room_id=room_id,
        setpoint=Decimal("23.0"),
        source=OverrideSource.DEVICE,
        expires_at=expires,
    )
    frontend_override = ManualOverride(
        room_id=room_id,
        setpoint=Decimal("21.0"),
        source=OverrideSource.FRONTEND_4H,
        expires_at=expires,
    )
    session.add_all([device_override, frontend_override])
    await session.flush()

    revoked = await auto_revoke_on_checkout(
        session,
        room_id,
        previous_status=RoomStatus.OCCUPIED,
        new_status=RoomStatus.VACANT,
        now=now,
    )
    assert revoked == 2
    await session.refresh(device_override)
    await session.refresh(frontend_override)
    assert device_override.revoked_at is not None
    assert device_override.revoked_reason == "auto_revoke_on_checkout"
    assert frontend_override.revoked_at is not None
    assert frontend_override.revoked_reason == "auto_revoke_on_checkout"


async def test_checkout_mit_folge_checkin_revoked_auch_frontend(
    session: AsyncSession,
) -> None:
    """**Umgedreht in Sprint 20f (T5)**, Gegenstueck mit FRONTEND-Quelle.

    Der Test prueft seit Sprint 12a T6, dass die Regel fuer **alle** Quellen
    gleich gilt — damals "kein Widerruf bei Folgegast", jetzt "Widerruf
    immer". Die Mitarbeiter-Eingabe traegt genauso wenig ueber die Abreise
    hinaus wie die Gast-Drehung.

    Der Folge-Checkin steht weiter auf exakt vier Stunden: das war die
    Grenze des alten Fensters, und ein Test genau dort zeigt am
    deutlichsten, dass es keine Grenze mehr gibt.
    """
    now = datetime.now(tz=UTC)
    room_id, _ = await _seed_room_with_device(session)
    expires = now + timedelta(days=2)

    frontend_override = ManualOverride(
        room_id=room_id,
        setpoint=Decimal("22.0"),
        source=OverrideSource.FRONTEND_4H,
        expires_at=expires,
    )
    session.add(frontend_override)
    # Folge-Checkin in exakt 4h — die alte Fenstergrenze, jetzt ohne Wirkung.
    session.add(
        Occupancy(
            room_id=room_id,
            check_in=now + timedelta(hours=4),
            check_out=now + timedelta(days=3),
        )
    )
    await session.flush()

    revoked = await auto_revoke_on_checkout(
        session,
        room_id,
        previous_status=RoomStatus.OCCUPIED,
        new_status=RoomStatus.VACANT,
        now=now,
    )
    assert revoked == 1
    await session.refresh(frontend_override)
    assert frontend_override.revoked_at is not None
    assert frontend_override.revoked_reason == "auto_revoke_on_checkout"


# ---------------------------------------------------------------------------
# Sprint 13 Hygiene (B-12c-AuditGap) — BusinessAudit-Schreibung
# ---------------------------------------------------------------------------


async def _count_audits(session: AsyncSession, room_id: int, action: str) -> list[BusinessAudit]:
    """Liefert alle BusinessAudit-Rows fuer (action, target_type='room', target_id=room_id)."""
    stmt = (
        select(BusinessAudit)
        .where(BusinessAudit.action == action)
        .where(BusinessAudit.target_type == "room")
        .where(BusinessAudit.target_id == room_id)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def test_audit_geschrieben_bei_effektiver_revokation(session: AsyncSession) -> None:
    """B-12c-AuditGap: pro effektiver Revokation ein BusinessAudit-Eintrag
    OVERRIDES_AUTO_REVOKED_ON_CHECKOUT mit korrektem revoked_overrides_count.
    """
    now = datetime.now(tz=UTC)
    room_id, _ = await _seed_room_with_device(session)
    expires = now + timedelta(days=2)
    session.add_all(
        [
            ManualOverride(
                room_id=room_id,
                setpoint=Decimal("23.0"),
                source=OverrideSource.DEVICE,
                expires_at=expires,
            ),
            ManualOverride(
                room_id=room_id,
                setpoint=Decimal("21.0"),
                source=OverrideSource.FRONTEND_4H,
                expires_at=expires,
            ),
        ]
    )
    await session.flush()

    revoked = await auto_revoke_on_checkout(
        session,
        room_id,
        previous_status=RoomStatus.OCCUPIED,
        new_status=RoomStatus.VACANT,
        now=now,
    )
    assert revoked == 2

    audits = await _count_audits(session, room_id, "OVERRIDES_AUTO_REVOKED_ON_CHECKOUT")
    assert len(audits) == 1
    audit = audits[0]
    assert audit.user_id is None  # System-Trigger, Praezedenzfall
    assert audit.old_value is None
    assert audit.new_value == {
        "room_id": room_id,
        "revoked_overrides_count": 2,
        "reason": "auto_revoke_on_checkout",
    }


async def test_idempotenz_kein_audit_ohne_active_overrides(session: AsyncSession) -> None:
    """B-12c-AuditGap Idempotenz: kein aktiver Override -> kein Revoke,
    kein Audit. Analog zum 12c-Pattern fuer ROOM_OVERRIDE_BLOCK_TOGGLED.
    """
    now = datetime.now(tz=UTC)
    room_id, _ = await _seed_room_with_device(session)
    # KEIN Override anlegen.

    revoked = await auto_revoke_on_checkout(
        session,
        room_id,
        previous_status=RoomStatus.OCCUPIED,
        new_status=RoomStatus.VACANT,
        now=now,
    )
    assert revoked == 0

    audits = await _count_audits(session, room_id, "OVERRIDES_AUTO_REVOKED_ON_CHECKOUT")
    assert audits == []


async def test_revoked_reason_filter_rekonstruktion(session: AsyncSession) -> None:
    """B-12c-AuditGap: Override-IDs stehen NICHT im Audit. Rekonstruktion
    erfolgt via Filter ``manual_override.revoked_reason='auto_revoke_on_checkout'``.

    Verifiziert dass der String identisch zwischen ``manual_override``-Row
    und ``business_audit.new_value.reason`` ist (Pflicht-Voraussetzung
    fuer die Audit-Rekonstruktion).
    """
    now = datetime.now(tz=UTC)
    room_id, _ = await _seed_room_with_device(session)
    expires = now + timedelta(days=2)
    override = ManualOverride(
        room_id=room_id,
        setpoint=Decimal("22.5"),
        source=OverrideSource.FRONTEND_MIDNIGHT,
        expires_at=expires,
    )
    session.add(override)
    await session.flush()

    revoked = await auto_revoke_on_checkout(
        session,
        room_id,
        previous_status=RoomStatus.OCCUPIED,
        new_status=RoomStatus.VACANT,
        now=now,
    )
    assert revoked == 1
    await session.refresh(override)

    audits = await _count_audits(session, room_id, "OVERRIDES_AUTO_REVOKED_ON_CHECKOUT")
    assert len(audits) == 1
    # Filter-Pfad: revoked_reason in manual_override == new_value.reason im Audit.
    assert override.revoked_reason == "auto_revoke_on_checkout"
    assert audits[0].new_value["reason"] == "auto_revoke_on_checkout"
