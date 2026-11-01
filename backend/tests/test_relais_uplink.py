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


# ---------------------------------------------------------------------------
# Die Version aus demselben Frame (Befund vom 01.11.2026)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_relais_firmware_aus_dem_ersten_frame_wird_gespeichert(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ein Relais meldet ``0x04`` im ersten Uplink — und es muss ankommen.

    **Der Befund.** ``_handle_firmware_version_report`` steht im
    Antwort-Zweig der Thermostate, und der Relais-Zweig kehrt **vorher**
    zurueck. ``device.firmware_version`` blieb damit leer, obwohl das
    Geraet die Zahl im ersten Frame nach dem Join mitschickt. Bei Relais
    109 war das am 01.11.2026 ``1.5``.

    Das ist nicht kosmetisch: unter Software 1.4 fehlen die
    Timer-Befehle, und ohne Timer ist „EIN nur befristet" (S1) nicht
    erfuellbar. Die Entscheidung über die Inbetriebnahme hing an einer
    Zahl, die nirgends stand.

    **Geprueft wird am Aufrufer** (``_persist_uplink``), nicht an der
    Hilfsfunktion. Genau diese Trennung war der Fehler — die
    Hilfsfunktion war die ganze Zeit in Ordnung, sie wurde nur nicht
    gerufen (§5.87).

    **Und mit einer zweiten Sitzung gelesen.** ``_persist_uplink``
    committet selbst; wer in derselben Sitzung nachsieht, sieht auch
    einen fehlenden Commit (§5.87, zweiter Teil).
    """
    from heizung.services import mqtt_subscriber
    from heizung.services.mqtt_subscriber import ChirpStackUplink, _persist_uplink
    from tests.conftest import purge_test_data_by_prefix

    engine = create_async_engine(TEST_DB_URL or "", poolclass=None)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(mqtt_subscriber, "SessionLocal", maker)

    try:
        async with maker() as aufbau:
            dev = await _relais(aufbau, marker="fw")
            dev.firmware_version = None
            dev_eui = dev.dev_eui
            await aufbau.commit()

        uplink = ChirpStackUplink.model_validate(
            {
                "deviceInfo": {"devEui": dev_eui},
                "fCnt": 1,
                "fPort": 2,
                "time": datetime.now(tz=UTC).isoformat(),
                # Der Ausgang des korrigierten Codecs fuer das erste Frame
                # von 109: Version **und** angehaengter Keepalive.
                "object": {
                    "report_type": "command_response",
                    "hw_version": "2.1",
                    "firmware_version": "1.5",
                    "lorawanRegion": "EU868",
                    **KEEPALIVE,
                },
                "data": "BCEVEgoZeBsAHQIYpAABHwAAAAAAAOQAAAE=",
            }
        )
        await _persist_uplink(uplink)

        async with maker() as pruefung:
            gespeichert = await pruefung.scalar(
                select(Device.firmware_version).where(Device.dev_eui == dev_eui)
            )
            assert gespeichert == "1.5", (
                "Die Version aus dem ersten Frame muss am Geraet stehen - "
                "vorher blieb sie leer, weil der Relais-Zweig vorher zurueckkehrt"
            )
            # Die Zeitreihe aus demselben Frame, damit der Test nicht
            # gruen ist, wenn der Relais-Zweig gar nicht gelaufen ist.
            zustand = await pruefung.scalar(
                select(RelayReading.relay_on).where(
                    RelayReading.device_id.in_(select(Device.id).where(Device.dev_eui == dev_eui))
                )
            )
            assert zustand is True, "derselbe Frame muss auch die Zeitreihe schreiben"
    finally:
        async with maker() as putzen:
            await purge_test_data_by_prefix(putzen, PREFIX, dev_eui_pattern="beef%")
            await putzen.commit()
        await engine.dispose()


def test_tasterdruck_steht_mit_grund_in_der_zeitreihe() -> None:
    """``0x5d`` ist ein Grund und nicht nur ein Zustandswechsel.

    **Der Befund vom 01.11.2026.** Der Codec dekodiert den Tastendruck
    seit Sprint 24 (``manualSwitch``), und ``werte_aus_codec`` hat das
    Feld verworfen. In der Zeitreihe stand damit „ging an" ohne Grund —
    und ein Relais, das ohne Grund angeht, ist genau die Zeile, bei der
    jemand nachfragt (S3).

    Eingetragen wird dasselbe Wort wie bei ``0x54``, nicht ein zweites
    fuer dieselbe Sache (§5.53).
    """
    werte = relay_uplink.werte_aus_codec(
        {"report_type": "command_response", "relayState": "ON", "manualSwitch": True},
        device_id=1,
        zeit=datetime.now(tz=UTC),
        fcnt=7,
    )

    assert werte["relay_on"] is True
    assert werte["change_reason"] == "manual_button"


def test_die_antwort_auf_0x54_schlaegt_den_nebeneffekt() -> None:
    """Traegt ein Frame beides, gilt ``0x54``.

    ``relayChangeReason`` ist die **Antwort auf die Frage** nach dem
    Grund, ``manualSwitch`` der Nebeneffekt einer Meldung. Zwei Quellen
    fuer ein Feld brauchen eine Reihenfolge, sonst entscheidet die
    Schreibweise des Codes (§5.53).
    """
    werte = relay_uplink.werte_aus_codec(
        {
            "relayState": "OFF",
            "manualSwitch": True,
            "relayChangeReason": "overheating_protection",
        },
        device_id=1,
        zeit=datetime.now(tz=UTC),
        fcnt=8,
    )

    assert werte["change_reason"] == "overheating_protection"


# ---------------------------------------------------------------------------
# Die Ruecklesung kommt an (Befund des Betreibers, 01.11.2026)
# ---------------------------------------------------------------------------

#: Die beiden echten Frames von Relais 109, Base64 wie in ChirpStack.
#: ``5f 02`` + Keepalive, 09:48:11 UTC+1, nach dem Provisionieren.
FRAME_5F_OFF = "XwIBJAAAAAAAAOUAAAE="
#: ``5a 00`` + Keepalive, 09:45:03, **vor** dem Setzen — also ``last_state``.
FRAME_5A_LAST_STATE = "WgABJAAAAAAAAOYAAAE="

#: Was der Codec aus ``FRAME_5F_OFF`` macht (nachgerechnet mit node).
OBJ_5F_OFF = {
    "report_type": "command_response",
    "stateAfterPowerReturn": "off",
    "internalTemperature": 36,
    "energy_raw": 0,
    "energy_kWh": 0,
    "power_W": 0,
    "acVoltage_V": 229,
    "acCurrent_mA": 0,
    "relayState": "ON",
    "keepalive_included": True,
}

#: Und aus ``FRAME_5A_LAST_STATE``.
OBJ_5A_LAST_STATE = {
    "report_type": "command_response",
    "stateAfterOverheatingRecovery": "last_state",
    "internalTemperature": 36,
    "energy_raw": 0,
    "energy_kWh": 0,
    "power_W": 0,
    "acVoltage_V": 230,
    "acCurrent_mA": 0,
    "relayState": "ON",
    "keepalive_included": True,
}


@pytest.mark.asyncio
async def test_ruecklesung_stromrueckkehr_wird_am_geraet_vermerkt() -> None:
    """Der Frame von 09:48:11 muss „bestätigt" ergeben.

    **Der Befund.** Relais 109 hat die Ruecklesung geschickt, der Codec
    hat sie richtig dekodiert (``stateAfterPowerReturn = "off"``) — und
    die Geraeteseite zeigte weiter „Aus nach Stromrueckkehr: nicht
    bestaetigt". Zwischen Uplink und Anzeige lag nichts:
    ``relay_service.vermerke_ruecklesung`` hatte **keinen Aufrufer**.

    Geprueft wird **am Aufrufer** (``_persist_uplink``) und mit dem
    **echten** Frame — nicht an der Funktion, die die ganze Zeit in
    Ordnung war (§5.87).
    """
    from heizung.services import mqtt_subscriber
    from heizung.services.mqtt_subscriber import ChirpStackUplink, _persist_uplink
    from tests.conftest import purge_test_data_by_prefix

    engine = create_async_engine(TEST_DB_URL or "", poolclass=None)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch_ziel = mqtt_subscriber.SessionLocal
    mqtt_subscriber.SessionLocal = maker  # type: ignore[assignment]

    try:
        async with maker() as aufbau:
            dev = await _relais(aufbau, marker="r5f")
            # Ausgangslage wie bei 109: noch nichts bestaetigt.
            dev.power_return_verified_at = None
            dev.overheating_recovery_verified_at = None
            dev.commissioned_at = None
            dev_eui = dev.dev_eui
            await aufbau.commit()

        await _persist_uplink(
            ChirpStackUplink.model_validate(
                {
                    "deviceInfo": {"devEui": dev_eui},
                    "fCnt": 12,
                    "fPort": 2,
                    "time": datetime.now(tz=UTC).isoformat(),
                    "object": dict(OBJ_5F_OFF),
                    "data": FRAME_5F_OFF,
                }
            )
        )

        async with maker() as pruefung:
            zeile = (
                (await pruefung.execute(select(Device).where(Device.dev_eui == dev_eui)))
                .scalars()
                .one()
            )
            assert zeile.power_return_verified_at is not None, (
                "die Ruecklesung 'off' muss den Vermerk setzen - genau das fehlte"
            )
            # Die zweite Achse bleibt unberuehrt: dieser Frame sagt nichts
            # ueber den Ueberhitzungsschutz.
            assert zeile.overheating_recovery_verified_at is None
            # Und der Keepalive-Schwanz desselben Frames muss weiter in die
            # Zeitreihe gehen, sonst prueft der Test nur die halbe Kette.
            assert (
                await pruefung.scalar(
                    select(RelayReading.ac_voltage_v).where(RelayReading.device_id == zeile.id)
                )
            ) == 229
    finally:
        mqtt_subscriber.SessionLocal = monkeypatch_ziel  # type: ignore[assignment]
        async with maker() as putzen:
            await purge_test_data_by_prefix(putzen, PREFIX, dev_eui_pattern="beef%")
            await putzen.commit()
        await engine.dispose()


@pytest.mark.asyncio
async def test_last_state_loescht_den_vermerk_wieder(db_session: AsyncSession) -> None:
    """``last_state`` ist ein **Nein**, kein „noch nicht".

    Der Frame von 09:45:03 kam **vor** dem Setzen und meldet die
    Werksvorgabe. Er darf einen bestandenen Vermerk von vorher nicht
    stehen lassen — sonst ueberdeckt ein Erfolg von gestern ein Nein von
    heute.

    **Das ist zugleich die Begruendung, warum es keinen Zeitvergleich
    gegen die Provisionierungszeit braucht:** nur ``off`` setzt, und
    ``off`` kann erst nach dem Setzen gemeldet werden. Eine veraltete
    Antwort kann den Vermerk nur **loeschen**, und das ist die sichere
    Richtung.
    """
    dev = await _relais(db_session, marker="r5a")
    dev.overheating_recovery_verified_at = datetime.now(tz=UTC) - timedelta(days=1)
    await db_session.flush()

    ergebnis = await relay_uplink._vermerke_ruecklesungen(
        db_session, device_id=dev.id, obj=dict(OBJ_5A_LAST_STATE)
    )

    assert ergebnis == {"overheating_recovery": False}
    assert dev.overheating_recovery_verified_at is None


@pytest.mark.asyncio
async def test_ein_frame_ohne_ruecklesung_ruehrt_die_vermerke_nicht_an(
    db_session: AsyncSession,
) -> None:
    """Ein gewoehnlicher Keepalive darf nichts zuruecksetzen.

    Der naheliegende Fehler waere, „kein Feld" wie ``last_state`` zu
    behandeln. Dann loeschte jeder Keepalive — also alle zehn Minuten —
    beide Vermerke, und eine Inbetriebnahme waere nie moeglich.
    """
    dev = await _relais(db_session, marker="rka")
    vorher = datetime.now(tz=UTC) - timedelta(hours=2)
    dev.power_return_verified_at = vorher
    dev.overheating_recovery_verified_at = vorher
    await db_session.flush()

    ergebnis = await relay_uplink._vermerke_ruecklesungen(
        db_session, device_id=dev.id, obj=dict(KEEPALIVE)
    )

    assert ergebnis == {}
    assert dev.power_return_verified_at == vorher
    assert dev.overheating_recovery_verified_at == vorher
