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
    HEARTBEAT_WAIT_MAX_S,
    SETPOINT_HIGH_C,
    SETPOINT_LOW_C,
    VALVE_CLOSED_MAX_PCT,
    VALVE_OPEN_MIN_PCT,
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
    r = _evaluate(_device(), _ok(SETPOINT_HIGH_C, 80), _ok(10, 5), "4.5", valve_check=True)
    assert r.status == "pass"
    assert "5 %" in r.reason
    assert "80 %" in r.reason
    assert r.hardware_nummer == "001"
    assert r.firmware_text == "4.5"


def test_evaluate_fail_when_valve_stays_open() -> None:
    """Der Befund an Geraet 001: 100 % offen bei Sollwert 10 °C.

    Sollwert aus der Spezifikation: bei einem Sollwert unter der
    Raumtemperatur muss das Ventil schliessen. Belegt an 101 und 002, die
    beide 0 % erreichen. Alles ueber VALVE_CLOSED_MAX_PCT heizt durch.
    """
    r = _evaluate(_device(), _ok(SETPOINT_HIGH_C, 100), _ok(10, 100), "4.5", valve_check=True)
    assert r.status == "fail"
    assert "schliesst nicht" in r.reason


def test_evaluate_fail_when_valve_stuck_half_open() -> None:
    """Beidseitig 40 % — schliesst nicht, obwohl es sich nie bewegt hat.

    Das entscheidende Kriterium ist der niedrige Sollwert, nicht die
    Differenz: 40 % bei 10 °C ist schon allein ein Fehler.
    """
    r = _evaluate(_device(), _ok(SETPOINT_HIGH_C, 40), _ok(10, 40), "4.5", valve_check=True)
    assert r.status == "fail"
    assert "schliesst nicht" in r.reason


def test_evaluate_fail_when_valve_does_not_open_enough() -> None:
    """Schliesst korrekt, oeffnet aber nicht — halbseitiger Defekt."""
    r = _evaluate(_device(), _ok(SETPOINT_HIGH_C, 30), _ok(10, 0), "4.5", valve_check=True)
    assert r.status == "fail"
    assert "oeffnet nicht" in r.reason


def test_evaluate_threshold_boundaries_pass() -> None:
    """Die Grenzwerte selbst gelten als bestanden.

    ``VALVE_CLOSED_MAX_PCT`` ist die hoechste erlaubte Stellung im
    geschlossenen Zustand, ``VALVE_OPEN_MIN_PCT`` die niedrigste erlaubte im
    offenen. Beide aus der Definition hergeleitet, nicht aus einem Lauf.
    """
    r = _evaluate(
        _device(),
        _ok(SETPOINT_HIGH_C, VALVE_OPEN_MIN_PCT),
        _ok(SETPOINT_LOW_C, VALVE_CLOSED_MAX_PCT),
        "4.5",
        valve_check=True,
    )
    assert r.status == "pass", r.reason


def test_evaluate_one_step_past_each_boundary_fails() -> None:
    """Ein Punkt jenseits der Grenze ist ein Fehler — beide Richtungen."""
    zu_offen = _evaluate(
        _device(),
        _ok(SETPOINT_HIGH_C, 80),
        _ok(SETPOINT_LOW_C, VALVE_CLOSED_MAX_PCT + 1),
        "4.5",
        valve_check=True,
    )
    assert zu_offen.status == "fail"
    zu_zu = _evaluate(
        _device(),
        _ok(SETPOINT_HIGH_C, VALVE_OPEN_MIN_PCT - 1),
        _ok(SETPOINT_LOW_C, 0),
        "4.5",
        valve_check=True,
    )
    assert zu_zu.status == "fail"


def test_no_spread_criterion_because_it_cannot_trigger() -> None:
    """Belegt, warum es keine dritte Schwelle auf die Spreizung gibt.

    Wer beide absoluten Schwellen passiert, hat mindestens
    ``VALVE_OPEN_MIN_PCT - VALVE_CLOSED_MAX_PCT`` Punkte Spreizung. Eine
    Mindest-Spreizung darunter waere wirkungslos. Der Test haelt die
    Begruendung fest, damit sie nicht spaeter als Luecke gelesen wird —
    und schlaegt an, falls jemand die Schwellen so verschiebt, dass die
    Ueberlegung nicht mehr traegt.
    """
    assert VALVE_OPEN_MIN_PCT - VALVE_CLOSED_MAX_PCT >= 25


def test_evaluate_fail_when_valve_moves_wrong_way() -> None:
    r = _evaluate(_device(), _ok(SETPOINT_HIGH_C, 10), _ok(10, 90), "4.5", valve_check=True)
    assert r.status == "fail"


def test_evaluate_pass_when_valve_check_disabled() -> None:
    r = _evaluate(_device(), _ok(SETPOINT_HIGH_C, 40), _ok(10, 40), "4.5", valve_check=False)
    assert r.status == "pass"
    assert "abgeschaltet" in r.reason


def test_evaluate_pass_when_valve_data_missing() -> None:
    """Fehlende Ventildaten sind kein Verstoss — das Kriterium ist nur
    nicht pruefbar. Der Readback allein hat bestanden."""
    r = _evaluate(_device(), _ok(SETPOINT_HIGH_C, None), _ok(10, None), "4.5", valve_check=True)
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


def test_require_motor_fails_when_valve_data_is_missing() -> None:
    """T3-Nachtrag — die zweite stille Tuer zu einem gruenen Bericht.

    Readback beidseitig korrekt, aber kein Reading traegt eine
    Ventilstellung (alter Codec in ChirpStack, §5.22). Ohne
    ``require_motor`` bleibt das ein PASS mit Vermerk — das Kriterium ist
    nicht pruefbar, nicht verletzt. Mit ``require_motor`` ist es ein
    Fehler: der Montage-Lauf verlangt einen belegten Motortest, und
    "nicht pruefbar" ist kein Beleg.
    """
    ohne_flag = _evaluate(
        _device(),
        _ok(SETPOINT_HIGH_C, None),
        _ok(SETPOINT_LOW_C, None),
        "4.5",
        valve_check=True,
    )
    assert ohne_flag.status == "pass"

    mit_flag = _evaluate(
        _device(),
        _ok(SETPOINT_HIGH_C, None),
        _ok(SETPOINT_LOW_C, None),
        "4.5",
        valve_check=True,
        require_motor=True,
    )
    assert mit_flag.status == "fail"
    assert "Ventildaten fehlen (Codec?)" in mit_flag.reason


def test_require_motor_fails_when_only_one_step_has_valve_data() -> None:
    """Eine Haelfte genuegt nicht — der Vergleich braucht beide Stellungen."""
    r = _evaluate(
        _device(),
        _ok(SETPOINT_HIGH_C, 80),
        _ok(SETPOINT_LOW_C, None),
        "4.5",
        valve_check=True,
        require_motor=True,
    )
    assert r.status == "fail"
    assert "Ventildaten fehlen (Codec?)" in r.reason


def test_require_motor_does_not_touch_a_measured_result() -> None:
    """Liegen beide Stellungen vor, aendert das Flag nichts am Urteil."""
    gut = _evaluate(
        _device(),
        _ok(SETPOINT_HIGH_C, 80),
        _ok(SETPOINT_LOW_C, 0),
        "4.5",
        valve_check=True,
        require_motor=True,
    )
    assert gut.status == "pass"

    schlecht = _evaluate(
        _device(),
        _ok(SETPOINT_HIGH_C, 100),
        _ok(SETPOINT_LOW_C, 100),
        "4.5",
        valve_check=True,
        require_motor=True,
    )
    assert schlecht.status == "fail"
    assert "schliesst nicht" in schlecht.reason


def test_require_motor_stays_out_when_valve_check_is_disabled() -> None:
    """``--no-valve-check`` schaltet das Kriterium ab; dann gibt es nichts zu
    verlangen. Die beiden Schalter widersprechen sich, und der spezifischere
    (Kriterium aus) gewinnt — sonst waere die Kombination ein FAIL, das
    niemand erklaeren kann."""
    r = _evaluate(
        _device(),
        _ok(SETPOINT_HIGH_C, None),
        _ok(SETPOINT_LOW_C, None),
        "4.5",
        valve_check=False,
        require_motor=True,
    )
    assert r.status == "pass"


def test_hardware_nummer_falls_back_to_dev_eui() -> None:
    dev = _device()
    dev.label = None
    r = _evaluate(dev, _ok(SETPOINT_HIGH_C, 80), _ok(10, 5), "4.5", valve_check=True)
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
    assert "2 PASS, 0 OHNE MOTOR, 1 FAIL, 1 TIMEOUT von 4 Geraeten" in text
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

    **Zwei Frames je Sollwert (Sprint 19 / T1).** Ein echter Vicki antwortet
    auf einen Sollwert-Downlink mit einem Uplink, der den neuen Sollwert
    zurueckmeldet — die Ventilstellung darin ist noch die **alte**, denn mit
    genau diesem Uplink hat ChirpStack den Downlink erst ausgeliefert und der
    Motor beginnt danach zu fahren. Erst der Folge-Uplink traegt die neue
    Stellung.

    Diese Reihenfolge ist hier absichtlich nachgebaut. Ein Test, der die
    Openness schon im Readback-Frame liefert, wuerde den Fehler, den T1
    behebt, gar nicht bemerken (§5.79: der Sollwert kommt aus der
    Spezifikation, nicht aus dem Lauf des Codes).
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
        #: (dev_eui, target) -> Anzahl bereits gelieferter Frames (0, 1 oder 2)
        self._frames: dict[tuple[str, int], int] = {}
        self._device_ids: dict[str, int] = {}
        #: aktuell gemeldete Ventilstellung je Geraet
        self._valve: dict[str, int | None] = {}

    async def register(
        self,
        dev: Device,
        *,
        backplate: bool | None = True,
        seed_uplink: bool = True,
        valve_start: int | None = 0,
    ) -> None:
        """Meldet ein Geraet an und legt sein Ausgangs-Reading.

        Das Ausgangs-Reading ist, was der Vor-Check sieht (Sprint 19 / T3, T4).
        ``seed_uplink=False`` simuliert ein Geraet, das noch nie gefunkt hat.
        """
        self._device_ids[dev.dev_eui] = dev.id
        self._valve[dev.dev_eui] = valve_start
        if not seed_uplink:
            return
        self.session.add(
            SensorReading(
                time=self.now,
                device_id=dev.id,
                fcnt=0,
                temperature=Decimal("21.0"),
                setpoint=Decimal(21),
                valve_position=valve_start,
                attached_backplate=backplate,
            )
        )
        await self.session.flush()

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
        """Spielt je gesendetem Sollwert bis zu zwei Frames ein."""
        for dev_eui, target in list(self.sent):
            key = (dev_eui, target)
            done = self._frames.get(key, 0)
            if done >= 2:
                continue
            answer = self.script[dev_eui](target)
            if answer is None:
                # Geraet schweigt: nie eine Antwort.
                self._frames[key] = 2
                continue
            setpoint, valve_new = answer
            if done == 0:
                # Readback-Frame: neuer Sollwert, ALTE Ventilstellung.
                valve = self._valve.get(dev_eui)
            else:
                # Setzframe: der Motor ist gefahren.
                valve = valve_new
                self._valve[dev_eui] = valve_new
            self.session.add(
                SensorReading(
                    time=self.now,
                    device_id=self._device_ids[dev_eui],
                    fcnt=sum(self._frames.values()) + 1,
                    temperature=Decimal("21.0"),
                    setpoint=Decimal(setpoint),
                    valve_position=valve,
                    attached_backplate=True,
                )
            )
            await self.session.flush()
            # Genau EIN Frame je Warte-Runde und Sollwert. Laegen Readback und
            # Setzframe in derselben Runde, waere die Unterscheidung, um die es
            # in T1 geht, nicht pruefbar.
            self._frames[key] = done + 1


@pytest.fixture
def patch_radio(monkeypatch: pytest.MonkeyPatch) -> Callable[[FakeRadio], None]:
    def apply(radio: FakeRadio) -> None:
        monkeypatch.setattr(bit, "send_setpoint", radio.send_setpoint)
        monkeypatch.setattr(bit, "query_firmware_version", radio.query_firmware_version)
        monkeypatch.setattr(bit, "_sleep", radio.sleep)
        monkeypatch.setattr(bit, "_now", radio.clock)

    return apply


def _antwortet(setpoint_offset: int = 0, valve_high: int = 80, valve_low: int = 0):  # type: ignore[no-untyped-def]
    """Geraet meldet den gesetzten Sollwert (ggf. verschoben) korrekt zurueck.

    Vorgabewerte aus dem Feldtest 29.09.2026: 002 erreicht 59 % bei 28 °C und
    0 % bei Sollwert unter Raumtemperatur. 80/0 liegt komfortabel innerhalb
    der Schwellen und ist damit ein unstrittiger PASS.
    """

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
    for d in (good, wrong):
        await radio.register(d)
    # Das stumme Geraet hat nie gefunkt: kein Ausgangs-Reading.
    await radio.register(silent, seed_uplink=False)
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

    # FW-Abfrage ging an die erreichbaren Geraete, nicht an das stumme:
    # einen Befehl an ein Geraet zu haengen, das nicht funkt, fuellt nur die
    # Warteschlange (Sprint 19 / T5).
    assert set(radio.fw_queries) == {good.dev_eui, wrong.dev_eui}

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
    await radio.register(good)
    await radio.register(silent)
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
    await radio.register(dev)
    patch_radio(radio)

    report = await run_batch_inbound_test(session, [dev], timeout_s=60, poll_interval_s=10)
    assert report.results[0].status == "fail"
    assert "schliesst nicht" in report.results[0].reason


async def test_batch_valve_check_can_be_disabled(
    session: AsyncSession,
    patch_radio: Callable[[FakeRadio], None],
) -> None:
    dev = await _make_pool_device(session, "021", fw="4.5")
    radio = FakeRadio(session, {dev.dev_eui: _antwortet(valve_high=42, valve_low=42)})
    await radio.register(dev)
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
    await radio.register(dev)
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
    assert audit.new_value["setpoint_high"]["outcome"] == "ok"
    assert audit.new_value["setpoint_high"]["target_c"] == SETPOINT_HIGH_C
    assert audit.new_value["setpoint_low"]["outcome"] == "ok"
    # Die gemessene Openness steht auch bei PASS im Audit (Sprint 19 / R3):
    # ohne die Werte der bestandenen Laeufe kann niemand die Schwellen gegen
    # echte Geraete nachziehen.
    assert audit.new_value["setpoint_high"]["valve_position"] == 80
    assert audit.new_value["setpoint_low"]["valve_position"] == 0
    assert audit.new_value["setpoint_high"]["valve_reading_at"] is not None


async def test_batch_timeout_device_audit_records_timeout(
    session: AsyncSession,
    patch_radio: Callable[[FakeRadio], None],
) -> None:
    dev = await _make_pool_device(session, "031", fw=None)
    radio = FakeRadio(session, {dev.dev_eui: _schweigt})
    await radio.register(dev, seed_uplink=False)
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
    await radio.register(dev)
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


# ---------------------------------------------------------------------------
# Sprint 19 — Setzframe, Backplate-Gate, Downlink-Disziplin
# ---------------------------------------------------------------------------


async def test_openness_comes_from_the_frame_after_the_readback(
    session: AsyncSession,
    patch_radio: Callable[[FakeRadio], None],
) -> None:
    """T1 — der Kern des Sprints.

    Das Geraet startet geschlossen (0 %), bekommt den hohen Sollwert und
    oeffnet auf 80 %. Der Readback-Frame traegt noch die **alte** Stellung,
    weil mit genau diesem Uplink der Downlink erst zugestellt wurde. Wer ihn
    bewertet, liest 0 % beim hohen Sollwert und urteilt "oeffnet nicht" — an
    einem Geraet, das einwandfrei arbeitet.

    Sollwert aus der Spezifikation: bewertet wird der Folge-Uplink.
    """
    dev = await _make_pool_device(session, "050", fw="4.5")
    radio = FakeRadio(session, {dev.dev_eui: _antwortet(valve_high=80, valve_low=0)})
    await radio.register(dev, valve_start=0)
    patch_radio(radio)

    report = await run_batch_inbound_test(session, [dev], timeout_s=600, poll_interval_s=10)

    r = report.results[0]
    assert r.status == "pass", r.reason
    assert r.high is not None and r.low is not None
    assert r.high.valve_position == 80
    # Der Setzframe liegt NACH dem Readback-Frame, nicht gleichzeitig.
    assert r.high.valve_reading_at is not None
    assert r.high.reading_at is not None
    assert r.high.valve_reading_at > r.high.reading_at


async def test_missing_follow_up_frame_is_timeout_not_fail(
    session: AsyncSession,
    patch_radio: Callable[[FakeRadio], None],
) -> None:
    """T1 — Readback ja, Folge-Uplink nein: Funk-Befund, kein Hardware-Verdacht.

    Der Readback beweist, dass das Geraet funkt und den Befehl verarbeitet
    hat. Bleibt der Folge-Uplink aus, ist die Ventilstellung ungeprueft — das
    ist dieselbe Lage wie ein ausgebliebener Uplink und darf kein Geraet in
    den Karton schicken.
    """
    dev = await _make_pool_device(session, "051", fw="4.5")

    class NurReadback(FakeRadio):
        """Liefert je Sollwert genau EINEN Frame: den Readback. Dann Stille."""

        async def _deliver(self) -> None:
            for dev_eui, target in list(self.sent):
                key = (dev_eui, target)
                if self._frames.get(key, 0) >= 1:
                    continue
                self.session.add(
                    SensorReading(
                        time=self.now,
                        device_id=self._device_ids[dev_eui],
                        fcnt=sum(self._frames.values()) + 1,
                        temperature=Decimal("21.0"),
                        setpoint=Decimal(target),
                        valve_position=0,
                        attached_backplate=True,
                    )
                )
                await self.session.flush()
                self._frames[key] = 1

    radio = NurReadback(session, {dev.dev_eui: _antwortet()})
    await radio.register(dev)
    patch_radio(radio)

    report = await run_batch_inbound_test(session, [dev], timeout_s=60, poll_interval_s=10)
    r = report.results[0]
    assert r.status == "timeout", r.reason
    assert "kein weiterer Uplink" in r.reason
    assert r.high is not None
    assert r.high.outcome == "valve_timeout"


async def test_no_backplate_is_passed_ohne_motor_and_sends_no_setpoint(
    session: AsyncSession,
    patch_radio: Callable[[FakeRadio], None],
) -> None:
    """T3 — ohne Backplate wird der Motor nicht geprueft, statt zu scheitern.

    Ohne Backplate meldet die Vicki ``motorRange 0``; das Ventil bewegt sich
    nie. Ein Sollwert-Test kann dort nichts belegen. Entscheidend ist, dass
    **kein Downlink** rausgeht — sonst kostet der Lauf Batterie und Wartezeit
    fuer eine Pruefung, die nicht stattfinden kann.
    """
    dev = await _make_pool_device(session, "060", fw="4.5")
    radio = FakeRadio(session, {dev.dev_eui: _antwortet()})
    await radio.register(dev, backplate=False)
    patch_radio(radio)

    report = await run_batch_inbound_test(session, [dev], timeout_s=60, poll_interval_s=10)

    r = report.results[0]
    assert r.status == "passed_ohne_motor", r.reason
    assert "Backplate" in r.reason
    assert radio.sent == []
    assert report.exit_code == 0
    assert report.passed_without_motor == [r]

    text = format_report(report)
    assert "[OHNE MOTOR]" in text
    assert "1 OHNE MOTOR" in text
    assert "--require-motor" in text


async def test_unknown_backplate_counts_as_not_attached(
    session: AsyncSession,
    patch_radio: Callable[[FakeRadio], None],
) -> None:
    """T3 — NULL ist nicht False, belegt aber auch keine Montage.

    Ein Reading ohne das Feld (alter Codec) ist kein Beleg dafuer, dass das
    Geraet auf der Backplate sitzt. Dieselbe Regel wie in Layer 4, wo NULL
    das Geraet aus dem Detached-Trigger heraushaelt statt es hineinzuziehen.
    """
    dev = await _make_pool_device(session, "061", fw="4.5")
    radio = FakeRadio(session, {dev.dev_eui: _antwortet()})
    await radio.register(dev, backplate=None)
    patch_radio(radio)

    report = await run_batch_inbound_test(session, [dev], timeout_s=60, poll_interval_s=10)
    assert report.results[0].status == "passed_ohne_motor"
    assert "alter Codec" in report.results[0].reason
    assert radio.sent == []


async def test_require_motor_turns_missing_backplate_into_fail(
    session: AsyncSession,
    patch_radio: Callable[[FakeRadio], None],
) -> None:
    """T3 — ``--require-motor``: der Montage-Lauf duldet kein "ungeprueft".

    Nach der Montage IST das Geraet auf der Backplate. Meldet es das nicht,
    ist das ein Befund und kein Tischzustand.
    """
    ohne = await _make_pool_device(session, "070", fw="4.5")
    unklar = await _make_pool_device(session, "071", fw="4.5")
    radio = FakeRadio(
        session,
        {ohne.dev_eui: _antwortet(), unklar.dev_eui: _antwortet()},
    )
    await radio.register(ohne, backplate=False)
    await radio.register(unklar, backplate=None)
    patch_radio(radio)

    report = await run_batch_inbound_test(
        session, [ohne, unklar], timeout_s=60, poll_interval_s=10, require_motor=True
    )

    assert {r.status for r in report.results} == {"fail"}
    assert all("--require-motor" in r.reason for r in report.results)
    assert report.passed_without_motor == []
    assert report.exit_code == 1
    assert radio.sent == []


async def test_require_motor_leaves_a_mounted_device_alone(
    session: AsyncSession,
    patch_radio: Callable[[FakeRadio], None],
) -> None:
    """T3 — mit belegter Backplate aendert das Flag nichts."""
    dev = await _make_pool_device(session, "072", fw="4.5")
    radio = FakeRadio(session, {dev.dev_eui: _antwortet()})
    await radio.register(dev, backplate=True)
    patch_radio(radio)

    report = await run_batch_inbound_test(
        session, [dev], timeout_s=600, poll_interval_s=10, require_motor=True
    )
    assert report.results[0].status == "pass", report.results[0].reason


async def test_only_one_downlink_per_device_is_outstanding(
    session: AsyncSession,
    patch_radio: Callable[[FakeRadio], None],
) -> None:
    """T5 — S4: zwischen zwei Befehlen an dasselbe Geraet liegt ein Uplink.

    Class A liefert einen Downlink je Uplink aus. Bis Sprint 18 lagen
    FW-Abfrage und Sollwert hintereinander in der Queue; der Sollwert wurde
    dadurch eine ganze Periode spaeter zugestellt und war bis dahin nicht von
    "nicht angekommen" zu unterscheiden.

    Der Test protokolliert Sende- und Empfangszeitpunkte und verlangt, dass
    zwischen zwei Sendungen mindestens ein Uplink liegt.
    """
    dev = await _make_pool_device(session, "080", fw="4.5")

    ereignisse: list[tuple[datetime, str]] = []

    class Protokoll(FakeRadio):
        async def send_setpoint(self, dev_eui: str, setpoint_c: int) -> str:
            ereignisse.append((self.now, f"send:{setpoint_c}"))
            return await super().send_setpoint(dev_eui, setpoint_c)

        async def query_firmware_version(self, dev_eui: str) -> str:
            ereignisse.append((self.now, "send:fw"))
            return await super().query_firmware_version(dev_eui)

        async def _deliver(self) -> None:
            vorher = sum(self._frames.values())
            await super()._deliver()
            if sum(self._frames.values()) > vorher:
                ereignisse.append((self.now, "uplink"))

    radio = Protokoll(session, {dev.dev_eui: _antwortet()})
    await radio.register(dev)
    patch_radio(radio)

    await run_batch_inbound_test(session, [dev], timeout_s=600, poll_interval_s=10)

    sendungen = [i for i, (_, art) in enumerate(ereignisse) if art.startswith("send:")]
    assert len(sendungen) == 3, ereignisse
    for links, rechts in zip(sendungen, sendungen[1:], strict=False):
        dazwischen = [art for _, art in ereignisse[links + 1 : rechts] if art == "uplink"]
        assert dazwischen, f"kein Uplink zwischen {ereignisse[links]} und {ereignisse[rechts]}"


async def test_firmware_query_comes_last(
    session: AsyncSession,
    patch_radio: Callable[[FakeRadio], None],
) -> None:
    """T5 — die FW-Abfrage steht hinter den Sollwerten, nicht davor."""
    dev = await _make_pool_device(session, "081", fw="4.5")

    reihenfolge: list[str] = []

    class Protokoll(FakeRadio):
        async def send_setpoint(self, dev_eui: str, setpoint_c: int) -> str:
            reihenfolge.append(f"setpoint:{setpoint_c}")
            return await super().send_setpoint(dev_eui, setpoint_c)

        async def query_firmware_version(self, dev_eui: str) -> str:
            reihenfolge.append("fw")
            return await super().query_firmware_version(dev_eui)

    radio = Protokoll(session, {dev.dev_eui: _antwortet()})
    await radio.register(dev)
    patch_radio(radio)

    await run_batch_inbound_test(session, [dev], timeout_s=600, poll_interval_s=10)
    assert reihenfolge == [f"setpoint:{SETPOINT_HIGH_C}", f"setpoint:{SETPOINT_LOW_C}", "fw"]


async def test_stale_reading_is_waited_out_not_failed(
    session: AsyncSession,
    patch_radio: Callable[[FakeRadio], None],
) -> None:
    """T4 — ein Reading jenseits der Frische fuehrt nicht sofort zum Urteil.

    Das Ausgangs-Reading liegt jenseits von ``HEARTBEAT_WAIT_MAX_S``. Der
    Vor-Check wartet, das Geraet meldet sich, der Lauf geht weiter. Vor
    Sprint 19 waere hier sofort abgebrochen worden — bei 10 Minuten Keepalive
    traf das im Mittel jedes zweite gesunde Geraet.
    """
    dev = await _make_pool_device(session, "090", fw="4.5")
    radio = FakeRadio(session, {dev.dev_eui: _antwortet()})
    await radio.register(dev, seed_uplink=False)
    session.add(
        SensorReading(
            time=T0 - timedelta(seconds=HEARTBEAT_WAIT_MAX_S + 300),
            device_id=dev.id,
            fcnt=0,
            temperature=Decimal("21.0"),
            setpoint=Decimal(21),
            valve_position=0,
            attached_backplate=True,
        )
    )
    await session.flush()

    gemeldet = False
    original_sleep = radio.sleep

    async def sleep_and_report(seconds: float) -> None:
        nonlocal gemeldet
        await original_sleep(seconds)
        if not gemeldet:
            gemeldet = True
            session.add(
                SensorReading(
                    time=radio.now,
                    device_id=dev.id,
                    fcnt=1,
                    temperature=Decimal("21.0"),
                    setpoint=Decimal(21),
                    valve_position=0,
                    attached_backplate=True,
                )
            )
            await session.flush()

    radio.sleep = sleep_and_report  # type: ignore[method-assign]
    patch_radio(radio)

    report = await run_batch_inbound_test(session, [dev], timeout_s=600, poll_interval_s=10)
    assert report.results[0].status == "pass", report.results[0].reason
