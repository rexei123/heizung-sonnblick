"""Eine abgewiesene Drehung holt das Gerät zurück (Sprint 23 T4-A2b).

**Der Befund des Betreibers, Zimmer 107 am 30.10.2026** — der Rad-Test
nach RUNBOOK §10aq, Schritt 3 nicht bestanden:

    11:46  Übersteuerung 23 °C bis Check-out + Häkchen gesetzt,
           Gerät auf 23.
    11:49  Gast dreht auf 25 (``0x28 manual_target_change``, target 25).
           Die Drehung wird korrekt abgewiesen, der Override bleibt 23.
    11:49  …und das Gerät meldet **25.0**. Ventil 18 -> 34 %,
    bis     Raum 22,5 -> 23,9 °C. **Zwei Stunden. Kein Befehl zurück.**
    13:49

Korrigiert hat es erst der Sechs-Stunden-Heartbeat.

**Zwei Mechaniken, die beide für sich richtig sind, und dazwischen die
Lücke:**

1. Die **Hysterese** vergleicht gegen den zuletzt **selbst gesendeten**
   Wert. Der war 23, gewollt waren 23, ``delta = 0`` — sie schweigt. Was
   am Gerät steht, kennt sie nicht; genau das war der Befund aus
   Sprint 20f.
2. Der **Engine-Abgleich** kennt den gemeldeten Wert und hätte gegriffen.
   Er war aber bei aktivem Override auf Werte **außerhalb** der Grenzen
   verengt (Hotfix 18.10.2026, aus gutem Grund: ein Gastwunsch soll nicht
   alle 30 Minuten überschrieben werden). 25 liegt in [15, 25] — also
   innerhalb, also stumm.

Unter der Sperre trägt dieser Grund nicht: der Gast **darf** nicht
stellen, eine Abweichung ist dort kein Wunsch, sondern eine abgewiesene
Drehung. Deshalb zwei Schichten, und diese Datei prüft beide:

| Schicht | greift nach | fängt |
|---|---|---|
| Re-Sync-Flag aus dem Sperr-Gate | einem Engine-Lauf (< 1 min) | die Abweisung selbst |
| Abgleich ohne die Ausnahme | ≤ 30 min (gedrosselt) | was die erste verpasst hat |

Die zweite ist kein Beiwerk. Das Flag liegt in Redis und ist deshalb
nicht garantiert: ist Redis nicht erreichbar, läuft es ab, oder weicht
ein Gerät **ohne** ``0x28``-Frame ab (Drift nach Neustart, Montage), dann
ist der Abgleich die einzige Stelle, die es noch merkt.

**Und eine Gegenprobe gehört dazu**: ohne Sperre muss die Ausnahme
unangetastet weiterhalten, sonst ist aus dem Fix ein Dauerstreit mit dem
Drehrad geworden. Das prüft
``test_hotfix_grenze_bei_override.py`` für den Bestand und
``test_ohne_sperre_bleibt_die_ausnahme`` hier für die neue Bedingung.

DB-Tests; skip ohne ``TEST_DATABASE_URL`` (§5.50, lokal gelaufen).
§5.59: alle Zeitpunkte sind **absolute** Werte gegen ``FROZEN_NOW``.
Der Redis-Doppelgänger kommt aus ``test_engine_abgleich`` statt als
zweite Kopie — eine Attrappe, mehrere Dateien (§5.53).
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
from freezegun import freeze_time
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from heizung.models.control_command import ControlCommand
from heizung.models.device import Device
from heizung.models.enums import (
    CommandReason,
    DeviceKind,
    DeviceVendor,
    EventLogLayer,
    HeatingZoneKind,
    OverrideSource,
    RoomStatus,
)
from heizung.models.event_log import EventLog
from heizung.models.heating_zone import HeatingZone
from heizung.models.manual_override import ManualOverride
from heizung.models.occupancy import Occupancy
from heizung.models.room import Room
from heizung.models.room_type import RoomType
from heizung.models.sensor_reading import SensorReading
from heizung.rules.engine import evaluate_room
from heizung.services import engine_abgleich, mqtt_subscriber, resync_flag
from heizung.services.mqtt_subscriber import (
    ChirpStackUplink,
    _handle_override_detection,
    _map_to_reading,
)
from heizung.tasks.engine_tasks import _dispatch_downlinks_per_zone
from tests.conftest import purge_test_data_by_prefix
from tests.test_engine_abgleich import _FakeRedis

TEST_DB_URL = os.environ.get("TEST_DATABASE_URL")
SKIP_REASON = "TEST_DATABASE_URL nicht gesetzt - DB-Tests brauchen Postgres"

# schema_constraint: room.number = VARCHAR(20) -> "sr-" + 4 hex = 7
PREFIX = "sr"
DEV_EUI_PATTERN = "5e9e5e9e%"

FROZEN_NOW = datetime(2026, 10, 30, 11, 50, tzinfo=UTC)

#: Die Grenzen des Hauses (Betreiber, 18.10.2026): Doppelzimmer 15-25 °C.
#: **25 liegt darin** — das ist der ganze Grund, warum der Abgleich im
#: Befund stumm blieb.
UNTEN, OBEN = 15, 25

#: Der eingetragene Wunsch der Rezeption und der gedrehte Wert des Gasts.
SOLL, GEDREHT = 23, 25

#: Der echte ``0x28``-Frame von Gerät 107/Schlafzimmer, 11:49 Uhr.
#:
#: ``data`` ist unverändert aus ChirpStack: ``KBmBGZx6idkR8DA=`` — erstes
#: Byte ``0x28``. ``object`` ist die Ausgabe des Repo-Codecs
#: (``infra/chirpstack/codecs/mclimate-vicki.js``) für genau diese Bytes,
#: mit den Zahlen als **Zahlen** und nicht als Zeichenketten: so kommt es
#: aus dem MQTT-JSON, und eine Zeichenkette im Prüfstand hätte eine
#: Umwandlung bewiesen, die in Betrieb niemand macht.
#:
#: Die Werte passen zum Bericht des Betreibers und belegen, dass es
#: dieser Frame ist: ``valve_openness 17`` (gemeldet „Ventil 18 %"),
#: ``temperature 22.53`` („Raum 22,5"), ``target_temperature 25``.
#:
#: ``childLock: false`` ist richtig und kein Widerspruch: den Befehl, der
#: das Rad **am Gerät** sperrt, baut erst T4-B. Bis dahin wirkt die Sperre
#: allein dadurch, dass der Dienst die Drehung abweist — und genau deshalb
#: muss jemand das Gerät zurückholen.
FRAME_0X28_DATA = "KBmBGZx6idkR8DA="
FRAME_0X28_OBJECT: dict[str, Any] = {
    "report_type": "manual_target_change",
    "temperature": 22.53,
    "target_temperature": 25.0,
    "battery_voltage": 3.5,
    "motor_position": 393,
    "motor_range": 473,
    "valve_openness": 17,
    "relativeHumidity": 47.66,
    "command": 40,
    "openWindow": False,
    "highMotorConsumption": False,
    "lowMotorConsumption": False,
    "brokenSensor": False,
    "childLock": False,
    "calibrationFailed": False,
    "attachedBackplate": True,
    "perceiveAsOnline": True,
    "antiFreezeProtection": False,
    "manual_target_temperature": 25.0,
    "manual_target_history": [25.0],
    "manual_target_change": True,
}

#: Zwei vierstellige Zählerstände, aufsteigend. Wichtig für den
#: Reboot-Gate: er greift nur unter ``fcnt < 10``, und ein Frame, den er
#: fälschlich als Neustart liest, käme nie beim Sperr-Gate an (§5.71).
FCNT_VORHER, FCNT_DREHUNG = 4330, 4338

# Kein ``pytestmark = pytest.mark.asyncio``: ``asyncio_mode = "auto"``
# (pyproject) nimmt die async-Tests von selbst, und die drei reinen Tests
# in Abschnitt 1 sind synchron.


@pytest.fixture(autouse=True)
def fake_redis(monkeypatch: pytest.MonkeyPatch) -> _FakeRedis:
    """Ein Doppelgänger für alle drei Nutzer.

    ``resync_flag``, ``engine_abgleich`` und ``device_adapter`` holen ihren
    Client über dasselbe ``redis_client.get_redis_client`` — eine Attrappe
    deckt alle.

    Ohne Redis sendet der Abgleich **nicht** und das Flag wird nicht
    gesetzt; ein stiller Lauf wäre dann kein Beleg, sondern eine fehlende
    Abhängigkeit (§5.55).
    """
    client = _FakeRedis()
    monkeypatch.setattr(engine_abgleich.redis_client, "get_redis_client", lambda: client)
    return client


@pytest_asyncio.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    if not TEST_DB_URL:
        pytest.skip(SKIP_REASON)
    engine = create_async_engine(TEST_DB_URL)
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    async with sessionmaker() as session:
        await purge_test_data_by_prefix(session, PREFIX, dev_eui_pattern=DEV_EUI_PATTERN)
        try:
            yield session
        finally:
            await session.rollback()
            await purge_test_data_by_prefix(session, PREFIX, dev_eui_pattern=DEV_EUI_PATTERN)
    await engine.dispose()


@pytest_asyncio.fixture
async def pruef_sitzung() -> AsyncIterator[AsyncSession]:
    """Eine **zweite** Verbindung, nur zum Nachsehen.

    **Die Mutationsprobe hat diesen Test zuerst als Attrappe entlarvt.**
    Erste Fassung las die Audit-Zeile aus derselben Sitzung, die der
    Subscriber geliehen bekam — und eine geflushte Zeile ist innerhalb
    ihrer eigenen Transaktion sichtbar, mit Commit wie ohne. Der Test war
    gruen, auch nachdem der Commit wieder entfernt war: also genau der
    Fall aus Paragraph 5.55, ein gruener Lauf, der nichts geprueft hat.

    Nur eine fremde Verbindung sieht ausschliesslich **committete**
    Zeilen. Deshalb diese Sitzung, und deshalb nur hier.
    """
    if not TEST_DB_URL:
        pytest.skip(SKIP_REASON)
    engine = create_async_engine(TEST_DB_URL)
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    async with sessionmaker() as session:
        yield session
    await engine.dispose()


@pytest.fixture
def subscriber_sitzung(monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession) -> None:
    """Leiht dem Subscriber die Test-Sitzung.

    ``_handle_override_detection`` öffnet seine eigene Sitzung über
    ``SessionLocal`` und **committet** — und genau darauf zielt ein Teil
    dieser Tests. Ein Commit auf der geliehenen Sitzung ist
    unproblematisch: aufgeräumt wird am Ende über den Prefix und nicht
    über einen Rollback.

    ``__aexit__`` darf die Sitzung **nicht** schließen — der Test liest
    danach weiter. Deshalb eine eigene Hülle und kein
    ``async_sessionmaker``. Und ``monkeypatch`` und nicht eine Zuweisung,
    damit der Eingriff mit dem Test endet.
    """

    class _Huelle:
        async def __aenter__(self) -> AsyncSession:
            return db_session

        async def __aexit__(self, *_exc: object) -> None:
            return None

    monkeypatch.setattr(mqtt_subscriber, "SessionLocal", _Huelle)


@pytest.fixture
def mock_send_setpoint(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, int]]:
    aufrufe: list[tuple[str, int]] = []

    async def _mock(dev_eui: str, setpoint_c: int) -> str:
        aufrufe.append((dev_eui, setpoint_c))
        return f"application/x/device/{dev_eui}/command/down"

    monkeypatch.setattr("heizung.tasks.engine_tasks.send_setpoint", _mock)
    return aufrufe


# ---------------------------------------------------------------------------
# Aufbau
# ---------------------------------------------------------------------------


async def _zimmer_107(
    session: AsyncSession,
    *,
    sperre: str | None,
) -> tuple[int, int]:
    """Belegtes Zimmer mit einer Zone. Gibt ``(room_id, zone_id)``.

    ``sperre``: ``None``, ``"dauerhaft"`` oder ``"bis_checkout"``. Die
    beiden Formen setzen **beide** ``guest_override_blocked`` und
    unterscheiden sich nur darin, wann sie enden
    (``services/gast_sperre``) — deshalb muss der Re-Sync in beiden
    greifen, und deshalb stehen beide hier als Parameter.
    """
    marker = uuid.uuid4().hex[:4]
    zimmertyp = RoomType(
        name=f"{PREFIX}-dz-{marker}",
        default_t_occupied=Decimal("21.0"),
        default_t_vacant=Decimal("18.0"),
        default_t_night=Decimal("19.0"),
        min_temp_celsius=Decimal(UNTEN),
        max_temp_celsius=Decimal(OBEN),
    )
    session.add(zimmertyp)
    await session.flush()

    room = Room(
        number=f"{PREFIX}-{marker}",
        room_type_id=zimmertyp.id,
        status=RoomStatus.OCCUPIED,
        guest_override_blocked=sperre is not None,
        guest_block_bis_checkout=sperre == "bis_checkout",
    )
    session.add(room)
    await session.flush()
    session.add(
        Occupancy(
            room_id=room.id,
            check_in=FROZEN_NOW - timedelta(hours=20),
            check_out=FROZEN_NOW + timedelta(days=2),
            is_active=True,
        )
    )
    zone = HeatingZone(room_id=room.id, kind=HeatingZoneKind.BEDROOM, name="Schlafzimmer")
    session.add(zone)
    await session.flush()
    await session.commit()
    return room.id, zone.id


async def _geraet(
    session: AsyncSession,
    zone_id: int,
    *,
    meldet: int,
    zuletzt_gesendet: int,
) -> tuple[int, str]:
    """Gesundes Gerät mit Messwert und Vorgeschichte. ``(device_id, dev_eui)``.

    ``zuletzt_gesendet`` liegt zwei Stunden zurück: über dem
    Ack-Fenster (60 s), über ``ABGLEICH_MIN_ABSTAND_S`` (900 s) und weit
    vor dem Sechs-Stunden-Heartbeat. Alle drei Fristen sind damit aus dem
    Weg — der Test soll an der **Sperre** hängen und an nichts sonst.
    """
    marker = uuid.uuid4().hex[:8]
    dev = Device(
        dev_eui=f"5e9e5e9e{marker}",
        kind=DeviceKind.THERMOSTAT,
        vendor=DeviceVendor.MCLIMATE,
        model="Vicki",
        heating_zone_id=zone_id,
        health_state="healthy",
    )
    session.add(dev)
    await session.flush()
    session.add(
        SensorReading(
            time=FROZEN_NOW - timedelta(minutes=5),
            device_id=dev.id,
            fcnt=FCNT_VORHER,
            temperature=Decimal("22.5"),
            setpoint=Decimal(meldet),
        )
    )
    session.add(
        ControlCommand(
            issued_at=FROZEN_NOW - timedelta(hours=2),
            device_id=dev.id,
            target_setpoint=Decimal(zuletzt_gesendet),
            reason=CommandReason.OCCUPIED_SETPOINT,
            sent_to_gateway_at=FROZEN_NOW - timedelta(hours=2),
        )
    )
    await session.commit()
    return dev.id, dev.dev_eui


async def _uebersteuerung(
    session: AsyncSession,
    room_id: int,
    *,
    zone_id: int | None,
    wert: int,
) -> None:
    """Die Übersteuerung der Rezeption, wie der Dialog sie anlegt.

    ``source=frontend_checkout`` ist die Form aus T4-A2: ein Wert, der
    bis zur Abreise gilt. Dass sie aus dem Frontend kommt, ist für diesen
    Test wesentlich — eine Drehrad-Übersteuerung (``device_manual``)
    könnte unter der Sperre gar nicht entstehen.
    """
    session.add(
        ManualOverride(
            room_id=room_id,
            heating_zone_id=zone_id,
            setpoint=Decimal(wert),
            source=OverrideSource.FRONTEND_CHECKOUT,
            expires_at=FROZEN_NOW + timedelta(days=2),
        )
    )
    await session.commit()


def _uplink(dev_eui: str, *, fcnt: int = FCNT_DREHUNG) -> ChirpStackUplink:
    """Der Frame von 11:49, wie ChirpStack ihn veröffentlicht."""
    return ChirpStackUplink.model_validate(
        {
            "deviceInfo": {"devEui": dev_eui},
            "fCnt": fcnt,
            "fPort": 2,
            "time": (FROZEN_NOW - timedelta(minutes=1)).isoformat(),
            "object": dict(FRAME_0X28_OBJECT),
            "rxInfo": [{"rssi": -91, "snr": 8.5}],
            "data": FRAME_0X28_DATA,
        }
    )


# ---------------------------------------------------------------------------
# 1. Der Schlüssel trägt seinen Grund — reine Logik
# ---------------------------------------------------------------------------


def test_grund_kommt_zurueck(fake_redis: _FakeRedis) -> None:
    """``sperre`` rein, ``sperre`` raus. Der Dispatch entscheidet daran."""
    assert resync_flag.mark_pending("5e9e5e9e0001", grund=resync_flag.GRUND_SPERRE) is True
    assert resync_flag.consume("5e9e5e9e0001") == resync_flag.GRUND_SPERRE


def test_alter_schluessel_aus_der_zeit_davor_gilt_als_neustart(fake_redis: _FakeRedis) -> None:
    """Ein Schlüssel mit dem alten Wert ``"1"`` bedeutet ``reboot``.

    **Der Deploy-Übergang, und er ist echt.** Der Schlüssel hat eine
    Stunde Frist. Wird mitten darin ausgeliefert, stehen in Redis
    Schlüssel aus der alten Fassung — damals gab es genau einen Grund,
    den Geräte-Neustart.

    Ohne diese Zeile käme dort der Rohwert ``"1"`` heraus und im
    ``control_command`` stünde ``base_reason`` statt ``reboot_resync``:
    ein verlorener Befund über ein Gerät, und zwar genau in der Stunde,
    in der niemand hinsieht.
    """
    fake_redis.store["resync_pending:5e9e5e9e0002"] = "1"
    assert resync_flag.consume("5e9e5e9e0002") == resync_flag.GRUND_REBOOT


def test_der_letzte_grund_gilt(fake_redis: _FakeRedis) -> None:
    """Zweimal gesetzt, einmal konsumiert — der zweite Grund steht da.

    Kein Vorrang-Geflecht: beide Gründe wollen denselben Downlink, und
    **einen** soll es geben und nicht zwei (§0 S4). Der Grund, der näher
    am Ereignis liegt, ist der bessere Bericht.
    """
    resync_flag.mark_pending("5e9e5e9e0003", grund=resync_flag.GRUND_REBOOT)
    resync_flag.mark_pending("5e9e5e9e0003", grund=resync_flag.GRUND_SPERRE)

    assert resync_flag.consume("5e9e5e9e0003") == resync_flag.GRUND_SPERRE
    assert resync_flag.consume("5e9e5e9e0003") is None, "der Schlüssel muss verbraucht sein"


# ---------------------------------------------------------------------------
# 2. Das Sperr-Gate löst den Re-Sync aus — beide Formen
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("form", ["dauerhaft", "bis_checkout"])
@freeze_time(FROZEN_NOW)
async def test_abgewiesene_drehung_setzt_das_flag(
    db_session: AsyncSession,
    fake_redis: _FakeRedis,
    subscriber_sitzung: None,
    form: str,
) -> None:
    """Drehung abgewiesen -> Flag mit ``grund=sperre``, in beiden Formen.

    Die beiden Formen gehen durch dieselbe Zeile
    (``room.guest_override_blocked``). Der Test prüft sie trotzdem
    einzeln: wer die Bedingung später auf ``guest_block_bis_checkout``
    verengt, soll das hier merken und nicht im Zimmer.
    """
    room_id, zone_id = await _zimmer_107(db_session, sperre=form)
    _, dev_eui = await _geraet(db_session, zone_id, meldet=SOLL, zuletzt_gesendet=SOLL)
    await _uebersteuerung(db_session, room_id, zone_id=zone_id, wert=SOLL)

    await _handle_override_detection(_uplink(dev_eui))

    assert fake_redis.store.get(f"resync_pending:{dev_eui}") == resync_flag.GRUND_SPERRE


@freeze_time(FROZEN_NOW)
async def test_das_audit_der_abweisung_steht_in_der_datenbank(
    db_session: AsyncSession,
    fake_redis: _FakeRedis,
    subscriber_sitzung: None,
    pruef_sitzung: AsyncSession,
) -> None:
    """**Der zweite Befund dieses PR, und er ist älter als T4-A2b.**

    ``_handle_override_detection`` hat bis zum 30.10.2026 nur dann
    committet, wenn ein Override **entstanden** ist. Die Gates davor
    schreiben aber ``event_log``-Zeilen und geben ``None`` zurück — die
    abgewiesene Drehung, das freie Zimmer, das offene Fenster, der
    erkannte Neustart. Alle vier haben ``flush`` gerufen und keinen
    Commit bekommen: beim Verlassen des ``async with`` rollte die Sitzung
    zurück.

    Seit Sprint 12a T4 hat der einzige produktive Aufrufer dieses Pfades
    damit **jede** Off-Pipeline-Audit-Zeile verworfen. Aufgefallen ist es
    nicht, weil alle Tests dazu ``handle_uplink_for_override`` direkt
    rufen und selbst committen — die Mechanik stimmte, die Wirkung fehlte
    (§5.76, §5.61).

    Dieser Test ist der einzige, der durch den **echten** Aufrufer geht.
    """
    room_id, zone_id = await _zimmer_107(db_session, sperre="bis_checkout")
    device_id, dev_eui = await _geraet(db_session, zone_id, meldet=SOLL, zuletzt_gesendet=SOLL)
    await _uebersteuerung(db_session, room_id, zone_id=zone_id, wert=SOLL)

    await _handle_override_detection(_uplink(dev_eui))

    # Gelesen wird aus der **fremden** Sitzung: nur so unterscheidet der
    # Test „committet" von „geflusht und gleich wieder weg".
    zeilen = (
        (
            await pruef_sitzung.execute(
                select(EventLog)
                .where(EventLog.room_id == room_id)
                .where(EventLog.layer == EventLogLayer.MANUAL_OVERRIDE_BLOCKED)
            )
        )
        .scalars()
        .all()
    )
    assert len(zeilen) == 1, f"genau eine Audit-Zeile erwartet, waren: {len(zeilen)}"
    eintrag = zeilen[0]
    assert eintrag.reason == CommandReason.DEVICE_BLOCKED_ROOM_BLOCKED
    assert eintrag.device_id == device_id
    assert Decimal(eintrag.details["uplink_setpoint"]) == Decimal(GEDREHT)
    # Der Beleg, dass der Rückhol-Weg wirklich offen war. Stünde hier
    # ``False``, käme das Gerät erst mit dem Abgleich zurück — Minuten
    # gegen eine halbe Stunde, und wer den Verlauf liest, muss das sehen.
    assert eintrag.details["resync_flag_set"] is True


@freeze_time(FROZEN_NOW)
async def test_kein_override_entsteht_trotz_der_drehung(
    db_session: AsyncSession,
    fake_redis: _FakeRedis,
    subscriber_sitzung: None,
) -> None:
    """Die Sperre hält: 23 bleibt stehen, 25 entsteht nicht.

    Die Zusicherung aus Sprint 12c, und sie darf durch den Re-Sync nicht
    kippen. Fällt dieser Test, holt der Fix das Gerät zurück **und** hat
    den Gastwert übernommen — das Schlechteste aus beidem.
    """
    room_id, zone_id = await _zimmer_107(db_session, sperre="bis_checkout")
    _, dev_eui = await _geraet(db_session, zone_id, meldet=SOLL, zuletzt_gesendet=SOLL)
    await _uebersteuerung(db_session, room_id, zone_id=zone_id, wert=SOLL)

    await _handle_override_detection(_uplink(dev_eui))

    werte = (
        (
            await db_session.execute(
                select(ManualOverride.setpoint).where(ManualOverride.room_id == room_id)
            )
        )
        .scalars()
        .all()
    )
    assert [Decimal(w) for w in werte] == [Decimal(SOLL)]


@freeze_time(FROZEN_NOW)
async def test_ohne_sperre_setzt_die_drehung_kein_flag(
    db_session: AsyncSession,
    fake_redis: _FakeRedis,
    subscriber_sitzung: None,
) -> None:
    """Die Gegenprobe: dasselbe Zimmer ohne Sperre -> **kein** Flag.

    Belegt, dass das Flag an der Sperre hängt und nicht an jeder Drehung.
    Ohne diese Prüfung wäre jede Handverstellung in jedem belegten Zimmer
    ein zusätzlicher Downlink — eine Motorbewegung für einen Wunsch, den
    die Engine gerade erst übernommen hat (§0 S4).
    """
    room_id, zone_id = await _zimmer_107(db_session, sperre=None)
    _, dev_eui = await _geraet(db_session, zone_id, meldet=SOLL, zuletzt_gesendet=SOLL)

    await _handle_override_detection(_uplink(dev_eui))

    assert f"resync_pending:{dev_eui}" not in fake_redis.store
    # Und der Gastwunsch ist angekommen — sonst hätte ein anderes Gate
    # gegriffen und der Test bewiese nichts über die Sperre.
    werte = (
        (
            await db_session.execute(
                select(ManualOverride.setpoint).where(ManualOverride.room_id == room_id)
            )
        )
        .scalars()
        .all()
    )
    assert [Decimal(w) for w in werte] == [Decimal(GEDREHT)]


# ---------------------------------------------------------------------------
# 3. Der Dispatch macht aus dem Flag einen Downlink
# ---------------------------------------------------------------------------


@freeze_time(FROZEN_NOW)
async def test_flag_erzwingt_downlink_und_behauptet_keinen_neustart(
    db_session: AsyncSession,
    fake_redis: _FakeRedis,
    mock_send_setpoint: list[tuple[str, int]],
) -> None:
    """Flag ``sperre`` -> Downlink 23, ``reason`` ist der Grund des Laufs.

    Die Hysterese schweigt hier (zuletzt gesendet 23, gewollt 23,
    ``delta = 0``) — ohne das Flag gäbe es keinen Downlink.

    **Und im ``control_command`` steht nicht ``reboot_resync``.** Das ist
    kein Schönheitspunkt: niemand hat neu gestartet, und ein Eintrag, der
    es behauptet, ist eine Falschaussage in einer Quelle, die später als
    Beleg gelesen wird (§5.68). Der Anlass steht im Hysterese-Text, genau
    wie beim Engine-Abgleich.
    """
    room_id, zone_id = await _zimmer_107(db_session, sperre="bis_checkout")
    device_id, dev_eui = await _geraet(db_session, zone_id, meldet=GEDREHT, zuletzt_gesendet=SOLL)
    resync_flag.mark_pending(dev_eui, grund=resync_flag.GRUND_SPERRE)

    pro_geraet, _ = await _dispatch_downlinks_per_zone(
        session=db_session,
        room_id=room_id,
        target_setpoint_c=SOLL,
        base_reason=CommandReason.GUEST_OVERRIDE,
        eval_id=uuid.uuid4(),
        zone_overrides={zone_id: SOLL},
        gast_sperre=True,
    )

    assert [sp for _, sp in mock_send_setpoint] == [SOLL]
    assert "sperre_resync" in pro_geraet[0]["hysteresis_reason"]

    befehle = (
        (
            await db_session.execute(
                select(ControlCommand)
                .where(ControlCommand.device_id == device_id)
                .where(ControlCommand.issued_at >= FROZEN_NOW - timedelta(minutes=1))
            )
        )
        .scalars()
        .all()
    )
    assert len(befehle) == 1
    assert befehle[0].reason == CommandReason.GUEST_OVERRIDE
    assert befehle[0].target_setpoint == Decimal(SOLL)


@freeze_time(FROZEN_NOW)
async def test_reboot_behaelt_seinen_eigenen_grund(
    db_session: AsyncSession,
    fake_redis: _FakeRedis,
    mock_send_setpoint: list[tuple[str, int]],
) -> None:
    """Regression zu AE-63: beim Neustart bleibt ``reboot_resync`` stehen.

    Der Grund im Schlüssel darf den Bestand nicht verwässern. Ein
    Neustart ist ein **Befund über das Gerät** und keine Nuance — er hat
    seinen eigenen ``reason`` und behält ihn.
    """
    room_id, zone_id = await _zimmer_107(db_session, sperre=None)
    device_id, dev_eui = await _geraet(db_session, zone_id, meldet=GEDREHT, zuletzt_gesendet=SOLL)
    resync_flag.mark_pending(dev_eui, grund=resync_flag.GRUND_REBOOT)

    await _dispatch_downlinks_per_zone(
        session=db_session,
        room_id=room_id,
        target_setpoint_c=SOLL,
        base_reason=CommandReason.OCCUPIED_SETPOINT,
        eval_id=uuid.uuid4(),
    )

    befehle = (
        (
            await db_session.execute(
                select(ControlCommand)
                .where(ControlCommand.device_id == device_id)
                .where(ControlCommand.issued_at >= FROZEN_NOW - timedelta(minutes=1))
            )
        )
        .scalars()
        .all()
    )
    assert len(befehle) == 1
    assert befehle[0].reason == CommandReason.REBOOT_RESYNC


# ---------------------------------------------------------------------------
# 4. Die zweite Schicht: der Abgleich ohne die Ausnahme
# ---------------------------------------------------------------------------


@freeze_time(FROZEN_NOW)
async def test_abgleich_holt_auch_innerhalb_der_grenzen_zurueck(
    db_session: AsyncSession,
    fake_redis: _FakeRedis,
    mock_send_setpoint: list[tuple[str, int]],
) -> None:
    """**Der Befund als Test, ohne Flag.** Sperre + Override + 25 in [15, 25].

    Genau die Lage von 11:49 bis 13:49, nur mit verlorenem Flag: kein
    Re-Sync-Schlüssel in Redis, Hysterese stumm (``delta = 0``), Gerät
    meldet 25, Grenzen 15 bis 25. Bis zum 30.10.2026 blieb es dabei.

    Jetzt muss der Abgleich senden, weil die Sperre steht. Fällt dieser
    Test, hängt der ganze Fix an einem Redis-Schlüssel — und der ist das
    Unzuverlässigste im Weg.
    """
    room_id, zone_id = await _zimmer_107(db_session, sperre="bis_checkout")
    await _geraet(db_session, zone_id, meldet=GEDREHT, zuletzt_gesendet=SOLL)
    await _uebersteuerung(db_session, room_id, zone_id=zone_id, wert=SOLL)

    pro_geraet, _ = await _dispatch_downlinks_per_zone(
        session=db_session,
        room_id=room_id,
        target_setpoint_c=SOLL,
        base_reason=CommandReason.GUEST_OVERRIDE,
        eval_id=uuid.uuid4(),
        zone_overrides={zone_id: SOLL},
        clamp_grenzen_c=(UNTEN, OBEN),
        gast_sperre=True,
    )

    assert [sp for _, sp in mock_send_setpoint] == [SOLL]
    grund = pro_geraet[0]["hysteresis_reason"]
    assert "engine_abgleich" in grund
    # Der Text muss den **richtigen** Grund nennen. „außerhalb der
    # Grenzen" wäre hier falsch — 25 liegt innerhalb.
    assert "Gast-Sperre steht" in grund
    assert "ausserhalb" not in grund


@freeze_time(FROZEN_NOW)
async def test_ohne_sperre_bleibt_die_ausnahme(
    db_session: AsyncSession,
    fake_redis: _FakeRedis,
    mock_send_setpoint: list[tuple[str, int]],
) -> None:
    """**Die wichtigste Gegenprobe.** Dieselbe Lage ohne Sperre -> still.

    Der Grund für die Ausnahme aus Sprint 20f T3 ist unverändert richtig:
    ohne Sperre **darf** der Gast stellen, eine Abweichung innerhalb der
    Grenzen ist dann sein Wunsch, und ein Abgleich darauf würde ihn alle
    30 Minuten überschreiben.

    T4-A2b darf die Ausnahme also an die Sperre binden, nicht aufheben.
    Fällt dieser Test, ist aus einem Fix ein Dauerstreit mit dem Drehrad
    geworden.
    """
    room_id, zone_id = await _zimmer_107(db_session, sperre=None)
    await _geraet(db_session, zone_id, meldet=GEDREHT, zuletzt_gesendet=SOLL)
    await _uebersteuerung(db_session, room_id, zone_id=zone_id, wert=SOLL)

    await _dispatch_downlinks_per_zone(
        session=db_session,
        room_id=room_id,
        target_setpoint_c=SOLL,
        base_reason=CommandReason.GUEST_OVERRIDE,
        eval_id=uuid.uuid4(),
        zone_overrides={zone_id: SOLL},
        clamp_grenzen_c=(UNTEN, OBEN),
        gast_sperre=False,
    )

    assert mock_send_setpoint == [], f"kein Downlink erwartet, war: {mock_send_setpoint}"


@freeze_time(FROZEN_NOW)
async def test_dauerhafte_sperre_ohne_uebersteuerung_zieht_auf_den_plan(
    db_session: AsyncSession,
    fake_redis: _FakeRedis,
    mock_send_setpoint: list[tuple[str, int]],
) -> None:
    """Punkt 4 des Auftrags: dauerhafte Sperre, kein Override.

    Dann ist der Engine-Soll der Plan-Wert, und das Gerät muss ebenso
    dorthin zurück. Diese Lage hätte auch der Bestands-Abgleich gefangen
    (ohne Override ist er nicht verengt) — geprüft wird sie trotzdem,
    weil der Auftrag sie ausdrücklich nennt und weil sie nach dem Umbau
    der Bedingung weiter stimmen muss.
    """
    room_id, zone_id = await _zimmer_107(db_session, sperre="dauerhaft")
    await _geraet(db_session, zone_id, meldet=GEDREHT, zuletzt_gesendet=21)

    await _dispatch_downlinks_per_zone(
        session=db_session,
        room_id=room_id,
        target_setpoint_c=21,
        base_reason=CommandReason.OCCUPIED_SETPOINT,
        eval_id=uuid.uuid4(),
        clamp_grenzen_c=(UNTEN, OBEN),
        gast_sperre=True,
    )

    assert [sp for _, sp in mock_send_setpoint] == [21]


@freeze_time(FROZEN_NOW)
async def test_die_drosselung_gilt_unter_der_sperre_weiter(
    db_session: AsyncSession,
    fake_redis: _FakeRedis,
    mock_send_setpoint: list[tuple[str, int]],
) -> None:
    """Zwei Läufe hintereinander -> **ein** Downlink.

    Die Sperre weitet den Abgleich aus, sie hebt seine Grenzen nicht auf.
    Jeder Downlink ist eine Motorbewegung, und der Engine-Takt läuft jede
    Minute: ohne Bremse wäre aus dem Fix ein Downlink pro Minute geworden,
    solange das Gerät nicht folgt (§0 S4).

    **Zwei Bremsen halten hier, und jede allein genügt** — das hat die
    Mutationsprobe gezeigt und die erste Fassung dieses Docstrings
    berichtigt (sie nannte nur die Drosselung):

    1. ``ABGLEICH_MIN_ABSTAND_S`` (900 s): der Downlink aus dem ersten Lauf
       ist Sekunden alt, der Abgleich fragt gar nicht.
    2. ``DROSSEL_TTL_S`` (1800 s): höchstens eine Nachsendung je Gerät und
       halbe Stunde.

    Der Test sagt deshalb nicht, **welche** hält, sondern dass gehalten
    wird. Rot wird er erst, wenn man beide entfernt — und das ist die
    richtige Aussage: wer eine davon anfässt, soll nicht in dem Glauben
    sein, der Schutz hänge an ihr allein.

    Die drei Versuche und der Zähler bleiben ebenfalls — sie hängen am
    selben Schlüssel und sind in ``test_engine_abgleich`` geprüft.
    """
    room_id, zone_id = await _zimmer_107(db_session, sperre="bis_checkout")
    await _geraet(db_session, zone_id, meldet=GEDREHT, zuletzt_gesendet=SOLL)
    await _uebersteuerung(db_session, room_id, zone_id=zone_id, wert=SOLL)

    for _ in range(2):
        await _dispatch_downlinks_per_zone(
            session=db_session,
            room_id=room_id,
            target_setpoint_c=SOLL,
            base_reason=CommandReason.GUEST_OVERRIDE,
            eval_id=uuid.uuid4(),
            zone_overrides={zone_id: SOLL},
            clamp_grenzen_c=(UNTEN, OBEN),
            gast_sperre=True,
        )

    assert [sp for _, sp in mock_send_setpoint] == [SOLL], "die Drosselung muss den zweiten halten"


# ---------------------------------------------------------------------------
# 5. Die Engine gibt die Sperre überhaupt erst weiter
# ---------------------------------------------------------------------------


@freeze_time(FROZEN_NOW)
async def test_engine_meldet_die_sperre_im_ergebnis(db_session: AsyncSession) -> None:
    """``RuleResult.gast_sperre`` kommt aus dem Zimmer.

    **Ohne diesen Test wäre die ganze Datei grün und der Fix wirkungslos.**
    Alle Dispatch-Tests oben setzen ``gast_sperre`` von Hand; ob der echte
    Engine-Lauf den Wert auch füllt, prüft nur diese Stelle. Genau so eine
    Lücke war §5.55: ein grüner Lauf, der nichts geprüft hat.
    """
    room_id, zone_id = await _zimmer_107(db_session, sperre="bis_checkout")
    await _geraet(db_session, zone_id, meldet=GEDREHT, zuletzt_gesendet=SOLL)

    ergebnis = await evaluate_room(db_session, room_id)

    assert ergebnis is not None
    assert ergebnis.gast_sperre is True

    frei_id, frei_zone = await _zimmer_107(db_session, sperre=None)
    await _geraet(db_session, frei_zone, meldet=SOLL, zuletzt_gesendet=SOLL)
    ohne = await evaluate_room(db_session, frei_id)
    assert ohne is not None
    assert ohne.gast_sperre is False


# ---------------------------------------------------------------------------
# 6. Ende zu Ende: der echte Frame von 11:49
# ---------------------------------------------------------------------------


@freeze_time(FROZEN_NOW)
async def test_ende_zu_ende_der_frame_von_1149_holt_23_zurueck(
    db_session: AsyncSession,
    fake_redis: _FakeRedis,
    mock_send_setpoint: list[tuple[str, int]],
    subscriber_sitzung: None,
) -> None:
    """**Die Regressions-Wand.** Der Rad-Test von Zimmer 107, als Test.

    Ein Durchlauf, vier Schritte, alle über den echten Code:

    1. Sperre bis Check-out + Übersteuerung 23, Gerät auf 23.
    2. Der ``0x28``-Frame von 11:49 geht durch
       ``_handle_override_detection`` — derselbe Weg, den der
       MQTT-Subscriber nimmt.
    3. Der Messwert daraus kommt über ``_map_to_reading`` in die
       Datenbank, also aus **demselben** Frame: das Gerät meldet jetzt 25.
    4. Der nächste Engine-Lauf: ``evaluate_room`` rechnet, der Dispatch
       sendet.

    Erwartet: ``control_command`` mit **23**. Vor dem 30.10.2026 kam hier
    nichts, zwei Stunden lang.
    """
    room_id, zone_id = await _zimmer_107(db_session, sperre="bis_checkout")
    device_id, dev_eui = await _geraet(db_session, zone_id, meldet=SOLL, zuletzt_gesendet=SOLL)
    await _uebersteuerung(db_session, room_id, zone_id=zone_id, wert=SOLL)

    # Schritt 2 — der Gast dreht, der Dienst weist ab.
    uplink = _uplink(dev_eui)
    await _handle_override_detection(uplink)

    assert fake_redis.store.get(f"resync_pending:{dev_eui}") == resync_flag.GRUND_SPERRE

    # Schritt 3 — der Messwert aus demselben Frame. In Betrieb schreibt
    # ihn ``_persist_uplink``; hier wird dieselbe reine Abbildung benutzt,
    # damit die gemeldeten 25 aus dem Frame kommen und nicht aus einer
    # Zahl, die der Test sich ausgedacht hat.
    db_session.add(SensorReading(**_map_to_reading(uplink, device_id)))
    await db_session.commit()
    gemeldet = await db_session.scalar(
        select(SensorReading.setpoint)
        .where(SensorReading.device_id == device_id)
        .order_by(SensorReading.time.desc())
        .limit(1)
    )
    assert gemeldet == Decimal(GEDREHT), "der Frame muss 25 melden, sonst prüft der Rest nichts"

    # Schritt 4 — der Engine-Lauf, mit echtem Ergebnis statt Handarbeit.
    ergebnis = await evaluate_room(db_session, room_id)
    assert ergebnis is not None
    # Eine **zonenweite** Übersteuerung lässt ``setpoint_c`` auf dem
    # Zimmerwert und steht in ``zone_overrides``; der Dispatch prüft die
    # Zone zuerst. Geprüft wird deshalb der Zonenwert — und unten der
    # Wert, der tatsächlich gesendet wurde.
    assert ergebnis.zone_overrides == {zone_id: SOLL}
    assert ergebnis.gast_sperre is True

    await _dispatch_downlinks_per_zone(
        session=db_session,
        room_id=room_id,
        target_setpoint_c=ergebnis.setpoint_c,
        base_reason=ergebnis.base_reason,
        eval_id=uuid.uuid4(),
        zone_overrides=ergebnis.zone_overrides,
        bad_setpoint_c=ergebnis.bad_setpoint_c,
        clamp_grenzen_c=ergebnis.clamp_grenzen_c,
        gast_sperre=ergebnis.gast_sperre,
    )

    assert [sp for _, sp in mock_send_setpoint] == [SOLL]
    befehle = (
        (
            await db_session.execute(
                select(ControlCommand)
                .where(ControlCommand.device_id == device_id)
                .where(ControlCommand.issued_at >= FROZEN_NOW - timedelta(minutes=1))
            )
        )
        .scalars()
        .all()
    )
    assert len(befehle) == 1
    assert befehle[0].target_setpoint == Decimal(SOLL)
    assert befehle[0].sent_to_gateway_at is not None


@pytest.mark.parametrize("gemeldeter_wert", [25, 25.0])
@freeze_time(FROZEN_NOW)
async def test_ganzzahl_oder_fliesskomma_macht_keinen_unterschied(
    db_session: AsyncSession,
    fake_redis: _FakeRedis,
    subscriber_sitzung: None,
    gemeldeter_wert: float,
) -> None:
    """``25`` und ``25.0`` im Frame führen zum selben Ergebnis.

    Der Codec gibt Zahlen aus, und ``JSON.stringify`` schreibt ``25`` für
    eine glatte und ``22.5`` für eine halbe Stufe — beim Empfänger wird
    daraus ``int`` oder ``float``, je nach Wert. Welcher Typ ankommt, darf
    die Entscheidung nicht ändern; verglichen wird über ``Decimal``.
    """
    room_id, zone_id = await _zimmer_107(db_session, sperre="bis_checkout")
    _, dev_eui = await _geraet(db_session, zone_id, meldet=SOLL, zuletzt_gesendet=SOLL)

    uplink = _uplink(dev_eui)
    assert uplink.object is not None
    uplink.object["target_temperature"] = gemeldeter_wert

    await _handle_override_detection(uplink)

    assert fake_redis.store.get(f"resync_pending:{dev_eui}") == resync_flag.GRUND_SPERRE
