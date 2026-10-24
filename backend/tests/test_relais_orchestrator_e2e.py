"""Ende-zu-Ende: von der Engine-Entscheidung bis zum bestaetigten Schalten.

**Das Abschlusskriterium von Sprint 24b.** Sprint 24 hatte die
Entscheidungen und keinen, der sie ausfuehrt. Diese Datei beweist, dass
der Weg laeuft: Engine-Sollwert → Zonen-Aggregat → Zweipunktregler →
Waechter → Downlink → Uplink-Bestaetigung → Schaltzyklus.

**Keine echten Downlinks.** ``relay_adapter.relais_ein_fuer`` und
``relais_aus`` sind per ``monkeypatch`` auf Mitschreiber umgeleitet. Die
**Bytes** sind in ``test_relay_adapter``-Nachbarn und im Codec-Test
gepruef; hier geht es um die Abfolge.

**Eigene Session mit echten Commits.** Der Orchestrator oeffnet seine
Session selbst (``_task_session``), wie jeder Beat-Task dieses Projekts.
Ein Test, der ihm eine Rollback-Session unterschiebt, wuerde etwas
anderes pruefen als das, was laeuft. Deshalb echte Commits und
ausdruecklicher Cleanup ueber den Prefix (§5.39).
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from heizung.models.device import Device
from heizung.models.enums import (
    CommandReason,
    DeviceKind,
    DeviceVendor,
    EventLogLayer,
    HeatingZoneKind,
)
from heizung.models.event_log import EventLog
from heizung.models.heating_zone import HeatingZone
from heizung.models.relay_reading import RelayReading
from heizung.models.room import Room
from heizung.models.room_type import RoomType
from heizung.models.sensor_reading import SensorReading
from heizung.tasks import relay_tasks

TEST_DB_URL = os.environ.get("TEST_DATABASE_URL")
SKIP_REASON = "TEST_DATABASE_URL nicht gesetzt - DB-Tests brauchen Postgres"
PREFIX = "t24e2e"

pytestmark = pytest.mark.skipif(not TEST_DB_URL, reason=SKIP_REASON)


@pytest_asyncio.fixture
async def setup_engine() -> AsyncIterator[Any]:
    engine = create_async_engine(TEST_DB_URL or "", poolclass=None)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def gesendet(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str, int | None]]:
    """Mitschreiber fuer Downlinks. ``(art, dev_eui, sekunden)``."""
    aufrufe: list[tuple[str, str, int | None]] = []

    async def _ein(dev_eui: str, sekunden: int) -> str:
        aufrufe.append(("ein", dev_eui, sekunden))
        return "topic/ein"

    async def _aus(dev_eui: str) -> str:
        aufrufe.append(("aus", dev_eui, None))
        return "topic/aus"

    monkeypatch.setattr(relay_tasks.relay_adapter, "relais_ein_fuer", _ein)
    monkeypatch.setattr(relay_tasks.relay_adapter, "relais_aus", _aus)
    return aufrufe


class Aufbau:
    """Die Ids des Testaufbaus, damit die Tests sie nicht durchreichen muessen."""

    def __init__(
        self, room_id: int, zone_id: int, fuehler_id: int, relais_id: int, relais_eui: str
    ):
        self.room_id = room_id
        self.zone_id = zone_id
        self.fuehler_id = fuehler_id
        self.relais_id = relais_id
        self.relais_eui = relais_eui


@pytest_asyncio.fixture
async def aufbau(setup_engine: Any) -> AsyncIterator[Aufbau]:
    """Zimmer „Bar"-Art: eine Zone, ein Fuehler, ein Relais in Betrieb.

    Der Raumtyp ist **nicht buchbar** — so sind die Allgemeinflaechen im
    Haus angelegt (Entscheidung zu Paket F).
    """
    maker = async_sessionmaker(setup_engine, expire_on_commit=False)
    short = uuid.uuid4().hex[:4]
    jetzt = datetime.now(tz=UTC)

    async with maker() as session:
        rt = RoomType(
            name=f"{PREFIX}-rt-{short}",
            is_bookable=False,
            default_t_occupied=Decimal("21.0"),
        )
        session.add(rt)
        await session.flush()

        room = Room(number=f"{PREFIX}-{short}", room_type_id=rt.id)
        session.add(room)
        await session.flush()

        zone = HeatingZone(room_id=room.id, kind=HeatingZoneKind.OTHER, name="Barbereich")
        session.add(zone)
        await session.flush()

        fuehler = Device(
            dev_eui=f"deadbeef{uuid.uuid4().hex[:8]}",
            kind=DeviceKind.THERMOSTAT,
            vendor=DeviceVendor.MCLIMATE,
            model="vicki",
            label="Fuehler",
            heating_zone_id=zone.id,
            health_state="healthy",
            measure_only=True,
        )
        relais = Device(
            dev_eui=f"deadbeef{uuid.uuid4().hex[:8]}",
            kind=DeviceKind.RELAY,
            vendor=DeviceVendor.MCLIMATE,
            model="16ASPM",
            label="Panel",
            heating_zone_id=zone.id,
            health_state="healthy",
            # In Betrieb genommen, beide Ruecklesungen bestanden (S3/S4).
            power_return_verified_at=jetzt - timedelta(hours=2),
            overheating_recovery_verified_at=jetzt - timedelta(hours=2),
            commissioned_at=jetzt - timedelta(hours=1),
        )
        session.add_all([fuehler, relais])
        await session.flush()

        # Der Sollwert der Engine: 21 °C, frisch (das Fenster ist 1 h).
        session.add(
            EventLog(
                time=jetzt - timedelta(minutes=1),
                room_id=room.id,
                evaluation_id=uuid.uuid4(),
                layer=EventLogLayer.HARD_CLAMP,
                setpoint_in=Decimal("21.0"),
                setpoint_out=Decimal("21.0"),
                reason=CommandReason.OCCUPIED_SETPOINT,
                details={"quelle": "e2e-test"},
            )
        )
        # Die Ausgangsmeldung des Relais: AUS. So, wie sie bei der
        # Inbetriebnahme entsteht -- Schritt 4 der Checkliste liest den
        # Zustand mit ``0xB1``, und die Antwort erzeugt diese Zeile.
        #
        # Ohne sie ist der Zustand **unbekannt**, und der Waechter
        # schaltet dann nicht ein, sondern fragt (``0xB1``). Dieser Pfad
        # hat seinen eigenen Test weiter unten.
        session.add(
            RelayReading(
                time=jetzt - timedelta(minutes=30),
                device_id=relais.id,
                relay_on=False,
                power_w=0,
            )
        )
        await session.commit()
        ids = Aufbau(room.id, zone.id, fuehler.id, relais.id, relais.dev_eui)

    try:
        yield ids
    finally:
        async with maker() as session:
            await session.execute(
                text("DELETE FROM event_log WHERE room_id = :r"), {"r": ids.room_id}
            )
            await session.execute(
                text("DELETE FROM relay_reading WHERE device_id = :d"), {"d": ids.relais_id}
            )
            await session.execute(
                text("DELETE FROM sensor_reading WHERE device_id = ANY(:d)"),
                {"d": [ids.fuehler_id, ids.relais_id]},
            )
            await session.execute(text("DELETE FROM room WHERE id = :r"), {"r": ids.room_id})
            # Die Geraete ausdruecklich loeschen: ``room`` CASCADE
            # raeumt die Zonen, aber ``device.heating_zone_id`` ist
            # nullable und wird dabei nur auf NULL gesetzt. Ohne diese
            # Zeile bleiben Relais ohne Zone liegen und sammeln sich bei
            # jedem Lauf (§5.39).
            await session.execute(
                text("DELETE FROM device WHERE id = ANY(:d)"),
                {"d": [ids.fuehler_id, ids.relais_id]},
            )
            await session.execute(
                text("DELETE FROM room_type WHERE name LIKE :p"), {"p": f"{PREFIX}-%"}
            )
            await session.commit()


async def _messwert(engine: Any, device_id: int, temperatur: str, *, vor_minuten: int = 2) -> None:
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        session.add(
            SensorReading(
                time=datetime.now(tz=UTC) - timedelta(minutes=vor_minuten),
                device_id=device_id,
                temperature=Decimal(temperatur),
                attached_backplate=False,
            )
        )
        await session.commit()


async def _relais_meldet(
    engine: Any, device_id: int, ein: bool, *, vor_minuten: int = 0, grund: str | None = None
) -> None:
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        session.add(
            RelayReading(
                time=datetime.now(tz=UTC) - timedelta(minutes=vor_minuten),
                device_id=device_id,
                relay_on=ein,
                power_w=1600 if ein else 0,
                change_reason=grund,
            )
        )
        await session.commit()


async def _geraet(engine: Any, device_id: int) -> Device:
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        geraet = await session.get(Device, device_id)
        assert geraet is not None
        return geraet


# ---------------------------------------------------------------------------
# Szenario 1 — der Heizzyklus. DAS Abschlusskriterium.
# ---------------------------------------------------------------------------


async def test_szenario_1_heizzyklus_laeuft_ende_zu_ende(
    aufbau: Aufbau,
    setup_engine: Any,
    gesendet: list[tuple[str, str, int | None]],
) -> None:
    """Ist unter Soll → ``0x57`` → Uplink EIN → Ist erreicht → AUS.

    Vier Durchlaeufe des Orchestrators, zwischen ihnen die Uplinks, die
    das Geraet geschickt haette. Jeder Schritt prueft **beides**: was
    gesendet wurde und was in der Datenbank steht.
    """
    jetzt = datetime.now(tz=UTC)

    # --- 1. Zone zu kalt: 19,0 gegen Soll 21,0, Schwelle 20,5.
    await _messwert(setup_engine, aufbau.fuehler_id, "19.0")
    e1 = await relay_tasks._steuere_relais_zonen_async(now=jetzt)

    zone = next(z for z in e1["details"] if z["zone_id"] == aufbau.zone_id)
    assert zone["regler"] == "ein", f"Regler sollte einschalten: {zone}"
    assert zone["regler_grund"] == "unter_ein_schwelle"
    assert gesendet == [("ein", aufbau.relais_eui, 1800)], (
        "ein 0x57 mit 30 min — und KEIN 0xC1 01 (S1)"
    )

    geraet = await _geraet(setup_engine, aufbau.relais_id)
    assert geraet.pending_target_on is True, "der offene Befehl ist vermerkt"
    assert geraet.pending_attempts == 1
    assert geraet.switch_cycles == 0, "noch nicht bestaetigt, also noch kein Zyklus"

    # --- 2. Das Geraet meldet EIN. Der Befehl ist bestaetigt.
    await _relais_meldet(setup_engine, aufbau.relais_id, True)
    e2 = await relay_tasks._steuere_relais_zonen_async(now=jetzt + timedelta(seconds=30))

    assert len(gesendet) == 1, "keine Wiederholung nach der Bestaetigung"
    geraet = await _geraet(setup_engine, aufbau.relais_id)
    assert geraet.pending_target_on is None, "offener Befehl geloescht"
    assert geraet.switch_cycles == 1, "ein bestaetigtes EIN ist ein Schaltzyklus"
    zone2 = next(z for z in e2["details"] if z["zone_id"] == aufbau.zone_id)
    assert zone2["gesendet"] == 0

    # --- 3. Noch im Lauf, Zone noch kalt: nichts passiert.
    #
    # Die Standardstrategie setzt NICHT auf ein laufendes EIN nach (S2) —
    # der Timer laeuft von selbst ab.
    e3 = await relay_tasks._steuere_relais_zonen_async(now=jetzt + timedelta(minutes=2))
    zone3 = next(z for z in e3["details"] if z["zone_id"] == aufbau.zone_id)
    assert zone3["gesendet"] == 0, f"nichts senden: {zone3}"
    assert len(gesendet) == 1

    # --- 4. Zone zu warm: 21,5 gegen Soll 21,0, Abschalt-Schwelle 21,3.
    #
    # Die Mindestlaufzeit ist 10 min; wir sind 12 min nach dem
    # Einschalten, sie ist also abgelaufen.
    await _messwert(setup_engine, aufbau.fuehler_id, "21.5", vor_minuten=0)
    e4 = await relay_tasks._steuere_relais_zonen_async(now=jetzt + timedelta(minutes=12))

    zone4 = next(z for z in e4["details"] if z["zone_id"] == aufbau.zone_id)
    assert zone4["regler"] == "aus", f"Regler sollte abschalten: {zone4}"
    assert zone4["regler_grund"] == "ueber_aus_schwelle"
    assert gesendet[-1] == ("aus", aufbau.relais_eui, None)

    # --- 5. Das Geraet meldet AUS.
    await _relais_meldet(setup_engine, aufbau.relais_id, False)
    await relay_tasks._steuere_relais_zonen_async(now=jetzt + timedelta(minutes=13))

    geraet = await _geraet(setup_engine, aufbau.relais_id)
    assert geraet.pending_target_on is None
    assert geraet.switch_cycles == 1, "ein AUS ist kein neuer Zyklus"
    assert len(gesendet) == 2, "genau zwei Downlinks im ganzen Zyklus"


# ---------------------------------------------------------------------------
# Szenario 8 — der Fall aus dem Betrieb
# ---------------------------------------------------------------------------


async def test_szenario_8_zone_mit_fuehler_hat_den_raumtyp_soll(
    aufbau: Aufbau,
    setup_engine: Any,
    gesendet: list[tuple[str, str, int | None]],
) -> None:
    """Reglersoll 21 °C, nicht 10 °C.

    Der Fuehler ist unmontiert und meldet ``attached_backplate=False`` —
    vor Paket 4 haette die Geraete-Sicherheit daraus 10 °C gemacht, und
    der Regler haette bei 19 °C Ist **nicht** eingeschaltet, weil 19 schon
    ueber 10 liegt.

    Der Test prueft deshalb nicht die Schicht (das tun die Tests in
    ``test_fuehler_geraetesicherheit.py``), sondern die **Wirkung** auf den
    Regler: mit 21 °C Soll wird eingeschaltet.
    """
    await _messwert(setup_engine, aufbau.fuehler_id, "19.0")
    e = await relay_tasks._steuere_relais_zonen_async()

    zone = next(z for z in e["details"] if z["zone_id"] == aufbau.zone_id)
    assert zone["soll"] == "21.0"
    assert zone["regler"] == "ein"
    assert len(gesendet) == 1


# ---------------------------------------------------------------------------
# Szenario 6 und die Sperre — M10 und M11
# ---------------------------------------------------------------------------


async def test_szenario_6_ohne_inbetriebnahme_kein_schaltbefehl(
    aufbau: Aufbau,
    setup_engine: Any,
    gesendet: list[tuple[str, str, int | None]],
) -> None:
    """**Mutationsprobe M10.** Auch der Orchestrator haelt sich an S3."""
    maker = async_sessionmaker(setup_engine, expire_on_commit=False)
    async with maker() as session:
        geraet = await session.get(Device, aufbau.relais_id)
        assert geraet is not None
        geraet.commissioned_at = None
        await session.commit()

    await _messwert(setup_engine, aufbau.fuehler_id, "19.0")
    e = await relay_tasks._steuere_relais_zonen_async()

    assert gesendet == [], "kein einziger Schaltbefehl"
    zone = next(z for z in e["details"] if z["zone_id"] == aufbau.zone_id)
    assert zone["uebersprungen"] == 1


async def test_szenario_5_schutz_sperre_haelt_die_zone_aus(
    aufbau: Aufbau,
    setup_engine: Any,
    gesendet: list[tuple[str, str, int | None]],
) -> None:
    """**Mutationsprobe M11.** Eine stehende Sperre schlaegt den Regler."""
    maker = async_sessionmaker(setup_engine, expire_on_commit=False)
    async with maker() as session:
        geraet = await session.get(Device, aufbau.relais_id)
        assert geraet is not None
        geraet.protection_tripped_at = datetime.now(tz=UTC) - timedelta(minutes=5)
        geraet.protection_kind = "overheating"
        await session.commit()

    await _messwert(setup_engine, aufbau.fuehler_id, "19.0")
    e = await relay_tasks._steuere_relais_zonen_async()

    assert gesendet == [], "gesperrt heisst gesperrt, auch wenn es kalt ist"
    zone = next(z for z in e["details"] if z["zone_id"] == aufbau.zone_id)
    assert zone["uebersprungen"] == 1


# ---------------------------------------------------------------------------
# Szenario 3 — Fuehler faellt aus
# ---------------------------------------------------------------------------


async def test_szenario_3_veralteter_fuehler_schaltet_aus(
    aufbau: Aufbau,
    setup_engine: Any,
    gesendet: list[tuple[str, str, int | None]],
) -> None:
    """Kein frischer Messwert → AUS, auch wenn es kalt ist (S5).

    Der Messwert ist sechs Stunden alt; das Fenster ist das
    Zweieinhalbfache der ``healthy``-Grenze (2 h), also 5 h.
    """
    await _messwert(setup_engine, aufbau.fuehler_id, "19.0", vor_minuten=360)
    await _relais_meldet(setup_engine, aufbau.relais_id, True, vor_minuten=20)

    e = await relay_tasks._steuere_relais_zonen_async()

    zone = next(z for z in e["details"] if z["zone_id"] == aufbau.zone_id)
    assert zone["regler"] == "aus"
    assert zone["regler_grund"] == "fuehler_veraltet"
    assert gesendet[-1][0] == "aus"


async def test_ohne_jeden_messwert_wird_nicht_eingeschaltet(
    aufbau: Aufbau,
    gesendet: list[tuple[str, str, int | None]],
) -> None:
    """Kein Istwert heisst AUS, nicht „letzten Zustand halten".

    Entscheidung aus Sprint 24 (AE-78 §9.3): ein Panel ohne Rueckmeldung,
    das weiterheizt, ist ein Sicherheitsfall; ein kaltes Zimmer ist ein
    Beschwerdefall.
    """
    e = await relay_tasks._steuere_relais_zonen_async()
    zone = next(z for z in e["details"] if z["zone_id"] == aufbau.zone_id)
    assert zone["regler_grund"] == "kein_istwert"
    assert gesendet == [], "nichts zu senden — das Relais ist ohnehin aus"


# ---------------------------------------------------------------------------
# Szenario 2 — Serverausfall
# ---------------------------------------------------------------------------


async def test_szenario_2_nach_timer_ablauf_wird_neu_gesetzt(
    aufbau: Aufbau,
    setup_engine: Any,
    gesendet: list[tuple[str, str, int | None]],
) -> None:
    """Der Timer laeuft ab, das Geraet meldet AUS, der Regler setzt neu.

    Das ist der Serverausfall aus der Sicht danach: waehrend der Server
    weg war, ist der Timer abgelaufen und das Relais abgefallen — genau
    die Eigenschaft, fuer die S1 gebaut ist. Nach dem Neustart sieht der
    Orchestrator ein AUS-Relais in einer kalten Zone und faengt sauber
    wieder an.
    """
    await _messwert(setup_engine, aufbau.fuehler_id, "19.0")
    # Das Geraet war ein und hat nach Ablauf AUS gemeldet.
    await _relais_meldet(setup_engine, aufbau.relais_id, True, vor_minuten=40)
    await _relais_meldet(setup_engine, aufbau.relais_id, False, vor_minuten=10, grund="radio_timer")

    e = await relay_tasks._steuere_relais_zonen_async()

    zone = next(z for z in e["details"] if z["zone_id"] == aufbau.zone_id)
    assert zone["regler"] == "ein"
    assert gesendet == [("ein", aufbau.relais_eui, 1800)]


# ---------------------------------------------------------------------------
# Unbekannter Zustand: fragen statt schweigen
# ---------------------------------------------------------------------------


async def test_unbekannter_zustand_fragt_statt_zu_schweigen(
    aufbau: Aufbau,
    setup_engine: Any,
    gesendet: list[tuple[str, str, int | None]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """**Der Fall, den der Ende-zu-Ende-Test gefunden hat.**

    Ohne Zeile in ``relay_reading`` ist der Zustand unbekannt, und der
    Waechter schaltet dann bewusst nicht ein. Das allein wuerde ein
    frisches Relais **dauerhaft** stilllegen: ohne Zustand kein Befehl,
    ohne Befehl keine Zeile.

    Der Orchestrator sendet deshalb ``0xB1`` — einen Lese-Befehl, der
    nichts schaltet. Beim naechsten Durchlauf ist der Zustand bekannt.
    """
    gefragt: list[str] = []

    async def _frage(dev_eui: str) -> str:
        gefragt.append(dev_eui)
        return "topic/frage"

    monkeypatch.setattr(relay_tasks.relay_adapter, "frage_zustand", _frage)

    maker = async_sessionmaker(setup_engine, expire_on_commit=False)
    async with maker() as session:
        await session.execute(
            text("DELETE FROM relay_reading WHERE device_id = :d"),
            {"d": aufbau.relais_id},
        )
        await session.commit()

    await _messwert(setup_engine, aufbau.fuehler_id, "19.0")
    e = await relay_tasks._steuere_relais_zonen_async()

    assert gesendet == [], "kein Schaltbefehl bei unbekanntem Zustand"
    assert gefragt == [aufbau.relais_eui], "aber eine Abfrage"
    zone = next(z for z in e["details"] if z["zone_id"] == aufbau.zone_id)
    assert zone.get("gefragt") == 1
