"""Sprint 17 (C4/E2) — Batch-Eingangstest.

Zwei Ebenen:

- **Reine Funktionen** (``_evaluate``, ``classify_firmware``) ohne DB — sie
  tragen die Urteilslogik und lassen sich erschoepfend pruefen.
- **DB-Tests** gegen ``TEST_DATABASE_URL`` fuer den Warte- und Gesamtablauf.

Die Zeit ist gesteuert: ``_now`` und ``_sleep`` werden ersetzt. ``_sleep``
laesst die Uhr springen und ruft einen Haken, der die Antwort-Readings so
einspielt, wie ein echtes Geraet sie senden wuerde — abhaengig davon, was
vorher an dieses Geraet gesendet wurde. Damit laeuft ein Test, der in echt
zweimal 45 Minuten wartet, in Millisekunden und bleibt deterministisch.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncIterator, Callable
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
from heizung.models.enums import DeviceKind, DeviceVendor
from heizung.models.sensor_reading import SensorReading
from heizung.scripts.pairing import batch_inbound_test as bit
from heizung.scripts.pairing.batch_inbound_test import (
    AUDIT_ACTION,
    SETPOINT_HIGH_C,
    SETPOINT_LOW_C,
    BatchReport,
    DeviceResult,
    StepResult,
    _evaluate,
    format_report,
    run_batch_inbound_test,
)
from heizung.scripts.pairing.firmware import (
    MIN_FW_FOR_OW_SET,
    classify_firmware,
    parse_fw_tuple,
    supports_ow_set,
)

DATABASE_URL = os.environ.get("DATABASE_URL")
SKIP_REASON = "DATABASE_URL nicht gesetzt - DB-Tests brauchen Test-DB"

T0 = datetime(2026, 9, 26, 8, 0, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Firmware — reine Funktionen
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("fw", "erwartet"),
    [
        ("4.5", "ow_faehig"),
        ("4.2", "ow_faehig"),
        ("5.0", "ow_faehig"),
        ("4.1", "zu_alt"),
        ("3.9", "zu_alt"),
        (None, "keine_antwort"),
        ("", "keine_antwort"),
        ("4", "keine_antwort"),
        ("vier.zwei", "keine_antwort"),
    ],
)
def test_classify_firmware(fw: str | None, erwartet: str) -> None:
    assert classify_firmware(fw) == erwartet


def test_parse_fw_tuple_accepts_three_components() -> None:
    """Codec koennte spaeter 'major.minor.patch' liefern — major.minor zaehlt."""
    assert parse_fw_tuple("4.5.1") == (4, 5)


def test_min_fw_threshold_is_4_2() -> None:
    """Schutz gegen ein unbeabsichtigtes Verschieben der Schwelle."""
    assert MIN_FW_FOR_OW_SET == (4, 2)
    assert supports_ow_set("4.2") is True
    assert supports_ow_set("4.1") is False


# ---------------------------------------------------------------------------
# Urteilslogik — reine Funktion
# ---------------------------------------------------------------------------


def _device(device_id: int = 1, label: str = "001") -> Device:
    return Device(
        id=device_id,
        dev_eui=f"deadbeef{device_id:08d}",
        kind=DeviceKind.THERMOSTAT,
        vendor=DeviceVendor.MCLIMATE,
        model="Vicki",
        label=label,
    )


def _ok(target: int, valve: int | None) -> StepResult:
    return StepResult(
        target_c=target,
        outcome="ok",
        observed_setpoint=Decimal(target),
        valve_position=valve,
        reading_at=T0,
        detail="",
    )


def test_evaluate_pass_with_moving_valve() -> None:
    r = _evaluate(_device(), _ok(25, 80), _ok(10, 5), "4.5", valve_check=True)
    assert r.status == "pass"
    assert "5 % -> 80 %" in r.reason
    assert r.hardware_nummer == "001"
    assert r.firmware_text == "4.5"


def test_evaluate_fail_when_valve_stuck() -> None:
    """Readback stimmt, Ventil bewegt sich nicht -> Hardware-Verdacht."""
    r = _evaluate(_device(), _ok(25, 40), _ok(10, 40), "4.5", valve_check=True)
    assert r.status == "fail"
    assert "Ventil unbewegt" in r.reason


def test_evaluate_fail_when_valve_moves_wrong_way() -> None:
    r = _evaluate(_device(), _ok(25, 10), _ok(10, 90), "4.5", valve_check=True)
    assert r.status == "fail"


def test_evaluate_pass_when_valve_check_disabled() -> None:
    r = _evaluate(_device(), _ok(25, 40), _ok(10, 40), "4.5", valve_check=False)
    assert r.status == "pass"
    assert "abgeschaltet" in r.reason


def test_evaluate_pass_when_valve_data_missing() -> None:
    """Fehlende Ventildaten sind kein Verstoss — das Kriterium ist nur
    nicht pruefbar. Der Readback allein hat bestanden."""
    r = _evaluate(_device(), _ok(25, None), _ok(10, None), "4.5", valve_check=True)
    assert r.status == "pass"
    assert "nicht pruefbar" in r.reason


def test_evaluate_fail_on_wrong_readback() -> None:
    wrong = StepResult(
        target_c=25,
        outcome="wrong_readback",
        observed_setpoint=Decimal(18),
        detail="Uplink kam, meldet aber 18 statt 25 °C.",
    )
    r = _evaluate(_device(), wrong, None, "4.5", valve_check=True)
    assert r.status == "fail"
    assert "18" in r.reason


def test_evaluate_timeout_is_not_fail() -> None:
    """TIMEOUT ist ein Funk-Befund, kein Hardware-Verdacht."""
    to = StepResult(target_c=25, outcome="timeout", detail="Kein Uplink innerhalb von 60 s.")
    r = _evaluate(_device(), to, None, None, valve_check=True)
    assert r.status == "timeout"
    assert r.firmware_text == "keine Antwort"


def test_evaluate_downlink_failure_is_fail() -> None:
    df = StepResult(target_c=25, outcome="downlink_failed", detail="MqttError: weg")
    r = _evaluate(_device(), df, None, "4.5", valve_check=True)
    assert r.status == "fail"


def test_hardware_nummer_falls_back_to_dev_eui() -> None:
    dev = _device()
    dev.label = None
    r = _evaluate(dev, _ok(25, 80), _ok(10, 5), "4.5", valve_check=True)
    assert r.hardware_nummer == dev.dev_eui


# ---------------------------------------------------------------------------
# Bericht
# ---------------------------------------------------------------------------


def _result(nr: str, status: str, fw: str | None) -> DeviceResult:
    return DeviceResult(
        device_id=int(nr),
        dev_eui=f"deadbeef{int(nr):08d}",
        hardware_nummer=nr,
        status=status,  # type: ignore[arg-type]
        reason="x",
        firmware_version=fw,
    )


def test_format_report_groups_firmware_and_names_devices() -> None:
    report = BatchReport(
        results=[
            _result("001", "pass", "4.5"),
            _result("002", "fail", "4.5"),
            _result("003", "timeout", None),
            _result("004", "pass", "4.1"),
        ]
    )
    text = format_report(report)
    assert "2 PASS, 1 FAIL, 1 TIMEOUT von 4 Geraeten" in text
    # FW-Inventar nennt die Nummern, damit der Hotelier sie abhaken kann.
    assert "004" in text
    assert "003" in text
    assert "Erwartungswert fuer den OW-Rollout: 2 Geraet(e)" in text
    # FAIL und TIMEOUT werden getrennt erklaert.
    assert "KEIN Hardware-Verdacht" in text
    assert "Hardware-Verdacht" in text
    assert report.exit_code == 1


def test_format_report_all_pass_exit_zero() -> None:
    report = BatchReport(results=[_result("001", "pass", "4.5")])
    assert report.exit_code == 0
    assert "Erwartungswert fuer den OW-Rollout: 0 Geraet(e)" in format_report(report)


def test_format_report_empty() -> None:
    assert "Keine Pool-Geraete" in format_report(BatchReport())


# ---------------------------------------------------------------------------
# DB-Ablauf
# ---------------------------------------------------------------------------


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


async def _make_pool_device(s: AsyncSession, label: str, fw: str | None = None) -> Device:
    """Pool-Geraet: heating_zone_id NULL, nicht retired."""
    dev = Device(
        dev_eui=_eui(),
        kind=DeviceKind.THERMOSTAT,
        vendor=DeviceVendor.MCLIMATE,
        model="Vicki",
        label=label,
        firmware_version=fw,
    )
    s.add(dev)
    await s.flush()
    return dev


class FakeRadio:
    """Steuert Uhr, Downlinks und die simulierten Antworten der Geraete.

    ``script`` sagt pro ``dev_eui``, wie das Geraet auf einen Sollwert
    antwortet: der zurueckgemeldete Sollwert und die Ventilstellung, oder
    ``None`` fuer "antwortet gar nicht".
    """

    def __init__(
        self,
        session: AsyncSession,
        script: dict[str, Callable[[int], tuple[int, int | None] | None]],
    ) -> None:
        self.session = session
        self.script = script
        self.now = T0
        self.sent: list[tuple[str, int]] = []
        self.fw_queries: list[str] = []
        self._answered: set[tuple[str, int]] = set()
        self._device_ids: dict[str, int] = {}

    def register(self, dev: Device) -> None:
        self._device_ids[dev.dev_eui] = dev.id

    async def send_setpoint(self, dev_eui: str, setpoint_c: int) -> str:
        self.sent.append((dev_eui, setpoint_c))
        return "topic"

    async def query_firmware_version(self, dev_eui: str) -> str:
        self.fw_queries.append(dev_eui)
        return "topic"

    async def sleep(self, seconds: float) -> None:
        self.now += timedelta(seconds=max(seconds, 0.001))
        await self._deliver()

    def clock(self) -> datetime:
        return self.now

    async def _deliver(self) -> None:
        """Spielt faellige Antworten ein — je gesendetem Sollwert genau eine."""
        for dev_eui, target in list(self.sent):
            key = (dev_eui, target)
            if key in self._answered:
                continue
            answer = self.script[dev_eui](target)
            if answer is None:
                # Geraet schweigt: nie eine Antwort. Als beantwortet
                # markieren, damit wir es nicht in jeder Runde neu pruefen.
                self._answered.add(key)
                continue
            setpoint, valve = answer
            self.session.add(
                SensorReading(
                    time=self.now,
                    device_id=self._device_ids[dev_eui],
                    fcnt=len(self._answered) + 1,
                    temperature=Decimal("21.0"),
                    setpoint=Decimal(setpoint),
                    valve_position=valve,
                )
            )
            await self.session.flush()
            self._answered.add(key)


@pytest.fixture
def patch_radio(monkeypatch: pytest.MonkeyPatch) -> Callable[[FakeRadio], None]:
    def apply(radio: FakeRadio) -> None:
        monkeypatch.setattr(bit, "send_setpoint", radio.send_setpoint)
        monkeypatch.setattr(bit, "query_firmware_version", radio.query_firmware_version)
        monkeypatch.setattr(bit, "_sleep", radio.sleep)
        monkeypatch.setattr(bit, "_now", radio.clock)

    return apply


def _antwortet(setpoint_offset: int = 0, valve_high: int = 80, valve_low: int = 5):  # type: ignore[no-untyped-def]
    """Geraet meldet den gesetzten Sollwert (ggf. verschoben) korrekt zurueck."""

    def responder(target: int) -> tuple[int, int | None]:
        valve = valve_high if target == SETPOINT_HIGH_C else valve_low
        return target + setpoint_offset, valve

    return responder


def _schweigt(_target: int) -> None:
    return None


async def test_batch_pass_fail_timeout_and_firmware(
    session: AsyncSession,
    patch_radio: Callable[[FakeRadio], None],
) -> None:
    """Der Brief-Fall: je ein Geraet pass, fail, timeout — plus FW-Inventar."""
    good = await _make_pool_device(session, "001", fw="4.5")
    wrong = await _make_pool_device(session, "002", fw="4.1")
    silent = await _make_pool_device(session, "003", fw=None)

    radio = FakeRadio(
        session,
        {
            good.dev_eui: _antwortet(),
            # meldet konstant 18 zurueck -> frischer Uplink, falscher Wert
            wrong.dev_eui: lambda _t: (18, 50),
            silent.dev_eui: _schweigt,
        },
    )
    for d in (good, wrong, silent):
        radio.register(d)
    patch_radio(radio)

    report = await run_batch_inbound_test(
        session, [good, wrong, silent], timeout_s=120, poll_interval_s=10
    )

    by_nr = {r.hardware_nummer: r for r in report.results}
    assert by_nr["001"].status == "pass"
    assert by_nr["002"].status == "fail"
    assert "18" in by_nr["002"].reason
    assert by_nr["003"].status == "timeout"
    assert report.exit_code == 1

    # FW-Inventar: drei Klassen, jeweils mit Nummer.
    groups = report.by_firmware()
    assert [r.hardware_nummer for r in groups["ow_faehig"]] == ["001"]
    assert [r.hardware_nummer for r in groups["zu_alt"]] == ["002"]
    assert [r.hardware_nummer for r in groups["keine_antwort"]] == ["003"]

    # FW-Abfrage ging an jedes Geraet, unabhaengig vom Testausgang.
    assert set(radio.fw_queries) == {good.dev_eui, wrong.dev_eui, silent.dev_eui}

    text = format_report(report)
    assert "Erwartungswert fuer den OW-Rollout: 2 Geraet(e)" in text


async def test_batch_skips_second_step_for_failed_devices(
    session: AsyncSession,
    patch_radio: Callable[[FakeRadio], None],
) -> None:
    """Ein Geraet ohne Uplink blockiert kein zweites volles Zeitfenster."""
    good = await _make_pool_device(session, "010", fw="4.5")
    silent = await _make_pool_device(session, "011", fw="4.5")
    radio = FakeRadio(session, {good.dev_eui: _antwortet(), silent.dev_eui: _schweigt})
    for d in (good, silent):
        radio.register(d)
    patch_radio(radio)

    await run_batch_inbound_test(session, [good, silent], timeout_s=60, poll_interval_s=10)

    # Das stumme Geraet hat nur den 25-°C-Downlink bekommen, keinen zweiten.
    silent_sends = [t for eui, t in radio.sent if eui == silent.dev_eui]
    good_sends = [t for eui, t in radio.sent if eui == good.dev_eui]
    assert silent_sends == [SETPOINT_HIGH_C]
    assert good_sends == [SETPOINT_HIGH_C, SETPOINT_LOW_C]


async def test_batch_valve_stuck_is_fail(
    session: AsyncSession,
    patch_radio: Callable[[FakeRadio], None],
) -> None:
    """Readback beidseitig korrekt, Ventil bleibt stehen -> FAIL."""
    dev = await _make_pool_device(session, "020", fw="4.5")
    radio = FakeRadio(session, {dev.dev_eui: _antwortet(valve_high=42, valve_low=42)})
    radio.register(dev)
    patch_radio(radio)

    report = await run_batch_inbound_test(session, [dev], timeout_s=60, poll_interval_s=10)
    assert report.results[0].status == "fail"
    assert "Ventil unbewegt" in report.results[0].reason


async def test_batch_valve_check_can_be_disabled(
    session: AsyncSession,
    patch_radio: Callable[[FakeRadio], None],
) -> None:
    dev = await _make_pool_device(session, "021", fw="4.5")
    radio = FakeRadio(session, {dev.dev_eui: _antwortet(valve_high=42, valve_low=42)})
    radio.register(dev)
    patch_radio(radio)

    report = await run_batch_inbound_test(
        session, [dev], timeout_s=60, poll_interval_s=10, valve_check=False
    )
    assert report.results[0].status == "pass"


async def test_batch_persists_audit_per_device(
    session: AsyncSession,
    patch_radio: Callable[[FakeRadio], None],
) -> None:
    """Ergebnis landet in business_audit — ohne Migration (event_log kann
    nicht, weil room_id NOT NULL und Teil des PK ist)."""
    dev = await _make_pool_device(session, "030", fw="4.5")
    radio = FakeRadio(session, {dev.dev_eui: _antwortet()})
    radio.register(dev)
    patch_radio(radio)

    await run_batch_inbound_test(session, [dev], timeout_s=60, poll_interval_s=10)

    stmt = select(BusinessAudit).where(
        BusinessAudit.action == AUDIT_ACTION, BusinessAudit.target_id == dev.id
    )
    audit = (await session.execute(stmt)).scalar_one()
    assert audit.target_type == "device"
    assert audit.new_value["status"] == "pass"
    assert audit.new_value["hardware_nummer"] == "030"
    assert audit.new_value["firmware_version"] == "4.5"
    assert audit.new_value["firmware_class"] == "ow_faehig"
    assert audit.new_value["setpoint_25"]["outcome"] == "ok"
    assert audit.new_value["setpoint_10"]["outcome"] == "ok"


async def test_batch_timeout_device_audit_records_timeout(
    session: AsyncSession,
    patch_radio: Callable[[FakeRadio], None],
) -> None:
    dev = await _make_pool_device(session, "031", fw=None)
    radio = FakeRadio(session, {dev.dev_eui: _schweigt})
    radio.register(dev)
    patch_radio(radio)

    await run_batch_inbound_test(session, [dev], timeout_s=60, poll_interval_s=10)
    stmt = select(BusinessAudit).where(
        BusinessAudit.action == AUDIT_ACTION, BusinessAudit.target_id == dev.id
    )
    audit = (await session.execute(stmt)).scalar_one()
    assert audit.new_value["status"] == "timeout"
    assert audit.new_value["firmware_class"] == "keine_antwort"


async def test_batch_downlink_failure_is_fail_not_timeout(
    session: AsyncSession,
    patch_radio: Callable[[FakeRadio], None],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ein gescheiterter Downlink ist ein Fehler, kein Funk-Befund."""
    dev = await _make_pool_device(session, "040", fw="4.5")
    radio = FakeRadio(session, {dev.dev_eui: _antwortet()})
    radio.register(dev)
    patch_radio(radio)

    async def boom(dev_eui: str, setpoint_c: int) -> str:
        raise RuntimeError("MQTT weg")

    monkeypatch.setattr(bit, "send_setpoint", boom)

    report = await run_batch_inbound_test(session, [dev], timeout_s=60, poll_interval_s=10)
    assert report.results[0].status == "fail"
    assert "Downlink" in report.results[0].reason


async def test_batch_empty_device_list(session: AsyncSession) -> None:
    report = await run_batch_inbound_test(session, [], timeout_s=10, poll_interval_s=1)
    assert report.results == []
    assert report.exit_code == 0
