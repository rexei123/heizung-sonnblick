"""Vicki-Eingangstest gemaess RUNBOOK §10h.1 (Sprint 13a T5).

5 Schritte pro Vicki am Office-Laptop-Tisch (plus Schritt 0 idempotenter
OW-Resend, T4-Variante-A-Mitigation):

0. ``resend_open_window``: ``set_open_window_detection`` (AE-48) erneut
   senden — billig, idempotent, schliesst den Pairing-Service-Vergessen-
   Pfad. Bei Exception bleibt der Test laufend (Vicki koennte trotzdem
   heartbeaten).
1. ``heartbeat``: letzter Uplink innerhalb 5 Min (Defensive: kein Reading
   = nicht im Funknetz, manuelle Diagnose noetig).
2. ``temp_plausi``: letzte Reading-Temperatur in [15, 30] °C (Raumtemp-
   Sanity, nicht Plausi-Filter aus AE-53 [-20, 60]).
3. ``setpoint_25``: ``send_setpoint(25)`` + 30 Sek Wartezeit + optional
   interaktiver Mitarbeiter-Prompt "Ventil hoerbar geoeffnet?".
4. ``setpoint_10``: analog mit 10 °C.
5. ``backplate``: ``attached_backplate=True`` im letzten Reading
   (Hardware ist auf Vicki-Wandhalterung angeflanscht).

``interactive=True`` (Default fuer CLI): User-Prompts via ``input()``.
``interactive=False`` (Tests + Smoke): Prompts werden uebersprungen,
Setpoint-Schritte enden mit ``status="ok"`` solange der Downlink-Call
nicht wirft. Akustik-Verify (Ventil-Bewegung) ist Mitarbeiter-Handwerk,
nicht Skript-Aufgabe.

Setpoint-Typ: ``send_setpoint(dev_eui: str, setpoint_c: int)`` — Vicki-
Hardware-Limit ist 1.0-°C-Schritt-only (AE-32 nach Sprint-9-Spike,
vorher 0.5 °C geplant). Daher ``int`` statt ``Decimal`` fuer die
Setpoint-Test-Konstanten 25 + 10 °C — Brief-Skizze
``Decimal("25.0")`` war historische Annahme, ist seit AE-32 obsolet.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Literal

from sqlalchemy import select

from heizung.models.device import Device
from heizung.models.sensor_reading import SensorReading
from heizung.services.downlink_adapter import (
    send_setpoint,
    set_open_window_detection,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

StepName = Literal[
    "resend_open_window",
    "heartbeat",
    "temp_plausi",
    "setpoint_25",
    "setpoint_10",
    "backplate",
]
StepStatus = Literal["ok", "skipped", "failed", "user_aborted"]
OverallStatus = Literal["passed", "failed", "user_aborted"]

# Schritt-Konstanten — aus RUNBOOK §10h.1 abgeleitet, plus Schritt 0
# (T4-Variante-A-Mitigation: idempotenter OW-Resend bevor wir vertrauen
# dass der Pairing-Service den ersten Downlink wirklich abgesetzt hat).
STEP_RESEND_OW: StepName = "resend_open_window"
STEP_HEARTBEAT: StepName = "heartbeat"
STEP_TEMP_PLAUSI: StepName = "temp_plausi"
STEP_SETPOINT_25: StepName = "setpoint_25"
STEP_SETPOINT_10: StepName = "setpoint_10"
STEP_BACKPLATE: StepName = "backplate"

# Schwellenwerte.
HEARTBEAT_MAX_AGE_MIN = 5
TEMP_PLAUSI_MIN_C = Decimal("15.0")
TEMP_PLAUSI_MAX_C = Decimal("30.0")
SETPOINT_TEST_HIGH_C = 25
SETPOINT_TEST_LOW_C = 10
SETPOINT_WAIT_SECONDS = 30

# OW-Resend nutzt dieselben Defaults wie Pairing-Service T4.
OW_DEFAULT_ENABLED: bool = True
OW_DEFAULT_DURATION_MIN: int = 10
OW_DEFAULT_DELTA_C: Decimal = Decimal("1.5")


@dataclass(frozen=True, slots=True)
class TestStepResult:
    """Ergebnis eines einzelnen Test-Schritts."""

    step: StepName
    status: StepStatus
    detail: str


@dataclass(slots=True)
class TestResult:
    """Gesamtergebnis des Eingangstests.

    ``overall_status``:
    - ``passed``: alle Schritte ``ok``.
    - ``failed``: mindestens ein Schritt ``failed`` (resend_open_window
      ist NON-blocking, aber zaehlt fuer overall_status).
    - ``user_aborted``: Mitarbeiter hat einen Setpoint-Prompt verneint.
    """

    device_id: int
    steps: list[TestStepResult] = field(default_factory=list)
    overall_status: OverallStatus = "passed"
    failed_step: StepName | None = None


async def _sleep(seconds: int) -> None:
    """Wrapper fuer ``asyncio.sleep`` — ermoeglicht Test-Mocking ohne
    den globalen ``asyncio.sleep`` zu patchen."""
    await asyncio.sleep(seconds)


def _user_confirm(prompt: str) -> bool:
    """``input()``-Wrapper fuer Mitarbeiter-Prompts. Akzeptiert 'j' / 'J'
    als Yes; alles andere als No. Eigene Funktion damit Tests sie via
    ``monkeypatch`` ersetzen koennen ohne den ``builtins.input`` global
    zu patchen."""
    answer = input(prompt)
    return answer.strip().lower() == "j"


async def _get_latest_reading(session: AsyncSession, device_id: int) -> SensorReading | None:
    """Letztes SensorReading fuer ein Device (Composite-PK-Lookup ueber
    ``(device_id, time DESC)``-Index)."""
    stmt = (
        select(SensorReading)
        .where(SensorReading.device_id == device_id)
        .order_by(SensorReading.time.desc())
        .limit(1)
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def _step_resend_ow(dev_eui: str) -> TestStepResult:
    """Schritt 0: idempotenter Open-Window-Detection-Resend (AE-48).

    NON-blocking — bei Exception laeuft der Test weiter (Vicki koennte
    trotzdem heartbeaten und der Backplate-Check funktionieren).
    """
    try:
        await set_open_window_detection(
            dev_eui,
            enabled=OW_DEFAULT_ENABLED,
            duration_min=OW_DEFAULT_DURATION_MIN,
            delta_c=OW_DEFAULT_DELTA_C,
        )
    except Exception as exc:  # noqa: BLE001 — Soft-Fail, Test laeuft weiter
        logger.warning("inbound_test: OW-Resend failed dev_eui=%s exc=%s", dev_eui, exc)
        return TestStepResult(
            step=STEP_RESEND_OW,
            status="failed",
            detail=f"DOWNLINK_FAILED: {type(exc).__name__}: {exc}",
        )
    return TestStepResult(
        step=STEP_RESEND_OW,
        status="ok",
        detail="OW-Detection erneut aktiviert (idempotent).",
    )


def _step_heartbeat(latest: SensorReading | None, now: datetime) -> TestStepResult:
    """Schritt 1: letzter Uplink innerhalb HEARTBEAT_MAX_AGE_MIN Min."""
    if latest is None:
        return TestStepResult(
            step=STEP_HEARTBEAT,
            status="failed",
            detail="Kein SensorReading in der DB — Vicki hat seit Pairing nie gesendet.",
        )
    age = now - latest.time
    if age > timedelta(minutes=HEARTBEAT_MAX_AGE_MIN):
        return TestStepResult(
            step=STEP_HEARTBEAT,
            status="failed",
            detail=(
                f"Letzter Uplink {age.total_seconds() / 60:.1f} Min alt "
                f"(Schwelle {HEARTBEAT_MAX_AGE_MIN} Min)."
            ),
        )
    return TestStepResult(
        step=STEP_HEARTBEAT,
        status="ok",
        detail=f"Letzter Uplink {age.total_seconds():.0f} Sek alt.",
    )


def _step_temp_plausi(latest: SensorReading) -> TestStepResult:
    """Schritt 2: Temperatur in [15, 30] °C."""
    temp = latest.temperature
    if temp is None:
        return TestStepResult(
            step=STEP_TEMP_PLAUSI,
            status="failed",
            detail="Letztes Reading hat keine Temperatur (Battery-only-Frame?).",
        )
    if temp < TEMP_PLAUSI_MIN_C or temp > TEMP_PLAUSI_MAX_C:
        return TestStepResult(
            step=STEP_TEMP_PLAUSI,
            status="failed",
            detail=(
                f"Temperatur {temp} °C ausserhalb [{TEMP_PLAUSI_MIN_C}, {TEMP_PLAUSI_MAX_C}] °C."
            ),
        )
    return TestStepResult(
        step=STEP_TEMP_PLAUSI,
        status="ok",
        detail=f"Temperatur {temp} °C plausibel.",
    )


async def _step_setpoint(
    dev_eui: str,
    setpoint_c: int,
    step_name: StepName,
    *,
    interactive: bool,
    prompt_action: str,
) -> TestStepResult:
    """Schritt 3+4: Setpoint senden, warten, optional Mitarbeiter-Prompt."""
    try:
        await send_setpoint(dev_eui, setpoint_c)
    except Exception as exc:  # noqa: BLE001 — Downlink-Failure ist test-failure
        return TestStepResult(
            step=step_name,
            status="failed",
            detail=f"DOWNLINK_FAILED: {type(exc).__name__}: {exc}",
        )
    await _sleep(SETPOINT_WAIT_SECONDS)
    if not interactive:
        return TestStepResult(
            step=step_name,
            status="ok",
            detail=(
                f"Setpoint {setpoint_c} °C gesendet, "
                f"{SETPOINT_WAIT_SECONDS} Sek gewartet. Skipped user prompt "
                "(interactive=False)."
            ),
        )
    if _user_confirm(f"Hat sich das Ventil {prompt_action}? [j/n]: "):
        return TestStepResult(
            step=step_name,
            status="ok",
            detail=f"Setpoint {setpoint_c} °C, Mitarbeiter bestaetigt: Ventil {prompt_action}.",
        )
    return TestStepResult(
        step=step_name,
        status="user_aborted",
        detail=(
            f"Setpoint {setpoint_c} °C: Mitarbeiter meldet Ventil hat sich "
            f"NICHT {prompt_action}. Manuelle Hardware-Diagnose noetig."
        ),
    )


def _step_backplate(latest: SensorReading) -> TestStepResult:
    """Schritt 5: Backplate-Bit muss True sein (Vicki montiert)."""
    if latest.attached_backplate is None:
        return TestStepResult(
            step=STEP_BACKPLATE,
            status="failed",
            detail=(
                "Letztes Reading hat kein attached_backplate-Feld "
                "(alter Codec FW < 4.1 oder Recovery-Daten)."
            ),
        )
    if latest.attached_backplate is False:
        return TestStepResult(
            step=STEP_BACKPLATE,
            status="failed",
            detail="Vicki nicht auf Heizkoerper-Backplate montiert (attached_backplate=False).",
        )
    return TestStepResult(
        step=STEP_BACKPLATE,
        status="ok",
        detail="Vicki auf Backplate montiert (attached_backplate=True).",
    )


def _finalize(result: TestResult) -> None:
    """Setzt ``overall_status`` + ``failed_step`` aus den Step-Results.

    Priorisierung:
    1. Erster ``user_aborted`` -> overall=user_aborted, failed_step=dieser Schritt.
    2. Erster ``failed`` -> overall=failed, failed_step=dieser Schritt.
    3. Alle ok -> overall=passed.
    """
    for step_result in result.steps:
        if step_result.status == "user_aborted":
            result.overall_status = "user_aborted"
            result.failed_step = step_result.step
            return
    for step_result in result.steps:
        if step_result.status == "failed":
            result.overall_status = "failed"
            result.failed_step = step_result.step
            return
    result.overall_status = "passed"
    result.failed_step = None


async def run_inbound_test(
    device_id: int,
    session: AsyncSession,
    *,
    interactive: bool = True,
) -> TestResult:
    """Fuehrt den 6-Schritt-Eingangstest aus (RUNBOOK §10h.1 + Schritt 0).

    :param device_id: Device-PK aus heizung-DB (nach Pairing-Service-Run).
    :param session: ``AsyncSession`` (read-only, kein commit).
    :param interactive: ``True`` (Default) zeigt User-Prompts bei
        Setpoint-Schritten. ``False`` ueberspringt Prompts — fuer
        Tests + Smoke-Runs.
    :raises ValueError: Device nicht in DB.
    """
    device = await session.get(Device, device_id)
    if device is None:
        raise ValueError(f"Device id={device_id} existiert nicht.")

    result = TestResult(device_id=device_id)
    now = datetime.now(tz=UTC)

    # Schritt 0: idempotenter OW-Resend (non-blocking).
    step0 = await _step_resend_ow(device.dev_eui)
    result.steps.append(step0)

    # Schritt 1: Heartbeat.
    latest = await _get_latest_reading(session, device_id)
    step1 = _step_heartbeat(latest, now)
    result.steps.append(step1)
    if step1.status == "failed":
        _finalize(result)
        return result

    # Wenn step1 ok, ist latest garantiert nicht None.
    assert latest is not None

    # Schritt 2: Temperatur-Plausi.
    step2 = _step_temp_plausi(latest)
    result.steps.append(step2)
    if step2.status == "failed":
        _finalize(result)
        return result

    # Schritt 3: Setpoint 25 °C.
    step3 = await _step_setpoint(
        device.dev_eui,
        SETPOINT_TEST_HIGH_C,
        STEP_SETPOINT_25,
        interactive=interactive,
        prompt_action="geoeffnet",
    )
    result.steps.append(step3)
    if step3.status in ("failed", "user_aborted"):
        _finalize(result)
        return result

    # Schritt 4: Setpoint 10 °C.
    step4 = await _step_setpoint(
        device.dev_eui,
        SETPOINT_TEST_LOW_C,
        STEP_SETPOINT_10,
        interactive=interactive,
        prompt_action="geschlossen",
    )
    result.steps.append(step4)
    if step4.status in ("failed", "user_aborted"):
        _finalize(result)
        return result

    # Schritt 5: Backplate-Bit.
    step5 = _step_backplate(latest)
    result.steps.append(step5)

    _finalize(result)
    return result


def format_test_result(result: TestResult) -> str:
    """Mensch-lesbare Multi-Line-Konsolen-Ausgabe fuer CLI-T6.

    Pro Schritt ein Symbol + Step-Name + Detail. Footer mit Overall-
    Status und failed_step.
    """
    symbols = {"ok": "[OK]", "skipped": "[-]", "failed": "[FAIL]", "user_aborted": "[ABORT]"}
    lines = [f"Eingangstest device_id={result.device_id}:"]
    for step_result in result.steps:
        sym = symbols.get(step_result.status, "[?]")
        lines.append(f"  {sym} {step_result.step}: {step_result.detail}")
    lines.append(
        f"Overall: {result.overall_status}"
        + (f" (failed_step={result.failed_step})" if result.failed_step else "")
    )
    return "\n".join(lines)
