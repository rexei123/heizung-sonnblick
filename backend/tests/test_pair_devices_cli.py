"""Sprint 13a T6 — CLI-Entrypoint Tests.

DB-Tests gegen ``TEST_DATABASE_URL`` (analog T3-T5). ``SessionLocal``
wird via ``monkeypatch`` durch eine Test-Session-Factory ersetzt, damit
der CLI denselben Session-Context nutzt wie die Test-Fixtures.

Downlinks des Eingangstests (``set_open_window_detection`` + ``send_setpoint``) werden
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
from heizung.scripts.pairing import inbound_test

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
    """Mockt set_open_window_detection + send_setpoint im Eingangstest.

    Sprint 17 (E3/C3): ``pairing_service`` hat keinen Downlink-Pfad mehr,
    daher patcht die Fixture nur noch ``inbound_test``. ``counters`` bleibt
    als Negativ-Beleg fuer die import-Tests ("es wurde nichts gesendet").
    """
    counters = {"set_ow": 0, "send_setpoint": 0}

    async def fake_set_ow(*args: object, **kwargs: object) -> str:
        counters["set_ow"] += 1
        return "topic"

    async def fake_send_setpoint(*args: object, **kwargs: object) -> str:
        counters["send_setpoint"] += 1
        return "topic"

    async def no_sleep(seconds: int) -> None:
        return None

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
    """import --dry-run: Device-Count unveraendert, KEINE Downlinks (Sprint 17 E3)."""
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
    # Sprint 17 (E3/C3): der Import ist rein transaktional.
    assert mock_all_downlinks["set_ow"] == 0
    captured = capsys.readouterr()
    # Die frueher noetige "[WARN] --dry-run aktiv: Downlinks gehen trotzdem
    # raus"-Warnung ist mit Sprint 17 (E3/C3) entfallen — es gibt nichts
    # mehr zu warnen.
    assert "[WARN]" not in captured.err
    assert "[DRY-RUN]" in captured.err
    assert "Keine Downlinks gesendet" in captured.err


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
    # Sprint 17 Nachtrag: die Meldung nennt jetzt Grund UND naechsten Schritt,
    # statt nur "nicht gefunden" (RUNBOOK 10h.0.2).
    assert "[FAIL]" in err
    assert "kein Konto mit der Adresse 'nonexistent@example.com'" in err
    assert "Tippfehler" in err
    # Kein Downlink — weder durch den Abbruch noch durch pair_batch.
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


# ---------------------------------------------------------------------------
# Sprint 17 Nachtrag — Geraete-Auswahl fuer den zweiten Eingangstest-Durchlauf
# ---------------------------------------------------------------------------
#
# Reine Funktion, keine DB: _filter_pool_devices bekommt die bereits geladene
# Pool-Liste und waehlt daraus aus. Getestet wird genau das, was der Hotelier
# am 26.09. tut — die TIMEOUT-Nummern aus dem Report abtippen.


class _FakeDevice:
    """Nur die zwei Felder, die die Auswahl liest."""

    def __init__(self, label: str | None, dev_eui: str) -> None:
        self.label = label
        self.dev_eui = dev_eui


POOL = [
    _FakeDevice("001", "70b3d57ed0000001"),
    _FakeDevice("017", "70b3d57ed0000017"),
    _FakeDevice("042", "70b3d57ed0000042"),
    _FakeDevice(None, "70b3d57ed0000099"),  # ohne hardware_nummer
]


def test_filter_pool_devices_nach_hardware_nummer() -> None:
    from heizung.scripts.pair_devices import _filter_pool_devices

    selected, unknown = _filter_pool_devices(POOL, "017,042")

    assert [d.label for d in selected] == ["017", "042"]
    assert unknown == []


def test_filter_pool_devices_toleriert_leerzeichen_und_grossschreibung() -> None:
    from heizung.scripts.pair_devices import _filter_pool_devices

    selected, unknown = _filter_pool_devices(POOL, " 017 , 70B3D57ED0000042 ")

    assert [d.label for d in selected] == ["017", "042"]
    assert unknown == []


def test_filter_pool_devices_findet_geraet_ohne_hardware_nummer_ueber_dev_eui() -> None:
    """Ohne ``hardware_nummer`` benennt der Report das Geraet mit der DevEUI —
    dann muss auch die Auswahl darueber gehen."""
    from heizung.scripts.pair_devices import _filter_pool_devices

    selected, unknown = _filter_pool_devices(POOL, "70b3d57ed0000099")

    assert [d.dev_eui for d in selected] == ["70b3d57ed0000099"]
    assert unknown == []


def test_filter_pool_devices_meldet_unbekannte_statt_sie_zu_schlucken() -> None:
    """Ein Tippfehler in der TIMEOUT-Liste darf nicht dazu fuehren, dass ein
    Geraet still uebersprungen wird — der zweite Durchlauf ist genau der,
    der es klaeren soll."""
    from heizung.scripts.pair_devices import _filter_pool_devices

    selected, unknown = _filter_pool_devices(POOL, "017,0177,999")

    assert [d.label for d in selected] == ["017"]
    assert unknown == ["0177", "999"]


def test_filter_pool_devices_behaelt_pool_reihenfolge() -> None:
    from heizung.scripts.pair_devices import _filter_pool_devices

    selected, _ = _filter_pool_devices(POOL, "042,001")

    assert [d.label for d in selected] == ["001", "042"]


def test_inbound_test_verlangt_genau_einen_auswahl_schalter() -> None:
    """--all-pool und --devices schliessen sich aus, einer ist Pflicht."""
    from heizung.scripts.pair_devices import _build_parser

    parser = _build_parser()

    args = parser.parse_args(["inbound-test", "--devices", "017"])
    assert args.devices == "017"
    assert args.all_pool is False

    with pytest.raises(SystemExit):
        parser.parse_args(["inbound-test"])
    with pytest.raises(SystemExit):
        parser.parse_args(["inbound-test", "--all-pool", "--devices", "017"])


# ---------------------------------------------------------------------------
# Sprint 17 Nachtrag — --user-email verlangt ein aktives Admin-Konto
# ---------------------------------------------------------------------------
#
# Bis dahin filterte _lookup_user_id nur auf email + is_active. Eine
# Mitarbeiter-Adresse waere angenommen worden und stuende als Urheber im
# Audit. Die Oberflaeche verlangt fuer Zuordnen/Trennen/Tauschen die
# Admin-Rolle (RUNBOOK 10h.0.2) — die CLI zieht jetzt nach.
#
# Die Fehlermeldung muss den Grund UND den naechsten Schritt nennen: der
# Hotelier steht am Montage-Abend allein davor.


async def _make_user(session: AsyncSession, *, role: UserRole, is_active: bool = True) -> str:
    """Legt ein Konto an und gibt seine Adresse zurueck."""
    email = f"cli-rolle-{_short()}@example.com"
    session.add(
        User(
            email=email,
            password_hash="x" * 60,
            role=role,
            is_active=is_active,
            must_change_password=False,
        )
    )
    await session.flush()
    return email


async def test_lookup_akzeptiert_aktives_admin_konto(
    patched_session_local: AsyncSession,
) -> None:
    from heizung.scripts.pair_devices import _lookup_user_id

    email = await _make_user(patched_session_local, role=UserRole.ADMIN)

    user_id, reason = await _lookup_user_id(patched_session_local, email)

    assert user_id is not None
    assert reason is None


async def test_lookup_weist_mitarbeiter_konto_ab(
    patched_session_local: AsyncSession,
) -> None:
    """Der Kern dieses Nachtrags."""
    from heizung.scripts.pair_devices import _lookup_user_id

    email = await _make_user(patched_session_local, role=UserRole.MITARBEITER)

    user_id, reason = await _lookup_user_id(patched_session_local, email)

    assert user_id is None
    assert reason is not None
    # Grund benannt …
    assert "mitarbeiter" in reason
    # … und das weitere Vorgehen.
    assert "admin" in reason
    assert "10h.0.2" in reason


async def test_lookup_weist_deaktiviertes_admin_konto_ab(
    patched_session_local: AsyncSession,
) -> None:
    """Deaktiviert ist ein anderer Grund als falsche Rolle — die Meldung
    muss das unterscheiden, sonst sucht der Hotelier an der falschen Stelle."""
    from heizung.scripts.pair_devices import _lookup_user_id

    email = await _make_user(patched_session_local, role=UserRole.ADMIN, is_active=False)

    user_id, reason = await _lookup_user_id(patched_session_local, email)

    assert user_id is None
    assert reason is not None
    assert "deaktiviert" in reason
    assert "aktivieren" in reason
    # Nicht die Rollen-Begruendung.
    assert "Rolle" not in reason


async def test_lookup_weist_unbekannte_adresse_ab(
    patched_session_local: AsyncSession,
) -> None:
    from heizung.scripts.pair_devices import _lookup_user_id

    user_id, reason = await _lookup_user_id(patched_session_local, "gibtesnicht@example.com")

    assert user_id is None
    assert reason is not None
    assert "kein Konto" in reason
    assert "Tippfehler" in reason
    # Weder Rolle noch Deaktivierung — die Adresse existiert schlicht nicht.
    assert "Rolle" not in reason
    assert "deaktiviert" not in reason


async def test_import_bricht_bei_mitarbeiter_konto_ab_ohne_zu_schreiben(
    patched_session_local: AsyncSession,
    tmp_path: Path,
    mock_all_downlinks: dict[str, int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """End-to-End ueber den CLI-Pfad: Exit 1, nichts angelegt, Grund im stderr."""
    room_num = str(7_300_000 + int(_short(), 16) % 100_000)
    await _seed_zone(patched_session_local, room_number=room_num, zone_name="Schlafzimmer")
    email = await _make_user(patched_session_local, role=UserRole.MITARBEITER)

    dev_eui = _eui()
    csv_path = tmp_path / "rolle.csv"
    _write_csv(
        csv_path,
        "stockwerk,zimmer_nummer,zimmer_typ,zone_label,dev_eui,app_key\n"
        f"1,{room_num},Standard,Schlafzimmer,{dev_eui},{_VALID_APP_KEY}\n",
    )

    exit_code = await pair_devices.main_async(["import", str(csv_path), "--user-email", email])
    assert exit_code == 1

    err = capsys.readouterr().err
    assert "[FAIL]" in err
    assert "mitarbeiter" in err
    assert "Import abgebrochen" in err

    # Kein Device angelegt.
    count = await patched_session_local.scalar(
        select(func.count()).select_from(Device).where(Device.dev_eui == dev_eui)
    )
    assert count == 0
    # Kein Downlink durch den Abbruch.
    assert mock_all_downlinks["set_ow"] == 0
