"""Relais-Uplinks: Zeitreihe und Schutz-Sperre (Sprint 24b, Paket 5).

Zwei Teile, und der zweite ist eine Zusicherung:

1. Der Codec-Ausgang wird auf eine ``relay_reading``-Zeile projiziert.
   Das ist die einzige Quelle fuer den bestaetigten Schaltzustand —
   ohne diesen Schreibpfad findet der Waechter nie einen Zustand.
2. Eine Schutzauslösung sperrt das Relais (S4). Die Sperre hebt nur ein
   Admin auf; das Geraet erholt sich **selbst**, und ohne Sperre waere
   der Vorfall nach einer Minute unsichtbar.

Dazu der Befund aus Paket 4: ein Relais wird nicht mehr dauerhaft als
``silent`` eingestuft, weil die Health-Berechnung jetzt
``relay_reading`` liest.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from heizung.models.device import Device
from heizung.models.enums import DeviceKind, DeviceVendor, HeatingZoneKind
from heizung.models.heating_zone import HeatingZone
from heizung.models.relay_reading import RelayReading
from heizung.models.room import Room
from heizung.models.room_type import RoomType
from heizung.services import relay_service, relay_uplink
from heizung.tasks.health_tasks import HealthSchwellen, _basis_state_from_age

TEST_DB_URL = os.environ.get("TEST_DATABASE_URL")
SKIP_REASON = "TEST_DATABASE_URL nicht gesetzt - DB-Tests brauchen Postgres"
PREFIX = "t24up"

pytestmark = pytest.mark.skipif(not TEST_DB_URL, reason=SKIP_REASON)

#: Ein vollstaendiger Keepalive, wie der Codec ihn liefert.
KEEPALIVE = {
    "report_type": "keepalive",
    "internalTemperature": 31,
    "energy_raw": 1234567,
    "energy_kWh": 1234.567,
    "power_W": 1600,
    "acVoltage_V": 230,
    "acCurrent_mA": 7000,
    "relayState": "ON",
}


@pytest_asyncio.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(TEST_DB_URL or "", poolclass=None)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
        await session.rollback()
    await engine.dispose()


async def _relais(session: AsyncSession, *, marker: str) -> Device:
    short = uuid.uuid4().hex[:4]
    rt = RoomType(name=f"{PREFIX}-rt-{marker}-{short}", is_bookable=False)
    session.add(rt)
    await session.flush()
    room = Room(number=f"{PREFIX}-{marker}-{short}", room_type_id=rt.id)
    session.add(room)
    await session.flush()
    zone = HeatingZone(room_id=room.id, kind=HeatingZoneKind.OTHER, name="Barbereich")
    session.add(zone)
    await session.flush()
    jetzt = datetime.now(tz=UTC)
    dev = Device(
        dev_eui=f"beef{uuid.uuid4().hex[:12]}",
        kind=DeviceKind.RELAY,
        vendor=DeviceVendor.MCLIMATE,
        model="16ASPM",
        label="Panel",
        heating_zone_id=zone.id,
        health_state="healthy",
        power_return_verified_at=jetzt - timedelta(hours=1),
        overheating_recovery_verified_at=jetzt - timedelta(hours=1),
        commissioned_at=jetzt - timedelta(minutes=30),
    )
    session.add(dev)
    await session.flush()
    return dev


# ---------------------------------------------------------------------------
# Projektion
# ---------------------------------------------------------------------------


def test_keepalive_wird_vollstaendig_projiziert() -> None:
    jetzt = datetime(2026, 10, 24, 9, 0, tzinfo=UTC)
    werte = relay_uplink.werte_aus_codec(KEEPALIVE, device_id=7, zeit=jetzt, fcnt=42)

    assert werte["device_id"] == 7
    assert werte["fcnt"] == 42
    assert werte["relay_on"] is True
    assert werte["power_w"] == 1600
    assert werte["energy_wh"] == 1234567, "der Rohzaehler in Wh, nicht die kWh"
    assert werte["ac_voltage_v"] == 230
    assert werte["ac_current_ma"] == 7000
    assert werte["internal_temperature_raw"] == 31


def test_befehlsantwort_ohne_keepalive_laesst_felder_leer() -> None:
    """Laut Doku kann der Keepalive-Schwanz fehlen.

    Dann sagt der Uplink nichts ueber Leistung oder Energie, und eine 0
    waere dort eine Behauptung. ``None`` heisst „diese Zeile sagt nichts
    darueber" — dieselbe Drei-Zustands-Regel wie bei ``open_window``.
    """
    nur_antwort = {"report_type": "command_response", "relayState": "OFF"}
    werte = relay_uplink.werte_aus_codec(
        nur_antwort, device_id=7, zeit=datetime.now(tz=UTC), fcnt=1
    )
    assert werte["relay_on"] is False
    assert werte["power_w"] is None
    assert werte["energy_wh"] is None
    assert werte["internal_temperature_raw"] is None


def test_uplink_ohne_zustand_sagt_nichts_ueber_den_zustand() -> None:
    """``relayState`` fehlt → ``relay_on`` bleibt ``None``.

    Wichtig fuer ``relay_state.bestaetigter_zustand``: eine solche Zeile
    darf keinen Wechsel vortaeuschen, und der Helfer filtert sie
    ausdruecklich aus.
    """
    werte = relay_uplink.werte_aus_codec(
        {"relayChangeReason": "radio_timer"}, device_id=7, zeit=datetime.now(tz=UTC), fcnt=1
    )
    assert werte["relay_on"] is None
    assert werte["change_reason"] == "radio_timer"


# ---------------------------------------------------------------------------
# Schreibpfad
# ---------------------------------------------------------------------------


async def test_uplink_landet_in_der_zeitreihe(db_session: AsyncSession) -> None:
    dev = await _relais(db_session, marker="wr")
    jetzt = datetime.now(tz=UTC)

    await relay_uplink.verarbeite_relais_uplink(
        db_session, device_id=dev.id, obj=KEEPALIVE, zeit=jetzt, fcnt=5
    )
    await db_session.flush()

    zeilen = (
        (
            await db_session.execute(
                select(RelayReading.relay_on, RelayReading.power_w).where(
                    RelayReading.device_id == dev.id
                )
            )
        )
        .tuples()
        .all()
    )
    assert zeilen == [(True, 1600)]


async def test_derselbe_frame_zweimal_erzeugt_eine_zeile(
    db_session: AsyncSession,
) -> None:
    """Idempotenz wie bei ``sensor_reading``: ``ON CONFLICT DO NOTHING``.

    MQTT stellt mindestens einmal zu, und ein doppelter Frame darf keine
    zweite Zeile erzeugen — sonst zaehlt der Waechter einen Wechsel, den
    es nicht gab.
    """
    dev = await _relais(db_session, marker="idem")
    jetzt = datetime.now(tz=UTC)
    for _ in range(2):
        await relay_uplink.verarbeite_relais_uplink(
            db_session, device_id=dev.id, obj=KEEPALIVE, zeit=jetzt, fcnt=5
        )
    await db_session.flush()

    anzahl = (
        await db_session.execute(
            text("SELECT count(*) FROM relay_reading WHERE device_id = :d"),
            {"d": dev.id},
        )
    ).scalar()
    assert anzahl == 1


# ---------------------------------------------------------------------------
# Szenario 5 — Schutzausloesung
# ---------------------------------------------------------------------------


async def test_schutzausloesung_sperrt_und_haelt_die_zone_aus(
    db_session: AsyncSession,
) -> None:
    """**Szenario 5.** Ueberhitzung → Sperre → ``darf_schalten`` ist aus."""
    dev = await _relais(db_session, marker="prot")
    assert relay_service.darf_schalten(dev) is True

    frame = dict(KEEPALIVE)
    frame.update(
        {
            "relayState": "OFF",
            "protection": "overheating",
            "protectionEventCount": 1,
            "protectionTemperatureC": 88,
        }
    )
    protokoll = await relay_uplink.verarbeite_relais_uplink(
        db_session, device_id=dev.id, obj=frame, zeit=datetime.now(tz=UTC), fcnt=9
    )

    assert protokoll["sperre_gesetzt"] is True
    # ``flush`` und NICHT ``refresh``: ``setze_schutz_sperre`` mutiert das
    # ORM-Objekt ohne zu schreiben, und ``refresh`` wuerde die Zeile neu
    # lesen und die Aenderung damit verwerfen. Derselbe Fehler ist in
    # dieser Sitzung schon einmal passiert.
    await db_session.flush()
    assert dev.protection_tripped_at is not None
    assert dev.protection_kind == "overheating"
    assert relay_service.darf_schalten(dev) is False


async def test_zweite_meldung_verschiebt_den_beginn_nicht(
    db_session: AsyncSession,
) -> None:
    """Bei Ueberstrom meldet das Geraet so lange, wie der Strom zu hoch ist.

    Jede Folgemeldung wuerde den Beginn des Vorfalls nach vorn schieben
    und damit die Frage „seit wann" unbeantwortbar machen.
    """
    dev = await _relais(db_session, marker="wdh")
    frame = {"relayState": "OFF", "protection": "overcurrent"}

    await relay_uplink.verarbeite_relais_uplink(
        db_session, device_id=dev.id, obj=frame, zeit=datetime.now(tz=UTC), fcnt=1
    )
    await db_session.flush()
    erster = dev.protection_tripped_at

    zweites = await relay_uplink.verarbeite_relais_uplink(
        db_session,
        device_id=dev.id,
        obj=frame,
        zeit=datetime.now(tz=UTC) + timedelta(minutes=1),
        fcnt=2,
    )
    await db_session.flush()

    assert zweites["sperre_gesetzt"] is False
    assert dev.protection_tripped_at == erster


async def test_erholungsmeldung_hebt_die_sperre_nicht_auf(
    db_session: AsyncSession,
) -> None:
    """**Die Zusicherung, auf die es ankommt.**

    Das Geraet erholt sich selbst und meldet das (``0x70``-``0x73``).
    Wuerde diese Meldung die Sperre loesen, waere der ganze Mechanismus
    wirkungslos: ein Panel mit echtem Fehler liefe in eine Schleife aus
    Abschalten und Wiedereinschalten, und niemand erfuehre davon.

    Der Codec setzt dafuer ein **anderes** Feld
    (``protectionRecovered``), und dieser Pfad liest nur
    ``protection``.
    """
    dev = await _relais(db_session, marker="erh")
    await relay_uplink.verarbeite_relais_uplink(
        db_session,
        device_id=dev.id,
        obj={"relayState": "OFF", "protection": "overheating"},
        zeit=datetime.now(tz=UTC),
        fcnt=1,
    )
    await db_session.flush()
    assert dev.protection_tripped_at is not None

    await relay_uplink.verarbeite_relais_uplink(
        db_session,
        device_id=dev.id,
        obj={
            "relayState": "ON",
            "protectionRecovered": "overheating",
            "protectionRuntimeS": 42,
        },
        zeit=datetime.now(tz=UTC) + timedelta(minutes=2),
        fcnt=2,
    )
    await db_session.flush()

    assert dev.protection_tripped_at is not None, (
        "nur ein Admin hebt die Sperre auf — nicht das Geraet selbst"
    )
    assert relay_service.darf_schalten(dev) is False


async def test_unbekannte_schutzart_sperrt_trotzdem(db_session: AsyncSession) -> None:
    """Lieber eine Sperre zu viel.

    Die Liste der Arten steht in der Geraete-Firmware. Ein neuer Wert
    soll nicht dazu fuehren, dass ein Panel nach einem Vorfall
    weiterlaeuft.
    """
    dev = await _relais(db_session, marker="unb")
    await relay_uplink.verarbeite_relais_uplink(
        db_session,
        device_id=dev.id,
        obj={"relayState": "OFF", "protection": "irgendwas_neues"},
        zeit=datetime.now(tz=UTC),
        fcnt=1,
    )
    await db_session.flush()
    assert dev.protection_tripped_at is not None
    assert dev.protection_kind == "irgendwas_neues"


async def test_ein_relais_wird_als_relais_erkannt(db_session: AsyncSession) -> None:
    """Das Gate, das den Thermostat-Pfad im Subscriber umgeht."""
    dev = await _relais(db_session, marker="art")
    assert await relay_uplink.ist_relais(db_session, dev.id) is True


# ---------------------------------------------------------------------------
# Der Befund aus Paket 4: ein Relais ist nicht dauerhaft silent
# ---------------------------------------------------------------------------


def test_frische_relais_meldung_ergibt_healthy() -> None:
    """Die reine Abbildung — mit einem Zeitpunkt statt ``None``.

    Vor Paket 4 kam fuer ein Relais immer ``None`` heraus, weil die
    Health-Berechnung ausschliesslich ``sensor_reading`` abfragte. Das
    Ergebnis war ``silent``, und zwar dauerhaft.
    """
    jetzt = datetime(2026, 10, 24, 9, 0, tzinfo=UTC)
    schwellen = HealthSchwellen(
        healthy_max_age=timedelta(hours=2), degraded_max_age=timedelta(hours=24)
    )

    assert _basis_state_from_age(jetzt - timedelta(minutes=5), jetzt, schwellen) == "healthy"
    assert _basis_state_from_age(None, jetzt, schwellen) == "silent", (
        "ohne Meldung bleibt es silent — das war der Zustand JEDES Relais"
    )
