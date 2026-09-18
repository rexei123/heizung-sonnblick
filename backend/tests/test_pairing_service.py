"""Sprint 13a T4 — Pairing-Service Tests.

DB-Tests gegen ``TEST_DATABASE_URL`` (analog T3 ``test_pairing_csv_parser``).

Sprint 17 (E3/C3): Der Pairing-Service sendet keinen Downlink mehr. Die
frueheren ``mock_downlink_ok`` / ``mock_downlink_raises``-Fixtures und der
``DOWNLINK_FAILED``-Test sind entfallen; stattdessen belegt
``test_pair_device_sends_no_downlink`` negativ, dass kein MQTT-Pfad mehr
angefasst wird.
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
from heizung.scripts.pairing import pairing_service
from heizung.scripts.pairing.csv_row import PairingCsvRow
from heizung.scripts.pairing.pairing_service import (
    pair_batch,
    pair_device,
)
from heizung.services import downlink_adapter

DATABASE_URL = os.environ.get("DATABASE_URL")
DATABASE_URL_PRESENT = bool(DATABASE_URL)
SKIP_REASON = "DATABASE_URL nicht gesetzt - DB-Tests brauchen Test-DB"

_VALID_APP_KEY = "abcdef0123456789abcdef0123456789"


# ---------------------------------------------------------------------------
# DB-Fixtures (analog T3)
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


async def _seed_zone(s: AsyncSession, *, room_number: str, zone_name: str) -> tuple[int, int]:
    """RoomType + Room + HeatingZone anlegen, returns (room_id, zone_id)."""
    short = _short()
    rt = RoomType(name=f"t13a-t4-{short}")
    s.add(rt)
    await s.flush()
    room = Room(number=room_number, room_type_id=rt.id)
    s.add(room)
    await s.flush()
    hz = HeatingZone(room_id=room.id, kind=HeatingZoneKind.BEDROOM, name=zone_name)
    s.add(hz)
    await s.flush()
    return room.id, hz.id


# ---------------------------------------------------------------------------
# Tests fuer pair_device
# ---------------------------------------------------------------------------


async def test_pair_device_happy_path_active(
    session: AsyncSession,
) -> None:
    """Active-Row: Device + Audit. status='paired'."""
    await _seed_zone(session, room_number="9401", zone_name="Schlafzimmer")
    row = PairingCsvRow(
        stockwerk=1,
        zimmer_nummer=9401,
        zimmer_typ="Standard",
        zone_label="Schlafzimmer",
        dev_eui=_eui(),
        app_key=_VALID_APP_KEY,
    )
    result = await pair_device(row, row_number=2, session=session)
    assert result.status == "paired"
    assert result.device_id is not None
    assert result.is_pool is False
    assert result.error_msg is None
    # Device in DB.
    device = await session.get(Device, result.device_id)
    assert device is not None
    assert device.dev_eui == row.dev_eui
    assert device.heating_zone_id is not None
    assert device.kind == DeviceKind.THERMOSTAT
    assert device.vendor == DeviceVendor.MCLIMATE


async def test_pair_device_happy_path_pool(
    session: AsyncSession,
) -> None:
    """Pool-Row: Device mit heating_zone_id=NULL."""
    row = PairingCsvRow(
        stockwerk=None,
        zimmer_nummer=None,
        zimmer_typ=None,
        zone_label=None,
        dev_eui=_eui(),
        app_key=_VALID_APP_KEY,
    )
    result = await pair_device(row, row_number=2, session=session)
    assert result.status == "paired"
    assert result.is_pool is True
    device = await session.get(Device, result.device_id)
    assert device is not None
    assert device.heating_zone_id is None


async def test_pair_device_dev_eui_exists_skipped(
    session: AsyncSession,
) -> None:
    """DEV_EUI_EXISTS -> status='skipped_exists', kein Audit."""
    _, zone_id = await _seed_zone(session, room_number="9402", zone_name="Schlafzimmer")
    existing_eui = _eui()
    existing_device = Device(
        dev_eui=existing_eui,
        kind=DeviceKind.THERMOSTAT,
        vendor=DeviceVendor.MCLIMATE,
        model="Vicki",
        heating_zone_id=zone_id,
    )
    session.add(existing_device)
    await session.flush()

    row = PairingCsvRow(
        stockwerk=1,
        zimmer_nummer=9402,
        zimmer_typ="Standard",
        zone_label="Schlafzimmer",
        dev_eui=existing_eui,
        app_key=_VALID_APP_KEY,
    )
    result = await pair_device(row, row_number=2, session=session)
    assert result.status == "skipped_exists"
    assert result.device_id == existing_device.id
    assert result.error_msg is not None
    assert "DEV_EUI_EXISTS" in result.error_msg


async def test_pair_device_zone_not_found_defensive(
    session: AsyncSession,
) -> None:
    """Active-Row mit nicht-existierender Zone -> status='error',
    kein Device-Row (Defensive fuer §S5)."""
    row = PairingCsvRow(
        stockwerk=1,
        zimmer_nummer=99999,
        zimmer_typ="Standard",
        zone_label="Schlafzimmer",
        dev_eui=_eui(),
        app_key=_VALID_APP_KEY,
    )
    result = await pair_device(row, row_number=2, session=session)
    assert result.status == "error"
    assert result.device_id is None
    assert result.error_msg is not None
    assert "ZONE_NOT_FOUND" in result.error_msg
    # Kein Device wurde angelegt.
    stmt = select(Device.id).where(Device.dev_eui == row.dev_eui)
    assert (await session.execute(stmt)).scalar_one_or_none() is None


async def test_pair_device_sends_no_downlink(
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sprint 17 (E3/C3): der Pairing-Lauf fasst keinen MQTT-Pfad an.

    Negativ-Beleg statt Downlink-Mock: ``send_raw_downlink`` ist die
    einzige MQTT-Publish-Stelle im Repo (AE-48). Wir patchen sie zu einem
    Raiser — wuerde der Pairing-Service noch irgendeinen Downlink-Wrapper
    rufen, schlaegt der Test fehl.
    """
    calls: list[str] = []

    async def explode(*args: object, **kwargs: object) -> str:
        calls.append("send_raw_downlink")
        raise AssertionError("Pairing darf keinen Downlink senden (Sprint 17 E3)")

    monkeypatch.setattr(downlink_adapter, "send_raw_downlink", explode)

    await _seed_zone(session, room_number="9403", zone_name="Schlafzimmer")
    row = PairingCsvRow(
        stockwerk=1,
        zimmer_nummer=9403,
        zimmer_typ="Standard",
        zone_label="Schlafzimmer",
        dev_eui=_eui(),
        app_key=_VALID_APP_KEY,
    )
    result = await pair_device(row, row_number=2, session=session)
    assert result.status == "paired"
    assert result.device_id is not None
    assert calls == []
    # Audit-Row ist da.
    audit_stmt = select(BusinessAudit).where(
        BusinessAudit.action == "DEVICE_PAIRED",
        BusinessAudit.target_id == result.device_id,
    )
    audits = list((await session.execute(audit_stmt)).scalars().all())
    assert len(audits) == 1


async def test_pair_device_audit_content(
    session: AsyncSession,
) -> None:
    """BusinessAudit-new_value enthaelt erwartete Keys."""
    await _seed_zone(session, room_number="9404", zone_name="Bad")
    dev_eui = _eui()
    row = PairingCsvRow(
        stockwerk=2,
        zimmer_nummer=9404,
        zimmer_typ="Standard",
        zone_label="Bad",
        dev_eui=dev_eui,
        app_key=_VALID_APP_KEY,
    )
    result = await pair_device(row, row_number=7, session=session)
    assert result.status == "paired"
    audit_stmt = select(BusinessAudit).where(BusinessAudit.target_id == result.device_id)
    audit = (await session.execute(audit_stmt)).scalar_one()
    assert audit.action == "DEVICE_PAIRED"
    assert audit.target_type == "device"
    # user_id=None Pfad — System-Trigger ohne CLI-User-Argument (Default).
    # FK-bezogene user_id-Tests brauchen separates User-Setup, ausserhalb
    # dieses Audit-Inhalt-Tests (test_pair_device_user_id_none_system_trigger).
    assert audit.user_id is None
    assert audit.old_value is None
    # heating_zone_id ist vom Lookup auf der gerade gesetzten Zone aus
    # _seed_zone — exakter Wert ist hier nicht relevant, nur dass die
    # Keys vorhanden sind und Werte konsistent.
    assert audit.new_value["dev_eui"] == dev_eui
    assert audit.new_value["heating_zone_id"] is not None
    assert audit.new_value["is_pool"] is False
    assert audit.new_value["csv_row_number"] == 7
    # Sprint 17 (E4/C2): "metadata" ist additiv dazugekommen.
    assert set(audit.new_value.keys()) == {
        "dev_eui",
        "heating_zone_id",
        "is_pool",
        "csv_row_number",
        "metadata",
    }
    assert audit.new_value["metadata"] == {}


async def test_pair_device_user_id_none_system_trigger(
    session: AsyncSession,
) -> None:
    """user_id=None Pfad (System-Trigger analog T2-AuditGap-Pattern)."""
    await _seed_zone(session, room_number="9405", zone_name="Schlafzimmer")
    row = PairingCsvRow(
        stockwerk=1,
        zimmer_nummer=9405,
        zimmer_typ="Standard",
        zone_label="Schlafzimmer",
        dev_eui=_eui(),
        app_key=_VALID_APP_KEY,
    )
    result = await pair_device(row, row_number=2, session=session, user_id=None)
    assert result.status == "paired"
    audit_stmt = select(BusinessAudit).where(BusinessAudit.target_id == result.device_id)
    audit = (await session.execute(audit_stmt)).scalar_one()
    assert audit.user_id is None


async def test_pair_device_lowercase_normalization_sanity(
    session: AsyncSession,
) -> None:
    """Pydantic-Normalisierung (T2) wirkt: Uppercase-DevEUI landet als lowercase in DB."""
    await _seed_zone(session, room_number="9406", zone_name="Schlafzimmer")
    upper_eui = _eui().upper()
    row = PairingCsvRow(
        stockwerk=1,
        zimmer_nummer=9406,
        zimmer_typ="Standard",
        zone_label="Schlafzimmer",
        dev_eui=upper_eui,
        app_key=_VALID_APP_KEY,
    )
    # Pydantic-Normalisierung wirkt schon vor pair_device.
    assert row.dev_eui == upper_eui.lower()
    result = await pair_device(row, row_number=2, session=session)
    assert result.status == "paired"
    device = await session.get(Device, result.device_id)
    assert device is not None
    assert device.dev_eui == upper_eui.lower()


# ---------------------------------------------------------------------------
# Tests fuer pair_batch
# ---------------------------------------------------------------------------


async def test_pair_batch_mixed_active_pool_duplicate(
    session: AsyncSession,
) -> None:
    """2 Active + 1 Pool + 1 Duplikat-DevEUI -> 3 paired, 1 skipped."""
    await _seed_zone(session, room_number="9501", zone_name="Schlafzimmer")
    await _seed_zone(session, room_number="9502", zone_name="Bad")
    eui1 = _eui()
    eui2 = _eui()
    eui_pool = _eui()
    eui_dup = _eui()
    # Existierendes Device fuer Duplikat-Check.
    _, zone_id = await _seed_zone(session, room_number="9503", zone_name="Bad")
    dup_existing = Device(
        dev_eui=eui_dup,
        kind=DeviceKind.THERMOSTAT,
        vendor=DeviceVendor.MCLIMATE,
        model="Vicki",
        heating_zone_id=zone_id,
    )
    session.add(dup_existing)
    await session.flush()

    rows = [
        PairingCsvRow(
            stockwerk=1,
            zimmer_nummer=9501,
            zimmer_typ="Standard",
            zone_label="Schlafzimmer",
            dev_eui=eui1,
            app_key=_VALID_APP_KEY,
        ),
        PairingCsvRow(
            stockwerk=1,
            zimmer_nummer=9502,
            zimmer_typ="Standard",
            zone_label="Bad",
            dev_eui=eui2,
            app_key=_VALID_APP_KEY,
        ),
        PairingCsvRow(
            stockwerk=None,
            zimmer_nummer=None,
            zimmer_typ=None,
            zone_label=None,
            dev_eui=eui_pool,
            app_key=_VALID_APP_KEY,
        ),
        PairingCsvRow(
            stockwerk=1,
            zimmer_nummer=9503,
            zimmer_typ="Standard",
            zone_label="Bad",
            dev_eui=eui_dup,
            app_key=_VALID_APP_KEY,
        ),
    ]
    results = await pair_batch(rows, session)
    assert len(results) == 4
    status_counts = {"paired": 0, "skipped_exists": 0, "error": 0}
    for r in results:
        status_counts[r.status] += 1
    assert status_counts == {"paired": 3, "skipped_exists": 1, "error": 0}
    # Row-Reihenfolge bleibt erhalten.
    assert results[0].dev_eui == eui1
    assert results[3].dev_eui == eui_dup
    assert results[3].status == "skipped_exists"


async def test_pair_batch_savepoint_rollback_on_unexpected_exception(
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Row 1 OK, Row 2 wirft unerwartete Exception im Zone-Lookup,
    Row 3 OK. Savepoint-Rollback raeumt Row 2 ohne Device-Row in DB,
    Row 1 + 3 bleiben — Brief-Anforderung 'andere Rows unangetastet'."""
    call_count = [0]
    original_lookup = pairing_service._lookup_zone

    async def fake_lookup_zone(s: AsyncSession, zimmer_nummer: int, zone_label: str) -> int | None:
        call_count[0] += 1
        # Row 2 (zweiter Zone-Lookup-Call) wirft.
        if call_count[0] == 2:
            raise RuntimeError("simulated DB-Connection-Drop in zone-lookup")
        return await original_lookup(s, zimmer_nummer, zone_label)

    monkeypatch.setattr(pairing_service, "_lookup_zone", fake_lookup_zone)

    await _seed_zone(session, room_number="9601", zone_name="Schlafzimmer")
    await _seed_zone(session, room_number="9602", zone_name="Schlafzimmer")
    await _seed_zone(session, room_number="9603", zone_name="Schlafzimmer")

    eui1 = _eui()
    eui2 = _eui()
    eui3 = _eui()
    rows = [
        PairingCsvRow(
            stockwerk=1,
            zimmer_nummer=9601,
            zimmer_typ="Standard",
            zone_label="Schlafzimmer",
            dev_eui=eui1,
            app_key=_VALID_APP_KEY,
        ),
        PairingCsvRow(
            stockwerk=1,
            zimmer_nummer=9602,
            zimmer_typ="Standard",
            zone_label="Schlafzimmer",
            dev_eui=eui2,
            app_key=_VALID_APP_KEY,
        ),
        PairingCsvRow(
            stockwerk=1,
            zimmer_nummer=9603,
            zimmer_typ="Standard",
            zone_label="Schlafzimmer",
            dev_eui=eui3,
            app_key=_VALID_APP_KEY,
        ),
    ]
    results = await pair_batch(rows, session)
    assert len(results) == 3
    assert results[0].status == "paired"
    # Row 2: unerwartete Exception -> Savepoint-Rollback, status=error,
    # error_msg-Prefix 'UNEXPECTED', kein Device in DB.
    assert results[1].status == "error"
    assert results[1].error_msg is not None
    assert "UNEXPECTED" in results[1].error_msg
    assert results[2].status == "paired"
    # Row 1 + 3 Device-Rows existieren, Row 2 NICHT (Savepoint-rollback).
    stmt1 = select(Device.id).where(Device.dev_eui == eui1)
    assert (await session.execute(stmt1)).scalar_one_or_none() is not None
    stmt2 = select(Device.id).where(Device.dev_eui == eui2)
    assert (await session.execute(stmt2)).scalar_one_or_none() is None
    stmt3 = select(Device.id).where(Device.dev_eui == eui3)
    assert (await session.execute(stmt3)).scalar_one_or_none() is not None


# ---------------------------------------------------------------------------
# Sprint 17 (E4/C2) — Metadaten: Neuanlage, Anreicherung, Konflikt
# ---------------------------------------------------------------------------

_APP_EUI = "70b3d57ed0000001"


def _row_with_metadata(
    *,
    dev_eui: str,
    hardware_nummer: str | None = None,
    app_eui: str | None = None,
    serial_number: str | None = None,
) -> PairingCsvRow:
    """Pool-Row (kein Zimmer noetig) mit den drei optionalen Metadaten."""
    return PairingCsvRow(
        stockwerk=None,
        zimmer_nummer=None,
        zimmer_typ=None,
        zone_label=None,
        dev_eui=dev_eui,
        app_key=_VALID_APP_KEY,
        hardware_nummer=hardware_nummer,
        app_eui=app_eui,
        serial_number=serial_number,
    )


async def test_pair_device_new_writes_all_three_metadata(session: AsyncSession) -> None:
    """Neuanlage: alle drei CSV-Felder landen in den Device-Spalten.

    Abbildung (ohne Migration): hardware_nummer -> label,
    app_eui -> app_eui, serial_number -> hardware_number (AE-61).
    """
    row = _row_with_metadata(
        dev_eui=_eui(),
        hardware_nummer="101",
        app_eui=_APP_EUI,
        serial_number="MDC5419731K6UF",
    )
    result = await pair_device(row, row_number=2, session=session)
    assert result.status == "paired"
    device = await session.get(Device, result.device_id)
    assert device is not None
    assert device.label == "101"
    assert device.app_eui == _APP_EUI
    assert device.hardware_number == "MDC5419731K6UF"
    # Audit haelt fest, WAS der Import mitgebracht hat.
    audit_stmt = select(BusinessAudit).where(BusinessAudit.target_id == result.device_id)
    audit = (await session.execute(audit_stmt)).scalar_one()
    assert audit.action == "DEVICE_PAIRED"
    assert audit.new_value["metadata"] == {
        "label": "101",
        "app_eui": _APP_EUI,
        "hardware_number": "MDC5419731K6UF",
    }


async def test_pair_device_new_without_metadata_leaves_columns_null(
    session: AsyncSession,
) -> None:
    """Bestands-CSV ohne die Spalten: Device-Spalten bleiben NULL."""
    row = _row_with_metadata(dev_eui=_eui())
    result = await pair_device(row, row_number=2, session=session)
    assert result.status == "paired"
    assert result.filled == ()
    device = await session.get(Device, result.device_id)
    assert device is not None
    assert device.label is None
    assert device.app_eui is None
    assert device.hardware_number is None
    audit_stmt = select(BusinessAudit).where(BusinessAudit.target_id == result.device_id)
    audit = (await session.execute(audit_stmt)).scalar_one()
    # Leeres Dict, nicht fehlender Key — "nichts mitgebracht" ist explizit.
    assert audit.new_value["metadata"] == {}


async def test_pair_device_existing_enriches_empty_fields(session: AsyncSession) -> None:
    """Der Fall der vier Testgeraete: leere Felder werden nachgetragen.

    Das Geraet steht seit Sprint 6 in der DB und hat ein gewachsenes
    ``label``. AppEUI und Seriennummer fehlen und kommen jetzt aus der CSV.
    Das ``label`` bleibt unberuehrt, weil die CSV es nicht nennt.
    """
    existing_eui = _eui()
    existing = Device(
        dev_eui=existing_eui,
        kind=DeviceKind.THERMOSTAT,
        vendor=DeviceVendor.MCLIMATE,
        model="Vicki",
        label="Vicki-001",
    )
    session.add(existing)
    await session.flush()

    row = _row_with_metadata(
        dev_eui=existing_eui,
        app_eui=_APP_EUI,
        serial_number="MDC-NEU-1",
    )
    result = await pair_device(row, row_number=5, session=session)
    assert result.status == "enriched"
    assert result.device_id == existing.id
    assert result.filled == ("app_eui", "hardware_number")
    assert result.conflicts == ()

    await session.refresh(existing)
    assert existing.app_eui == _APP_EUI
    assert existing.hardware_number == "MDC-NEU-1"
    assert existing.label == "Vicki-001"  # unveraendert

    audit_stmt = select(BusinessAudit).where(
        BusinessAudit.action == "DEVICE_METADATA_ENRICHED",
        BusinessAudit.target_id == existing.id,
    )
    audit = (await session.execute(audit_stmt)).scalar_one()
    assert audit.new_value["filled_fields"] == ["app_eui", "hardware_number"]
    assert audit.new_value["conflicting_fields"] == []
    assert audit.new_value["csv_row_number"] == 5


async def test_pair_device_existing_conflict_does_not_overwrite(
    session: AsyncSession,
) -> None:
    """Abweichender Wert wird gemeldet, nicht ueberschrieben."""
    existing_eui = _eui()
    existing = Device(
        dev_eui=existing_eui,
        kind=DeviceKind.THERMOSTAT,
        vendor=DeviceVendor.MCLIMATE,
        model="Vicki",
        label="Vicki-001",
        hardware_number="MDC-ALT",
    )
    session.add(existing)
    await session.flush()

    row = _row_with_metadata(
        dev_eui=existing_eui,
        hardware_nummer="101",
        serial_number="MDC-NEU",
    )
    result = await pair_device(row, row_number=7, session=session)
    assert result.status == "conflict"
    assert result.conflicts == ("hardware_number", "label")
    assert result.filled == ()
    assert result.error_msg is not None
    assert "METADATA_CONFLICT" in result.error_msg

    await session.refresh(existing)
    assert existing.label == "Vicki-001"
    assert existing.hardware_number == "MDC-ALT"

    # Kein Anreicherungs-Audit, weil nichts geschrieben wurde.
    audit_stmt = select(BusinessAudit).where(
        BusinessAudit.action == "DEVICE_METADATA_ENRICHED",
        BusinessAudit.target_id == existing.id,
    )
    assert list((await session.execute(audit_stmt)).scalars().all()) == []


async def test_pair_device_existing_partial_conflict_fills_the_rest(
    session: AsyncSession,
) -> None:
    """Gemischt: ein Feld widerspricht, ein anderes ist leer.

    Das leere Feld wird trotzdem befuellt — sonst blockiert ein einzelner
    Widerspruch die gesamte Nachtragung fuer dieses Geraet.
    """
    existing_eui = _eui()
    existing = Device(
        dev_eui=existing_eui,
        kind=DeviceKind.THERMOSTAT,
        vendor=DeviceVendor.MCLIMATE,
        model="Vicki",
        label="Vicki-002",
    )
    session.add(existing)
    await session.flush()

    row = _row_with_metadata(
        dev_eui=existing_eui,
        hardware_nummer="102",
        app_eui=_APP_EUI,
    )
    result = await pair_device(row, row_number=8, session=session)
    assert result.status == "conflict"
    assert result.conflicts == ("label",)
    assert result.filled == ("app_eui",)

    await session.refresh(existing)
    assert existing.label == "Vicki-002"  # Widerspruch: unveraendert
    assert existing.app_eui == _APP_EUI  # leer gewesen: befuellt

    audit_stmt = select(BusinessAudit).where(
        BusinessAudit.action == "DEVICE_METADATA_ENRICHED",
        BusinessAudit.target_id == existing.id,
    )
    audit = (await session.execute(audit_stmt)).scalar_one()
    assert audit.new_value["filled_fields"] == ["app_eui"]
    assert audit.new_value["conflicting_fields"] == ["label"]


async def test_pair_device_existing_identical_values_is_noop(session: AsyncSession) -> None:
    """Zweiter Lauf derselben CSV: nichts zu tun, kein Audit (Idempotenz)."""
    existing_eui = _eui()
    existing = Device(
        dev_eui=existing_eui,
        kind=DeviceKind.THERMOSTAT,
        vendor=DeviceVendor.MCLIMATE,
        model="Vicki",
        label="103",
        app_eui=_APP_EUI,
        hardware_number="MDC-GLEICH",
    )
    session.add(existing)
    await session.flush()

    row = _row_with_metadata(
        dev_eui=existing_eui,
        hardware_nummer="103",
        app_eui=_APP_EUI,
        serial_number="MDC-GLEICH",
    )
    result = await pair_device(row, row_number=9, session=session)
    assert result.status == "skipped_exists"
    assert result.filled == ()
    assert result.conflicts == ()

    audit_stmt = select(BusinessAudit).where(BusinessAudit.target_id == existing.id)
    assert list((await session.execute(audit_stmt)).scalars().all()) == []


async def test_pair_device_existing_keeps_zone_assignment(session: AsyncSession) -> None:
    """Anreicherung haengt ein gepairtes Geraet NICHT um.

    Ein zweimal eingelesenes CSV darf keine Zonen verschieben (S2/S4) —
    Umhaengen ist Aufgabe von ``assign`` bzw. des Tausch-Endpoints.
    """
    _, zone_id = await _seed_zone(session, room_number="9801", zone_name="Bad")
    existing_eui = _eui()
    existing = Device(
        dev_eui=existing_eui,
        kind=DeviceKind.THERMOSTAT,
        vendor=DeviceVendor.MCLIMATE,
        model="Vicki",
        heating_zone_id=zone_id,
    )
    session.add(existing)
    await session.flush()

    # CSV nennt das Geraet als Pool-Zeile (ohne Zimmer/Zone).
    row = _row_with_metadata(dev_eui=existing_eui, serial_number="MDC-Z")
    result = await pair_device(row, row_number=3, session=session)
    assert result.status == "enriched"

    await session.refresh(existing)
    assert existing.heating_zone_id == zone_id
    assert existing.hardware_number == "MDC-Z"
