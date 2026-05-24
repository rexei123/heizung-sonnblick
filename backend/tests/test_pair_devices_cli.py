"""Sprint 13a T6 — CLI-Entrypoint Tests.

DB-Tests gegen ``TEST_DATABASE_URL`` (analog T3-T5). ``SessionLocal``
wird via ``monkeypatch`` durch eine Test-Session-Factory ersetzt, damit
der CLI denselben Session-Context nutzt wie die Test-Fixtures.

Downlinks (``set_open_window_detection`` + ``send_setpoint``) werden
ueber den jeweiligen Modul-Pfad gemockt — kein echter MQTT-Call.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
import pytest_asyncio
from alembic.config import Config
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from alembic import command
from heizung.models.device import Device
from heizung.models.enums import DeviceKind, DeviceVendor, HeatingZoneKind, UserRole
from heizung.models.heating_zone import HeatingZone
from heizung.models.room import Room
from heizung.models.room_type import RoomType
from heizung.models.sensor_reading import SensorReading
from heizung.models.user import User
from heizung.scripts import pair_devices
from heizung.scripts.pairing import inbound_test, pairing_service

DATABASE_URL = os.environ.get("DATABASE_URL")
DATABASE_URL_PRESENT = bool(DATABASE_URL)
SKIP_REASON = "DATABASE_URL nicht gesetzt - DB-Tests brauchen Test-DB"

_VALID_APP_KEY = "abcdef0123456789abcdef0123456789"


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


@pytest_asyncio.fixture
def patched_session_local(session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> AsyncSession:
    """Patcht ``pair_devices.SessionLocal`` durch eine Factory, die die
    Test-Session als Context-Manager rausgibt. ``commit``/``rollback`` werden
    von dem CLI gerufen, der finale Test-Rollback der ``session``-Fixture
    raeumt alles weg.
    """

    @asynccontextmanager
    async def fake_factory() -> AsyncIterator[AsyncSession]:
        yield session

    monkeypatch.setattr(pair_devices, "SessionLocal", fake_factory)
    return session


@pytest_asyncio.fixture
def mock_all_downlinks(monkeypatch: pytest.MonkeyPatch) -> dict[str, int]:
    """Mockt set_open_window_detection + send_setpoint in BEIDEN
    konsumierenden Modulen (pairing_service + inbound_test)."""
    counters = {"set_ow": 0, "send_setpoint": 0}

    async def fake_set_ow(*args: object, **kwargs: object) -> str:
        counters["set_ow"] += 1
        return "topic"

    async def fake_send_setpoint(*args: object, **kwargs: object) -> str:
        counters["send_setpoint"] += 1
        return "topic"

    async def no_sleep(seconds: int) -> None:
        return None

    monkeypatch.setattr(pairing_service, "set_open_window_detection", fake_set_ow)
    monkeypatch.setattr(inbound_test, "set_open_window_detection", fake_set_ow)
    monkeypatch.setattr(inbound_test, "send_setpoint", fake_send_setpoint)
    monkeypatch.setattr(inbound_test, "_sleep", no_sleep)
    return counters


def _short() -> str:
    return uuid.uuid4().hex[:8]


def _eui() -> str:
    return uuid.uuid4().hex[:16]


async def _seed_zone(s: AsyncSession, *, room_number: str, zone_name: str) -> tuple[int, int]:
    short = _short()
    rt = RoomType(name=f"t6-{short}")
    s.add(rt)
    await s.flush()
    room = Room(number=room_number, room_type_id=rt.id)
    s.add(room)
    await s.flush()
    hz = HeatingZone(room_id=room.id, kind=HeatingZoneKind.BEDROOM, name=zone_name)
    s.add(hz)
    await s.flush()
    return room.id, hz.id


def _write_csv(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_cmd_validate_happy_path(
    patched_session_local: AsyncSession,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """validate-Subcommand: gueltige CSV -> Exit 0 + '[OK] N CSV-Rows validiert'."""
    await _seed_zone(patched_session_local, room_number="7101", zone_name="Schlafzimmer")
    csv_path = tmp_path / "ok.csv"
    _write_csv(
        csv_path,
        "stockwerk,zimmer_nummer,zimmer_typ,zone_label,dev_eui,app_key\n"
        f"1,7101,Standard,Schlafzimmer,{_eui()},{_VALID_APP_KEY}\n",
    )
    exit_code = await pair_devices.main_async(["validate", str(csv_path)])
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "[OK]" in out
    assert "1 CSV-Rows validiert" in out


async def test_cmd_validate_with_errors_returns_1(
    patched_session_local: AsyncSession,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """validate-Subcommand: Zimmer fehlt in DB -> Exit 1 + Diff-Liste."""
    csv_path = tmp_path / "bad.csv"
    _write_csv(
        csv_path,
        "stockwerk,zimmer_nummer,zimmer_typ,zone_label,dev_eui,app_key\n"
        f"1,99999,Standard,Schlafzimmer,{_eui()},{_VALID_APP_KEY}\n",
    )
    exit_code = await pair_devices.main_async(["validate", str(csv_path)])
    assert exit_code == 1
    out = capsys.readouterr().out
    assert "[FAIL]" in out
    assert "Zimmer 99999" in out


async def test_cmd_import_dry_run_db_unchanged(
    patched_session_local: AsyncSession,
    tmp_path: Path,
    mock_all_downlinks: dict[str, int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """import --dry-run: Device-Count unveraendert, Downlinks gesendet."""
    await _seed_zone(patched_session_local, room_number="7102", zone_name="Schlafzimmer")
    before = await patched_session_local.scalar(select(func.count(Device.id)))
    csv_path = tmp_path / "dry.csv"
    _write_csv(
        csv_path,
        "stockwerk,zimmer_nummer,zimmer_typ,zone_label,dev_eui,app_key\n"
        f"1,7102,Standard,Schlafzimmer,{_eui()},{_VALID_APP_KEY}\n",
    )
    exit_code = await pair_devices.main_async(["import", str(csv_path), "--dry-run"])
    assert exit_code == 0
    after = await patched_session_local.scalar(select(func.count(Device.id)))
    assert before == after  # Rollback hat geklappt
    # Downlink wurde trotzdem gesendet.
    assert mock_all_downlinks["set_ow"] == 1
    captured = capsys.readouterr()
    assert "[WARN] --dry-run aktiv" in captured.err
    assert "[DRY-RUN]" in captured.err


async def test_cmd_import_real_with_user_email(
    patched_session_local: AsyncSession,
    tmp_path: Path,
    mock_all_downlinks: dict[str, int],
) -> None:
    """import (ohne --dry-run): Device + Audit angelegt, user_id im Audit."""
    # Sprint 13b.2 T7-prep (CLAUDE.md §5.18): Suffix gegen Stale-Rows aus
    # frueheren Test-Runs (uq_room_number-UniqueViolation). CSV-
    # zimmer_nummer wird vom Pydantic-Validator als int geparsed
    # (csv_parser §142), also muss der Suffix numerisch bleiben — keine
    # Bindestrich-Variante moeglich.
    room_num = str(7_100_000 + int(_short(), 16) % 100_000)
    await _seed_zone(patched_session_local, room_number=room_num, zone_name="Schlafzimmer")
    test_email = f"cli-t6-{_short()}@example.com"
    user = User(
        email=test_email,
        password_hash="x" * 60,
        role=UserRole.ADMIN,
        is_active=True,
        must_change_password=False,
    )
    patched_session_local.add(user)
    await patched_session_local.flush()
    dev_eui = _eui()
    csv_path = tmp_path / "real.csv"
    _write_csv(
        csv_path,
        "stockwerk,zimmer_nummer,zimmer_typ,zone_label,dev_eui,app_key\n"
        f"1,{room_num},Standard,Schlafzimmer,{dev_eui},{_VALID_APP_KEY}\n",
    )
    exit_code = await pair_devices.main_async(["import", str(csv_path), "--user-email", test_email])
    assert exit_code == 0
    # Device existiert in DB.
    stmt = select(Device.id).where(Device.dev_eui == dev_eui)
    device_id = await patched_session_local.scalar(stmt)
    assert device_id is not None
    # Audit-Row hat user_id gesetzt.
    from heizung.models.business_audit import BusinessAudit

    audit_stmt = select(BusinessAudit).where(BusinessAudit.target_id == device_id)
    audit = (await patched_session_local.execute(audit_stmt)).scalar_one()
    assert audit.user_id == user.id


async def test_cmd_import_invalid_user_email_aborts(
    patched_session_local: AsyncSession,
    tmp_path: Path,
    mock_all_downlinks: dict[str, int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """import mit unbekannter --user-email -> Exit 1, kein Pairing."""
    await _seed_zone(patched_session_local, room_number="7104", zone_name="Schlafzimmer")
    csv_path = tmp_path / "no-user.csv"
    _write_csv(
        csv_path,
        "stockwerk,zimmer_nummer,zimmer_typ,zone_label,dev_eui,app_key\n"
        f"1,7104,Standard,Schlafzimmer,{_eui()},{_VALID_APP_KEY}\n",
    )
    exit_code = await pair_devices.main_async(
        ["import", str(csv_path), "--user-email", "nonexistent@example.com"]
    )
    assert exit_code == 1
    err = capsys.readouterr().err
    assert "[FAIL] User-Email 'nonexistent@example.com' nicht gefunden" in err
    # Kein Downlink, weil Abbruch VOR pair_batch.
    assert mock_all_downlinks["set_ow"] == 0


async def test_cmd_test_via_device_id(
    patched_session_local: AsyncSession,
    mock_all_downlinks: dict[str, int],
) -> None:
    """test <device.id>: Auto-Detect Integer-Pfad -> Eingangstest laeuft."""
    device = Device(
        dev_eui=_eui(),
        kind=DeviceKind.THERMOSTAT,
        vendor=DeviceVendor.MCLIMATE,
        model="Vicki",
    )
    patched_session_local.add(device)
    await patched_session_local.flush()
    patched_session_local.add(
        SensorReading(
            time=datetime.now(tz=UTC) - timedelta(minutes=1),
            device_id=device.id,
            temperature=Decimal("22.0"),
            attached_backplate=True,
        )
    )
    await patched_session_local.flush()
    exit_code = await pair_devices.main_async(["test", str(device.id), "--non-interactive"])
    assert exit_code == 0
    assert mock_all_downlinks["set_ow"] >= 1  # OW-Resend Schritt 0
    assert mock_all_downlinks["send_setpoint"] == 2  # Setpoint 25 + 10


async def test_cmd_test_via_dev_eui(
    patched_session_local: AsyncSession,
    mock_all_downlinks: dict[str, int],
) -> None:
    """test <dev_eui>: Auto-Detect Hex-Pfad -> Eingangstest laeuft."""
    dev_eui = _eui()
    device = Device(
        dev_eui=dev_eui,
        kind=DeviceKind.THERMOSTAT,
        vendor=DeviceVendor.MCLIMATE,
        model="Vicki",
    )
    patched_session_local.add(device)
    await patched_session_local.flush()
    patched_session_local.add(
        SensorReading(
            time=datetime.now(tz=UTC) - timedelta(minutes=1),
            device_id=device.id,
            temperature=Decimal("22.0"),
            attached_backplate=True,
        )
    )
    await patched_session_local.flush()
    # dev_eui in uppercase angeben — Auto-Detect lowercased intern.
    exit_code = await pair_devices.main_async(["test", dev_eui.upper(), "--non-interactive"])
    assert exit_code == 0


async def test_cmd_test_invalid_arg_returns_1(
    patched_session_local: AsyncSession,
    mock_all_downlinks: dict[str, int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """test <invalid>: weder int noch 16-Hex -> [FAIL] Device nicht gefunden."""
    exit_code = await pair_devices.main_async(["test", "xyz_not_an_id_or_eui", "--non-interactive"])
    assert exit_code == 1
    err = capsys.readouterr().err
    assert "[FAIL] Device 'xyz_not_an_id_or_eui' nicht gefunden" in err


async def test_cmd_list_pool_shows_pool_devices(
    patched_session_local: AsyncSession,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """list-pool: Devices ohne heating_zone_id sind in der Ausgabe."""
    # Pool-Device anlegen (heating_zone_id = NULL).
    pool_eui = _eui()
    patched_session_local.add(
        Device(
            dev_eui=pool_eui,
            kind=DeviceKind.THERMOSTAT,
            vendor=DeviceVendor.MCLIMATE,
            model="Vicki",
        )
    )
    # Active-Device zur Negativ-Probe.
    _, zone_id = await _seed_zone(
        patched_session_local, room_number="7105", zone_name="Schlafzimmer"
    )
    active_eui = _eui()
    patched_session_local.add(
        Device(
            dev_eui=active_eui,
            kind=DeviceKind.THERMOSTAT,
            vendor=DeviceVendor.MCLIMATE,
            model="Vicki",
            heating_zone_id=zone_id,
        )
    )
    await patched_session_local.flush()
    exit_code = await pair_devices.main_async(["list-pool"])
    assert exit_code == 0
    out = capsys.readouterr().out
    assert pool_eui in out
    # Active-Device taucht NICHT auf (es hat heating_zone_id).
    assert active_eui not in out
