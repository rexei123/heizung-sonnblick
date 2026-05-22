"""Sprint 13a T3 — CSV-Parser + DB-Pre-Flight-Checks.

Pure-Function-Tests fuer ``parse_csv`` via ``tmp_path``-Fixture.
DB-Tests fuer ``validate_against_db`` + ``check_dev_eui_duplicates``
skippen ohne ``TEST_DATABASE_URL`` (analog ``test_override_pms_hook.py``).
"""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from alembic.config import Config
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
from heizung.scripts.pairing.csv_parser import (
    MAX_ROWS,
    check_dev_eui_duplicates,
    parse_csv,
    validate_against_db,
)
from heizung.scripts.pairing.csv_row import PairingCsvRow
from heizung.scripts.pairing.exceptions import ParseError

DATABASE_URL = os.environ.get("DATABASE_URL")
DATABASE_URL_PRESENT = bool(DATABASE_URL)
SKIP_REASON = "DATABASE_URL nicht gesetzt - DB-Tests brauchen Test-DB"

_VALID_DEV_EUI_1 = "70b3d52dd3034de4"
_VALID_DEV_EUI_2 = "70b3d52dd3034de5"
_VALID_DEV_EUI_3 = "70b3d52dd3034de6"
_VALID_APP_KEY = "abcdef0123456789abcdef0123456789"


# ---------------------------------------------------------------------------
# Pure-Function-Tests fuer parse_csv
# ---------------------------------------------------------------------------


def _write_csv(path: Path, content: str) -> None:
    """Helper: schreibt einen String als utf-8 (ohne BOM, fuer Standard-Tests)."""
    path.write_text(content, encoding="utf-8")


def test_parse_csv_happy_path_comma_delimiter(tmp_path: Path) -> None:
    """3 Rows (2 Active + 1 Pool), Komma-Trennzeichen."""
    csv_path = tmp_path / "pairing.csv"
    _write_csv(
        csv_path,
        "stockwerk,zimmer_nummer,zimmer_typ,zone_label,dev_eui,app_key\n"
        f"1,101,Standard,Schlafzimmer,{_VALID_DEV_EUI_1},{_VALID_APP_KEY}\n"
        f"1,101,Standard,Bad,{_VALID_DEV_EUI_2},{_VALID_APP_KEY}\n"
        f",,,,{_VALID_DEV_EUI_3},{_VALID_APP_KEY}\n",
    )
    rows = parse_csv(csv_path)
    assert len(rows) == 3
    assert rows[0].zimmer_nummer == 101
    assert rows[0].zone_label == "Schlafzimmer"
    assert rows[0].is_pool_device is False
    assert rows[2].is_pool_device is True
    assert rows[2].zimmer_nummer is None


def test_parse_csv_happy_path_semicolon_delimiter(tmp_path: Path) -> None:
    """Deutsches Excel produziert Semikolon-getrennte CSV."""
    csv_path = tmp_path / "pairing-de.csv"
    _write_csv(
        csv_path,
        "stockwerk;zimmer_nummer;zimmer_typ;zone_label;dev_eui;app_key\n"
        f"1;101;Standard;Schlafzimmer;{_VALID_DEV_EUI_1};{_VALID_APP_KEY}\n"
        f"2;202;Suite;Wohnzimmer;{_VALID_DEV_EUI_2};{_VALID_APP_KEY}\n",
    )
    rows = parse_csv(csv_path)
    assert len(rows) == 2
    assert rows[0].stockwerk == 1
    assert rows[1].zimmer_typ == "Suite"


def test_parse_csv_utf8_bom_handled(tmp_path: Path) -> None:
    """Excel-Export-BOM (utf-8-sig) wird transparent gestrippt."""
    csv_path = tmp_path / "pairing-bom.csv"
    # BOM (﻿) am Anfang der Datei — typisch fuer Excel-Export.
    content = (
        "﻿stockwerk,zimmer_nummer,zimmer_typ,zone_label,dev_eui,app_key\n"
        f"1,101,Standard,Schlafzimmer,{_VALID_DEV_EUI_1},{_VALID_APP_KEY}\n"
    )
    csv_path.write_text(content, encoding="utf-8")
    rows = parse_csv(csv_path)
    assert len(rows) == 1
    # Erste Spalte muss als 'stockwerk' (ohne BOM-Praefix) erkannt sein.
    assert rows[0].stockwerk == 1


def test_parse_csv_pool_row_empty_strings_to_none(tmp_path: Path) -> None:
    """Leere Strings in Pool-Spalten werden zu None konvertiert (Pydantic
    int|None erlaubt sonst kein '')."""
    csv_path = tmp_path / "pool.csv"
    _write_csv(
        csv_path,
        "stockwerk,zimmer_nummer,zimmer_typ,zone_label,dev_eui,app_key\n"
        f",,,,{_VALID_DEV_EUI_1},{_VALID_APP_KEY}\n",
    )
    rows = parse_csv(csv_path)
    assert len(rows) == 1
    assert rows[0].stockwerk is None
    assert rows[0].zimmer_nummer is None
    assert rows[0].zimmer_typ is None
    assert rows[0].zone_label is None
    assert rows[0].is_pool_device is True


def test_parse_csv_header_case_insensitive(tmp_path: Path) -> None:
    """Spalten-Header in gemischter Schreibweise (Excel exportiert oft so)."""
    csv_path = tmp_path / "case.csv"
    _write_csv(
        csv_path,
        "Stockwerk,ZIMMER_NUMMER,Zimmer_Typ,Zone_Label,DEV_EUI,App_Key\n"
        f"1,101,Standard,Schlafzimmer,{_VALID_DEV_EUI_1},{_VALID_APP_KEY}\n",
    )
    rows = parse_csv(csv_path)
    assert len(rows) == 1
    assert rows[0].dev_eui == _VALID_DEV_EUI_1


def test_parse_csv_collects_validation_errors(tmp_path: Path) -> None:
    """Pydantic-Fehler in Zeile 2 + 4 werden GESAMMELT, nicht fail-fast."""
    csv_path = tmp_path / "errors.csv"
    _write_csv(
        csv_path,
        "stockwerk,zimmer_nummer,zimmer_typ,zone_label,dev_eui,app_key\n"
        # Zeile 2: dev_eui zu kurz
        f"1,101,Standard,Schlafzimmer,DEADBEEF,{_VALID_APP_KEY}\n"
        # Zeile 3: OK
        f"1,101,Standard,Bad,{_VALID_DEV_EUI_2},{_VALID_APP_KEY}\n"
        # Zeile 4: Pool-Inkonsistenz (zimmer_nummer ohne zone_label)
        f"2,202,Suite,,{_VALID_DEV_EUI_3},{_VALID_APP_KEY}\n",
    )
    with pytest.raises(ParseError) as exc_info:
        parse_csv(csv_path)
    assert len(exc_info.value.errors) == 2
    # Beide Errors enthalten ihre Zeilen-Nummer.
    joined = "\n".join(exc_info.value.errors)
    assert "Zeile 2" in joined
    assert "Zeile 4" in joined


def test_parse_csv_max_rows_exceeded(tmp_path: Path) -> None:
    """Datei > MAX_ROWS bricht mit ParseError ab."""
    csv_path = tmp_path / "huge.csv"
    header = "stockwerk,zimmer_nummer,zimmer_typ,zone_label,dev_eui,app_key\n"
    # Generiere MAX_ROWS+1 Daten-Zeilen mit eindeutigen DevEUIs.
    rows = "\n".join(
        f"1,{100 + i},Standard,Schlafzimmer,{i:016x},{_VALID_APP_KEY}" for i in range(MAX_ROWS + 1)
    )
    _write_csv(csv_path, header + rows + "\n")
    with pytest.raises(ParseError) as exc_info:
        parse_csv(csv_path)
    assert f"{MAX_ROWS}-Zeilen-Limit" in str(exc_info.value)


def test_parse_csv_empty_file_raises(tmp_path: Path) -> None:
    """Leere Datei -> ParseError mit klarem Hinweis."""
    csv_path = tmp_path / "empty.csv"
    _write_csv(csv_path, "")
    with pytest.raises(ParseError) as exc_info:
        parse_csv(csv_path)
    assert "leer" in str(exc_info.value).lower()


# ---------------------------------------------------------------------------
# DB-Tests fuer validate_against_db + check_dev_eui_duplicates
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


def _short() -> str:
    return uuid.uuid4().hex[:8]


def _eui() -> str:
    return uuid.uuid4().hex[:16]


async def _seed_room_with_zone(
    s: AsyncSession, *, room_number: str, zone_name: str
) -> tuple[int, int]:
    """Legt RoomType + Room + HeatingZone an, returns (room_id, zone_id)."""
    short = _short()
    rt = RoomType(name=f"t13a-{short}")
    s.add(rt)
    await s.flush()
    room = Room(number=room_number, room_type_id=rt.id)
    s.add(room)
    await s.flush()
    hz = HeatingZone(room_id=room.id, kind=HeatingZoneKind.BEDROOM, name=zone_name)
    s.add(hz)
    await s.flush()
    return room.id, hz.id


async def test_validate_against_db_happy_path(session: AsyncSession) -> None:
    """Active-Row mit passender Zimmer+Zone in DB -> leere Diff-Liste."""
    await _seed_room_with_zone(session, room_number="9101", zone_name="Schlafzimmer")
    row = PairingCsvRow(
        stockwerk=1,
        zimmer_nummer=9101,
        zimmer_typ="Standard",
        zone_label="Schlafzimmer",
        dev_eui=_eui(),
        app_key=_VALID_APP_KEY,
    )
    errors = await validate_against_db([row], session)
    assert errors == []


async def test_validate_against_db_room_missing(session: AsyncSession) -> None:
    """Active-Row, Zimmer existiert nicht in DB -> Diff-Message."""
    row = PairingCsvRow(
        stockwerk=1,
        zimmer_nummer=99999,  # garantiert nicht in DB
        zimmer_typ="Standard",
        zone_label="Schlafzimmer",
        dev_eui=_eui(),
        app_key=_VALID_APP_KEY,
    )
    errors = await validate_against_db([row], session)
    assert len(errors) == 1
    assert "Zimmer 99999" in errors[0]
    assert "Schlafzimmer" in errors[0]


async def test_validate_against_db_zone_label_wrong(session: AsyncSession) -> None:
    """Zimmer existiert, aber Zone-Label passt nicht -> Diff-Message."""
    await _seed_room_with_zone(session, room_number="9102", zone_name="Schlafzimmer")
    row = PairingCsvRow(
        stockwerk=1,
        zimmer_nummer=9102,
        zimmer_typ="Standard",
        zone_label="Bad",  # 'Bad' existiert nicht fuer diesen Raum
        dev_eui=_eui(),
        app_key=_VALID_APP_KEY,
    )
    errors = await validate_against_db([row], session)
    assert len(errors) == 1
    assert "Zimmer 9102" in errors[0]
    assert "Bad" in errors[0]


async def test_validate_against_db_pool_row_skipped(session: AsyncSession) -> None:
    """Pool-Row (zimmer_nummer/zone_label None) wird im DB-Check uebersprungen."""
    row = PairingCsvRow(
        stockwerk=None,
        zimmer_nummer=None,
        zimmer_typ=None,
        zone_label=None,
        dev_eui=_eui(),
        app_key=_VALID_APP_KEY,
    )
    errors = await validate_against_db([row], session)
    assert errors == []


async def test_check_dev_eui_duplicates_within_csv(session: AsyncSession) -> None:
    """DevEUI in zwei verschiedenen CSV-Rows -> Duplikat-Message."""
    dup_eui = _eui()
    row1 = PairingCsvRow(
        stockwerk=1,
        zimmer_nummer=9201,
        zimmer_typ="Standard",
        zone_label="Schlafzimmer",
        dev_eui=dup_eui,
        app_key=_VALID_APP_KEY,
    )
    row2 = PairingCsvRow(
        stockwerk=1,
        zimmer_nummer=9202,
        zimmer_typ="Standard",
        zone_label="Bad",
        dev_eui=dup_eui,
        app_key=_VALID_APP_KEY,
    )
    errors = await check_dev_eui_duplicates([row1, row2], session)
    assert len(errors) >= 1
    msg = errors[0]
    assert dup_eui in msg
    assert "Zeilen 2, 3" in msg or "mehrfach" in msg


async def test_check_dev_eui_duplicates_against_db(session: AsyncSession) -> None:
    """DevEUI existiert bereits in DB -> Konflikt-Message."""
    short = _short()
    rt = RoomType(name=f"t13a-{short}")
    session.add(rt)
    await session.flush()
    room = Room(number=f"t13a-dup-{short}"[:20], room_type_id=rt.id)
    session.add(room)
    await session.flush()
    hz = HeatingZone(room_id=room.id, kind=HeatingZoneKind.BEDROOM, name="zone-1")
    session.add(hz)
    await session.flush()
    existing_eui = _eui()
    existing_device = Device(
        dev_eui=existing_eui,
        kind=DeviceKind.THERMOSTAT,
        vendor=DeviceVendor.MCLIMATE,
        model="Vicki",
        heating_zone_id=hz.id,
    )
    session.add(existing_device)
    await session.flush()

    row = PairingCsvRow(
        stockwerk=1,
        zimmer_nummer=9301,
        zimmer_typ="Standard",
        zone_label="Schlafzimmer",
        dev_eui=existing_eui,
        app_key=_VALID_APP_KEY,
    )
    errors = await check_dev_eui_duplicates([row], session)
    assert len(errors) == 1
    assert existing_eui in errors[0]
    assert "existiert bereits in DB" in errors[0]
