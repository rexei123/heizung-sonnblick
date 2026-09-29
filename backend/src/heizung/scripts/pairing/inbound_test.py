"""Vicki-Eingangstest gemaess RUNBOOK §10h.4 (Sprint 13a T5).

5 Schritte pro Vicki am Office-Laptop-Tisch:

1. ``heartbeat``: es kommt ein Uplink innerhalb von
   ``HEARTBEAT_MAX_AGE_MIN`` Minuten — **wartend**, nicht sofort urteilend
   (Sprint 19 / T4).
2. ``temp_plausi``: letzte Reading-Temperatur in [15, 30] °C (Raumtemp-
   Sanity, nicht Plausi-Filter aus AE-53 [-20, 60]).
3. ``setpoint_25``: ``send_setpoint(25)`` + 30 Sek Wartezeit + optional
   interaktiver Mitarbeiter-Prompt "Ventil hoerbar geoeffnet?".
4. ``setpoint_10``: analog mit 10 °C.
5. ``backplate``: ``attached_backplate=True`` im **frisch nachgelesenen**
   Reading (Hardware ist auf Vicki-Wandhalterung angeflanscht).
   ``skip_backplate=True`` laesst den Schritt aus — am Tisch ist ``false``
   der erwartete Zustand (RUNBOOK §10h.4), dort ist die Pruefung
   sinnlos.

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
from heizung.services.downlink_adapter import send_setpoint

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

StepName = Literal[
    "heartbeat",
    "temp_plausi",
    "setpoint_25",
    "setpoint_10",
    "backplate",
]
StepStatus = Literal["ok", "skipped", "failed", "user_aborted"]
OverallStatus = Literal["passed", "failed", "user_aborted"]

# Schritt-Konstanten — aus RUNBOOK §10h.4 abgeleitet.
STEP_HEARTBEAT: StepName = "heartbeat"
STEP_TEMP_PLAUSI: StepName = "temp_plausi"
STEP_SETPOINT_25: StepName = "setpoint_25"
STEP_SETPOINT_10: StepName = "setpoint_10"
STEP_BACKPLATE: StepName = "backplate"

# Schwellenwerte.
# Sprint 19 (T4): 15 statt 5 Minuten, und es wird **gewartet**. Das
# Keepalive-Intervall der Vicki liegt bei rund 10 Minuten; eine Schwelle von
# 5 Minuten trifft damit im Mittel jedes zweite gesunde Geraet. Die Pruefung
# war ein Muenzwurf mit dem Anschein eines Kriteriums.
HEARTBEAT_MAX_AGE_MIN = 15
HEARTBEAT_POLL_INTERVAL_S = 30
TEMP_PLAUSI_MIN_C = Decimal("15.0")
TEMP_PLAUSI_MAX_C = Decimal("30.0")
# Bleibt bei 25, waehrend der Batch-Pfad auf 28 gegangen ist
# (``batch_inbound_test.SETPOINT_HIGH_C``, Sprint 19 / T2). Kein Widerspruch:
# hier urteilt das Auge des Mitarbeiters, nicht eine Openness-Schwelle — und
# die 28 sind genau fuer die Schwelle belegt. Dieser Pfad wird in Sprint 19
# T11 auf den Batch-Mechanismus umgeleitet; bis dahin ist die verbindliche
# Zahl die im Batch.
SETPOINT_TEST_HIGH_C = 25
SETPOINT_TEST_LOW_C = 10
SETPOINT_WAIT_SECONDS = 30


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
    - ``failed``: mindestens ein Schritt ``failed``.
    - ``user_aborted``: Mitarbeiter hat einen Setpoint-Prompt verneint.
    """

    device_id: int
    steps: list[TestStepResult] = field(default_factory=list)
    overall_status: OverallStatus = "passed"
    failed_step: StepName | None = None


def _now() -> datetime:
    """Testbarer Zeit-Einhaengepunkt, analog ``_sleep``."""
    return datetime.now(tz=UTC)


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


async def _await_fresh_reading(session: AsyncSession, device_id: int) -> SensorReading | None:
    """Wartet bis ``HEARTBEAT_MAX_AGE_MIN`` auf einen aktuellen Uplink.

    Sprint 19 (T4). Vorher urteilte Schritt 1 sofort: war das juengste
    Reading aelter als 5 Minuten, galt das Geraet als nicht im Funknetz. Bei
    einem Keepalive von 10 Minuten ist das kein Kriterium, sondern ein
    Muenzwurf — rund die Haelfte der gesunden Geraete fiel zufaellig durch.

    Gibt das juengste bekannte Reading zurueck, sobald es frisch genug ist,
    sonst nach Ablauf des Fensters den letzten Stand (auch ``None``). Das
    Urteil faellt weiterhin ``_step_heartbeat``.
    """
    limit = timedelta(minutes=HEARTBEAT_MAX_AGE_MIN)
    deadline = _now() + limit
    latest = await _get_latest_reading(session, device_id)
    while True:
        if latest is not None and _now() - latest.time <= limit:
            return latest
        if _now() >= deadline:
            return latest
        await _sleep(HEARTBEAT_POLL_INTERVAL_S)
        latest = await _get_latest_reading(session, device_id)


def _step_heartbeat(latest: SensorReading | None, now: datetime) -> TestStepResult:
    """Schritt 1: es kam ein Uplink innerhalb HEARTBEAT_MAX_AGE_MIN Min."""
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
    3. Alle ok (oder ``skipped``) -> overall=passed. Ein bewusst
       uebersprungener Schritt ist kein Mangel.
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
    skip_backplate: bool = False,
) -> TestResult:
    """Fuehrt den 6-Schritt-Eingangstest aus (RUNBOOK §10h.4 + Schritt 0).

    :param device_id: Device-PK aus heizung-DB (nach Pairing-Service-Run).
    :param session: ``AsyncSession`` (read-only, kein commit).
    :param interactive: ``True`` (Default) zeigt User-Prompts bei
        Setpoint-Schritten. ``False`` ueberspringt Prompts — fuer
        Tests + Smoke-Runs.
    :param skip_backplate: laesst Schritt 5 aus (Sprint 17 / C4). Am Tisch
        ist ``attached_backplate=false`` der erwartete Zustand (RUNBOOK
        §10h.4) — den Schritt dort zu pruefen hiesse, jedes Geraet
        durchfallen zu lassen. Er gehoert nach die Montage.
    :raises ValueError: Device nicht in DB.
    """
    device = await session.get(Device, device_id)
    if device is None:
        raise ValueError(f"Device id={device_id} existiert nicht.")

    result = TestResult(device_id=device_id)

    # Schritt 1: Heartbeat — wartend (Sprint 19 / T4).
    latest = await _await_fresh_reading(session, device_id)
    step1 = _step_heartbeat(latest, _now())
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
    #
    # Sprint 17 (C4): liest bewusst NEU aus der DB. Bis Sprint 16 wertete
    # dieser Schritt ``latest`` aus Schritt 1 aus — also den Stand VOR den
    # beiden Setpoint-Downlinks und den 60 Sekunden Wartezeit. Der Test
    # behauptete damit eine Aussage ueber "jetzt", belegte aber eine ueber
    # "vor einer Minute". Zwischen beiden liegen bei einem Vicki mit
    # 15-Minuten-Periodik durchaus neue Frames.
    if skip_backplate:
        result.steps.append(
            TestStepResult(
                step=STEP_BACKPLATE,
                status="skipped",
                detail="Uebersprungen (--skip-backplate): am Tisch ist false erwartet.",
            )
        )
        _finalize(result)
        return result

    fresh = await _get_latest_reading(session, device_id)
    if fresh is None:
        result.steps.append(
            TestStepResult(
                step=STEP_BACKPLATE,
                status="failed",
                detail="Kein Reading mehr auffindbar — Backplate nicht bewertbar.",
            )
        )
        _finalize(result)
        return result

    step5 = _step_backplate(fresh)
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
