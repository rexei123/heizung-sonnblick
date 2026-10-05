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

import logging
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Literal

from sqlalchemy import select

from heizung.models.business_audit import BusinessAudit
from heizung.models.device import Device
from heizung.models.sensor_reading import SensorReading
from heizung.scripts.pairing.clock import REAL_CLOCK, Clock
from heizung.scripts.pairing.firmware import classify_firmware, min_fw_text
from heizung.services.business_audit_service import record_business_action
from heizung.services.downlink_adapter import query_firmware_version, send_setpoint

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

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

# Werkswert der Vicki. Nach dem Test wird darauf zurueckgestellt (Sprint 19 /
# T9): ohne das bleibt jedes geprueftes Geraet auf SETPOINT_LOW_C stehen und
# heizt nicht. Bei Frostschutz 10 °C ist das nicht gefaehrlich, aber ein
# kaltes Zimmer, bis die Engine das naechste Mal greift.
SETPOINT_RESET_C = 21


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

# Sprint 20f (T4): **Altersgrenze**, getrennt von der Wartezeit. Bis hierher
# war beides dieselbe Zahl — der Vor-Check wurde mit ``wait_s`` aufgerufen und
# benutzte sie zugleich als ``max_age_s``. Folge: ein Reading von bis zu
# 15 Minuten vor dem Lauf galt als "frisch" und wurde sofort beurteilt.
#
# **Damit hat ``--heartbeat-wait`` am 05.10.2026 keine Sekunde gewartet.** Die
# Geraete 038-044 bekamen ihr FAIL aus einer Zeile, die vor dem Lauf
# entstanden war.
#
# Zwei Minuten: kurz genug, dass das Urteil den Zustand *nach* der Montage
# beschreibt, lang genug, dass ein Geraet, das gerade eben gesendet hat,
# nicht auf den naechsten Keepalive warten muss. Der Preis ist Wartezeit —
# im schlechtesten Fall eine Keepalive-Periode (~10 Min) fuer alle noch
# offenen Geraete **gemeinsam**, weil die Warte-Schleife sie in einer Abfrage
# abholt.
PRECHECK_MAX_AGE_S = 120

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
PrecheckVerdict = Literal[
    "ready",
    "no_uplink",
    "not_attached",
    "backplate_unknown",
    # Sprint 20f (T7): Geraet sitzt auf der Backplate, meldet aber
    # ``calibrationFailed``. Eigener Wert, damit das Urteil den Grund nennt.
    "calibration_failed",
]

# Endgueltige Ergebnisse — ``--resume`` fasst sie nicht mehr an (T7).
# ``timeout`` fehlt bewusst: dort ist kein Urteil gefallen, das Geraet hat nur
# nicht geantwortet. Genau diese Geraete sind der Grund fuer den zweiten Lauf.
TERMINAL_STATUSES: frozenset[str] = frozenset({"pass", "passed_ohne_motor", "fail"})

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
    #: ``brokenSensor`` aus dem Setzframe. NULL = Feld nicht im Payload.
    broken_sensor: bool | None = None
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
    #: ``True`` = Ruecksetzen auf SETPOINT_RESET_C bestaetigt, ``False`` =
    #: gesendet aber nicht bestaetigt, ``None`` = nicht versucht (T9).
    reset_confirmed: bool | None = None

    @property
    def firmware_text(self) -> str:
        return self.firmware_version or "keine Antwort"

    @property
    def reset_note(self) -> str | None:
        """Hinweis, wenn das Ruecksetzen nicht bestaetigt ist (T9)."""
        if self.reset_confirmed is not False:
            return None
        return (
            f"Ruecksetzen auf {SETPOINT_RESET_C} °C NICHT bestaetigt — das "
            f"Geraet steht moeglicherweise noch auf {SETPOINT_LOW_C} °C."
        )


@dataclass
class BatchReport:
    """Sammelergebnis. ``exit_code`` ist 1, sobald ein Geraet nicht besteht."""

    results: list[DeviceResult] = field(default_factory=list)
    #: Wie viele Geraete ``--resume`` uebersprungen hat (T7).
    skipped_resume: int = 0

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
    devices: Sequence[Device], target_c: int, *, clock: Clock
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
        sent_at[dev.id] = clock.now()
        await clock.sleep(SEND_SPACING_S)
    return sent_at, failures


async def _await_readbacks(
    session: AsyncSession,
    sent_at: dict[int, datetime],
    target_c: int,
    *,
    timeout_s: int,
    poll_interval_s: int,
    clock: Clock,
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
    deadline = clock.now().timestamp() + timeout_s

    while pending:
        await clock.sleep(poll_interval_s)
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
        if clock.now().timestamp() >= deadline:
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
    clock: Clock,
    brauchbar: Callable[[SensorReading], bool] | None = None,
) -> tuple[dict[int, SensorReading], dict[int, SensorReading]]:
    """Ein **brauchbares** Reading je Geraet — wartend, nicht sofort urteilend.

    Sprint 19 (T4). Ein Reading, das juenger ist als ``max_age_s``, wird
    genommen. Fehlt es, wird bis ``timeout_s`` auf einen **neuen** Uplink
    gewartet (``time`` nach dem Beginn des Wartens).

    Der alte Einzeltest verglich das Reading-Alter gegen 5 Minuten und
    scheiterte sofort, wenn es darueber lag ([inbound_test.py] Schritt 1).
    Bei einem Keepalive von 10 Minuten trifft das im Mittel jedes zweite
    gesunde Geraet — die Pruefung war ein Muenzwurf mit dem Anschein eines
    Kriteriums.

    **Sprint 20f (T4): ``brauchbar``.** Ein Zeitstempel allein sagt nicht,
    dass die Zeile die gesuchte Angabe **enthaelt**. Am 05.10.2026 trug ein
    ``0x28``-Frame (Handverstellung) einen vollstaendigen Keep-alive, den der
    Codec verwarf — der Subscriber schrieb daraus eine Zeile, in der alles
    ``NULL`` war. Diese Funktion nahm sie als "frisches Reading", und der
    Vor-Check urteilte darauf. Sieben montierte Geraete bekamen FAIL.

    Mit ``brauchbar`` wird nur eine Zeile genommen, die die Frage auch
    beantworten kann. Alles andere wird uebersprungen und weiter gewartet.

    :return: ``(brauchbare, unbrauchbare)`` — zwei Abbildungen. Die zweite
        traegt je Geraet das juengste Reading, das **nicht** brauchbar war,
        und ist genau die Unterscheidung, die der Aufrufer fuer sein Urteil
        braucht: hat das Geraet geschwiegen (nichts in beiden) oder hat es
        gesendet, ohne die Angabe zu fuehren (nur in der zweiten)? Das erste
        ist ein Funk-Befund, das zweite ein Codec- oder Firmware-Befund — und
        die beiden duerfen nicht dasselbe Urteil bekommen.
    """
    start = clock.now()
    cutoff = start - timedelta(seconds=max_age_s)
    found: dict[int, SensorReading] = {}
    unbrauchbar: dict[int, SensorReading] = {}
    pending = set(device_ids)
    if not pending:
        return found, unbrauchbar

    def _nimm(device_id: int, reading: SensorReading) -> bool:
        """True, wenn die Zeile das Urteil tragen kann."""
        if brauchbar is not None and not brauchbar(reading):
            unbrauchbar[device_id] = reading
            return False
        return True

    latest = await _latest_readings(session, list(pending))
    for device_id in list(pending):
        reading = latest.get(device_id)
        if reading is not None and reading.time >= cutoff and _nimm(device_id, reading):
            found[device_id] = reading
            pending.discard(device_id)

    deadline = start.timestamp() + timeout_s
    while pending:
        await clock.sleep(poll_interval_s)
        latest = await _latest_readings(session, list(pending))
        for device_id in list(pending):
            reading = latest.get(device_id)
            if reading is not None and reading.time > start and _nimm(device_id, reading):
                found[device_id] = reading
                pending.discard(device_id)
        if clock.now().timestamp() >= deadline:
            break
    return found, unbrauchbar


async def _precheck(
    session: AsyncSession,
    devices: Sequence[Device],
    *,
    wait_s: int,
    poll_interval_s: int,
    clock: Clock,
    max_age_s: int = PRECHECK_MAX_AGE_S,
) -> dict[int, tuple[PrecheckVerdict, str]]:
    """Funk und Backplate **vor** dem ersten Downlink (Sprint 19 / T3, T4).

    Ohne Backplate meldet die Vicki ``motorRange 0`` und der Motor faehrt
    nie. Ein Sollwert-Test am Tisch kann dann nicht bestehen — er prueft
    nichts, er scheitert nur. Bis Sprint 18 lief die Backplate-Pruefung als
    **letzter** Schritt, also nach den beiden Sollwert-Schritten, die sie
    erklaeren wuerde.

    **Sprint 20f (T4): es wird auf ein Reading gewartet, das die Angabe
    fuehrt.** Vorher galt ``None`` wie ``False`` — und das war genau dann
    falsch, wenn die Zeile aus einem Frame stammte, den der Codec nicht
    dekodieren konnte (``0x28``-Handverstellung, siehe T1). Am 05.10.2026
    bekamen die Geraete 038-044 dadurch ein terminales FAIL, obwohl alle
    sieben montiert **und** kalibriert waren.

    Die Unterscheidung, die daraus folgt:

    - **nichts empfangen** -> ``no_uplink``, ein Funk-Befund.
    - **empfangen, aber ohne das Feld** -> ``backplate_unknown``. Der Funk
      hat funktioniert, also ist das **kein** ``no_uplink``. Es heisst
      entweder alter Codec oder alte Firmware.
    - **Feld vorhanden und ``False``** -> ``not_attached``.
    - **Feld ``True``, aber ``calibration_failed``** -> eigener Befund
      (T7), siehe unten.

    ``max_age_s`` ist **getrennt** von ``wait_s``. Bis Sprint 20f war beides
    dieselbe Zahl, weshalb ein Reading von vor dem Lauf sofort akzeptiert
    wurde und das Wartefenster nie zum Tragen kam.
    """
    fresh, ohne_feld = await _await_fresh_readings(
        session,
        [d.id for d in devices],
        max_age_s=max_age_s,
        timeout_s=wait_s,
        poll_interval_s=poll_interval_s,
        clock=clock,
        # Brauchbar ist eine Zeile, die die Backplate-Frage beantworten kann.
        brauchbar=lambda r: r.attached_backplate is not None,
    )
    verdicts: dict[int, tuple[PrecheckVerdict, str]] = {}
    for dev in devices:
        reading = fresh.get(dev.id)
        if reading is None:
            stumm = ohne_feld.get(dev.id)
            if stumm is None:
                verdicts[dev.id] = (
                    "no_uplink",
                    f"Kein Uplink innerhalb von {wait_s} s. Funk, "
                    "Duty-Cycle oder Batterie — kein Hardware-Verdacht. Es wurde "
                    "kein Downlink gesendet.",
                )
            else:
                verdicts[dev.id] = (
                    "backplate_unknown",
                    f"Uplinks empfangen, aber keiner fuehrte innerhalb von "
                    f"{wait_s} s ein attached_backplate (alter Codec oder "
                    "Firmware < 4.1) — Montage unbelegt. Der Funk ist in "
                    "Ordnung. Ohne Backplate-Angabe ist nicht entscheidbar, ob "
                    "motorRange 0 Montage oder Kalibrierung bedeutet; die "
                    "Sollwert-Schritte wurden uebersprungen.",
                )
            continue
        if reading.attached_backplate is not True:
            verdicts[dev.id] = (
                "not_attached",
                "Vicki nicht auf der Backplate (attached_backplate=false)."
                " Ohne Backplate ist motorRange 0 und der Motor faehrt nie; "
                "die Sollwert-Schritte wurden uebersprungen.",
            )
            continue
        # Sprint 20f (T7): Geraet sitzt, meldet aber eine fehlgeschlagene
        # Kalibrierung. Bis hierher fiel so ein Geraet erst am
        # Ventilkriterium durch — mit "Ventil oeffnet nicht weit genug" und
        # ohne den Grund. Der Hinweis ist ein Handgriff am Geraet
        # (Recalibrate, Cmd 0x03), keine Fehlersuche.
        #
        # Terminal und damit ``--resume``-fest: das ist Absicht. Ein Geraet,
        # dessen Kalibrierung fehlgeschlagen ist, darf nicht zugeordnet
        # werden. Nach dem Recalibrate hilft ein Lauf **ohne** ``--resume``
        # fuer genau diese Nummern.
        if reading.calibration_failed is True:
            verdicts[dev.id] = (
                "calibration_failed",
                "Vicki sitzt auf der Backplate, meldet aber "
                "calibrationFailed — die Kalibrierung ist fehlgeschlagen. "
                "Das Ventil wird nicht korrekt gefuehrt, ein Sollwert-Test "
                "waere nicht aussagekraeftig. Handgriff: Recalibrate "
                "(Cmd 0x03) am Geraet, dann erneut testen (ohne --resume).",
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
    clock: Clock,
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
    deadline = clock.now().timestamp() + timeout_s
    while True:
        for device_id, fw in (await session.execute(stmt)).all():
            known[device_id] = fw
        if all(fw is not None for fw in known.values()) or clock.now().timestamp() >= deadline:
            return known
        await clock.sleep(poll_interval_s)


async def _await_valve_frames(
    session: AsyncSession,
    steps: dict[int, StepResult],
    *,
    timeout_s: int,
    poll_interval_s: int,
    clock: Clock,
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

    deadline = clock.now().timestamp() + timeout_s
    while pending:
        await clock.sleep(poll_interval_s)
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
                broken_sensor=reading.broken_sensor,
                detail=(
                    f"Readback {step.target_c} °C bestaetigt, Ventil im "
                    f"Folge-Uplink {reading.valve_position} %."
                ),
            )
            del pending[device_id]
        if clock.now().timestamp() >= deadline:
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
    require_motor: bool = False,
    reset_confirmed: bool | None = None,
) -> DeviceResult:
    """Fasst beide Schritte zu einem Geraete-Urteil zusammen.

    :param require_motor: verlangt einen belegten Motortest. Trifft hier den
        Fall, dass die Readings zwar da sind, aber **keine Ventilstellung**
        tragen — ohne Openness ist das Kriterium nicht pruefbar, und ein
        Montage-Lauf darf das nicht als Erfolg verbuchen.

        Zusammen mit ``valve_check=False`` waere der Parameter sinnlos; die
        CLI weist diese Kombination deshalb beim Start ab (Exit 2,
        ``pair_devices._reject_contradicting_flags``). Hier wird sie nicht
        abgefangen — eine zweite Pruefung an einer Stelle, die der Aufrufer
        nicht erreichen kann, waere toter Code.
    """
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
            reset_confirmed=reset_confirmed,
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

    # Vor jedem Ventilurteil: traut das Geraet seinem eigenen Messwert?
    # Die Vicki regelt gegen ihren internen Temperatursensor. Meldet der
    # einen Defekt, ist jede Aussage ueber die Ventilstellung wertlos — das
    # Geraet regelt dann gegen eine Zahl, der es selbst nicht traut.
    #
    # Nur ``True`` zaehlt. ``None`` heisst "Feld nicht im Payload" (alter
    # Codec) und ist kein Befund. Geprueft wird der **Setzframe**, also der
    # Uplink, aus dem auch die Openness kommt — nicht der Vor-Check.
    for step in (high, low):
        if step is not None and step.broken_sensor is True:
            return result(
                "fail",
                "Temperatursensor meldet Defekt (brokenSensor) im Uplink bei "
                f"{step.target_c} °C. Die Vicki regelt gegen ihren internen "
                "Fuehler; ein Ventilurteil ist damit wertlos. Geraet zurueck "
                "in den Karton.",
            )

    if valve_check:
        if high.valve_position is None or low.valve_position is None:
            # Ohne Ventildaten ist das Kriterium nicht pruefbar, nicht
            # verletzt. Ohne ``require_motor`` bleibt das ein PASS mit
            # Vermerk — der Readback allein hat bestanden.
            #
            # Mit ``require_motor`` ist es ein Fehler (Sprint 19 / T3,
            # Nachtrag): das war die **zweite** stille Tuer zu einem gruenen
            # Bericht ohne Motorpruefung. Die erste ist die fehlende
            # Backplate; beide fuehren zu "bestanden, Motor ungeprueft", und
            # ein Montage-Lauf darf keine davon offenlassen.
            if require_motor:
                return result(
                    "fail",
                    "Ventildaten fehlen (Codec?). Readback beidseitig korrekt, "
                    "aber kein Reading traegt eine Ventilstellung — der "
                    "Motortest ist damit unbelegt, und --require-motor "
                    "verlangt ihn. Codec-Stand in ChirpStack pruefen (§5.22).",
                )
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

    **Sprint 20f (T7): ``calibration_failed`` ist immer ``fail``**, auch ohne
    ``require_motor``. Das ist die einzige Ausnahme von der Regel oben, und
    sie hat einen Grund: dieses Urteil wird nur erreicht, wenn
    ``attached_backplate is True`` — das Geraet sitzt also, der Tisch-Fall
    ist ausgeschlossen. Was bleibt, ist eine Hardware-Aussage des Geraets
    ueber sich selbst, und die gilt unabhaengig davon, was der Aufrufer
    zugesichert hat.
    """
    status: DeviceStatus
    if verdict == "no_uplink":
        status = "timeout"
    elif verdict == "calibration_failed":
        status = "fail"
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
            # Der Ruecksetz-Beleg gehoert ins Audit, nicht nur in die
            # Konsole: der Bericht scrollt weg, das Audit bleibt.
            "reset_confirmed": r.reset_confirmed,
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
                "broken_sensor": step.broken_sensor,
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


async def _already_settled(session: AsyncSession, device_ids: Sequence[int]) -> dict[int, str]:
    """Geraete mit einem **endgueltigen** Ergebnis aus einem frueheren Lauf.

    Sprint 19 (T7). Grundlage von ``--resume``: ein abgebrochener Lauf soll
    fortgesetzt werden koennen, ohne die bereits geprueften Geraete erneut
    anzufassen — jeder Downlink kostet Batterie, und ein Lauf ueber 104
    Geraete dauert Stunden.

    Endgueltig sind ``pass``, ``passed_ohne_motor`` und ``fail``. **Nicht**
    endgueltig ist ``timeout``: dort ist ueberhaupt kein Urteil gefallen, das
    Geraet hat nur nicht geantwortet. Genau diese Geraete sind der Grund,
    warum man einen zweiten Durchlauf macht.

    Gelesen wird der **juengste** Audit-Eintrag je Geraet. Gibt es mehrere
    Laeufe, gilt der letzte — ein Geraet, das gestern ``pass`` war und heute
    ``timeout``, ist heute offen.
    """
    if not device_ids:
        return {}

    # DISTINCT ON (target_id) ueber ts DESC: ein Roundtrip, juengster Eintrag
    # je Geraet. Analog zu ``_latest_readings``.
    stmt = (
        select(BusinessAudit.target_id, BusinessAudit.new_value)
        .where(
            BusinessAudit.action == AUDIT_ACTION,
            BusinessAudit.target_type == "device",
            BusinessAudit.target_id.in_(list(device_ids)),
        )
        .order_by(BusinessAudit.target_id, BusinessAudit.ts.desc())
        .distinct(BusinessAudit.target_id)
    )
    settled: dict[int, str] = {}
    for target_id, new_value in (await session.execute(stmt)).all():
        if target_id is None or not isinstance(new_value, dict):
            continue
        status = new_value.get("status")
        if isinstance(status, str) and status in TERMINAL_STATUSES:
            settled[target_id] = status
    return settled


async def _finalize_device(
    session: AsyncSession,
    result: DeviceResult,
    *,
    user_id: int | None,
    on_device: Callable[[DeviceResult], None] | None,
) -> None:
    """Schreibt EIN Geraete-Ergebnis fest und meldet es nach aussen.

    Sprint 19 (T6). ``_persist`` lief bis PR A erst nach dem letzten Geraet;
    ein Abbruch verlor damit alles — bei einem Lauf von ueber einer Stunde
    die gesamte Arbeit.

    **Dieser Aufruf committet**, und das weicht bewusst von der
    Repo-Konvention ab (§5.61: Services committen nicht, der Endpoint tut
    es). Begruendung: das hier ist kein Request-Handler, sondern ein
    langlaufender Vorgang mit Aussenwirkung — jeder Downlink ist passiert,
    ob die Transaktion spaeter committet oder nicht. Ein Urteil, das
    nachweislich gefallen ist, darf nicht an einem Ctrl-C haengen. Dieselbe
    Linie wie ``pair_devices._cmd_import``, das ebenfalls selbst committet.

    Was ein Abbruch weiterhin verliert: die Geraete, deren Urteil noch
    **nicht** gefallen ist. Das ist keine Luecke, sondern die Sache selbst —
    ein Urteil, das es nicht gibt, kann man nicht festschreiben. Genau diese
    Geraete holt ``--resume`` im zweiten Durchlauf.
    """
    await _persist(session, [result], user_id=user_id)
    await session.commit()
    if on_device is not None:
        on_device(result)


async def run_batch_inbound_test(
    session: AsyncSession,
    devices: Sequence[Device],
    *,
    timeout_s: int = DEFAULT_TIMEOUT_S,
    poll_interval_s: int = DEFAULT_POLL_INTERVAL_S,
    valve_check: bool = True,
    require_motor: bool = False,
    heartbeat_wait_s: int = HEARTBEAT_WAIT_MAX_S,
    reset_setpoint: bool = True,
    resume: bool = False,
    user_id: int | None = None,
    clock: Clock = REAL_CLOCK,
    on_phase: Callable[[str], None] | None = None,
    on_device: Callable[[DeviceResult], None] | None = None,
) -> BatchReport:
    """Fuehrt den Batch-Eingangstest aus. Committet je Geraete-Urteil selbst.

    Ablauf (Sprint 19). Die Reihenfolge ist nicht beliebig: **je Geraet darf
    immer nur EIN Downlink ausstehen.** Class A liefert einen Downlink pro
    Uplink aus; zwei Befehle in der Warteschlange heissen, dass der zweite
    eine ganze Periode spaeter zugestellt wird und bis dahin nicht
    unterscheidbar ist von "nicht angekommen". Bis Sprint 18 lagen FW-Abfrage
    und Sollwert hintereinander in der Queue (S4).

    1. **Vor-Check**, ohne Downlink: frischer Uplink (T4) und Backplate (T3).
    2. Sollwert ``SETPOINT_HIGH_C`` -> Readback -> Setzframe.
    3. Sollwert ``SETPOINT_LOW_C`` -> Readback -> Setzframe.
    4. Ruecksetzen auf ``SETPOINT_RESET_C`` -> Readback (T9).
    5. FW-Abfrage (0x04) **zuletzt**, danach die Antwort abwarten.

    Nach jedem beobachteten Uplink ist die Warteschlange des Geraets leer —
    der vorige Befehl wurde damit zugestellt. Das ist der Beleg, auf den die
    Disziplin sich stuetzt; ein ``txack`` waere der direktere, ist aber ueber
    den MQTT-Pfad nicht verfuegbar (§5.28).

    :param devices: die zu pruefenden Geraete (typischerweise der Pool).
    :param timeout_s: Wartefenster je Sollwert-Schritt.
    :param poll_interval_s: Abstand zwischen zwei DB-Abfragen.
    :param valve_check: Ventilkriterium mitpruefen.
    :param require_motor: verlangt einen **belegten** Motortest. Schliesst
        beide Wege zu einem gruenen Bericht ohne Motorpruefung: fehlende
        Backplate (``passed_ohne_motor`` -> ``fail``) und fehlende
        Ventilstellung im Reading (``pass`` mit Vermerk -> ``fail``). Pflicht
        fuer den Montage-Lauf: dort IST das Geraet montiert, beides ist dann
        ein Befund und kein Tischzustand.
    :param heartbeat_wait_s: Wartefenster des Vor-Checks auf den ersten
        frischen Uplink. War bis PR A eine Konstante, waehrend jedes andere
        Fenster ein Parameter ist — ein stummes Geraet hat damit 15 Minuten
        blockiert, bevor ueberhaupt etwas gesendet wurde, und in Tests war
        es gar nicht erreichbar.
    :param reset_setpoint: nach dem Test auf ``SETPOINT_RESET_C`` zurueck
        (T9). Ohne das bleibt jedes gepruefte Geraet auf 10 °C stehen.
    :param resume: Geraete mit endgueltigem Ergebnis aus einem frueheren Lauf
        ueberspringen (T7). ``timeout`` gilt als offen und wird wiederholt.
    :param user_id: fuer den Audit-Eintrag.
    :param clock: Zeitquelle der Warte-Schleifen. Default ist die echte Uhr;
        Tests geben ``virtual_clock(...)`` und warten damit nicht wirklich.
        Uhr und Warten sind **ein** Wert, damit sie nicht getrennt ersetzt
        werden koennen — siehe ``clock.py`` (Sprint 19 / T14).
    :param on_phase: wird zu Beginn jedes Abschnitts mit einer fertigen
        Meldezeile gerufen (T10). Ohne das steht der Lauf ueber eine Stunde
        stumm da und wird fuer haengend gehalten.
    :param on_device: wird gerufen, sobald **ein** Geraete-Urteil feststeht
        und festgeschrieben ist.
    """
    report = BatchReport()
    if not devices:
        return report

    def phase(text: str) -> None:
        if on_phase is not None:
            on_phase(text)

    todo = list(devices)
    if resume:
        settled = await _already_settled(session, [d.id for d in devices])
        if settled:
            todo = [d for d in devices if d.id not in settled]
            phase(
                f"--resume: {len(settled)} von {len(devices)} Geraet(en) haben "
                "schon ein endgueltiges Ergebnis und werden nicht erneut "
                "angefasst. TIMEOUT gilt als offen."
            )
    report.skipped_resume = len(devices) - len(todo)
    if not todo:
        phase("Nichts offen — alle Geraete haben ein endgueltiges Ergebnis.")
        return report

    # Schritt 1: Vor-Check. Sendet nichts.
    phase(f"Vor-Check: Funk und Backplate fuer {len(todo)} Geraet(e), ohne Downlink.")
    verdicts = await _precheck(
        session,
        todo,
        wait_s=heartbeat_wait_s,
        poll_interval_s=poll_interval_s,
        clock=clock,
    )
    ready = [d for d in todo if verdicts[d.id][0] == "ready"]

    # Geraete, die der Vor-Check ausschliesst, haben ihr Urteil JETZT. Sie
    # werden sofort festgeschrieben (T6) — nicht erst nach den Wartefenstern
    # der anderen, die ueber eine Stunde dauern koennen.
    for dev in todo:
        verdict, reason = verdicts[dev.id]
        if verdict == "ready":
            continue
        result = _precheck_result(dev, verdict, reason, None, require_motor=require_motor)
        report.results.append(result)
        await _finalize_device(session, result, user_id=user_id, on_device=on_device)

    high: dict[int, StepResult] = {}
    low: dict[int, StepResult] = {}

    if ready:
        # Schritt 2: hoher Sollwert -> Readback -> Setzframe.
        phase(f"Sollwert {SETPOINT_HIGH_C} °C an {len(ready)} Geraet(e), dann warten.")
        sent_high, fail_high = await _send_round(ready, SETPOINT_HIGH_C, clock=clock)
        high = await _await_readbacks(
            session,
            sent_high,
            SETPOINT_HIGH_C,
            timeout_s=timeout_s,
            poll_interval_s=poll_interval_s,
            clock=clock,
        )
        phase(f"Readback {SETPOINT_HIGH_C} °C da, warte auf den Setzframe.")
        high = await _await_valve_frames(
            session,
            high,
            timeout_s=timeout_s,
            poll_interval_s=poll_interval_s,
            clock=clock,
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
        phase(f"Sollwert {SETPOINT_LOW_C} °C an {len(second)} Geraet(e), dann warten.")
        sent_low, fail_low = await _send_round(second, SETPOINT_LOW_C, clock=clock)
        low = await _await_readbacks(
            session,
            sent_low,
            SETPOINT_LOW_C,
            timeout_s=timeout_s,
            poll_interval_s=poll_interval_s,
            clock=clock,
        )
        phase(f"Readback {SETPOINT_LOW_C} °C da, warte auf den Setzframe.")
        low = await _await_valve_frames(
            session,
            low,
            timeout_s=timeout_s,
            poll_interval_s=poll_interval_s,
            clock=clock,
        )
        for device_id, detail in fail_low.items():
            low[device_id] = StepResult(
                target_c=SETPOINT_LOW_C, outcome="downlink_failed", detail=detail
            )

    # Schritt 4: Ruecksetzen (T9). Nur an Geraete, die tatsaechlich einen
    # Sollwert bekommen haben — wer nie einen bekam, steht noch auf seinem
    # alten Wert und braucht keinen Downlink.
    #
    # Der Readback wird abgewartet, nicht weil das Ruecksetzen ein
    # Pruefkriterium waere, sondern weil "gesendet" bei Class A nichts
    # beweist. Ein Geraet, das auf 10 °C stehenbleibt, heizt nicht — das
    # muss im Bericht stehen und nicht geraten werden.
    reset_ok: dict[int, bool] = {}
    # NUR an Geraete, deren letzter Befehl **belegt zugestellt** ist, also
    # deren niedriger Sollwert mit einem Readback bestaetigt wurde. Bei allen
    # anderen kann der vorige Befehl noch in der Queue liegen; ein weiterer
    # waere der zweite ausstehende und damit ein S4-Verstoss.
    beschickt = [d for d in ready if (st := low.get(d.id)) is not None and st.outcome == "ok"]
    # Geraete, die den niedrigen Sollwert bekamen, ihn aber nicht
    # zurueckgemeldet haben, stehen **moeglicherweise auf 10 °C** — und
    # bekommen bewusst KEINEN Ruecksetz-Befehl, weil ihre Queue nicht
    # nachweislich leer ist. Das muss im Bericht stehen, statt still zu
    # bleiben: ein Geraet auf 10 °C heizt nicht.
    if reset_setpoint:
        for dev in ready:
            st = low.get(dev.id)
            if st is not None and st.outcome != "ok":
                reset_ok[dev.id] = False
    if reset_setpoint and beschickt:
        phase(f"Ruecksetzen auf {SETPOINT_RESET_C} °C an {len(beschickt)} Geraet(e).")
        sent_reset, _fail_reset = await _send_round(beschickt, SETPOINT_RESET_C, clock=clock)
        zurueck = await _await_readbacks(
            session,
            sent_reset,
            SETPOINT_RESET_C,
            timeout_s=timeout_s,
            poll_interval_s=poll_interval_s,
            clock=clock,
        )
        reset_ok.update({device_id: step.outcome == "ok" for device_id, step in zurueck.items()})

    # Schritt 5: FW-Abfrage zuletzt. Geraete ohne jeden Uplink werden
    # uebersprungen — an ein Geraet, das nicht funkt, einen Befehl zu haengen,
    # fuellt nur die Warteschlange.
    fw_targets = [d for d in todo if verdicts[d.id][0] != "no_uplink"]
    if fw_targets:
        phase(f"Firmware-Abfrage an {len(fw_targets)} Geraet(e).")
    for dev in fw_targets:
        try:
            await query_firmware_version(dev.dev_eui)
        except Exception as exc:  # noqa: BLE001 — FW ist kein Fehlerkriterium
            logger.warning("batch: FW-Query fehlgeschlagen dev_eui=%s exc=%s", dev.dev_eui, exc)
        await clock.sleep(SEND_SPACING_S)
    firmware = await _await_firmware(
        session,
        [d.id for d in todo],
        timeout_s=timeout_s if fw_targets else 0,
        poll_interval_s=poll_interval_s,
        clock=clock,
    )

    for dev in ready:
        result = _evaluate(
            dev,
            high.get(dev.id),
            low.get(dev.id),
            firmware.get(dev.id),
            valve_check=valve_check,
            require_motor=require_motor,
            reset_confirmed=reset_ok.get(dev.id) if reset_setpoint else None,
        )
        report.results.append(result)
        await _finalize_device(session, result, user_id=user_id, on_device=on_device)

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


def status_tag(status: DeviceStatus) -> str:
    """Kurzmarke eines Status fuer die Konsole — eine Quelle fuer alle Ausgaben."""
    return _STATUS_TAG[status]


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
        befund = r.reason
        # Batterie und Ruecksetz-Beleg haengen hinten an, statt eigene
        # Spalten zu bekommen: sie sind Hinweise, nicht das Urteil, und eine
        # Spalte mit variabler Breite verschiebt die Tabelle (§5.66).
        for hinweis in (r.reset_note,):
            if hinweis:
                befund = f"{befund} | {hinweis}"
        lines.append(
            f"{r.hardware_nummer.ljust(nr_w)}  {_STATUS_TAG[r.status].ljust(9)}  "
            f"{r.firmware_text.ljust(fw_w)}  {befund}"
        )

    lines.append("")
    lines.append(
        f"Eingangstest: {len(report.passed)} PASS, "
        f"{len(report.passed_without_motor)} OHNE MOTOR, {len(report.failed)} FAIL, "
        f"{len(report.timed_out)} TIMEOUT von {len(report.results)} Geraeten."
    )
    if report.skipped_resume:
        lines.append(
            f"  {report.skipped_resume} Geraet(e) uebersprungen (--resume, "
            "endgueltiges Ergebnis aus einem frueheren Lauf)."
        )
    ohne_reset = sorted(
        (r for r in report.results if r.reset_confirmed is False),
        key=lambda x: x.hardware_nummer,
    )
    if ohne_reset:
        lines.append(
            f"  ACHTUNG: Ruecksetzen auf {SETPOINT_RESET_C} °C nicht bestaetigt — "
            f"diese Geraete stehen moeglicherweise noch auf {SETPOINT_LOW_C} °C "
            "und heizen nicht: " + ", ".join(r.hardware_nummer for r in ohne_reset)
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
