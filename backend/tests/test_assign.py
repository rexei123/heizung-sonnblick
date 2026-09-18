"""Sprint 17 (C8/D4) — Zonen-Zuordnung am Montage-Abend.

DB-Tests gegen ``TEST_DATABASE_URL``. Geprueft werden der Zimmer-Filter,
jeder einzelne Pre-Flight-Fehler, die Alles-oder-nichts-Eigenschaft, das
geteilte Audit mit dem API-Pfad, die ``"52.0"``-Coercion (B-Sprint13a-3)
und die Backplate-Nachpruefung mit ihrem eigenen Exit-Code.
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
from heizung.models.enums import DeviceKind, DeviceVendor, HeatingZoneKind
from heizung.models.heating_zone import HeatingZone
from heizung.models.room import Room
from heizung.models.room_type import RoomType
from heizung.models.sensor_reading import SensorReading
from heizung.scripts.pairing.assign import (
    check_backplate,
    filter_rows,
    format_report,
    run_assign,
)
from heizung.scripts.pairing.csv_row import PairingCsvRow

DATABASE_URL = os.environ.get("DATABASE_URL")
SKIP_REASON = "DATABASE_URL nicht gesetzt - DB-Tests brauchen Test-DB"

NOW = datetime(2026, 9, 29, 18, 0, 0, tzinfo=UTC)


@pytest_asyncio.fixture(scope="module", autouse=True)
async def _migrate_db() -> None:
    if not DATABASE_URL:
        return
    backend_root = Path(__file__).resolve().parents[1]
    cfg = Config(str(backend_root / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend_root / "alembic"))
    cfg.set_main_option("sqlalchemy.url", DATABASE_URL or "")
    await asyncio.to_thread(command.upgrade, cfg, "head")


@pytest_asyncio.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    if not DATABASE_URL:
        pytest.skip(SKIP_REASON)
    eng = create_async_engine(DATABASE_URL or "")
    try:
        yield eng
    finally:
        await eng.dispose()


@pytest_asyncio.fixture
async def session(engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        try:
            yield s
        finally:
            await s.rollback()


def _eui() -> str:
    return uuid.uuid4().hex[:16]


def _short() -> str:
    return uuid.uuid4().hex[:8]


async def _make_room(s: AsyncSession, number: str, *zone_names: str) -> dict[str, int]:
    """Room + Zonen. Returns ``zone_label -> zone_id``. §5.49: number <= 20."""
    rt = RoomType(name=f"c8-{_short()}")
    s.add(rt)
    await s.flush()
    room = Room(number=number, room_type_id=rt.id)
    s.add(room)
    await s.flush()
    out: dict[str, int] = {}
    for name in zone_names:
        hz = HeatingZone(room_id=room.id, kind=HeatingZoneKind.BEDROOM, name=name)
        s.add(hz)
        await s.flush()
        out[name] = hz.id
    return out


async def _make_device(
    s: AsyncSession,
    label: str,
    *,
    dev_eui: str | None = None,
    zone_id: int | None = None,
    retired: bool = False,
) -> Device:
    dev = Device(
        dev_eui=dev_eui or _eui(),
        kind=DeviceKind.THERMOSTAT,
        vendor=DeviceVendor.MCLIMATE,
        model="Vicki",
        label=label,
        heating_zone_id=zone_id,
        retired_at=NOW - timedelta(days=1) if retired else None,
    )
    s.add(dev)
    await s.flush()
    return dev


def _row(zimmer: str | None, zone: str | None, dev_eui: str) -> PairingCsvRow:
    return PairingCsvRow(
        stockwerk=None,
        zimmer_nummer=zimmer,
        zimmer_typ=None,
        zone_label=zone,
        dev_eui=dev_eui,
        app_key=None,  # Montage-CSV kommt ohne AppKey (C8)
    )


async def _add_reading(
    s: AsyncSession,
    device_id: int,
    *,
    minutes_ago: int,
    backplate: bool | None,
) -> None:
    s.add(
        SensorReading(
            time=NOW - timedelta(minutes=minutes_ago),
            device_id=device_id,
            temperature=Decimal("21.0"),
            attached_backplate=backplate,
        )
    )
    await s.flush()


# ---------------------------------------------------------------------------
# Filter + Coercion (reine Funktionen)
# ---------------------------------------------------------------------------


def test_filter_keeps_only_named_rooms() -> None:
    rows = [
        _row("54", "Bad", "aabbccddeeff0001"),
        _row("102", "Bad", "aabbccddeeff0002"),
        _row("207", "Bad", "aabbccddeeff0003"),
    ]
    gefiltert = filter_rows(rows, ["54", "207"])
    assert [r.zimmer_nummer for _o, r in gefiltert] == ["54", "207"]


def test_filter_drops_pool_rows() -> None:
    rows = [_row(None, None, "aabbccddeeff0001"), _row("54", "Bad", "aabbccddeeff0002")]
    gefiltert = filter_rows(rows, ["54"])
    assert len(gefiltert) == 1
    assert gefiltert[0][1].zimmer_nummer == "54"


def test_filter_keeps_original_csv_line_numbers() -> None:
    """Fehlermeldungen muessen auf die Zeile in der Datei zeigen, nicht auf
    die Position nach dem Filtern."""
    rows = [
        _row("999", "Bad", "aabbccddeeff0001"),
        _row("999", "Bad", "aabbccddeeff0002"),
        _row("54", "Bad", "aabbccddeeff0003"),
    ]
    gefiltert = filter_rows(rows, ["54"])
    assert gefiltert[0][0] == 4  # Zeile 1 = Header, also ist die dritte Row Zeile 4


def test_zimmer_nummer_float_string_is_coerced() -> None:
    """B-Sprint13a-3: Excel schreibt aus '52' gern '52.0'."""
    assert _row("52.0", "Bad", "aabbccddeeff0001").zimmer_nummer == "52"
    assert _row("52.00", "Bad", "aabbccddeeff0001").zimmer_nummer == "52"


def test_zimmer_nummer_keeps_non_numeric() -> None:
    """B-Sprint13a-2: 'DG' oder '101A' duerfen nicht mehr crashen."""
    assert _row("101A", "Bad", "aabbccddeeff0001").zimmer_nummer == "101A"
    assert _row("DG", "Bad", "aabbccddeeff0001").zimmer_nummer == "DG"


def test_zimmer_nummer_does_not_truncate_real_decimals() -> None:
    """Aus '52.5' darf NICHT '52' werden — das waere stilles Verbiegen."""
    assert _row("52.5", "Bad", "aabbccddeeff0001").zimmer_nummer == "52.5"


# ---------------------------------------------------------------------------
# Happy Path
# ---------------------------------------------------------------------------


async def test_assign_writes_and_confirms_backplate(session: AsyncSession) -> None:
    zonen = await _make_room(session, f"c8{_short()}"[:20], "Bad", "Schlafzimmer")
    d1 = await _make_device(session, "006")
    d2 = await _make_device(session, "007")
    room_number = (
        await session.execute(
            select(Room.number).where(
                Room.id.in_(select(HeatingZone.room_id).where(HeatingZone.id == zonen["Bad"]))
            )
        )
    ).scalar_one()

    rows = [
        _row(room_number, "Bad", d1.dev_eui),
        _row(room_number, "Schlafzimmer", d2.dev_eui),
    ]
    await _add_reading(session, d1.id, minutes_ago=2, backplate=True)
    await _add_reading(session, d2.id, minutes_ago=3, backplate=True)

    report = await run_assign(session, rows, [room_number], now=NOW)
    assert report.errors == []
    assert report.written == 2
    assert report.backplate_warnings == []
    assert report.exit_code == 0

    await session.refresh(d1)
    await session.refresh(d2)
    assert d1.heating_zone_id == zonen["Bad"]
    assert d2.heating_zone_id == zonen["Schlafzimmer"]


async def test_assign_writes_shared_audit(session: AsyncSession) -> None:
    """Dasselbe Audit wie der API-Pfad — eine Service-Funktion, eine Spur."""
    zonen = await _make_room(session, f"c8{_short()}"[:20], "Bad")
    room_number = (
        await session.execute(
            select(Room.number).where(
                Room.id.in_(select(HeatingZone.room_id).where(HeatingZone.id == zonen["Bad"]))
            )
        )
    ).scalar_one()
    dev = await _make_device(session, "008")
    await _add_reading(session, dev.id, minutes_ago=1, backplate=True)

    await run_assign(session, [_row(room_number, "Bad", dev.dev_eui)], [room_number], now=NOW)

    audit = (
        await session.execute(
            select(BusinessAudit).where(
                BusinessAudit.action == "DEVICE_ZONE_ASSIGNED",
                BusinessAudit.target_id == dev.id,
            )
        )
    ).scalar_one()
    assert audit.target_type == "device"
    assert audit.old_value == {"heating_zone_id": None}
    assert audit.new_value["heating_zone_id"] == zonen["Bad"]
    assert audit.new_value["source"] == "assign_cli"


async def test_assign_dry_run_writes_nothing(session: AsyncSession) -> None:
    zonen = await _make_room(session, f"c8{_short()}"[:20], "Bad")
    room_number = (
        await session.execute(
            select(Room.number).where(
                Room.id.in_(select(HeatingZone.room_id).where(HeatingZone.id == zonen["Bad"]))
            )
        )
    ).scalar_one()
    dev = await _make_device(session, "009")

    report = await run_assign(
        session, [_row(room_number, "Bad", dev.dev_eui)], [room_number], dry_run=True, now=NOW
    )
    assert report.errors == []
    assert len(report.planned) == 1
    assert report.written == 0
    await session.refresh(dev)
    assert dev.heating_zone_id is None
    assert "Vorschau" in format_report(report, dry_run=True)


# ---------------------------------------------------------------------------
# Pre-Flight: jeder Fehler einzeln, und nichts wird geschrieben
# ---------------------------------------------------------------------------


async def test_preflight_unknown_device(session: AsyncSession) -> None:
    zonen = await _make_room(session, f"c8{_short()}"[:20], "Bad")
    room_number = (
        await session.execute(
            select(Room.number).where(
                Room.id.in_(select(HeatingZone.room_id).where(HeatingZone.id == zonen["Bad"]))
            )
        )
    ).scalar_one()
    report = await run_assign(session, [_row(room_number, "Bad", _eui())], [room_number], now=NOW)
    assert report.exit_code == 1
    assert any("Geraet unbekannt" in e for e in report.errors)
    assert report.written == 0


async def test_preflight_retired_device(session: AsyncSession) -> None:
    zonen = await _make_room(session, f"c8{_short()}"[:20], "Bad")
    room_number = (
        await session.execute(
            select(Room.number).where(
                Room.id.in_(select(HeatingZone.room_id).where(HeatingZone.id == zonen["Bad"]))
            )
        )
    ).scalar_one()
    dev = await _make_device(session, "010", retired=True)
    report = await run_assign(
        session, [_row(room_number, "Bad", dev.dev_eui)], [room_number], now=NOW
    )
    assert any("stillgelegt" in e for e in report.errors)
    await session.refresh(dev)
    assert dev.heating_zone_id is None


async def test_preflight_device_already_in_other_zone(session: AsyncSession) -> None:
    zonen = await _make_room(session, f"c8{_short()}"[:20], "Bad", "Schlafzimmer")
    room_number = (
        await session.execute(
            select(Room.number).where(
                Room.id.in_(select(HeatingZone.room_id).where(HeatingZone.id == zonen["Bad"]))
            )
        )
    ).scalar_one()
    dev = await _make_device(session, "011", zone_id=zonen["Schlafzimmer"])
    report = await run_assign(
        session, [_row(room_number, "Bad", dev.dev_eui)], [room_number], now=NOW
    )
    assert any("haengt bereits an Zone" in e for e in report.errors)


async def test_preflight_unknown_zone(session: AsyncSession) -> None:
    zonen = await _make_room(session, f"c8{_short()}"[:20], "Bad")
    room_number = (
        await session.execute(
            select(Room.number).where(
                Room.id.in_(select(HeatingZone.room_id).where(HeatingZone.id == zonen["Bad"]))
            )
        )
    ).scalar_one()
    dev = await _make_device(session, "012")
    report = await run_assign(
        session, [_row(room_number, "Kinderzimmer", dev.dev_eui)], [room_number], now=NOW
    )
    assert any("Zone nicht in der Datenbank" in e for e in report.errors)


async def test_preflight_zone_already_occupied(session: AsyncSession) -> None:
    zonen = await _make_room(session, f"c8{_short()}"[:20], "Bad")
    room_number = (
        await session.execute(
            select(Room.number).where(
                Room.id.in_(select(HeatingZone.room_id).where(HeatingZone.id == zonen["Bad"]))
            )
        )
    ).scalar_one()
    await _make_device(session, "013", zone_id=zonen["Bad"])
    neu = await _make_device(session, "014")
    report = await run_assign(
        session, [_row(room_number, "Bad", neu.dev_eui)], [room_number], now=NOW
    )
    assert any("bereits ein aktives Geraet" in e for e in report.errors)
    await session.refresh(neu)
    assert neu.heating_zone_id is None


async def test_preflight_duplicate_zone_within_csv(session: AsyncSession) -> None:
    zonen = await _make_room(session, f"c8{_short()}"[:20], "Bad")
    room_number = (
        await session.execute(
            select(Room.number).where(
                Room.id.in_(select(HeatingZone.room_id).where(HeatingZone.id == zonen["Bad"]))
            )
        )
    ).scalar_one()
    a = await _make_device(session, "015")
    b = await _make_device(session, "016")
    report = await run_assign(
        session,
        [_row(room_number, "Bad", a.dev_eui), _row(room_number, "Bad", b.dev_eui)],
        [room_number],
        now=NOW,
    )
    assert any("zweimal" in e for e in report.errors)


async def test_preflight_collects_all_errors_not_just_first(session: AsyncSession) -> None:
    """Der Hotelier soll die Liste EINMAL korrigieren, nicht vierzehnmal."""
    zonen = await _make_room(session, f"c8{_short()}"[:20], "Bad", "Schlafzimmer")
    room_number = (
        await session.execute(
            select(Room.number).where(
                Room.id.in_(select(HeatingZone.room_id).where(HeatingZone.id == zonen["Bad"]))
            )
        )
    ).scalar_one()
    retired = await _make_device(session, "017", retired=True)
    report = await run_assign(
        session,
        [
            _row(room_number, "Bad", _eui()),  # unbekannt
            _row(room_number, "Schlafzimmer", retired.dev_eui),  # stillgelegt
        ],
        [room_number],
        now=NOW,
    )
    assert len(report.errors) == 2
    assert report.written == 0
    assert "[ABBRUCH]" in format_report(report, dry_run=False)


async def test_no_matching_rooms_is_an_error(session: AsyncSession) -> None:
    report = await run_assign(session, [_row("54", "Bad", _eui())], ["999"], now=NOW)
    assert report.exit_code == 1
    assert any("Keine Zeile passt" in e for e in report.errors)


async def test_assign_is_idempotent(session: AsyncSession) -> None:
    """Zweiter Lauf derselben Liste: nichts Neues, kein zweites Audit."""
    zonen = await _make_room(session, f"c8{_short()}"[:20], "Bad")
    room_number = (
        await session.execute(
            select(Room.number).where(
                Room.id.in_(select(HeatingZone.room_id).where(HeatingZone.id == zonen["Bad"]))
            )
        )
    ).scalar_one()
    dev = await _make_device(session, "018")
    await _add_reading(session, dev.id, minutes_ago=1, backplate=True)
    rows = [_row(room_number, "Bad", dev.dev_eui)]

    first = await run_assign(session, rows, [room_number], now=NOW)
    assert first.written == 1
    second = await run_assign(session, rows, [room_number], now=NOW)
    assert second.written == 0
    assert second.unchanged == 1

    audits = (
        (
            await session.execute(
                select(BusinessAudit).where(
                    BusinessAudit.action == "DEVICE_ZONE_ASSIGNED",
                    BusinessAudit.target_id == dev.id,
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(list(audits)) == 1


# ---------------------------------------------------------------------------
# Backplate-Nachpruefung
# ---------------------------------------------------------------------------


async def test_backplate_warning_does_not_roll_back(session: AsyncSession) -> None:
    """Warnung, Exit-Code 2 — aber die Zuordnung bleibt stehen."""
    zonen = await _make_room(session, f"c8{_short()}"[:20], "Bad")
    room_number = (
        await session.execute(
            select(Room.number).where(
                Room.id.in_(select(HeatingZone.room_id).where(HeatingZone.id == zonen["Bad"]))
            )
        )
    ).scalar_one()
    dev = await _make_device(session, "019")
    await _add_reading(session, dev.id, minutes_ago=2, backplate=False)

    report = await run_assign(
        session, [_row(room_number, "Bad", dev.dev_eui)], [room_number], now=NOW
    )
    assert report.written == 1
    assert report.exit_code == 2
    assert any("NICHT montiert" in w for w in report.backplate_warnings)
    await session.refresh(dev)
    assert dev.heating_zone_id == zonen["Bad"]  # NICHT zurueckgenommen

    text = format_report(report, dry_run=False)
    assert "NICHT zurueckgenommen" in text


async def test_backplate_stale_reading_warns(session: AsyncSession) -> None:
    dev = await _make_device(session, "020")
    await _add_reading(session, dev.id, minutes_ago=120, backplate=True)
    from heizung.scripts.pairing.assign import PlannedAssignment

    warnings = await check_backplate(
        session,
        [
            PlannedAssignment(
                row_number=2,
                device_id=dev.id,
                dev_eui=dev.dev_eui,
                hardware_nummer="020",
                heating_zone_id=1,
                zimmer_nummer="54",
                zone_label="Bad",
            )
        ],
        now=NOW,
    )
    assert len(warnings) == 1
    assert "aelter als" in warnings[0]


async def test_backplate_no_reading_warns(session: AsyncSession) -> None:
    dev = await _make_device(session, "021")
    from heizung.scripts.pairing.assign import PlannedAssignment

    warnings = await check_backplate(
        session,
        [
            PlannedAssignment(
                row_number=2,
                device_id=dev.id,
                dev_eui=dev.dev_eui,
                hardware_nummer="021",
                heating_zone_id=1,
                zimmer_nummer="54",
                zone_label="Bad",
            )
        ],
        now=NOW,
    )
    assert len(warnings) == 1
    assert "noch kein einziger Uplink" in warnings[0]


async def test_backplate_null_field_warns(session: AsyncSession) -> None:
    """Alter Codec / FW < 4.1: Feld fehlt — das ist nicht dasselbe wie false."""
    dev = await _make_device(session, "022")
    await _add_reading(session, dev.id, minutes_ago=2, backplate=None)
    from heizung.scripts.pairing.assign import PlannedAssignment

    warnings = await check_backplate(
        session,
        [
            PlannedAssignment(
                row_number=2,
                device_id=dev.id,
                dev_eui=dev.dev_eui,
                hardware_nummer="022",
                heating_zone_id=1,
                zimmer_nummer="54",
                zone_label="Bad",
            )
        ],
        now=NOW,
    )
    assert len(warnings) == 1
    assert "ohne Backplate-Feld" in warnings[0]
