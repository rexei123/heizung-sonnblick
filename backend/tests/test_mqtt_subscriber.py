"""Unit-Tests fuer mqtt_subscriber.

Deckt die Pure-Functions ab (Pydantic-Validierung, Battery-Conversion,
Object-zu-Reading-Mapping). MQTT-Loop und DB-Layer sind nicht im Scope -
End-to-End wurde im Sprint-5-Brief manuell verifiziert.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
import pytest_asyncio
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from heizung.services.mqtt_subscriber import (
    ChirpStackUplink,
    _battery_pct_from_volts,
    _handle_firmware_version_report,
    _map_to_reading,
    _persist_uplink,
    _to_decimal,
)

TEST_DB_URL = os.environ.get("TEST_DATABASE_URL")
SKIP_REASON = "TEST_DATABASE_URL nicht gesetzt - DB-Tests brauchen Postgres"

# ---------------------------------------------------------------------------
# _battery_pct_from_volts
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("volts", "expected"),
    [
        (None, None),
        (3.0, 0),
        (4.2, 100),
        (3.6, 50),
        (3.9, 75),  # vom Mock-Uplink-Test in Sprint 5.6
        (2.5, 0),  # unter Lower-Bound -> geclampt
        (5.0, 100),  # ueber Upper-Bound -> geclampt
    ],
)
def test_battery_pct_clamping(volts: float | None, expected: int | None) -> None:
    assert _battery_pct_from_volts(volts) == expected


# ---------------------------------------------------------------------------
# _to_decimal
# ---------------------------------------------------------------------------


def test_to_decimal_passthrough() -> None:
    assert _to_decimal(21.5) == Decimal("21.5")
    assert _to_decimal("18.3") == Decimal("18.3")
    assert _to_decimal(None) is None


def test_to_decimal_returns_none_for_garbage() -> None:
    assert _to_decimal("not-a-number") is None
    assert _to_decimal({"unexpected": "type"}) is None


# ---------------------------------------------------------------------------
# ChirpStackUplink (Pydantic)
# ---------------------------------------------------------------------------


def _valid_payload() -> dict[str, Any]:
    return {
        "deviceInfo": {"devEui": "0011223344556677"},
        "fCnt": 1,
        "fPort": 1,
        "time": "2026-04-28T08:00:00Z",
        "object": {
            "command": 1,
            "battery_voltage": 3.9,
            "temperature": 24,
            "target_temperature": 21.0,
            "motor_position": 100,
        },
        "rxInfo": [{"rssi": -85, "snr": 7.5}],
        "data": "AQkYKshkAA==",
    }


def test_chirpstack_uplink_validates_minimal_payload() -> None:
    minimal = {
        "deviceInfo": {"devEui": "0011223344556677"},
        "fCnt": 0,
    }
    uplink = ChirpStackUplink.model_validate(minimal)
    assert uplink.deviceInfo.devEui == "0011223344556677"
    assert uplink.fCnt == 0
    assert uplink.object is None
    assert uplink.rxInfo == []


def test_chirpstack_uplink_validates_full_payload() -> None:
    uplink = ChirpStackUplink.model_validate(_valid_payload())
    assert uplink.fCnt == 1
    assert uplink.fPort == 1
    assert uplink.object is not None
    assert uplink.object["target_temperature"] == 21.0
    assert uplink.rxInfo[0].rssi == -85
    assert uplink.rxInfo[0].snr == 7.5


def test_chirpstack_uplink_rejects_missing_dev_eui() -> None:
    with pytest.raises(ValidationError):
        ChirpStackUplink.model_validate({"fCnt": 1})


def test_chirpstack_uplink_rejects_negative_fcnt() -> None:
    with pytest.raises(ValidationError):
        ChirpStackUplink.model_validate({"deviceInfo": {"devEui": "00"}, "fCnt": -1})


# ---------------------------------------------------------------------------
# _map_to_reading
# ---------------------------------------------------------------------------


def test_map_to_reading_full() -> None:
    uplink = ChirpStackUplink.model_validate(_valid_payload())
    row = _map_to_reading(uplink, device_id=42)
    assert row["device_id"] == 42
    assert row["fcnt"] == 1
    assert row["temperature"] == Decimal("24")
    assert row["setpoint"] == Decimal("21.0")
    assert row["valve_position"] == 100
    assert row["battery_percent"] == 75
    assert row["rssi_dbm"] == -85
    assert row["snr_db"] == Decimal("7.5")
    assert row["raw_payload"] == "AQkYKshkAA=="
    assert row["time"] == datetime(2026, 4, 28, 8, 0, 0, tzinfo=UTC)


def test_map_to_reading_object_missing_uses_now() -> None:
    minimal = {"deviceInfo": {"devEui": "00"}, "fCnt": 5}
    uplink = ChirpStackUplink.model_validate(minimal)
    before = datetime.now(tz=UTC)
    row = _map_to_reading(uplink, device_id=1)
    after = datetime.now(tz=UTC)
    assert before <= row["time"] <= after
    assert row["temperature"] is None
    assert row["setpoint"] is None
    assert row["battery_percent"] is None


def test_map_to_reading_partial_object() -> None:
    payload = _valid_payload()
    payload["object"] = {"temperature": 22.5}  # nur temperature
    uplink = ChirpStackUplink.model_validate(payload)
    row = _map_to_reading(uplink, device_id=1)
    assert row["temperature"] == Decimal("22.5")
    assert row["setpoint"] is None
    assert row["valve_position"] is None
    assert row["battery_percent"] is None


def test_map_to_reading_no_rxinfo() -> None:
    payload = _valid_payload()
    payload["rxInfo"] = []
    uplink = ChirpStackUplink.model_validate(payload)
    row = _map_to_reading(uplink, device_id=1)
    assert row["rssi_dbm"] is None
    assert row["snr_db"] is None


# ---------------------------------------------------------------------------
# Sprint 9.0: valve_openness aus neuem Codec hat Vorrang vor motor_position
# ---------------------------------------------------------------------------


def test_map_to_reading_uses_valve_openness_when_present() -> None:
    """Neuer Codec liefert geclamptes valve_openness 0..100."""
    payload = _valid_payload()
    payload["object"]["valve_openness"] = 73
    payload["object"]["motor_position"] = 1984  # raw, soll IGNORIERT werden
    uplink = ChirpStackUplink.model_validate(payload)
    row = _map_to_reading(uplink, device_id=1)
    assert row["valve_position"] == 73


def test_map_to_reading_falls_back_to_motor_position() -> None:
    """Alter Codec ohne valve_openness -> Fallback motor_position (Uebergang)."""
    payload = _valid_payload()
    # valve_openness explizit nicht setzen
    payload["object"].pop("valve_openness", None)
    payload["object"]["motor_position"] = 88
    uplink = ChirpStackUplink.model_validate(payload)
    row = _map_to_reading(uplink, device_id=1)
    assert row["valve_position"] == 88


def test_map_to_reading_valve_openness_zero_is_persisted() -> None:
    """Sprint-9.0-Codec clamping kann 0 liefern — darf nicht als None
    gespeichert werden (sonst wuerde fallback auf motor_position greifen
    und falsche Werte schreiben)."""
    payload = _valid_payload()
    payload["object"]["valve_openness"] = 0
    payload["object"]["motor_position"] = 9999
    uplink = ChirpStackUplink.model_validate(payload)
    row = _map_to_reading(uplink, device_id=1)
    assert row["valve_position"] == 0


def test_map_to_reading_live_codec_output_fport2_periodic() -> None:
    """Regression-Wand fuer Sprint 9.10c (Codec-Routing-Bug).

    Vor dem 9.10c-Fix routete der Codec fPort=2 hartcodiert in den
    Reply-Pfad — Vicki-Periodics kamen damit als
    ``{command: 129, report_type: 'unknown_reply'}`` durch und der
    Subscriber persistierte temperature/setpoint/valve/battery als
    NULL. Diese Fixture verwendet ein echtes Codec-Output-Beispiel
    (fPort=2, cmd=0x81 bytes), wie es seit dem Fix vorliegt — voller
    object-Block. Der Test verifiziert, dass _map_to_reading alle
    Felder korrekt herausliest.
    """
    payload = {
        "deviceInfo": {"devEui": "70b3d52dd3034de4"},
        "fCnt": 895,
        "fPort": 2,
        "time": "2026-05-07T10:00:04Z",
        "object": {
            "report_type": "periodic",
            "command": 129,
            "temperature": 19.42,
            "target_temperature": 22,
            "battery_voltage": 3.5,
            "valve_openness": 65,
            "motor_position": 100,
            "motor_range": 285,
            "openWindow": False,
            "highMotorConsumption": False,
            "brokenSensor": False,
        },
        "rxInfo": [{"rssi": -90, "snr": 9.8}],
        "data": "gRKdYZmZEeAw",
    }
    uplink = ChirpStackUplink.model_validate(payload)
    row = _map_to_reading(uplink, device_id=42)

    assert row["device_id"] == 42
    assert row["fcnt"] == 895
    assert row["temperature"] == Decimal("19.42")
    assert row["setpoint"] == Decimal("22")
    assert row["valve_position"] == 65
    assert row["battery_percent"] == 42  # (3.5 - 3.0) / 1.2 * 100 = 41.67 -> 42
    assert row["open_window"] is False
    assert row["rssi_dbm"] == -90
    assert row["snr_db"] == Decimal("9.8")
    assert row["raw_payload"] == "gRKdYZmZEeAw"


# ---------------------------------------------------------------------------
# Sprint 9.10: openWindow aus Vicki-Codec persistieren (Layer-4-Voraussetzung)
# ---------------------------------------------------------------------------


def test_map_to_reading_open_window_true() -> None:
    """openWindow=true im Codec-Output landet als open_window=True in der Row."""
    payload = _valid_payload()
    payload["object"]["openWindow"] = True
    uplink = ChirpStackUplink.model_validate(payload)
    row = _map_to_reading(uplink, device_id=1)
    assert row["open_window"] is True


def test_map_to_reading_open_window_false() -> None:
    payload = _valid_payload()
    payload["object"]["openWindow"] = False
    uplink = ChirpStackUplink.model_validate(payload)
    row = _map_to_reading(uplink, device_id=1)
    assert row["open_window"] is False


def test_map_to_reading_open_window_missing_is_none() -> None:
    """Feld fehlt im Payload (alter Codec) -> NULL in DB, NICHT False.

    Layer 4 behandelt NULL und False gleich, aber die Persistenz muss die
    Lueke abbilden, damit Backfills/Audits unterscheiden koennen.
    """
    payload = _valid_payload()
    payload["object"].pop("openWindow", None)
    uplink = ChirpStackUplink.model_validate(payload)
    row = _map_to_reading(uplink, device_id=1)
    assert row["open_window"] is None


# ---------------------------------------------------------------------------
# Sprint 9.10 T3: _persist_uplink schedult evaluate_room.delay nach commit
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def db_session_for_persist() -> AsyncIterator[AsyncSession]:
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


async def test_persist_uplink_schedules_evaluate_room(
    db_session_for_persist: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Periodic-Uplink -> Reading wird inserted UND evaluate_room.delay
    wird mit der korrekten room_id aufgerufen.

    Mockt sowohl den Subscriber-eigenen ``SessionLocal`` (damit unser
    rollback-fixture-Session verwendet wird) als auch ``evaluate_room.delay``
    (damit kein Redis-Roundtrip noetig ist).
    """
    from heizung.models.device import Device
    from heizung.models.enums import DeviceKind, DeviceVendor, HeatingZoneKind
    from heizung.models.heating_zone import HeatingZone
    from heizung.models.room import Room
    from heizung.models.room_type import RoomType
    from heizung.services import mqtt_subscriber as sub_module

    suffix = uuid.uuid4().hex[:8]
    rt = RoomType(name=f"t3-rt-{suffix}")
    db_session_for_persist.add(rt)
    await db_session_for_persist.flush()
    room = Room(number=f"t3-{suffix}", room_type_id=rt.id)
    db_session_for_persist.add(room)
    await db_session_for_persist.flush()
    zone = HeatingZone(room_id=room.id, kind=HeatingZoneKind.BEDROOM, name="bedroom")
    db_session_for_persist.add(zone)
    await db_session_for_persist.flush()
    dev_eui = f"deadbeef{suffix}"
    device = Device(
        dev_eui=dev_eui,
        kind=DeviceKind.THERMOSTAT,
        vendor=DeviceVendor.MCLIMATE,
        model="vicki",
        heating_zone_id=zone.id,
    )
    db_session_for_persist.add(device)
    await db_session_for_persist.flush()
    expected_room_id = room.id

    # SessionLocal so monkeypatchen, dass _persist_uplink unsere
    # rollback-Session wiederverwendet (commit() wird auf der gleichen
    # Verbindung gemacht und beim Test-Tear-down weggerollt).
    class _FakeContext:
        async def __aenter__(self) -> AsyncSession:  # noqa: PLW0211 - Test-Fake
            return db_session_for_persist

        async def __aexit__(self, *args: object) -> None:  # noqa: PLW0211 - Test-Fake
            return None

    monkeypatch.setattr(sub_module, "SessionLocal", lambda: _FakeContext())

    delay_calls: list[tuple[int, ...]] = []
    monkeypatch.setattr(
        sub_module.evaluate_room,
        "delay",
        lambda *args: delay_calls.append(args),
    )

    payload = {
        "deviceInfo": {"devEui": dev_eui},
        "fCnt": 42,
        "fPort": 1,
        "time": "2026-05-07T08:00:00Z",
        "object": {
            "temperature": 22.5,
            "target_temperature": 21.0,
            "valve_openness": 50,
            "openWindow": True,
        },
    }
    uplink = ChirpStackUplink.model_validate(payload)

    await _persist_uplink(uplink)

    assert delay_calls == [(expected_room_id,)], (
        f"erwarte genau einen evaluate_room.delay({expected_room_id})-Call, gefunden {delay_calls}"
    )


async def test_persist_uplink_unknown_dev_eui_no_eval(
    db_session_for_persist: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unbekannte DevEUI -> early return, KEIN evaluate_room.delay."""
    from heizung.services import mqtt_subscriber as sub_module

    class _FakeContext:
        async def __aenter__(self) -> AsyncSession:  # noqa: PLW0211 - Test-Fake
            return db_session_for_persist

        async def __aexit__(self, *args: object) -> None:  # noqa: PLW0211 - Test-Fake
            return None

    monkeypatch.setattr(sub_module, "SessionLocal", lambda: _FakeContext())

    delay_calls: list[tuple[int, ...]] = []
    monkeypatch.setattr(
        sub_module.evaluate_room,
        "delay",
        lambda *args: delay_calls.append(args),
    )

    payload = {
        "deviceInfo": {"devEui": "ffffffffffffffff"},  # nicht in DB
        "fCnt": 1,
    }
    uplink = ChirpStackUplink.model_validate(payload)
    await _persist_uplink(uplink)

    assert delay_calls == [], "unbekannte DevEUI darf evaluate_room nicht triggern"


# ---------------------------------------------------------------------------
# Sprint 9.11x.c B-9.11x.b-6: FW-Persist-Logger feuert
# ---------------------------------------------------------------------------


async def test_handle_firmware_version_persists_and_logs(
    db_session_for_persist: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Echtes Device mit dev_eui in DB -> UPDATE matched 1 row,
    logger.info "firmware_version persistiert" feuert mit der korrekten
    Message und enthaelt rowcount=1 zur Diagnose.

    Wachposten gegen B-9.11x.b-6 (Log feuerte auf heizung-test nicht
    zuverlaessig — Fix: Log AUSSERHALB des async-with-Blocks).

    Test-Order-Defensive: andere Tests koennen ``propagate=False`` auf
    dem Subscriber-Logger setzen (z.B. via ``heizung.main``-Import,
    der ``logging.basicConfig`` ruft). Wir erzwingen Propagation
    explizit, damit caplog die Records auch in voller Suite sieht.
    """
    import logging as _stdlib_logging

    from heizung.models.device import Device
    from heizung.models.enums import DeviceKind, DeviceVendor
    from heizung.services import mqtt_subscriber as sub_module

    suffix = uuid.uuid4().hex[:8]
    dev_eui = f"fwtest00{suffix}"
    device = Device(
        dev_eui=dev_eui,
        kind=DeviceKind.THERMOSTAT,
        vendor=DeviceVendor.MCLIMATE,
        model="vicki",
    )
    db_session_for_persist.add(device)
    await db_session_for_persist.flush()

    class _FakeContext:
        async def __aenter__(self) -> AsyncSession:
            return db_session_for_persist

        async def __aexit__(self, *args: object) -> None:
            return None

    monkeypatch.setattr(sub_module, "SessionLocal", lambda: _FakeContext())

    uplink = ChirpStackUplink.model_validate(
        {
            "deviceInfo": {"devEui": dev_eui.upper()},  # Case-Insensitive-Check
            "fCnt": 1,
            "object": {
                "firmware_version": "4.4",
                "report_type": "firmware_version_reply",
            },
        }
    )

    sub_logger = _stdlib_logging.getLogger("heizung.services.mqtt_subscriber")
    monkeypatch.setattr(sub_logger, "propagate", True)
    monkeypatch.setattr(sub_logger, "disabled", False)
    caplog.set_level(_stdlib_logging.INFO, logger="heizung.services.mqtt_subscriber")

    await _handle_firmware_version_report(uplink)

    info_messages = [r.getMessage() for r in caplog.records if r.levelname == "INFO"]
    assert any("firmware_version persistiert" in m for m in info_messages), (
        f"erwarte INFO-Log mit 'firmware_version persistiert', gefunden: {info_messages}"
    )
    assert any(dev_eui in m for m in info_messages), "log muss dev_eui enthalten (lowercase)"
    assert any("fw=4.4" in m for m in info_messages), "log muss fw=4.4 enthalten"


async def test_handle_firmware_version_unknown_dev_eui_logs_warning(
    db_session_for_persist: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """dev_eui nicht in DB -> UPDATE matched 0 rows, WARNING-Log statt
    silent passthrough (B-9.11x.b-6 Defensive-Erweiterung)."""
    import logging as _stdlib_logging

    from heizung.services import mqtt_subscriber as sub_module

    class _FakeContext:
        async def __aenter__(self) -> AsyncSession:
            return db_session_for_persist

        async def __aexit__(self, *args: object) -> None:
            return None

    monkeypatch.setattr(sub_module, "SessionLocal", lambda: _FakeContext())

    uplink = ChirpStackUplink.model_validate(
        {
            "deviceInfo": {"devEui": "ffffffffffffffff"},  # nicht in DB
            "fCnt": 1,
            "object": {"firmware_version": "4.4"},
        }
    )

    sub_logger = _stdlib_logging.getLogger("heizung.services.mqtt_subscriber")
    monkeypatch.setattr(sub_logger, "propagate", True)
    monkeypatch.setattr(sub_logger, "disabled", False)
    caplog.set_level(_stdlib_logging.WARNING, logger="heizung.services.mqtt_subscriber")

    await _handle_firmware_version_report(uplink)

    warning_messages = [r.getMessage() for r in caplog.records if r.levelname == "WARNING"]
    assert any("UPDATE matched 0 rows" in m for m in warning_messages), (
        f"erwarte WARNING fuer unbekannte dev_eui, gefunden: {warning_messages}"
    )


async def test_handle_firmware_version_none_silent_skip(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """firmware_version fehlt im object -> silent return, kein Log,
    kein DB-Touch."""
    uplink = ChirpStackUplink.model_validate(
        {
            "deviceInfo": {"devEui": "aa00aa00aa00aa00"},
            "fCnt": 1,
            "object": {"temperature": 22.0},  # kein firmware_version
        }
    )
    with caplog.at_level("DEBUG", logger="heizung.services.mqtt_subscriber"):
        await _handle_firmware_version_report(uplink)
    messages = [r.getMessage() for r in caplog.records]
    assert not any("firmware_version" in m for m in messages), (
        f"erwarte KEINE firmware_version-Logs, gefunden: {messages}"
    )
