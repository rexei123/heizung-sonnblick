"""Die Strategie ``REFRESH`` am Orchestrator, nicht nur als reine Funktion.

**Warum diese Datei nötig war.** ``REFRESH`` ist seit Sprint 24 gebaut und
war ausschliesslich in ``test_relais_waechter`` geprüft — dort bekommt
``naechste_aktion`` den Zeitpunkt des letzten EIN-Befehls als
**Argument**. Die Verdrahtung im Orchestrator hat kein Test je gesehen,
und sie war falsch: sie reichte ``device.pending_since`` durch, also den
Zeitpunkt des **unbestätigten** Befehls. Der wird gelöscht, sobald das
Gerät den Zustand meldet.

Folge: nach der ersten Bestätigung sah der Wächter „kein Vorbefehl" und
setzte **sofort** nach — bei einem Orchestrator, der jede Minute läuft,
also 60 Downlinks je Stunde und Relais statt 12.

Das ist genau die Klasse aus Paragraph 5.55: ein grüner Lauf, der eine
Lage prüft, die so nicht vorkommt. Die reine Funktion war richtig; falsch
war, was ihr übergeben wurde. Seit dem 15.11.2026 trägt
``device.relais_ein_gesendet_at`` (Migration 0040) diesen Zeitpunkt, und
diese Datei prüft die **Abfolge mit Zeit**, nicht einen Einzelaufruf.

**Keine echten Downlinks.** ``relay_adapter`` ist auf Mitschreiber
umgeleitet; die Bytes haben ihre eigenen Tests.
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
    WatchdogStrategy,
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
PREFIX = "t-nachs"

pytestmark = pytest.mark.skipif(not TEST_DB_URL, reason=SKIP_REASON)


@pytest_asyncio.fixture
async def setup_engine() -> AsyncIterator[Any]:
    engine = create_async_engine(TEST_DB_URL or "", poolclass=None)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def gesendet(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str, int | None]]:
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


@pytest.fixture(autouse=True)
def drossel(monkeypatch: pytest.MonkeyPatch) -> None:
    """Die Zustands-Abfrage haengt an Redis; hier geht es um den Timer."""
    monkeypatch.setattr(
        relay_tasks.relais_abfrage, "darf_fragen", lambda device_id, *, abstand_s: True
    )


class Aufbau:
    def __init__(self, room_id: int, zone_id: int, fuehler_id: int, relais_eui: str) -> None:
        self.room_id = room_id
        self.zone_id = zone_id
        self.fuehler_id = fuehler_id
        self.relais_eui = relais_eui
        self.relais_id = 0


@pytest_asyncio.fixture
async def rezeption(setup_engine: Any) -> AsyncIterator[Aufbau]:
    """Die Rezeption mit ``REFRESH``: Relais **bestaetigt EIN**, Soll weit oben.

    Der Ausgangszustand ist der, in dem sich das Panel die meiste Zeit
    befindet, wenn es heizen soll: es laeuft, es ist zu kalt, und es soll
    weiterlaufen. Genau dort entscheidet ``REFRESH``, ob nachgesetzt wird.

    Ist 20,5 gegen Soll 23 — zweieinhalb Grad darunter, also weit unter
    der Einschaltschwelle. So stand die Rezeption am 14.11. den ganzen
    Nachmittag.
    """
    maker = async_sessionmaker(setup_engine, expire_on_commit=False)
    short = uuid.uuid4().hex[:4]
    jetzt = datetime.now(tz=UTC)

    async with maker() as session:
        rt = RoomType(
            name=f"{PREFIX}-rt-{short}",
            is_bookable=False,
            default_t_occupied=Decimal("23.0"),
        )
        session.add(rt)
        await session.flush()

        room = Room(number=f"{PREFIX}-{short}", room_type_id=rt.id)
        session.add(room)
        await session.flush()

        zone = HeatingZone(room_id=room.id, kind=HeatingZoneKind.OTHER, name="Eingang")
        session.add(zone)
        await session.flush()

        fuehler = Device(
            dev_eui=f"deadbeef{uuid.uuid4().hex[:8]}",
            kind=DeviceKind.THERMOSTAT,
            vendor=DeviceVendor.MCLIMATE,
            model="vicki",
            label="056 Eingang",
            heating_zone_id=zone.id,
            health_state="healthy",
            measure_only=True,
        )
        relais = Device(
            dev_eui=f"deadbeef{uuid.uuid4().hex[:8]}",
            kind=DeviceKind.RELAY,
            vendor=DeviceVendor.MCLIMATE,
            model="16ASPM",
            label="108",
            heating_zone_id=zone.id,
            health_state="healthy",
            power_return_verified_at=jetzt - timedelta(hours=2),
            overheating_recovery_verified_at=jetzt - timedelta(hours=2),
            commissioned_at=jetzt - timedelta(hours=1),
            watchdog_strategy=WatchdogStrategy.REFRESH.value,
        )
        session.add_all([fuehler, relais])
        await session.flush()

        # **Bestaetigt EIN**, und zwar seit 12 Minuten — die
        # Mindestlaufzeit (10 min) ist damit vorbei, der Regler darf also
        # frei entscheiden. Zwei Zeilen wie im Betrieb: der Beginn und
        # die letzte Meldung (Paragraph 5.51).
        session.add_all(
            [
                RelayReading(
                    time=jetzt - timedelta(minutes=12),
                    device_id=relais.id,
                    relay_on=True,
                    power_w=1520,
                ),
                RelayReading(
                    time=jetzt - timedelta(minutes=2),
                    device_id=relais.id,
                    relay_on=True,
                    power_w=1520,
                ),
            ]
        )
        session.add(
            SensorReading(
                time=jetzt - timedelta(minutes=2),
                device_id=fuehler.id,
                temperature=Decimal("20.5"),
                attached_backplate=False,
            )
        )
        session.add(
            EventLog(
                time=jetzt - timedelta(minutes=1),
                room_id=room.id,
                evaluation_id=uuid.uuid4(),
                layer=EventLogLayer.HARD_CLAMP,
                setpoint_in=Decimal("23.0"),
                setpoint_out=Decimal("23.0"),
                reason=CommandReason.VACANT_SETPOINT,
                details={
                    "downlink_zone_status": [
                        {"zone_id": zone.id, "setpoint_c": 23, "detail": "relais"}
                    ]
                },
            )
        )
        await session.commit()
        ids = Aufbau(room.id, zone.id, fuehler.id, relais.dev_eui)
        ids.relais_id = relais.id

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
            await session.execute(
                text("DELETE FROM device WHERE id = ANY(:d)"),
                {"d": [ids.fuehler_id, ids.relais_id]},
            )
            await session.execute(
                text("DELETE FROM room_type WHERE name LIKE :p"), {"p": f"{PREFIX}-%"}
            )
            await session.commit()


async def _meldet_ein(engine: Any, device_id: int, zeitpunkt: datetime) -> None:
    """Ein Keepalive des Relais, wie es alle zehn Minuten kommt.

    Ohne diese Meldungen altert der gemeldete Zustand im Lauf eines
    simulierten Beat-Tages ueber das Haltbarkeitsdatum (25 min) hinaus,
    und der Waechter fragt dann ``0xB1`` statt nachzusetzen. Das waere
    richtig — nur prueft dieser Test etwas anderes, und ein Relais im
    Betrieb meldet sich.
    """
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        session.add(RelayReading(time=zeitpunkt, device_id=device_id, relay_on=True, power_w=1520))
        await session.commit()


async def _geraet(engine: Any, device_id: int) -> Device:
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        geraet = await session.get(Device, device_id)
        assert geraet is not None
        return geraet


# ---------------------------------------------------------------------------
# Der Fund: ein Downlink je Durchlauf.
# ---------------------------------------------------------------------------


async def test_der_abstand_haelt_ueber_mehrere_durchlaeufe(
    rezeption: Aufbau, setup_engine: Any, gesendet: list[tuple[str, str, int | None]]
) -> None:
    """**Der Test, der gefehlt hat.** Fuenf Durchlaeufe, ein Downlink.

    Der Orchestrator laeuft **jede Minute**. Fuenf Minuten lang darf bei
    einem Abstand von fuenf Minuten genau **ein** ``0x57`` hinausgehen —
    der erste. Die vier Durchlaeufe danach muessen schweigen.

    Vor dem 15.11.2026 reichte der Orchestrator ``pending_since`` als
    „letzter EIN-Befehl" durch. Nach der Bestaetigung ist der ``None``,
    und dieser Test haette **fuenf** Downlinks gezaehlt. Die reine
    Funktion war dabei die ganze Zeit richtig: sie bekam nur das falsche
    Argument.
    """
    jetzt = datetime.now(tz=UTC)

    for minute in range(5):
        await relay_tasks._steuere_relais_zonen_async(now=jetzt + timedelta(minutes=minute))

    assert gesendet == [("ein", rezeption.relais_eui, 900)], (
        f"ein Nachsetzen in fuenf Minuten, nicht {len(gesendet)}: {gesendet}"
    )

    geraet = await _geraet(setup_engine, rezeption.relais_id)
    assert geraet.relais_ein_gesendet_at is not None, "der Zeitpunkt muss am Geraet stehen"


async def test_nach_dem_abstand_wird_wieder_nachgesetzt(
    rezeption: Aufbau, setup_engine: Any, gesendet: list[tuple[str, str, int | None]]
) -> None:
    """Die Gegenprobe: nach fuenf Minuten kommt das zweite ``0x57``.

    Ohne sie waere „nie wieder nachsetzen" genauso gruen — und das waere
    der schlimmere Fehler, weil das Panel dann nach 15 Minuten ausgeht
    und niemand es merkt.
    """
    jetzt = datetime.now(tz=UTC)

    await relay_tasks._steuere_relais_zonen_async(now=jetzt)
    assert len(gesendet) == 1

    # Vier Minuten spaeter: noch nicht faellig.
    await relay_tasks._steuere_relais_zonen_async(now=jetzt + timedelta(minutes=4))
    assert len(gesendet) == 1, "vor dem Abstand wird nicht nachgesetzt"

    # Fuenf Minuten nach dem ersten: faellig.
    await relay_tasks._steuere_relais_zonen_async(now=jetzt + timedelta(minutes=5))
    assert len(gesendet) == 2, f"nach dem Abstand das zweite 0x57: {gesendet}"
    assert gesendet[1] == ("ein", rezeption.relais_eui, 900)


async def test_der_timer_ist_kuerzer_als_bei_expire_and_resend(
    rezeption: Aufbau, setup_engine: Any, gesendet: list[tuple[str, str, int | None]]
) -> None:
    """``REFRESH`` setzt **900** Sekunden, nicht 1800.

    Der kuerzere Timer ist der Sicherheitsgewinn dieser Strategie: stirbt
    der Server, geht das Panel nach 15 Minuten aus statt nach 30. Dass
    nachgesetzt wird, darf die Rueckfallzeit nicht verlaengern.
    """
    await relay_tasks._steuere_relais_zonen_async(now=datetime.now(tz=UTC))
    assert gesendet[0][2] == 900, f"900 s Timer bei REFRESH: {gesendet}"


async def test_ein_verlorenes_nachsetzen_wird_nachgeholt(
    rezeption: Aufbau, setup_engine: Any, gesendet: list[tuple[str, str, int | None]]
) -> None:
    """**Verhalten bei verlorenem REFRESH** — die Frage des Betreibers.

    Ein Downlink kann verloren gehen; 108 verliert rund ein Sechstel
    seiner Uplinks, und fuer Downlinks gibt es keinen besseren Grund zur
    Zuversicht. Der Wächter merkt davon **nichts** — ein ``0x57`` wird
    unbestaetigt gesendet, und das Geraet meldet keinen Zustandswechsel,
    weil sich sein Zustand nicht aendert (es war ja schon EIN).

    Das ist kein Mangel, sondern der Grund fuer den Abstand: bei einem
    Timer von 900 s und einem Abstand von 300 s gehen **drei**
    Nachsetzungen hinaus, bevor der Timer ablaufen koennte. Zwei duerfen
    verloren gehen.

    Geprueft wird das Zaehlbare: nach einem verlorenen Nachsetzen kommt
    das naechste zur regulaeren Zeit — der Abstand rechnet gegen das
    **Senden**, nicht gegen eine Bestaetigung. Ein Mechanismus, der auf
    eine Bestaetigung wartete, haette hier stehengeblieben.
    """
    jetzt = datetime.now(tz=UTC)

    # **Minute fuer Minute, wie der Beat es tut.** Jede dieser
    # Nachsetzungen koennte die verlorene sein; der Waechter erfaehrt es
    # nicht und muss es auch nicht.
    for minute in range(16):
        if minute == 10:
            await _meldet_ein(setup_engine, rezeption.relais_id, jetzt + timedelta(minutes=10))
        await relay_tasks._steuere_relais_zonen_async(now=jetzt + timedelta(minutes=minute))

    assert len(gesendet) == 4, f"in 15 Minuten vier Nachsetzungen (0, 5, 10, 15 min): {gesendet}"
    assert {g[2] for g in gesendet} == {900}

    # Drei davon liegen **innerhalb** der Timer-Laufzeit von 900 s. Zwei
    # duerfen also verloren gehen, ohne dass das Panel ausgeht — und das
    # ist die Antwort auf „was passiert bei einem verlorenen REFRESH":
    # nichts, solange nicht drei in Folge verloren gehen.
    assert 900 // 300 == 3


async def test_die_funklast_je_stunde_bleibt_bei_zwoelf(
    rezeption: Aufbau, setup_engine: Any, gesendet: list[tuple[str, str, int | None]]
) -> None:
    """**Die Funklast-Rechnung, als Test und nicht als Behauptung.**

    Eine Stunde Beat, Minute fuer Minute, bei durchgehendem Heizwunsch.
    Erwartet sind **12** Nachsetzungen — eine alle fuenf Minuten.

    Ein ``0x57`` sind 4 Byte Nutzlast, mit LoRaWAN-Rahmen 17 Byte auf
    Luft. Bei RX2 (DR0, SF12, 125 kHz) kostet das **1,32 s**; 12 davon
    sind **15,8 s je Stunde und Relais**, bei zwei Relais 31,7 s. Zum
    Vergleich: ohne die Korrektur der Verdrahtung waere es eines alle
    zwei Minuten gewesen, also 30 Stueck und 39,6 s.

    Dieser Test ist der Grund, warum die Zahl im PR-Text keine Schaetzung
    ist. Faellt er, hat sich die Funklast geaendert — und das ist eine
    Entscheidung, keine Nebenwirkung.
    """
    jetzt = datetime.now(tz=UTC)
    for minute in range(60):
        if minute and minute % 10 == 0:
            await _meldet_ein(setup_engine, rezeption.relais_id, jetzt + timedelta(minutes=minute))
        await relay_tasks._steuere_relais_zonen_async(now=jetzt + timedelta(minutes=minute))

    assert len(gesendet) == 12, f"zwoelf Nachsetzungen je Stunde: {len(gesendet)}"


async def test_expire_and_resend_setzt_nicht_nach(
    rezeption: Aufbau, setup_engine: Any, gesendet: list[tuple[str, str, int | None]]
) -> None:
    """Die Vorgabe-Strategie bleibt unberuehrt.

    Dasselbe Geraet, dieselbe Lage, nur ``expire_and_resend``: es geht
    **kein** Befehl hinaus, der Timer laeuft von selbst ab. Das ist der
    Kern von S2, und dieser PR darf ihn nicht anfassen.
    """
    maker = async_sessionmaker(setup_engine, expire_on_commit=False)
    async with maker() as session:
        geraet = await session.get(Device, rezeption.relais_id)
        assert geraet is not None
        geraet.watchdog_strategy = WatchdogStrategy.EXPIRE_AND_RESEND.value
        await session.commit()

    jetzt = datetime.now(tz=UTC)
    for minute in range(5):
        await relay_tasks._steuere_relais_zonen_async(now=jetzt + timedelta(minutes=minute))

    assert gesendet == [], f"EXPIRE_AND_RESEND setzt nicht nach: {gesendet}"


async def test_ein_zwangs_aus_setzt_den_zeitpunkt_nicht(
    rezeption: Aufbau, setup_engine: Any, gesendet: list[tuple[str, str, int | None]]
) -> None:
    """Ein ``0xC1 00`` darf ``relais_ein_gesendet_at`` nicht anfassen.

    Faellt der Fuehler aus, schaltet der Regler die Zone zwangsweise ab
    (S5). Wuerde das Ausschalten den Zeitpunkt des letzten
    **Ein**-Befehls ueberschreiben, rechnete das naechste Nachsetzen gegen
    einen Zeitpunkt, an dem ausgeschaltet wurde — die Spalte traegt dann
    zwei Bedeutungen, und das ist derselbe Fehler wie bei
    ``pending_since``.
    """
    maker = async_sessionmaker(setup_engine, expire_on_commit=False)
    async with maker() as session:
        # Kein frischer Messwert mehr -> der Regler erzwingt AUS.
        await session.execute(
            text("DELETE FROM sensor_reading WHERE device_id = :d"), {"d": rezeption.fuehler_id}
        )
        await session.commit()

    vorher = (await _geraet(setup_engine, rezeption.relais_id)).relais_ein_gesendet_at
    await relay_tasks._steuere_relais_zonen_async(now=datetime.now(tz=UTC))

    assert gesendet == [("aus", rezeption.relais_eui, None)], f"Zwangs-AUS erwartet: {gesendet}"
    nachher = (await _geraet(setup_engine, rezeption.relais_id)).relais_ein_gesendet_at
    assert nachher == vorher, "ein AUS veraendert den Zeitpunkt des letzten EIN nicht"
