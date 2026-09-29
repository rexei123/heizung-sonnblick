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
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
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

# Sprint 19 (T2): 28 statt 25 °C. Der einzige **gemessene** Beleg fuer eine
# Oeffnung stammt von Geraet 002 am 29.09.2026: 59 % bei Sollwert 28 °C. Was
# ein gesunder Vicki bei 25 °C und 20-22 °C Raumtemperatur oeffnet, ist
# unbelegt — der Regler moduliert, und 20 % koennen dort voellig richtig
# sein. Eine Schwelle auf unbelegter Grundlage ist der Fehler aus
# CLAUDE.md §5.79. 28 liegt innerhalb ``MAX_SETPOINT_C`` (30).
SETPOINT_HIGH_C = 28
SETPOINT_LOW_C = 10

# Absolute Ventil-Schwellen (Sprint 19 / T2). Belegt am Feldtest 28./29.09.2026:
#
#   Geraet 101 und 002: Openness **0 %** bei Sollwert unter Raumtemperatur.
#   Geraet 002:         Openness **59 %** bei Sollwert 28 °C.
#   Geraet 001 (defekt): **100 %** bei Sollwert 10 °C und Raum 19 °C.
#
# Der **niedrige** Sollwert traegt das Urteil: sein Erwartungswert ist mit
# 0 % an zwei Geraeten scharf belegt, waehrend die Oeffnung am hohen Sollwert
# von der Raumtemperatur abhaengt. Und er trifft den gefaehrlichen Fehler —
# ein klemmend **offenes** Ventil heizt ein leeres Zimmer durch, ein
# klemmend geschlossenes laesst es nur kalt.
VALVE_CLOSED_MAX_PCT = 10
VALVE_OPEN_MIN_PCT = 40

# Eine dritte Schwelle auf die **Spreizung** (hoch minus niedrig) war geplant
# und ist gestrichen: sie kann nicht ausloesen. Wer beide Schwellen oben
# passiert, hat mindestens 40 - 10 = 30 Punkte Spreizung; jede Mindest-
# Spreizung unter 30 ist damit wirkungslos, und eine darueber waere aus den
# drei Feldwerten nicht belegbar. Ein Kriterium, das nie greift, ist ein
# Schalter ohne Wirkung (§5.77) und haette einen Test gebraucht, der
# unerreichbares Verhalten zusichert.

# Zwei verpasste Periodic-Reports (Default ~15 Min) plus Reserve fuer die
# Class-A-Latenz. Bewusst grosszuegig: ein zu kurzes Fenster erzeugt
# Falsch-TIMEOUTs, ein zu langes kostet nur Wartezeit.
DEFAULT_TIMEOUT_S = 2700
DEFAULT_POLL_INTERVAL_S = 15

# Vor-Check (Sprint 19 / T4): wie lange auf den ersten frischen Uplink eines
# Geraets gewartet wird. Der alte Einzeltest brach bei einem Reading-Alter
# ueber 5 Minuten sofort ab — bei einem Keepalive von 10 Minuten ist das ein
# Muenzwurf, kein Kriterium.
HEARTBEAT_WAIT_MAX_S = 900

# Pause zwischen den Downlinks einer Sende-Runde. Verteilt die Last auf dem
# Gateway, statt 104 Publishes in einer Sekunde abzusetzen (S4).
SEND_SPACING_S = 0.5

StepOutcome = Literal[
    "ok",
    "timeout",
    "valve_timeout",
    "wrong_readback",
    "downlink_failed",
    "skipped",
]
DeviceStatus = Literal["pass", "passed_ohne_motor", "fail", "timeout"]
PrecheckVerdict = Literal["ready", "no_uplink", "not_attached", "backplate_unknown"]

AUDIT_ACTION = "DEVICE_INBOUND_TEST"


@dataclass(frozen=True, slots=True)
class StepResult:
    """Ergebnis eines Sollwert-Schritts fuer ein Geraet."""

    target_c: int
    outcome: StepOutcome
    observed_setpoint: Decimal | None = None
    #: Openness aus dem **Setzframe** — dem Uplink NACH dem Readback. Sprint 19
    #: (T1): bis dahin stand hier die Openness aus dem Readback-Frame selbst,
    #: also aus genau dem Uplink, mit dem der Downlink erst ausgeliefert wurde.
    #: Der Motor hatte zu diesem Zeitpunkt noch nicht gefahren. Der Test
    #: bewertete die Stellung *vor* der Bewegung, die er pruefen soll.
    valve_position: int | None = None
    #: Zeitpunkt des Readback-Frames (Sollwert bestaetigt).
    reading_at: datetime | None = None
    #: Zeitpunkt des Setzframes, aus dem ``valve_position`` stammt.
    valve_reading_at: datetime | None = None
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
    def passed_without_motor(self) -> list[DeviceResult]:
        """Bestanden, soweit pruefbar — **Motor ungeprueft** (Sprint 19 / T3).

        Ein Status, der gut aussieht und wenig sagt. Wer 104 Geraete so
        durchlaufen laesst, hat 104 ungepruefte Motoren und einen gruenen
        Bericht. Deshalb steht er in der Zusammenfassung getrennt und mit
        Klartext, und deshalb gibt es ``--require-motor``.
        """
        return [r for r in self.results if r.status == "passed_ohne_motor"]

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
                # Bewusst OHNE ``valve_position``: dieser Uplink ist derjenige,
                # mit dem ChirpStack den Downlink erst ausgeliefert hat. Die
                # Openness darin ist der Stand VOR der Bewegung. Sie kommt aus
                # dem Setzframe, siehe ``_await_valve_frames`` (Sprint 19 / T1).
                results[device_id] = StepResult(
                    target_c=target_c,
                    outcome="ok",
                    observed_setpoint=reading.setpoint,
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


async def _await_fresh_readings(
    session: AsyncSession,
    device_ids: Sequence[int],
    *,
    max_age_s: int,
    timeout_s: int,
    poll_interval_s: int,
) -> dict[int, SensorReading]:
    """Ein aktuelles Reading je Geraet — wartend, nicht sofort urteilend.

    Sprint 19 (T4). Ein Reading, das juenger ist als ``max_age_s``, wird
    sofort genommen. Fehlt es, wird bis ``timeout_s`` auf einen **neuen**
    Uplink gewartet (``time`` nach dem Beginn des Wartens).

    Der alte Einzeltest verglich das Reading-Alter gegen 5 Minuten und
    scheiterte sofort, wenn es darueber lag ([inbound_test.py] Schritt 1).
    Bei einem Keepalive von 10 Minuten trifft das im Mittel jedes zweite
    gesunde Geraet — die Pruefung war ein Muenzwurf mit dem Anschein eines
    Kriteriums.
    """
    start = _now()
    cutoff = start - timedelta(seconds=max_age_s)
    found: dict[int, SensorReading] = {}
    pending = set(device_ids)
    if not pending:
        return found

    latest = await _latest_readings(session, list(pending))
    for device_id in list(pending):
        reading = latest.get(device_id)
        if reading is not None and reading.time >= cutoff:
            found[device_id] = reading
            pending.discard(device_id)

    deadline = start.timestamp() + timeout_s
    while pending:
        await _sleep(poll_interval_s)
        latest = await _latest_readings(session, list(pending))
        for device_id in list(pending):
            reading = latest.get(device_id)
            if reading is not None and reading.time > start:
                found[device_id] = reading
                pending.discard(device_id)
        if _now().timestamp() >= deadline:
            break
    return found


async def _precheck(
    session: AsyncSession,
    devices: Sequence[Device],
    *,
    poll_interval_s: int,
) -> dict[int, tuple[PrecheckVerdict, str]]:
    """Funk und Backplate **vor** dem ersten Downlink (Sprint 19 / T3, T4).

    Ohne Backplate meldet die Vicki ``motorRange 0`` und der Motor faehrt
    nie. Ein Sollwert-Test am Tisch kann dann nicht bestehen — er prueft
    nichts, er scheitert nur. Bis Sprint 18 lief die Backplate-Pruefung als
    **letzter** Schritt, also nach den beiden Sollwert-Schritten, die sie
    erklaeren wuerde.

    ``None`` gilt wie ``False``: ein Reading ohne das Feld (alter Codec)
    belegt keine Montage. Dieselbe Regel wie in Layer 4, wo NULL das Geraet
    aus dem Detached-Trigger heraushaelt statt es hineinzuziehen.
    """
    fresh = await _await_fresh_readings(
        session,
        [d.id for d in devices],
        max_age_s=HEARTBEAT_WAIT_MAX_S,
        timeout_s=HEARTBEAT_WAIT_MAX_S,
        poll_interval_s=poll_interval_s,
    )
    verdicts: dict[int, tuple[PrecheckVerdict, str]] = {}
    for dev in devices:
        reading = fresh.get(dev.id)
        if reading is None:
            verdicts[dev.id] = (
                "no_uplink",
                f"Kein Uplink innerhalb von {HEARTBEAT_WAIT_MAX_S} s. Funk, "
                "Duty-Cycle oder Batterie — kein Hardware-Verdacht. Es wurde "
                "kein Downlink gesendet.",
            )
            continue
        if reading.attached_backplate is not True:
            unklar = reading.attached_backplate is None
            verdicts[dev.id] = (
                "backplate_unknown" if unklar else "not_attached",
                (
                    "Letztes Reading fuehrt kein attached_backplate (alter "
                    "Codec) — Montage unbelegt."
                    if unklar
                    else "Vicki nicht auf der Backplate (attached_backplate=false)."
                )
                + " Ohne Backplate ist motorRange 0 und der Motor faehrt nie; "
                "die Sollwert-Schritte wurden uebersprungen.",
            )
            continue
        verdicts[dev.id] = ("ready", "")
    return verdicts


async def _await_firmware(
    session: AsyncSession,
    device_ids: Sequence[int],
    *,
    timeout_s: int,
    poll_interval_s: int,
) -> dict[int, str | None]:
    """Wartet auf die Antworten der FW-Abfrage und liest sie aus ``device``.

    Fragt direkt die Zielspalte ab, statt auf einen Uplink zu warten: die
    Antwort auf 0x04 kommt als eigenes Frame und erzeugt **keine**
    ``sensor_reading``-Zeile ([mqtt_subscriber.py] ``_handle_firmware_
    version_report``). Wer hier auf ein frisches Reading wartet, wartet auf
    den naechsten Periodic-Report danach — also eine Periode zu lang.

    Eine fehlende Antwort ist kein Fehler; sie schliesst das Geraet nur vom
    OW-Rollout aus.
    """
    known: dict[int, str | None] = dict.fromkeys(device_ids)
    if not known:
        return known

    stmt = select(Device.id, Device.firmware_version).where(Device.id.in_(list(known)))
    deadline = _now().timestamp() + timeout_s
    while True:
        for device_id, fw in (await session.execute(stmt)).all():
            known[device_id] = fw
        if all(fw is not None for fw in known.values()) or _now().timestamp() >= deadline:
            return known
        await _sleep(poll_interval_s)


async def _await_valve_frames(
    session: AsyncSession,
    steps: dict[int, StepResult],
    *,
    timeout_s: int,
    poll_interval_s: int,
) -> dict[int, StepResult]:
    """Wartet je Geraet auf den **Setzframe** — den Uplink nach dem Readback.

    Sprint 19 (T1). Der Readback-Uplink ist derjenige, mit dem ChirpStack den
    Downlink ueberhaupt erst ausgeliefert hat (Class A: ein Downlink je
    Uplink). Der Motor beginnt danach zu fahren. Die Openness im Readback-Frame
    ist damit der Stand **vor** der Bewegung — der Test bewertete bis hierher
    genau die Zahl, die sich noch nicht geaendert haben kann.

    Gewartet wird auf ein Reading mit ``time`` **strikt nach** dem
    Readback-Frame. Kommt keines, ist das Ergebnis ``valve_timeout`` und
    **nicht** ``fail``: der Readback beweist, dass das Geraet funkt und den
    Befehl verarbeitet hat. Ein ausbleibender Folge-Uplink ist ein Funk- oder
    Duty-Cycle-Befund, kein Hardware-Verdacht — dieselbe Trennlinie wie
    zwischen ``timeout`` und ``fail``.

    :param steps: Ergebnisse aus ``_await_readbacks``; nur ``ok`` wird
        weiterverfolgt.
    :return: dieselbe Abbildung, ``ok``-Eintraege um Openness und
        ``valve_reading_at`` ergaenzt.
    """
    out = dict(steps)
    pending = {
        device_id: step
        for device_id, step in steps.items()
        if step.outcome == "ok" and step.reading_at is not None
    }
    if not pending:
        return out

    deadline = _now().timestamp() + timeout_s
    while pending:
        await _sleep(poll_interval_s)
        latest = await _latest_readings(session, list(pending))
        for device_id in list(pending):
            step = pending[device_id]
            reading = latest.get(device_id)
            # ``step.reading_at`` ist in ``pending`` garantiert nicht None.
            if reading is None or reading.time <= step.reading_at:  # type: ignore[operator]
                continue
            out[device_id] = replace(
                step,
                valve_position=reading.valve_position,
                valve_reading_at=reading.time,
                detail=(
                    f"Readback {step.target_c} °C bestaetigt, Ventil im "
                    f"Folge-Uplink {reading.valve_position} %."
                ),
            )
            del pending[device_id]
        if _now().timestamp() >= deadline:
            break

    for device_id, step in pending.items():
        out[device_id] = replace(
            step,
            outcome="valve_timeout",
            detail=(
                f"Readback {step.target_c} °C bestaetigt, aber innerhalb von "
                f"{timeout_s} s kam kein weiterer Uplink. Ventilstellung damit "
                "ungeprueft — Funk oder Duty-Cycle, kein Hardware-Verdacht."
            ),
        )
    return out


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
        # ``valve_timeout`` steht bewusst neben ``timeout`` und nicht neben
        # ``fail``: der Readback ist angekommen, das Geraet funkt und hat den
        # Befehl verarbeitet. Nur der Folge-Uplink fehlt (Sprint 19 / T1).
        if step.outcome in ("timeout", "valve_timeout"):
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
        # Das entscheidende Kriterium zuerst: bleibt das Ventil bei einem
        # Sollwert unter der Raumtemperatur offen, heizt es ein leeres Zimmer
        # durch. Genau der Befund an Geraet 001 (100 % bei Sollwert 10 °C).
        if low.valve_position > VALVE_CLOSED_MAX_PCT:
            return result(
                "fail",
                f"Ventil schliesst nicht: {low.valve_position} % bei "
                f"{low.target_c} °C, erlaubt sind bis {VALVE_CLOSED_MAX_PCT} %. "
                "Ein Ventil, das bei Sollwert unter Raumtemperatur offen bleibt, "
                "heizt durch.",
            )
        if high.valve_position < VALVE_OPEN_MIN_PCT:
            return result(
                "fail",
                f"Ventil oeffnet nicht: {high.valve_position} % bei "
                f"{high.target_c} °C, erwartet sind mindestens "
                f"{VALVE_OPEN_MIN_PCT} %.",
            )
        return result(
            "pass",
            f"Readback beidseitig korrekt, Ventil {low.valve_position} % bei "
            f"{low.target_c} °C -> {high.valve_position} % bei "
            f"{high.target_c} °C.",
        )

    return result("pass", "Readback beidseitig korrekt (Ventilkriterium abgeschaltet).")


def _precheck_result(
    dev: Device,
    verdict: PrecheckVerdict,
    reason: str,
    firmware: str | None,
    *,
    require_motor: bool,
) -> DeviceResult:
    """Uebersetzt ein Vor-Check-Urteil in ein Geraete-Ergebnis (Sprint 19 / T3).

    ``no_uplink`` ist ein Funk-Befund und wird ``timeout`` — dieselbe
    Trennlinie wie ueberall sonst: kein Uplink heisst nicht defekt.

    Fehlende Backplate ist ohne ``require_motor`` **kein Fehler**, sondern
    eine nicht durchfuehrbare Pruefung: am Tisch ist ``false`` der erwartete
    Zustand. Mit ``require_motor`` ist es ein Fehler, weil der Aufrufer dann
    zugesichert hat, dass die Geraete montiert sind.
    """
    status: DeviceStatus
    if verdict == "no_uplink":
        status = "timeout"
    elif require_motor:
        status = "fail"
        reason = f"{reason} --require-motor verlangt einen belegten Motortest."
    else:
        status = "passed_ohne_motor"
    return DeviceResult(
        device_id=dev.id,
        dev_eui=dev.dev_eui,
        hardware_nummer=dev.label or dev.dev_eui,
        status=status,
        reason=reason,
        firmware_version=firmware,
    )


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
        # Schluessel ohne Gradzahl im Namen: der hohe Sollwert ist in Sprint 19
        # von 25 auf 28 °C gewandert, und ein Audit-Feld ``setpoint_25`` mit
        # ``target_c: 28`` darin waere genau die Sorte Widerspruch, die spaeter
        # als Beleg gelesen wird. Die Gradzahl steht im Wert, nicht im Namen.
        for name, step in (("setpoint_high", r.high), ("setpoint_low", r.low)):
            if step is None:
                continue
            payload[name] = {
                "target_c": step.target_c,
                "outcome": step.outcome,
                "observed_setpoint": step.observed_setpoint,
                # Die gemessene Openness steht IMMER hier — auch bei ``pass``.
                # Die Schwellen aus T2 ruhen auf drei Geraeten; ohne die
                # Messwerte der bestandenen Laeufe kann sie niemand gegen
                # echte Werte nachziehen (Sprint 19 / R3).
                "valve_position": step.valve_position,
                "readback_at": step.reading_at,
                "valve_reading_at": step.valve_reading_at,
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
    require_motor: bool = False,
    user_id: int | None = None,
) -> BatchReport:
    """Fuehrt den Batch-Eingangstest aus. Caller committet.

    Ablauf (Sprint 19). Die Reihenfolge ist nicht beliebig: **je Geraet darf
    immer nur EIN Downlink ausstehen.** Class A liefert einen Downlink pro
    Uplink aus; zwei Befehle in der Warteschlange heissen, dass der zweite
    eine ganze Periode spaeter zugestellt wird und bis dahin nicht
    unterscheidbar ist von "nicht angekommen". Bis Sprint 18 lagen FW-Abfrage
    und Sollwert hintereinander in der Queue (S4).

    1. **Vor-Check**, ohne Downlink: frischer Uplink (T4) und Backplate (T3).
    2. Sollwert ``SETPOINT_HIGH_C`` -> Readback -> Setzframe.
    3. Sollwert ``SETPOINT_LOW_C`` -> Readback -> Setzframe.
    4. FW-Abfrage (0x04) **zuletzt**, danach die Antwort abwarten.

    Nach jedem beobachteten Uplink ist die Warteschlange des Geraets leer —
    der vorige Befehl wurde damit zugestellt. Das ist der Beleg, auf den die
    Disziplin sich stuetzt; ein ``txack`` waere der direktere, ist aber ueber
    den MQTT-Pfad nicht verfuegbar (§5.28).

    :param devices: die zu pruefenden Geraete (typischerweise der Pool).
    :param timeout_s: Wartefenster je Sollwert-Schritt.
    :param poll_interval_s: Abstand zwischen zwei DB-Abfragen.
    :param valve_check: Ventilkriterium mitpruefen.
    :param require_motor: ohne belegte Backplate ``fail`` statt
        ``passed_ohne_motor``. Pflicht fuer den Montage-Lauf: dort IST das
        Geraet montiert, eine fehlende Backplate-Meldung ist also ein Befund
        und kein Tischzustand.
    :param user_id: fuer den Audit-Eintrag.
    """
    report = BatchReport()
    if not devices:
        return report

    # Schritt 1: Vor-Check. Sendet nichts.
    verdicts = await _precheck(session, devices, poll_interval_s=poll_interval_s)
    ready = [d for d in devices if verdicts[d.id][0] == "ready"]

    high: dict[int, StepResult] = {}
    low: dict[int, StepResult] = {}

    if ready:
        # Schritt 2: hoher Sollwert -> Readback -> Setzframe.
        sent_high, fail_high = await _send_round(ready, SETPOINT_HIGH_C)
        high = await _await_readbacks(
            session,
            sent_high,
            SETPOINT_HIGH_C,
            timeout_s=timeout_s,
            poll_interval_s=poll_interval_s,
        )
        high = await _await_valve_frames(
            session, high, timeout_s=timeout_s, poll_interval_s=poll_interval_s
        )
        for device_id, detail in fail_high.items():
            high[device_id] = StepResult(
                target_c=SETPOINT_HIGH_C, outcome="downlink_failed", detail=detail
            )

        # Schritt 3: niedriger Sollwert, nur fuer Geraete mit bestandenem
        # ersten Schritt. Ein Geraet ohne Folge-Uplink wuerde sonst ein
        # zweites volles Fenster blockieren, ohne dass sich am Urteil etwas
        # aendern kann — und bekaeme einen zweiten Befehl in die Queue,
        # bevor der erste belegt zugestellt ist.
        second = [d for d in ready if high.get(d.id) is not None and high[d.id].outcome == "ok"]
        sent_low, fail_low = await _send_round(second, SETPOINT_LOW_C)
        low = await _await_readbacks(
            session,
            sent_low,
            SETPOINT_LOW_C,
            timeout_s=timeout_s,
            poll_interval_s=poll_interval_s,
        )
        low = await _await_valve_frames(
            session, low, timeout_s=timeout_s, poll_interval_s=poll_interval_s
        )
        for device_id, detail in fail_low.items():
            low[device_id] = StepResult(
                target_c=SETPOINT_LOW_C, outcome="downlink_failed", detail=detail
            )

    # Schritt 4: FW-Abfrage zuletzt. Geraete ohne jeden Uplink werden
    # uebersprungen — an ein Geraet, das nicht funkt, einen Befehl zu haengen,
    # fuellt nur die Warteschlange.
    fw_targets = [d for d in devices if verdicts[d.id][0] != "no_uplink"]
    for dev in fw_targets:
        try:
            await query_firmware_version(dev.dev_eui)
        except Exception as exc:  # noqa: BLE001 — FW ist kein Fehlerkriterium
            logger.warning("batch: FW-Query fehlgeschlagen dev_eui=%s exc=%s", dev.dev_eui, exc)
        await _sleep(SEND_SPACING_S)
    firmware = await _await_firmware(
        session,
        [d.id for d in devices],
        timeout_s=timeout_s if fw_targets else 0,
        poll_interval_s=poll_interval_s,
    )

    for dev in devices:
        verdict, reason = verdicts[dev.id]
        if verdict == "ready":
            report.results.append(
                _evaluate(
                    dev,
                    high.get(dev.id),
                    low.get(dev.id),
                    firmware.get(dev.id),
                    valve_check=valve_check,
                )
            )
            continue
        report.results.append(
            _precheck_result(
                dev,
                verdict,
                reason,
                firmware.get(dev.id),
                require_motor=require_motor,
            )
        )

    await _persist(session, report.results, user_id=user_id)
    return report


# ---------------------------------------------------------------------------
# Ausgabe
# ---------------------------------------------------------------------------

_STATUS_TAG = {
    "pass": "[PASS]",
    "passed_ohne_motor": "[OHNE MOTOR]",
    "fail": "[FAIL]",
    "timeout": "[TIMEOUT]",
}


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
        f"Eingangstest: {len(report.passed)} PASS, "
        f"{len(report.passed_without_motor)} OHNE MOTOR, {len(report.failed)} FAIL, "
        f"{len(report.timed_out)} TIMEOUT von {len(report.results)} Geraeten."
    )
    if report.passed_without_motor:
        lines.append(
            "  OHNE MOTOR = Geraet funkt und antwortet, aber es meldet keine "
            "Backplate. Der Motor wurde NICHT geprueft — ohne Backplate ist "
            "motorRange 0 und das Ventil bewegt sich nie. Nach der Montage mit "
            "--require-motor wiederholen: "
            + ", ".join(
                r.hardware_nummer
                for r in sorted(report.passed_without_motor, key=lambda x: x.hardware_nummer)
            )
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
