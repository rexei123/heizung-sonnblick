"""Tests fuer den Zimmer-Stammdaten-Seed (heizung.scripts.seed_rooms).

Zwei Schichten:
- Pure-Function-Tests fuer ``parse_and_validate`` (kein DB, laufen immer).
- DB-Tests (skip ohne ``DATABASE_URL``) fuer Step 0, Wipe+Reseed,
  blockierende Vorstufe und --dry-run. Alle DB-Tests arbeiten in-session
  und werden von der Fixture zurueckgerollt — kein Commit, keine Pollution
  (§5.39). ``_wipe_and_reseed`` loescht im Test-Transaktions-View alle Rows,
  der finale Rollback stellt Fremd-Bestand wieder her.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
import pytest_asyncio
from alembic.config import Config
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from alembic import command
from heizung.models.device import Device
from heizung.models.enums import DeviceKind, DeviceVendor, HeatingZoneKind
from heizung.models.heating_zone import HeatingZone
from heizung.models.room import Room
from heizung.models.room_type import RoomType
from heizung.scripts import seed_rooms
from heizung.scripts.seed_rooms import _read_csv_text, parse_and_validate

DATABASE_URL = os.environ.get("DATABASE_URL")
DATABASE_URL_PRESENT = bool(DATABASE_URL)
SKIP_REASON = "DATABASE_URL nicht gesetzt - DB-Tests brauchen Test-DB"

HEADER = (
    "Zimmer_Nummer,Anzeigename,Etage,Ausrichtung,Zimmer_Kategorie,"
    "PMS_Mapping,Zone_Index,Zone_Label,Room_Type"
)


# ---------------------------------------------------------------------------
# Pure-Function: parse_and_validate (kein DB)
# ---------------------------------------------------------------------------


def test_embedded_csv_validates_clean() -> None:
    """Die eingebettete Package-Data-CSV ist schemakonform: 45/103, 0 Fehler."""
    rows, errors = parse_and_validate(_read_csv_text(None))
    assert errors == []
    assert len(rows) == 103
    assert len({r.zimmer_nummer for r in rows}) == 45


def test_header_mismatch_is_rejected() -> None:
    _, errors = parse_and_validate("foo,bar\n1,2\n")
    assert any("Header-Mismatch" in e for e in errors)


def test_float_int_coercion() -> None:
    """``52.0`` wird zu 52 coerct (B-Sprint13a-3)."""
    csv = f"{HEADER}\n52.0,Zimmer 52,0.0,N,Doppelzimmer,52.0,1,Schlafzimmer,Schlafzimmer\n"
    rows, errors = parse_and_validate(csv)
    # Count-Fehler erwartet (nur 1 Zeile), aber die Coercion selbst fehlerfrei.
    assert not any("ist kein Integer" in e for e in errors)
    assert rows[0].zimmer_nummer == "52"
    assert rows[0].etage == 0


def test_bad_orientation_rejected() -> None:
    csv = f"{HEADER}\n52,Zimmer 52,0,X,Doppelzimmer,52,1,Schlafzimmer,Schlafzimmer\n"
    _, errors = parse_and_validate(csv)
    assert any("Ausrichtung='X'" in e for e in errors)


def test_bad_room_type_rejected() -> None:
    csv = f"{HEADER}\n52,Zimmer 52,0,N,Doppelzimmer,52,1,Wohnzimmer,Wohnzimmer\n"
    _, errors = parse_and_validate(csv)
    assert any("Room_Type='Wohnzimmer'" in e for e in errors)


def test_bad_kategorie_rejected() -> None:
    csv = f"{HEADER}\n52,Zimmer 52,0,N,Penthouse,52,1,Schlafzimmer,Schlafzimmer\n"
    _, errors = parse_and_validate(csv)
    assert any("Zimmer_Kategorie='Penthouse'" in e for e in errors)


def test_pms_mismatch_rejected() -> None:
    csv = f"{HEADER}\n52,Zimmer 52,0,N,Doppelzimmer,99,1,Schlafzimmer,Schlafzimmer\n"
    _, errors = parse_and_validate(csv)
    assert any("PMS_Mapping=99 != Zimmer_Nummer=52" in e for e in errors)


def test_missing_bathroom_rejected() -> None:
    csv = f"{HEADER}\n52,Zimmer 52,0,N,Doppelzimmer,52,1,Schlafzimmer,Schlafzimmer\n"
    _, errors = parse_and_validate(csv)
    assert any("Badezimmer-Zonen (erwartet genau 1)" in e for e in errors)


def test_duplicate_zone_name_rejected() -> None:
    csv = (
        f"{HEADER}\n"
        "52,Zimmer 52,0,N,Doppelzimmer,52,1,Bad,Schlafzimmer\n"
        "52,Zimmer 52,0,N,Doppelzimmer,52,2,Bad,Badezimmer\n"
    )
    _, errors = parse_and_validate(csv)
    assert any("doppelte Zone-Namen" in e for e in errors)


def test_inconsistent_room_attrs_rejected() -> None:
    csv = (
        f"{HEADER}\n"
        "52,Zimmer 52,0,N,Doppelzimmer,52,1,Schlafzimmer,Schlafzimmer\n"
        "52,Zimmer 52,1,N,Doppelzimmer,52,2,Bad,Badezimmer\n"  # Etage abweichend
    )
    _, errors = parse_and_validate(csv)
    assert any("inkonsistente etage" in e for e in errors)


# ---------------------------------------------------------------------------
# DB-Fixtures
# ---------------------------------------------------------------------------


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


@pytest.fixture
def patched_session_local(session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> AsyncSession:
    """``seed_rooms.SessionLocal`` -> Factory, die die Test-Session rausgibt."""

    @asynccontextmanager
    async def fake_factory() -> AsyncIterator[AsyncSession]:
        yield session

    monkeypatch.setattr(seed_rooms, "SessionLocal", fake_factory)
    return session


async def _seed_one_fictional_room(session: AsyncSession) -> tuple[Room, HeatingZone]:
    """Ein fiktives Zimmer + Zone (uncommitted) als Wipe-Ausgangslage."""
    rt = await session.scalar(select(RoomType).where(RoomType.name == "Doppelzimmer"))
    if rt is None:
        rt = RoomType(name="Doppelzimmer", description="x")
        session.add(rt)
        await session.flush()
    room = Room(number=f"T-{uuid.uuid4().hex[:6]}", room_type_id=rt.id)
    session.add(room)
    await session.flush()
    zone = HeatingZone(room_id=room.id, kind=HeatingZoneKind.BEDROOM, name="Alt-Zone")
    session.add(zone)
    await session.flush()
    return room, zone


# ---------------------------------------------------------------------------
# DB: Step 0 + Wipe + Reseed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_wipe_and_reseed_creates_45_103(session: AsyncSession) -> None:
    """Nach Reseed exakt 45 room + 103 heating_zone, alle Invarianten."""
    await _seed_one_fictional_room(session)
    rows, errors = parse_and_validate(_read_csv_text(None))
    assert errors == []

    room_types = await seed_rooms._ensure_room_types(session)
    rooms_created, zones_created = await seed_rooms._wipe_and_reseed(session, rows, room_types)
    assert (rooms_created, zones_created) == (45, 103)

    room_total = await session.scalar(select(func.count()).select_from(Room))
    zone_total = await session.scalar(select(func.count()).select_from(HeatingZone))
    assert room_total == 45
    assert zone_total == 103

    # Jedes Zimmer genau 1 bathroom-Zone.
    bath_per_room = (
        await session.execute(
            select(HeatingZone.room_id, func.count())
            .where(HeatingZone.kind == HeatingZoneKind.BATHROOM)
            .group_by(HeatingZone.room_id)
        )
    ).all()
    assert len(bath_per_room) == 45
    assert all(c == 1 for _, c in bath_per_room)

    # Genau 9 Zonen name="Kinderzimmer", alle bedroom, an den Soll-Zimmern.
    child = (
        await session.execute(
            select(Room.number, HeatingZone.kind)
            .join(HeatingZone, HeatingZone.room_id == Room.id)
            .where(HeatingZone.name == "Kinderzimmer")
        )
    ).all()
    assert len(child) == 9
    assert {num for num, _ in child} == seed_rooms.CHILD_ROOMS
    assert all(kind == HeatingZoneKind.BEDROOM for _, kind in child)

    # Alle room.room_type_id gesetzt, nur Doppelzimmer/Suite.
    type_names = (
        (
            await session.execute(
                select(RoomType.name).join(Room, Room.room_type_id == RoomType.id).distinct()
            )
        )
        .scalars()
        .all()
    )
    assert set(type_names) <= {"Doppelzimmer", "Suite"}
    assert (
        await session.scalar(
            select(func.count()).select_from(Room).where(Room.room_type_id.is_(None))
        )
        == 0
    )


@pytest.mark.asyncio
async def test_ensure_room_types_idempotent(session: AsyncSession) -> None:
    """Step 0 legt fehlende an, dupliziert vorhandene nicht."""
    # Vorhandene entfernen (in-session) -> beide fehlen.
    await session.execute(delete(RoomType).where(RoomType.name.in_({"Doppelzimmer", "Suite"})))
    await session.flush()
    types1 = await seed_rooms._ensure_room_types(session)
    assert set(types1) == {"Doppelzimmer", "Suite"}
    # Zweiter Lauf darf nicht duplizieren.
    await seed_rooms._ensure_room_types(session)
    for name in ("Doppelzimmer", "Suite"):
        cnt = await session.scalar(
            select(func.count()).select_from(RoomType).where(RoomType.name == name)
        )
        assert cnt == 1


# ---------------------------------------------------------------------------
# DB: blockierende Vorstufe + dry-run (via Handler)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_import_aborts_when_device_attached(
    patched_session_local: AsyncSession,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Device an Zone -> ABBRUCH, KEIN Wipe (fiktives Zimmer bleibt)."""
    session = patched_session_local
    room, zone = await _seed_one_fictional_room(session)
    device = Device(
        dev_eui=uuid.uuid4().hex[:16],
        kind=DeviceKind.THERMOSTAT,
        vendor=DeviceVendor.MCLIMATE,
        model="vicki",
        heating_zone_id=zone.id,
    )
    session.add(device)
    await session.flush()

    args = seed_rooms._build_parser().parse_args(["import"])
    rc = await seed_rooms._cmd_import(args)
    assert rc == 1
    captured = capsys.readouterr()
    assert "ABBRUCH" in captured.err
    # Zimmer NICHT gewiped (Abort vor dem Wipe).
    assert await session.get(Room, room.id) is not None
    assert await session.get(HeatingZone, zone.id) is not None


@pytest.mark.asyncio
async def test_import_dry_run_rolls_back(
    patched_session_local: AsyncSession,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """--dry-run: exit 0, Reseed wird zurueckgerollt (kein Commit).

    Der interne ``session.rollback()`` rollt die GESAMTE Transaktion zurueck,
    daher kein before/after-Vergleich; stattdessen: das CSV-Zimmer "52" ist
    nach dem Lauf NICHT committet (Folge-Query liest committed).
    """
    session = patched_session_local
    # Ordering-robust: committete Device-Zone-Zuordnungen aus anderen Test-
    # Files in-session loesen, damit die blockierende Vorstufe nicht greift
    # (die wird separat in test_import_aborts_when_device_attached geprueft).
    await session.execute(update(Device).values(heating_zone_id=None))
    await session.flush()
    args = seed_rooms._build_parser().parse_args(["import", "--dry-run"])
    rc = await seed_rooms._cmd_import(args)
    assert rc == 0
    assert "DRY-RUN" in capsys.readouterr().err
    # Reseed nicht persistiert: CSV-Zimmer "52" ist nicht committet.
    assert await session.scalar(select(Room).where(Room.number == "52")) is None
