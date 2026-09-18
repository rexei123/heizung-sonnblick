"""Batch-Eingangstest fuer den Montage-Vorlauf (Sprint 17 / C4, E2).

Der Einzeltest aus Sprint 13a (``inbound_test``) braucht pro Geraet zwei
Zwangswartezeiten und zwei Mitarbeiter-Rueckfragen. Bei 104 Geraeten sind
das rund zwei Stunden reine Maschinenzeit und 208 Tastendruecke. Dieses
Modul prueft **alle Pool-Geraete gleichzeitig**: es sendet erst an alle,
wartet dann einmal gemeinsam.

Ablauf
------

1. **FW-Abfrage** (0x04) an alle Geraete. Die Antwort kommt asynchron mit
   einem der naechsten Uplinks; der MQTT-Subscriber schreibt sie nach
   ``device.firmware_version``. Wir fragen hier zu Beginn, lesen am Ende —
   das Warte-Fenster des Readback-Tests deckt die Antwort mit ab.
2. **Sollwert 25 °C** an alle. Sendezeitpunkt pro Geraet gemerkt.
3. **Gemeinsames Warten** auf einen Uplink *nach* dem Sendezeitpunkt, der
   25 °C zurueckmeldet.
4. **Sollwert 10 °C** an alle, die Schritt 3 bestanden haben.
5. **Gemeinsames Warten** analog.
6. **Bewertung**: Readback in beiden Schritten korrekt, und — sofern nicht
   abgeschaltet — Ventilstellung bei 25 °C hoeher als bei 10 °C.

Class A: ein Downlink verlaesst die Warteschlange erst beim naechsten
Uplink des Geraets. Bis der neue Sollwert zurueckgemeldet wird, koennen
zwei Periodic-Intervalle vergehen (Vicki-Default ~15 Min). Deshalb ist das
Zeitfenster ein freier Parameter und nicht fest verdrahtet — Geraet 101
hatte am 17./18.09.2026 Uplink-Luecken von 1 bis 4 Stunden. Ein zu kurzes
Fenster wuerde 103 gesunde Geraete als TIMEOUT abstempeln.

FAIL ist nicht gleich TIMEOUT
-----------------------------

- ``TIMEOUT``: im Fenster kam ueberhaupt kein frischer Uplink. Das ist ein
  Funk-, Duty-Cycle- oder Batterie-Befund — **kein** Hardware-Verdacht.
  Das Geraet kann tadellos sein und nur schlecht stehen.
- ``FAIL``: es kam ein frischer Uplink, aber der Sollwert stimmt nicht oder
  das Ventil hat sich nicht bewegt. **Das** ist der Hardware-Verdacht.

Nur ``FAIL`` gehoert zurueck in den Karton. Beide setzen den Exit-Code auf
1, damit ein Skript-Aufruf nicht stillschweigend weiterlaeuft.

Firmware ist eine eigene Spalte, kein Fehlerkriterium
-----------------------------------------------------

Eine fehlende FW-Antwort macht ein Geraet nicht defekt — sie schliesst es
nur vom Open-Window-Rollout aus, weil
``activate_open_window_detection`` ohne bekannte Version nicht beschickt.
Das Inventar muss vor der Montage vorliegen, nicht erst beim Rollout: die
Firmware der 100 neuen Geraete ist unbekannt.

Was der Batch **nicht** prueft
------------------------------

Den Backplate-Schritt. Am Tisch ist ``attached_backplate=false`` der
erwartete Zustand (RUNBOOK §10h.4) — ihn dort zu pruefen hiesse, jedes
Geraet durchfallen zu lassen. Er gehoert nach der Montage.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Literal

from sqlalchemy import select

from heizung.models.device import Device
from heizung.models.sensor_reading import SensorReading
from heizung.scripts.pairing.firmware import classify_firmware, min_fw_text
from heizung.services.business_audit_service import record_business_action
from heizung.services.downlink_adapter import query_firmware_version, send_setpoint

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

SETPOINT_HIGH_C = 25
SETPOINT_LOW_C = 10

# Zwei verpasste Periodic-Reports (Default ~15 Min) plus Reserve fuer die
# Class-A-Latenz. Bewusst grosszuegig: ein zu kurzes Fenster erzeugt
# Falsch-TIMEOUTs, ein zu langes kostet nur Wartezeit.
DEFAULT_TIMEOUT_S = 2700
DEFAULT_POLL_INTERVAL_S = 15

# Pause zwischen den Downlinks einer Sende-Runde. Verteilt die Last auf dem
# Gateway, statt 104 Publishes in einer Sekunde abzusetzen (S4).
SEND_SPACING_S = 0.5

StepOutcome = Literal["ok", "timeout", "wrong_readback", "downlink_failed", "skipped"]
DeviceStatus = Literal["pass", "fail", "timeout"]

AUDIT_ACTION = "DEVICE_INBOUND_TEST"


@dataclass(frozen=True, slots=True)
class StepResult:
    """Ergebnis eines Sollwert-Schritts fuer ein Geraet."""

    target_c: int
    outcome: StepOutcome
    observed_setpoint: Decimal | None = None
    valve_position: int | None = None
    reading_at: datetime | None = None
    detail: str = ""


@dataclass(frozen=True, slots=True)
class DeviceResult:
    """Gesamtergebnis eines Geraets."""

    device_id: int
    dev_eui: str
    hardware_nummer: str
    status: DeviceStatus
    reason: str
    firmware_version: str | None
    high: StepResult | None = None
    low: StepResult | None = None

    @property
    def firmware_text(self) -> str:
        return self.firmware_version or "keine Antwort"


@dataclass
class BatchReport:
    """Sammelergebnis. ``exit_code`` ist 1, sobald ein Geraet nicht besteht."""

    results: list[DeviceResult] = field(default_factory=list)

    @property
    def passed(self) -> list[DeviceResult]:
        return [r for r in self.results if r.status == "pass"]

    @property
    def failed(self) -> list[DeviceResult]:
        return [r for r in self.results if r.status == "fail"]

    @property
    def timed_out(self) -> list[DeviceResult]:
        return [r for r in self.results if r.status == "timeout"]

    @property
    def exit_code(self) -> int:
        return 1 if self.failed or self.timed_out else 0

    def by_firmware(self) -> dict[str, list[DeviceResult]]:
        """Gruppiert nach FW-Klasse — die drei Zeilen der Zusammenfassung."""
        groups: dict[str, list[DeviceResult]] = {
            "ow_faehig": [],
            "zu_alt": [],
            "keine_antwort": [],
        }
        for r in self.results:
            groups[classify_firmware(r.firmware_version)].append(r)
        return groups


# ---------------------------------------------------------------------------
# Test-Einhaengepunkte: Tests ersetzen diese Namen per monkeypatch, analog
# ``inbound_test._sleep`` (Sprint 13a T5).
# ---------------------------------------------------------------------------


async def _sleep(seconds: float) -> None:
    await asyncio.sleep(seconds)


def _now() -> datetime:
    return datetime.now(tz=UTC)


# ---------------------------------------------------------------------------
# Bausteine
# ---------------------------------------------------------------------------


async def _latest_readings(
    session: AsyncSession, device_ids: Sequence[int]
) -> dict[int, SensorReading]:
    """Juengstes Reading je Geraet in EINER Abfrage.

    ``DISTINCT ON (device_id)`` ueber ``ix_sensor_reading_device_time``.
    Ein Roundtrip pro Warte-Runde fuer alle Geraete — nicht einer je
    Geraet, sonst waeren es bei 104 Geraeten und 15-s-Takt ueber 7000
    Abfragen pro Stunde.
    """
    if not device_ids:
        return {}
    stmt = (
        select(SensorReading)
        .where(SensorReading.device_id.in_(list(device_ids)))
        .order_by(SensorReading.device_id, SensorReading.time.desc())
        .distinct(SensorReading.device_id)
    )
    rows = (await session.execute(stmt)).scalars().all()
    return {r.device_id: r for r in rows}


async def _send_round(
    devices: Sequence[Device], target_c: int
) -> tuple[dict[int, datetime], dict[int, str]]:
    """Sendet einen Sollwert an alle Geraete. Returns (Sendezeit, Fehler)."""
    sent_at: dict[int, datetime] = {}
    failures: dict[int, str] = {}
    for dev in devices:
        try:
            await send_setpoint(dev.dev_eui, target_c)
        except Exception as exc:  # noqa: BLE001 — ein Geraet stoppt nicht die anderen
            failures[dev.id] = f"{type(exc).__name__}: {exc}"
            logger.warning(
                "batch: Downlink %s °C fehlgeschlagen dev_eui=%s exc=%s",
                target_c,
                dev.dev_eui,
                exc,
            )
            continue
        sent_at[dev.id] = _now()
        await _sleep(SEND_SPACING_S)
    return sent_at, failures


async def _await_readbacks(
    session: AsyncSession,
    sent_at: dict[int, datetime],
    target_c: int,
    *,
    timeout_s: int,
    poll_interval_s: int,
) -> dict[int, StepResult]:
    """Wartet gemeinsam auf den Readback aller Geraete.

    Ein frischer Uplink mit dem **alten** Sollwert ist noch kein Fehler —
    die Vicki kann einen Periodic-Report abgesetzt haben, bevor sie den
    Downlink verarbeitet hat. Wir merken ihn uns und warten weiter. Erst am
    Ende des Fensters wird entschieden:

    - nie ein frischer Uplink  -> ``timeout``
    - frische Uplinks, aber nie der Zielwert -> ``wrong_readback``
    """
    pending = dict(sent_at)
    results: dict[int, StepResult] = {}
    saw_fresh: dict[int, SensorReading] = {}
    deadline = _now().timestamp() + timeout_s

    while pending:
        await _sleep(poll_interval_s)
        latest = await _latest_readings(session, list(pending))
        for device_id in list(pending):
            reading = latest.get(device_id)
            if reading is None or reading.time <= pending[device_id]:
                continue
            saw_fresh[device_id] = reading
            if reading.setpoint is not None and int(reading.setpoint) == target_c:
                results[device_id] = StepResult(
                    target_c=target_c,
                    outcome="ok",
                    observed_setpoint=reading.setpoint,
                    valve_position=reading.valve_position,
                    reading_at=reading.time,
                    detail=f"Readback {target_c} °C bestaetigt.",
                )
                del pending[device_id]
        if _now().timestamp() >= deadline:
            break

    for device_id in pending:
        fresh = saw_fresh.get(device_id)
        if fresh is None:
            results[device_id] = StepResult(
                target_c=target_c,
                outcome="timeout",
                detail=(
                    f"Kein Uplink innerhalb von {timeout_s} s. Funk, Duty-Cycle "
                    "oder Batterie — kein Hardware-Verdacht."
                ),
            )
        else:
            results[device_id] = StepResult(
                target_c=target_c,
                outcome="wrong_readback",
                observed_setpoint=fresh.setpoint,
                valve_position=fresh.valve_position,
                reading_at=fresh.time,
                detail=(f"Uplink kam, meldet aber {fresh.setpoint} statt {target_c} °C."),
            )
    return results


def _evaluate(
    dev: Device,
    high: StepResult | None,
    low: StepResult | None,
    firmware: str | None,
    *,
    valve_check: bool,
) -> DeviceResult:
    """Fasst beide Schritte zu einem Geraete-Urteil zusammen."""
    hardware_nummer = dev.label or dev.dev_eui

    def result(status: DeviceStatus, reason: str) -> DeviceResult:
        return DeviceResult(
            device_id=dev.id,
            dev_eui=dev.dev_eui,
            hardware_nummer=hardware_nummer,
            status=status,
            reason=reason,
            firmware_version=firmware,
            high=high,
            low=low,
        )

    for step in (high, low):
        if step is None:
            continue
        if step.outcome == "timeout":
            return result("timeout", f"{step.target_c} °C: {step.detail}")
        if step.outcome == "downlink_failed":
            return result("fail", f"{step.target_c} °C: Downlink fehlgeschlagen. {step.detail}")
        if step.outcome == "wrong_readback":
            return result("fail", f"{step.target_c} °C: {step.detail}")

    if high is None or low is None or high.outcome != "ok" or low.outcome != "ok":
        return result("fail", "Unvollstaendiger Ablauf.")

    if valve_check:
        if high.valve_position is None or low.valve_position is None:
            # Kein FAIL: ohne Ventildaten ist das Kriterium nicht pruefbar,
            # nicht verletzt. Der Readback allein hat bestanden.
            return result(
                "pass",
                "Readback beidseitig korrekt. Ventilkriterium nicht pruefbar "
                "(keine Ventilstellung im Reading).",
            )
        if high.valve_position <= low.valve_position:
            return result(
                "fail",
                f"Ventil unbewegt: {high.valve_position} % bei 25 °C ist nicht "
                f"hoeher als {low.valve_position} % bei 10 °C.",
            )
        return result(
            "pass",
            f"Readback beidseitig korrekt, Ventil {low.valve_position} % -> "
            f"{high.valve_position} %.",
        )

    return result("pass", "Readback beidseitig korrekt (Ventilkriterium abgeschaltet).")


async def _persist(
    session: AsyncSession, results: Sequence[DeviceResult], *, user_id: int | None
) -> None:
    """Schreibt je Geraet einen ``DEVICE_INBOUND_TEST``-Eintrag.

    ``business_audit`` statt ``event_log``: letzteres hat ``room_id`` als
    NOT-NULL-Teil des Primaerschluessels, und ein Pool-Geraet hat keinen
    Raum. ``business_audit`` traegt ``target_id`` nullable und ``new_value``
    als JSONB — keine Migration noetig.
    """
    for r in results:
        payload: dict[str, Any] = {
            "dev_eui": r.dev_eui,
            "hardware_nummer": r.hardware_nummer,
            "status": r.status,
            "reason": r.reason,
            "firmware_version": r.firmware_version,
            "firmware_class": classify_firmware(r.firmware_version),
        }
        for name, step in (("setpoint_25", r.high), ("setpoint_10", r.low)):
            if step is None:
                continue
            payload[name] = {
                "outcome": step.outcome,
                "observed_setpoint": step.observed_setpoint,
                "valve_position": step.valve_position,
                "reading_at": step.reading_at,
            }
        await record_business_action(
            session,
            user_id=user_id,
            action=AUDIT_ACTION,
            target_type="device",
            target_id=r.device_id,
            old_value=None,
            new_value=payload,
        )


# ---------------------------------------------------------------------------
# Einstieg
# ---------------------------------------------------------------------------


async def run_batch_inbound_test(
    session: AsyncSession,
    devices: Sequence[Device],
    *,
    timeout_s: int = DEFAULT_TIMEOUT_S,
    poll_interval_s: int = DEFAULT_POLL_INTERVAL_S,
    valve_check: bool = True,
    user_id: int | None = None,
) -> BatchReport:
    """Fuehrt den Batch-Eingangstest aus. Caller committet.

    :param devices: die zu pruefenden Geraete (typischerweise der Pool).
    :param timeout_s: Wartefenster je Sollwert-Schritt.
    :param poll_interval_s: Abstand zwischen zwei DB-Abfragen.
    :param valve_check: Ventilkriterium mitpruefen.
    :param user_id: fuer den Audit-Eintrag.
    """
    report = BatchReport()
    if not devices:
        return report

    # Schritt 1: FW-Abfrage. Antwort kommt asynchron, wir lesen sie am Ende.
    for dev in devices:
        try:
            await query_firmware_version(dev.dev_eui)
        except Exception as exc:  # noqa: BLE001 — FW ist kein Fehlerkriterium
            logger.warning("batch: FW-Query fehlgeschlagen dev_eui=%s exc=%s", dev.dev_eui, exc)
        await _sleep(SEND_SPACING_S)

    # Schritt 2 + 3: 25 °C.
    sent_high, fail_high = await _send_round(devices, SETPOINT_HIGH_C)
    high = await _await_readbacks(
        session, sent_high, SETPOINT_HIGH_C, timeout_s=timeout_s, poll_interval_s=poll_interval_s
    )
    for device_id, detail in fail_high.items():
        high[device_id] = StepResult(
            target_c=SETPOINT_HIGH_C, outcome="downlink_failed", detail=detail
        )

    # Schritt 4 + 5: 10 °C, nur fuer Geraete, die den ersten Schritt bestanden
    # haben. Ein Geraet ohne Uplink wuerde sonst ein zweites volles Fenster
    # blockieren, ohne dass sich am Urteil etwas aendern kann.
    ready = [d for d in devices if high.get(d.id) is not None and high[d.id].outcome == "ok"]
    sent_low, fail_low = await _send_round(ready, SETPOINT_LOW_C)
    low = await _await_readbacks(
        session, sent_low, SETPOINT_LOW_C, timeout_s=timeout_s, poll_interval_s=poll_interval_s
    )
    for device_id, detail in fail_low.items():
        low[device_id] = StepResult(
            target_c=SETPOINT_LOW_C, outcome="downlink_failed", detail=detail
        )

    # Schritt 6: FW aus der DB nachlesen (der Subscriber hat sie inzwischen
    # geschrieben, falls die Vicki geantwortet hat).
    fw_rows = (
        await session.execute(
            select(Device.id, Device.firmware_version).where(Device.id.in_([d.id for d in devices]))
        )
    ).all()
    firmware: dict[int, str | None] = dict(fw_rows)  # type: ignore[arg-type]

    for dev in devices:
        report.results.append(
            _evaluate(
                dev,
                high.get(dev.id),
                low.get(dev.id),
                firmware.get(dev.id),
                valve_check=valve_check,
            )
        )

    await _persist(session, report.results, user_id=user_id)
    return report


# ---------------------------------------------------------------------------
# Ausgabe
# ---------------------------------------------------------------------------

_STATUS_TAG = {"pass": "[PASS]", "fail": "[FAIL]", "timeout": "[TIMEOUT]"}


def format_report(report: BatchReport) -> str:
    """Tabelle je ``hardware_nummer`` plus Zusammenfassung."""
    if not report.results:
        return "Keine Pool-Geraete gefunden — nichts zu pruefen."

    rows = sorted(report.results, key=lambda r: r.hardware_nummer)
    nr_w = max(len("Nummer"), max(len(r.hardware_nummer) for r in rows))
    fw_w = max(len("Firmware"), max(len(r.firmware_text) for r in rows))

    lines = [
        f"{'Nummer'.ljust(nr_w)}  {'Status'.ljust(9)}  {'Firmware'.ljust(fw_w)}  Befund",
        f"{'-' * nr_w}  {'-' * 9}  {'-' * fw_w}  {'-' * 40}",
    ]
    for r in rows:
        lines.append(
            f"{r.hardware_nummer.ljust(nr_w)}  {_STATUS_TAG[r.status].ljust(9)}  "
            f"{r.firmware_text.ljust(fw_w)}  {r.reason}"
        )

    lines.append("")
    lines.append(
        f"Eingangstest: {len(report.passed)} PASS, {len(report.failed)} FAIL, "
        f"{len(report.timed_out)} TIMEOUT von {len(report.results)} Geraeten."
    )
    if report.failed:
        lines.append(
            "  FAIL = Uplink kam, aber Sollwert oder Ventil stimmen nicht. "
            "Hardware-Verdacht, Geraet zurueck in den Karton: "
            + ", ".join(
                r.hardware_nummer for r in sorted(report.failed, key=lambda x: x.hardware_nummer)
            )
        )
    if report.timed_out:
        lines.append(
            "  TIMEOUT = kein Uplink im Fenster. Funk, Duty-Cycle oder Batterie — "
            "KEIN Hardware-Verdacht. Mit groesserem --timeout wiederholen: "
            + ", ".join(
                r.hardware_nummer for r in sorted(report.timed_out, key=lambda x: x.hardware_nummer)
            )
        )

    groups = report.by_firmware()
    lines.append("")
    lines.append("Firmware-Inventar (kein Fehlerkriterium, steuert nur den OW-Rollout):")
    for key, text in (
        ("ow_faehig", f"FW >= {min_fw_text()} — wird beim OW-Rollout beschickt"),
        ("zu_alt", f"FW < {min_fw_text()} — wird uebersprungen (B-9.11x.b-2)"),
        ("keine_antwort", "keine FW-Antwort — wird uebersprungen"),
    ):
        members = sorted(groups[key], key=lambda r: r.hardware_nummer)
        nummern = ", ".join(r.hardware_nummer for r in members) if members else "—"
        lines.append(f"  {len(members):3d}  {text}")
        lines.append(f"       {nummern}")
    skipped = len(groups["zu_alt"]) + len(groups["keine_antwort"])
    lines.append(f"  Erwartungswert fuer den OW-Rollout: {skipped} Geraet(e) werden uebersprungen.")
    return "\n".join(lines)
