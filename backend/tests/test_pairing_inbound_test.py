"""Sprint 13a T5 — Vicki-Eingangstest.

DB-Tests gegen ``TEST_DATABASE_URL`` (analog T4 ``test_pairing_service``).
Downlinks + Sleep + User-Prompts werden via ``monkeypatch`` gemockt.
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
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from alembic import command
from heizung.models.device import Device
from heizung.models.enums import DeviceKind, DeviceVendor
from heizung.models.sensor_reading import SensorReading
from heizung.scripts.pairing import inbound_test
from heizung.scripts.pairing.inbound_test import (
    STEP_BACKPLATE,
    STEP_HEARTBEAT,
    STEP_RESEND_OW,
    STEP_SETPOINT_10,
    STEP_SETPOINT_25,
    STEP_TEMP_PLAUSI,
    run_inbound_test,
)

DATABASE_URL = os.environ.get("DATABASE_URL")
DATABASE_URL_PRESENT = bool(DATABASE_URL)
SKIP_REASON = "DATABASE_URL nicht gesetzt - DB-Tests brauchen Test-DB"


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


def _eui() -> str:
    return uuid.uuid4().hex[:16]


async def _seed_device(session: AsyncSession) -> int:
    """Legt ein Device an (ohne Zone — Pool-Style fuer Test-Isolation)."""
    device = Device(
        dev_eui=_eui(),
        kind=DeviceKind.THERMOSTAT,
        vendor=DeviceVendor.MCLIMATE,
        model="Vicki",
    )
    session.add(device)
    await session.flush()
    return device.id


async def _add_reading(
    session: AsyncSession,
    device_id: int,
    *,
    age_min: int,
    temperature: Decimal | None = Decimal("22.0"),
    attached_backplate: bool | None = True,
) -> SensorReading:
    """Legt ein SensorReading an. ``age_min`` = wie viele Min in der Vergangenheit."""
    reading = SensorReading(
        time=datetime.now(tz=UTC) - timedelta(minutes=age_min),
        device_id=device_id,
        temperature=temperature,
        attached_backplate=attached_backplate,
    )
    session.add(reading)
    await session.flush()
    return reading


@pytest_asyncio.fixture
def mock_downlinks_ok(
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, list[tuple[str, ...]]]:
    """Mockt ``set_open_window_detection`` + ``send_setpoint`` + ``_sleep``
    + ``_user_confirm``. Recorded Calls pro Funktion."""
    calls: dict[str, list[tuple[str, ...]]] = {
        "set_ow": [],
        "send_setpoint": [],
        "sleep": [],
    }

    async def fake_set_ow(dev_eui: str, enabled: bool, duration_min: int, delta_c: Decimal) -> str:
        calls["set_ow"].append((dev_eui, str(enabled), str(duration_min), str(delta_c)))
        return "topic"

    async def fake_send_setpoint(dev_eui: str, setpoint_c: int) -> str:
        calls["send_setpoint"].append((dev_eui, str(setpoint_c)))
        return "topic"

    async def fake_sleep(seconds: int) -> None:
        calls["sleep"].append((str(seconds),))

    monkeypatch.setattr(inbound_test, "set_open_window_detection", fake_set_ow)
    monkeypatch.setattr(inbound_test, "send_setpoint", fake_send_setpoint)
    monkeypatch.setattr(inbound_test, "_sleep", fake_sleep)
    return calls


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_inbound_test_happy_path_non_interactive(
    session: AsyncSession,
    mock_downlinks_ok: dict[str, list[tuple[str, ...]]],
) -> None:
    """interactive=False, alle Schritte ok -> passed."""
    device_id = await _seed_device(session)
    await _add_reading(session, device_id, age_min=1)  # frischer Heartbeat
    result = await run_inbound_test(device_id, session, interactive=False)
    assert result.overall_status == "passed"
    assert result.failed_step is None
    statuses = [s.status for s in result.steps]
    assert statuses == ["ok"] * 6
    steps = [s.step for s in result.steps]
    assert steps == [
        STEP_RESEND_OW,
        STEP_HEARTBEAT,
        STEP_TEMP_PLAUSI,
        STEP_SETPOINT_25,
        STEP_SETPOINT_10,
        STEP_BACKPLATE,
    ]
    # Downlink-Calls: 1 OW-Resend + 2 Setpoints.
    assert len(mock_downlinks_ok["set_ow"]) == 1
    assert len(mock_downlinks_ok["send_setpoint"]) == 2
    # 2 Sleep-Calls (zwischen Setpoint und naechstem Schritt).
    assert mock_downlinks_ok["sleep"] == [("30",), ("30",)]


async def test_inbound_test_ow_resend_failure_continues(
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Schritt 0 wirft -> failed (non-blocking), andere Schritte laufen weiter."""
    calls: dict[str, list[tuple[str, ...]]] = {"send_setpoint": []}

    async def raise_ow(*args: object, **kwargs: object) -> str:
        raise RuntimeError("MQTT down")

    async def fake_send_setpoint(dev_eui: str, setpoint_c: int) -> str:
        calls["send_setpoint"].append((dev_eui, str(setpoint_c)))
        return "topic"

    async def no_sleep(seconds: int) -> None:
        return None

    monkeypatch.setattr(inbound_test, "set_open_window_detection", raise_ow)
    monkeypatch.setattr(inbound_test, "send_setpoint", fake_send_setpoint)
    monkeypatch.setattr(inbound_test, "_sleep", no_sleep)

    device_id = await _seed_device(session)
    await _add_reading(session, device_id, age_min=1)
    result = await run_inbound_test(device_id, session, interactive=False)
    # OW-Resend failed, aber andere Schritte ausgefuehrt.
    assert result.steps[0].step == STEP_RESEND_OW
    assert result.steps[0].status == "failed"
    assert "DOWNLINK_FAILED" in result.steps[0].detail
    # Heartbeat + Temp + Setpoints + Backplate alle ok.
    for step in result.steps[1:]:
        assert step.status == "ok"
    # overall=failed wegen Schritt 0.
    assert result.overall_status == "failed"
    assert result.failed_step == STEP_RESEND_OW
    # Setpoints wurden trotzdem gesendet.
    assert len(calls["send_setpoint"]) == 2


async def test_inbound_test_no_heartbeat_aborts(
    session: AsyncSession,
    mock_downlinks_ok: dict[str, list[tuple[str, ...]]],
) -> None:
    """Kein SensorReading -> heartbeat-failed, Schritte 2-5 nicht ausgefuehrt."""
    device_id = await _seed_device(session)
    # KEIN Reading.
    result = await run_inbound_test(device_id, session, interactive=False)
    assert result.overall_status == "failed"
    assert result.failed_step == STEP_HEARTBEAT
    # Nur Schritt 0 + 1 im result.steps.
    assert [s.step for s in result.steps] == [STEP_RESEND_OW, STEP_HEARTBEAT]
    assert result.steps[1].status == "failed"
    assert "Kein SensorReading" in result.steps[1].detail
    # Keine Setpoint-Downlinks (Schritte 3-4 nicht erreicht).
    assert mock_downlinks_ok["send_setpoint"] == []


async def test_inbound_test_temperature_out_of_range(
    session: AsyncSession,
    mock_downlinks_ok: dict[str, list[tuple[str, ...]]],
) -> None:
    """Temperatur 35 °C ausserhalb [15, 30] -> temp_plausi-failed, Abbruch."""
    device_id = await _seed_device(session)
    await _add_reading(session, device_id, age_min=1, temperature=Decimal("35.0"))
    result = await run_inbound_test(device_id, session, interactive=False)
    assert result.overall_status == "failed"
    assert result.failed_step == STEP_TEMP_PLAUSI
    assert [s.step for s in result.steps] == [STEP_RESEND_OW, STEP_HEARTBEAT, STEP_TEMP_PLAUSI]
    assert "35.0" in result.steps[2].detail
    # Setpoints nicht ausgefuehrt.
    assert mock_downlinks_ok["send_setpoint"] == []


async def test_inbound_test_setpoint_25_downlink_exception(
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """send_setpoint(25) wirft -> setpoint_25-failed, Abbruch vor Schritt 4."""

    async def fake_set_ow(*args: object, **kwargs: object) -> str:
        return "topic"

    async def raising_send_setpoint(dev_eui: str, setpoint_c: int) -> str:
        if setpoint_c == 25:
            raise RuntimeError("simulated MQTT failure on setpoint=25")
        return "topic"

    async def no_sleep(seconds: int) -> None:
        return None

    monkeypatch.setattr(inbound_test, "set_open_window_detection", fake_set_ow)
    monkeypatch.setattr(inbound_test, "send_setpoint", raising_send_setpoint)
    monkeypatch.setattr(inbound_test, "_sleep", no_sleep)

    device_id = await _seed_device(session)
    await _add_reading(session, device_id, age_min=1)
    result = await run_inbound_test(device_id, session, interactive=False)
    assert result.overall_status == "failed"
    assert result.failed_step == STEP_SETPOINT_25
    # Schritt 4 + 5 NICHT ausgefuehrt.
    steps = [s.step for s in result.steps]
    assert STEP_SETPOINT_10 not in steps
    assert STEP_BACKPLATE not in steps


async def test_inbound_test_backplate_false_fails(
    session: AsyncSession,
    mock_downlinks_ok: dict[str, list[tuple[str, ...]]],
) -> None:
    """Backplate=False -> backplate-failed, alle anderen Schritte ok."""
    device_id = await _seed_device(session)
    await _add_reading(session, device_id, age_min=1, attached_backplate=False)
    result = await run_inbound_test(device_id, session, interactive=False)
    assert result.overall_status == "failed"
    assert result.failed_step == STEP_BACKPLATE
    # Alle 6 Schritte im result.steps.
    assert len(result.steps) == 6
    # Backplate-Step ist failed mit klarem Detail.
    backplate_step = result.steps[-1]
    assert backplate_step.step == STEP_BACKPLATE
    assert backplate_step.status == "failed"
    assert "nicht auf Heizkoerper-Backplate" in backplate_step.detail


async def test_inbound_test_user_aborts_at_setpoint_25(
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mitarbeiter antwortet 'n' beim Setpoint-25-Prompt -> user_aborted,
    Schritte 4 + 5 nicht ausgefuehrt."""

    async def fake_set_ow(*args: object, **kwargs: object) -> str:
        return "topic"

    async def fake_send_setpoint(dev_eui: str, setpoint_c: int) -> str:
        return "topic"

    async def no_sleep(seconds: int) -> None:
        return None

    confirm_calls = [0]

    def fake_user_confirm(prompt: str) -> bool:
        confirm_calls[0] += 1
        return False  # Mitarbeiter antwortet 'n'

    monkeypatch.setattr(inbound_test, "set_open_window_detection", fake_set_ow)
    monkeypatch.setattr(inbound_test, "send_setpoint", fake_send_setpoint)
    monkeypatch.setattr(inbound_test, "_sleep", no_sleep)
    monkeypatch.setattr(inbound_test, "_user_confirm", fake_user_confirm)

    device_id = await _seed_device(session)
    await _add_reading(session, device_id, age_min=1)
    result = await run_inbound_test(device_id, session, interactive=True)
    assert result.overall_status == "user_aborted"
    assert result.failed_step == STEP_SETPOINT_25
    # Schritt 4 + 5 NICHT ausgefuehrt — Prompt wurde nur 1x gerufen.
    assert confirm_calls[0] == 1
    steps = [s.step for s in result.steps]
    assert STEP_SETPOINT_10 not in steps
    assert STEP_BACKPLATE not in steps


async def test_inbound_test_device_not_found_raises(
    session: AsyncSession,
) -> None:
    """Nicht-existierendes Device -> ValueError."""
    with pytest.raises(ValueError, match=r"Device id=999999 existiert nicht"):
        await run_inbound_test(999999, session, interactive=False)
