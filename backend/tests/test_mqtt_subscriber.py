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
from unittest.mock import MagicMock

import pytest
import pytest_asyncio
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from heizung.services import redis_client
from heizung.services.mqtt_subscriber import (
    BATTERY_CURVE_2XAA,
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
# _battery_pct_from_volts (Sprint 15b: 2xAA-Alkaline-Kennlinie, AE-64)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("volts", "expected"),
    [
        # Stuetzstellen exakt (AE-64-Live-Kalibrierung 2026-06-02)
        (3.50, 100),  # Codec-Saettigung (Nibble=15), frische 2xAA
        (3.20, 80),
        (3.00, 50),
        (2.90, 30),
        (2.80, 10),  # MClimate-Warnschwelle
        (2.70, 0),  # Geraete-Mindestbetrieb, Wechsel ueberfaellig
        # Clamps oberhalb / unterhalb der Kennlinien-Endpunkte
        (3.60, 100),  # ueber Codec-Bereich (Lithium-AA-Spec)
        (2.60, 0),  # unter MClimate-Mindestbetrieb
        (2.00, 0),  # Codec-Minimum (Nibble=0)
        # None-Eingang
        (None, None),
    ],
)
def test_battery_pct_curve_anchors_and_clamps(volts: float | None, expected: int | None) -> None:
    """Stuetzstellen exakt + Clamps an Kennlinien-Raendern."""
    assert _battery_pct_from_volts(volts) == expected


@pytest.mark.parametrize(
    ("volts", "expected"),
    [
        # 0.1-V-Raster aus Codec (V = 2.0 + nibble * 0.1, nibble 0..15)
        # AE-64-Live-kalibrierte Kennlinie:
        # 2.0..2.7 V geclampt auf 0; dann 10/30/50/65/80/87/93/100 % an
        # den Codec-Stufen 2.8..3.5 V. KEINE Stufen-Luecken.
        (2.0, 0),
        (2.1, 0),
        (2.2, 0),
        (2.3, 0),
        (2.4, 0),
        (2.5, 0),
        (2.6, 0),
        (2.7, 0),
        (2.8, 10),
        (2.9, 30),
        (3.0, 50),
        (3.1, 65),  # Interpolation Mittelpunkt (3.0,50)-(3.2,80)
        (3.2, 80),
        (3.3, 87),  # ~1/3 zwischen (3.2,80)-(3.5,100) -> 86.67 ROUND_HALF_UP
        (3.4, 93),  # ~2/3 -> 93.33 ROUND_HALF_UP
        (3.5, 100),
    ],
)
def test_battery_pct_each_codec_step_has_defined_value(volts: float, expected: int) -> None:
    """Jede diskrete Codec-Spannungsstufe (0.1-V-Raster) liefert einen
    definierten %-Wert — keine Sprung-Luecken im Aussage-Raster.
    """
    assert _battery_pct_from_volts(volts) == expected


def test_battery_pct_curve_monotonically_non_decreasing() -> None:
    """Ueber alle Codec-Stufen (2.0..3.5 V in 0.1-V-Schritten) ist die
    Funktion monoton nicht-fallend — hoehere Spannung => >= Prozent.
    """
    pcts: list[int] = []
    for nibble in range(16):  # nibble 0..15 -> 2.0..3.5 V
        v = 2.0 + nibble * 0.1
        pct = _battery_pct_from_volts(v)
        assert pct is not None
        pcts.append(pct)
    for prev, curr in zip(pcts[:-1], pcts[1:], strict=True):
        assert curr >= prev, f"nicht monoton: prev={prev} curr={curr} in {pcts}"


def test_battery_pct_interpolation_between_anchors() -> None:
    """Sub-Quantisierung (Hypothetisch — Codec-Raster ist 0.1 V, aber
    die Interpolation muss zwischen den Anchors korrekt rechnen): 2.85 V
    liegt mittig zwischen 2.80 (10%) und 2.90 (30%) -> 20 %.
    """
    assert _battery_pct_from_volts(2.85) == 20


def test_battery_curve_anchors_match_adr_definition() -> None:
    """Schutzlatte gegen versehentliches Verschieben der Anker-Werte.
    Anker-Definition gegen AE-64 (Live-Kalibrierung 2026-06-02).
    """
    assert (
        (Decimal("2.70"), 0),
        (Decimal("2.80"), 10),
        (Decimal("2.90"), 30),
        (Decimal("3.00"), 50),
        (Decimal("3.20"), 80),
        (Decimal("3.50"), 100),
    ) == BATTERY_CURVE_2XAA


@pytest.mark.parametrize(
    ("volts", "expected", "vicki_label"),
    [
        # AE-64-Live-Kalibrierung 2026-06-02: 4 produktive Vickis auf
        # heizung-test. Alte LiPo-Linear-Skala zeigte intakte Vickis als
        # 0 % (Cowork-Befund Sprint 15a). Mit AE-64-Kennlinie:
        (3.5, 100, "Vicki-3 (Codec-Saettigung, frisch)"),
        (3.5, 100, "Vicki-4 (Codec-Saettigung, frisch)"),
        (3.5, 100, "Vicki-5 (Codec-Saettigung, frisch)"),
        (3.0, 50, "Vicki-2 (schwaechste der 4, mittlere Restkapazitaet)"),
    ],
)
def test_battery_pct_real_live_fixture_4_vickis(
    volts: float, expected: int, vicki_label: str
) -> None:
    """Akzeptanztest gegen die realen Live-Werte der 4 Produktiv-Vickis
    (heizung-test, 2026-06-02): intaktes Geraet ist NICHT 0 %, schwaechstes
    Geraet ist mittig, nicht voll. Der eigentliche AE-64-Akzeptanzpunkt.
    """
    assert _battery_pct_from_volts(volts) == expected, (
        f"Live-Kalibrierungs-Regression fuer {vicki_label}"
    )


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
            # Sprint 15b (AE-64): realer Codec-Bereich 2.0-3.5 V in 0.1-V-Schritten.
            # 3.0 V = Kennlinien-Mitte = 50 % (entspricht der schwaechsten der
            # 4 Produktiv-Vickis bei Live-Kalibrierung 2026-06-02).
            "battery_voltage": 3.0,
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
    assert row["battery_percent"] == 50  # AE-64: 3.0 V = Mitte der Kennlinie
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
    # Sprint 15b (AE-64): 3.5 V ist Codec-Saettigung (Nibble=15) und
    # oberer Kennlinien-Anchor = 100 % — frische 2xAA Alkaline. Alte
    # LiPo-Formel ergab 42 % bei intakter Batterie (Cowork-Befund 15a).
    assert row["battery_percent"] == 100
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


# ---------------------------------------------------------------------------
# Sprint 11 T2: Plausi-Filter [-20 °C, 60 °C] auf temperature (AE-53)
# Sprint 11 T5: Plus Redis-Implausible-Counter (Pipeline: incr + expire 86400).
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_redis(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Mockt ``redis_client.get_redis_client`` fuer die T2-Tests.

    Sprint 11 T5: implausible Readings rufen
    ``_increment_implausible_counter`` (Pipeline: incr + expire). Tests
    verifizieren die Pipeline-Aufrufe ueber Aufruf-Tracking, ohne echtes
    Redis zu brauchen.
    """
    fake = MagicMock()
    monkeypatch.setattr(redis_client, "get_redis_client", lambda: fake)
    return fake


async def _setup_plausi_device(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> tuple[str, int, list[tuple[int, ...]]]:
    """Setup-Helper: RoomType + Room + HeatingZone + Device + Mocks.

    Liefert (dev_eui, expected_room_id, delay_calls_list) zurueck.
    SessionLocal wird so monkeypatched, dass ``_persist_uplink`` die
    test-fixture-Session wiederverwendet. ``evaluate_room.delay`` wird
    durch eine Liste ersetzt, die jeder Call anhaengt — Tests pruefen
    die Liste statt Redis zu beruehren.
    """
    from heizung.models.device import Device
    from heizung.models.enums import DeviceKind, DeviceVendor, HeatingZoneKind
    from heizung.models.heating_zone import HeatingZone
    from heizung.models.room import Room
    from heizung.models.room_type import RoomType
    from heizung.services import mqtt_subscriber as sub_module

    suffix = uuid.uuid4().hex[:8]
    rt = RoomType(name=f"plausi-rt-{suffix}")
    session.add(rt)
    await session.flush()
    room = Room(number=f"plausi-{suffix}", room_type_id=rt.id)
    session.add(room)
    await session.flush()
    zone = HeatingZone(room_id=room.id, kind=HeatingZoneKind.BEDROOM, name="bedroom")
    session.add(zone)
    await session.flush()
    dev_eui = f"deadbeef{suffix}"
    device = Device(
        dev_eui=dev_eui,
        kind=DeviceKind.THERMOSTAT,
        vendor=DeviceVendor.MCLIMATE,
        model="vicki",
        heating_zone_id=zone.id,
    )
    session.add(device)
    await session.flush()

    class _FakeContext:
        async def __aenter__(self) -> AsyncSession:
            return session

        async def __aexit__(self, *args: object) -> None:
            return None

    monkeypatch.setattr(sub_module, "SessionLocal", lambda: _FakeContext())

    delay_calls: list[tuple[int, ...]] = []
    monkeypatch.setattr(
        sub_module.evaluate_room,
        "delay",
        lambda *args: delay_calls.append(args),
    )

    return dev_eui, room.id, delay_calls


def _enable_subscriber_log_propagation(monkeypatch: pytest.MonkeyPatch) -> None:
    """caplog-Defensive analog Sprint 9.11x.c: erzwingt Propagation auf
    den Subscriber-Logger, damit ``caplog`` Records in voller Suite sieht."""
    import logging as _stdlib_logging

    sub_logger = _stdlib_logging.getLogger("heizung.services.mqtt_subscriber")
    monkeypatch.setattr(sub_logger, "propagate", True)
    monkeypatch.setattr(sub_logger, "disabled", False)


async def test_subscriber_rejects_temperature_below_minus_20_implausible(
    db_session_for_persist: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    fake_redis: MagicMock,
) -> None:
    """temperature=-25 °C -> kein Insert, kein evaluate_room.delay,
    WARNING ``implausible_reading`` mit extra-Feldern.

    Sprint 11 T5: zusaetzlich Implausible-Counter via Pipeline
    (incr + expire 86400) — Reject-Pfad muss den Pipeline-INCR aufrufen.
    """
    import logging as _stdlib_logging

    dev_eui, _expected_room_id, delay_calls = await _setup_plausi_device(
        db_session_for_persist, monkeypatch
    )
    _enable_subscriber_log_propagation(monkeypatch)
    caplog.set_level(_stdlib_logging.WARNING, logger="heizung.services.mqtt_subscriber")

    payload = {
        "deviceInfo": {"devEui": dev_eui},
        "fCnt": 1,
        "fPort": 1,
        "time": "2026-05-17T08:00:00Z",
        "object": {"temperature": -25.0},
        "data": "implausible-low",
    }
    uplink = ChirpStackUplink.model_validate(payload)

    await _persist_uplink(uplink)

    assert delay_calls == [], (
        f"implausible Reading darf evaluate_room nicht triggern, gefunden: {delay_calls}"
    )
    plausi_records = [r for r in caplog.records if r.getMessage() == "implausible_reading"]
    assert plausi_records, (
        f"erwarte WARNING 'implausible_reading', gefunden: "
        f"{[(r.levelname, r.getMessage()) for r in caplog.records]}"
    )
    rec = plausi_records[0]
    assert rec.levelname == "WARNING"
    assert getattr(rec, "dev_eui", None) == dev_eui
    assert getattr(rec, "temperature", None) == "-25.0"
    assert getattr(rec, "reason", None) == "out_of_bounds"
    assert getattr(rec, "raw_payload", None) == "implausible-low"

    # T5: Redis-Counter-Pipeline wurde aufgerufen (incr + expire).
    pipe = fake_redis.pipeline.return_value
    pipe.incr.assert_called_once_with(f"implausible:{dev_eui}")
    pipe.expire.assert_called_once_with(f"implausible:{dev_eui}", 86400)
    pipe.execute.assert_called_once()


async def test_subscriber_rejects_temperature_above_60_implausible(
    db_session_for_persist: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    fake_redis: MagicMock,
) -> None:
    """temperature=65 °C -> kein Insert, kein evaluate_room.delay,
    WARNING ``implausible_reading`` (analog Lower-Bound).

    Sprint 11 T5: zusaetzlich Pipeline-INCR + EXPIRE.
    """
    import logging as _stdlib_logging

    dev_eui, _expected_room_id, delay_calls = await _setup_plausi_device(
        db_session_for_persist, monkeypatch
    )
    _enable_subscriber_log_propagation(monkeypatch)
    caplog.set_level(_stdlib_logging.WARNING, logger="heizung.services.mqtt_subscriber")

    payload = {
        "deviceInfo": {"devEui": dev_eui},
        "fCnt": 1,
        "fPort": 1,
        "time": "2026-05-17T08:00:00Z",
        "object": {"temperature": 65.0},
        "data": "implausible-high",
    }
    uplink = ChirpStackUplink.model_validate(payload)

    await _persist_uplink(uplink)

    assert delay_calls == [], (
        f"implausible Reading darf evaluate_room nicht triggern, gefunden: {delay_calls}"
    )
    plausi_records = [r for r in caplog.records if r.getMessage() == "implausible_reading"]
    assert plausi_records, (
        f"erwarte WARNING 'implausible_reading', gefunden: "
        f"{[(r.levelname, r.getMessage()) for r in caplog.records]}"
    )
    rec = plausi_records[0]
    assert getattr(rec, "temperature", None) == "65.0"
    assert getattr(rec, "reason", None) == "out_of_bounds"

    # T5: Redis-Counter-Pipeline wurde aufgerufen.
    pipe = fake_redis.pipeline.return_value
    pipe.incr.assert_called_once_with(f"implausible:{dev_eui}")
    pipe.expire.assert_called_once_with(f"implausible:{dev_eui}", 86400)
    pipe.execute.assert_called_once()


async def test_subscriber_accepts_temperature_at_lower_bound(
    db_session_for_persist: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    fake_redis: MagicMock,
) -> None:
    """temperature=-20.0 °C ist Grenze inklusiv -> Reading persistiert,
    evaluate_room.delay() laeuft genau einmal mit der richtigen room_id.

    Sprint 11 T5: Counter-Pipeline darf NICHT angefasst werden (akzeptiertes
    Reading ist kein Implausible-Trigger).
    """
    dev_eui, expected_room_id, delay_calls = await _setup_plausi_device(
        db_session_for_persist, monkeypatch
    )

    payload = {
        "deviceInfo": {"devEui": dev_eui},
        "fCnt": 1,
        "fPort": 1,
        "time": "2026-05-17T08:00:00Z",
        "object": {"temperature": -20.0, "target_temperature": 21.0},
    }
    uplink = ChirpStackUplink.model_validate(payload)

    await _persist_uplink(uplink)

    assert delay_calls == [(expected_room_id,)], (
        f"erwarte genau einen evaluate_room.delay({expected_room_id})-Call, gefunden {delay_calls}"
    )
    fake_redis.pipeline.assert_not_called()


async def test_subscriber_accepts_temperature_in_normal_range(
    db_session_for_persist: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    fake_redis: MagicMock,
) -> None:
    """temperature=20.0 °C ist plausibel -> normaler Pfad wie heute.

    Sprint 11 T5: Counter-Pipeline darf nicht angefasst werden.
    """
    dev_eui, expected_room_id, delay_calls = await _setup_plausi_device(
        db_session_for_persist, monkeypatch
    )

    payload = {
        "deviceInfo": {"devEui": dev_eui},
        "fCnt": 1,
        "fPort": 1,
        "time": "2026-05-17T08:00:00Z",
        "object": {"temperature": 20.0, "target_temperature": 21.0},
    }
    uplink = ChirpStackUplink.model_validate(payload)

    await _persist_uplink(uplink)

    assert delay_calls == [(expected_room_id,)], (
        f"erwarte genau einen evaluate_room.delay({expected_room_id})-Call, gefunden {delay_calls}"
    )
    fake_redis.pipeline.assert_not_called()
