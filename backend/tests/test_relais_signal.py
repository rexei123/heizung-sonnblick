"""RSSI und SNR fuer Relais — und der Pfad, den noch nie ein Test gesehen hat.

**Der Anlass, 16.11.2026.** ADR hat Relais 108 auf **DR5** hochgezogen,
vier ``LinkADRReq acknowledged`` bei ``installation_margin = 20`` und
voller Sendeleistung. Die Frage, die darueber entscheidet, ob DR1
ueberhaupt die richtige Abhilfe ist — *ist der Link zu schwach, oder
kollidieren die Pakete?* — war **nicht beantwortbar**: ``sensor_reading``
traegt die Empfangsdaten, aber ein Relais schreibt dort nicht hin;
``relay_reading`` hatte die Spalten nicht; und das ChirpStack-Protokoll
fuehrt sie fuer dieses Geraet nicht.

Die Messung dazu, am selben Tag:

===========  ==================  ==================
Fenster      108                 109 Panel
===========  ==================  ==================
6 Stunden    **25,8 %** Verlust  **0,0 %**
48 Stunden   6,2 %               5,1 %
===========  ==================  ==================

Ueber 48 Stunden sind beide Relais kaum zu unterscheiden; in sechs
Stunden verlor eines ein Viertel. Ob das Reichweite war, sagen nur RSSI
und SNR.

## Der wichtigste Test hier prueft keine Fachlichkeit

``test_der_subscriber_schreibt_die_empfangsdaten`` schickt einen
Relais-Uplink durch ``_persist_uplink`` und sieht in der Tabelle nach.
**Im Subscriber-Test gab es bis heute keinen einzigen Relais-Fall** — der
Relais-Zweig dort war nie durchgaengig geprueft, nur seine Bausteine.

Das ist in genau diesem Geraetepfad schon dreimal teuer geworden
(Paragraph 5.87): die Firmware kam nicht an, der Tastendruck verlor seinen
Grund, und die Ruecklesung wurde nie vermerkt. **Alle drei Male war die
Funktion in Ordnung und hatte keinen Aufrufer.** Ein Test, der nur
``werte_aus_codec`` prueft, haette alle drei durchgelassen — und wuerde
auch diese zwei Spalten durchlassen.

## Die 0-dB-Luecke gilt auch hier

``chirpstack.toml`` setzt ``[integration.mqtt] json = true``. ChirpStack
serialisiert dann ueber protojson, und protojson **laesst Felder mit
Default-Wert weg**: ``"snr": 0.0`` steht gar nicht im JSON. Fuer den
Thermostat-Pfad ist das seit Sprint 20e belegt und entschieden — „Block
da, Feld weg" heisst genau 0 — und der Relais-Pfad ruft **denselben**
Helfer. Zwei Entscheidungen fuer dieselbe Frage waeren zwei Wahrheiten
(Paragraph 5.53), und die zweite waere die, die niemand pflegt.
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
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from heizung.models.relay_reading import RelayReading
from heizung.services import relay_uplink
from heizung.services.mqtt_subscriber import ChirpStackUplink

TEST_DB_URL = os.environ.get("TEST_DATABASE_URL")
SKIP_REASON = "TEST_DATABASE_URL nicht gesetzt - DB-Tests brauchen Postgres"

#: **Nur die Datenbank-Tests werden uebersprungen, nicht das ganze Modul.**
#: Die zwei reinen Tests darueber brauchen kein Postgres, und ein Modul-Mark
#: haette sie lokal mit uebersprungen — also genau dort, wo man sie beim
#: Entwickeln braucht.
nur_mit_db = pytest.mark.skipif(not TEST_DB_URL, reason=SKIP_REASON)


#: Alles, was dieses Modul anlegt, traegt dieses Praefix im Namen. Es ist
#: die Handhabe zum Aufraeumen.
PREFIX = "sig"


@pytest_asyncio.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    """Session mit **echtem** Aufraeumen, nicht nur mit ``rollback()``.

    **Der Grund, und er ist beim Bauen dieses Moduls aufgefallen.** Drei
    Tests hier schicken ein Ereignis durch ``_persist_uplink``, und das
    ruft intern ``session.commit()``. Ein ``rollback()`` am Ende raeumt
    danach **nichts** weg: die Zeilen stehen. Gemessen am 16.11.2026 nach
    einem Lauf — drei Geraete, drei Raeume, drei Raumtypen blieben in der
    lokalen Datenbank liegen, und im Gesamtlauf fielen danach fuenf
    fremde Tests um (Boost und Allgemeinbereiche), weil sie hausweite
    Zahlen pruefen.

    Das ist Paragraph 5.39 und dieselbe Klasse wie das Leck in
    ``test_api_rooms.zimmer_mit_thermostat``, das am 15.11. den
    Funkempfangs-Test umgeworfen hat. Der Kommentar im Nachbar-Harness
    (*„commit() wird auf der gleichen Verbindung gemacht und beim
    Tear-down weggerollt"*) gilt dort, wo der Test selbst nicht
    committet — hier gilt er nicht.

    Deshalb wird **nach Namen** geloescht, nicht nach Transaktion.
    ``device`` haengt per ``ON DELETE CASCADE`` an ``room``, und
    ``relay_reading`` an ``device`` — die Reihenfolge unten ist trotzdem
    ausgeschrieben, damit sie nicht von einer Fremdschlüssel-Regel
    abhaengt, die jemand aendert.
    """
    engine = create_async_engine(TEST_DB_URL or "", poolclass=None)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with maker() as session:
            try:
                yield session
            finally:
                await session.rollback()
        async with maker() as aufraeumen:
            await aufraeumen.execute(
                text(
                    "DELETE FROM relay_reading WHERE device_id IN "
                    "(SELECT id FROM device WHERE label = :etikett)"
                ),
                {"etikett": f"{PREFIX}-Panel"},
            )
            await aufraeumen.execute(
                text("DELETE FROM device WHERE label = :etikett"),
                {"etikett": f"{PREFIX}-Panel"},
            )
            await aufraeumen.execute(
                text(
                    "DELETE FROM heating_zone WHERE room_id IN "
                    "(SELECT id FROM room WHERE number LIKE :muster)"
                ),
                {"muster": f"{PREFIX}-%"},
            )
            await aufraeumen.execute(
                text("DELETE FROM room WHERE number LIKE :muster"),
                {"muster": f"{PREFIX}-%"},
            )
            await aufraeumen.execute(
                text("DELETE FROM room_type WHERE name LIKE :muster"),
                {"muster": f"{PREFIX}-rt-%"},
            )
            await aufraeumen.commit()
    finally:
        await engine.dispose()


# ------------------------------------------------------- ohne Datenbank


def test_die_empfangsdaten_landen_in_der_zeile() -> None:
    """Durchgereicht, nicht aus dem Codec geraten.

    ``rssi`` und ``snr`` stehen im ``rxInfo``-Block des Ereignisses, nicht
    in der Nutzlast — der Codec sieht sie nie. Deshalb sind sie Parameter
    und keine ``obj.get``-Zeile.
    """
    werte = relay_uplink.werte_aus_codec(
        {"relayState": "ON", "power_W": 1500},
        device_id=7,
        zeit=datetime(2026, 11, 16, 9, 0, tzinfo=UTC),
        fcnt=3,
        rssi_dbm=-109,
        snr_db=Decimal("2.5"),
    )
    assert werte["rssi_dbm"] == -109
    assert werte["snr_db"] == Decimal("2.5")
    # Und der Rest bleibt, wie er war.
    assert werte["relay_on"] is True
    assert werte["power_w"] == 1500


def test_ohne_empfangsdaten_bleibt_die_zeile_leer_und_nicht_null() -> None:
    """``None`` heisst „sagt nichts darueber", nicht „kein Empfang".

    Eine 0 waere hier eine Behauptung ueber einen Funk, den wir nicht
    gemessen haben — und sie waere beim Median in ``funkqualitaet`` ein
    Ausreisser, der das Bild verschiebt.
    """
    werte = relay_uplink.werte_aus_codec(
        {"relayState": "OFF"},
        device_id=7,
        zeit=datetime(2026, 11, 16, 9, 0, tzinfo=UTC),
        fcnt=4,
    )
    assert werte["rssi_dbm"] is None
    assert werte["snr_db"] is None


# -------------------------------------------------------- mit Datenbank


async def _relais(session: AsyncSession) -> tuple[int, str]:
    """Ein Relais mit Raum und Zone. Gibt (device_id, dev_eui) zurueck."""
    from heizung.models.device import Device
    from heizung.models.enums import DeviceKind, DeviceVendor, HeatingZoneKind
    from heizung.models.heating_zone import HeatingZone
    from heizung.models.room import Room
    from heizung.models.room_type import RoomType

    suffix = uuid.uuid4().hex[:8]
    rt = RoomType(name=f"{PREFIX}-rt-{suffix}", is_bookable=False)
    session.add(rt)
    await session.flush()
    room = Room(number=f"{PREFIX}-{suffix}", room_type_id=rt.id)
    session.add(room)
    await session.flush()
    zone = HeatingZone(room_id=room.id, kind=HeatingZoneKind.BEDROOM, name="zone")
    session.add(zone)
    await session.flush()

    jetzt = datetime.now(tz=UTC)
    dev_eui = f"5165{uuid.uuid4().hex[:12]}"
    dev = Device(
        dev_eui=dev_eui,
        kind=DeviceKind.RELAY,
        vendor=DeviceVendor.MCLIMATE,
        model="16ASPM",
        label=f"{PREFIX}-Panel",
        heating_zone_id=zone.id,
        health_state="healthy",
        power_return_verified_at=jetzt - timedelta(hours=1),
        overheating_recovery_verified_at=jetzt - timedelta(hours=1),
        commissioned_at=jetzt - timedelta(minutes=30),
    )
    session.add(dev)
    await session.flush()
    return dev.id, dev_eui


def _relais_payload(dev_eui: str, *, rx: list[dict[str, Any]] | None, fcnt: int) -> dict[str, Any]:
    """Ein Keepalive des 16ASPM, wie ChirpStack es ueber MQTT schickt."""
    payload: dict[str, Any] = {
        "deviceInfo": {"devEui": dev_eui},
        "fCnt": fcnt,
        "fPort": 1,
        "time": "2026-11-16T08:00:00Z",
        "object": {"relayState": "ON", "power_W": 1540},
    }
    if rx is not None:
        payload["rxInfo"] = rx
    return payload


async def _durch_den_subscriber(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch, payload: dict[str, Any]
) -> None:
    """Schickt ein Ereignis durch ``_persist_uplink`` auf dieser Session."""
    from heizung.services import mqtt_subscriber as sub

    class _Kontext:
        async def __aenter__(self) -> AsyncSession:
            return session

        async def __aexit__(self, *args: object) -> None:
            return None

    monkeypatch.setattr(sub, "SessionLocal", lambda: _Kontext())
    await sub._persist_uplink(ChirpStackUplink.model_validate(payload))


async def _juengste(session: AsyncSession, device_id: int) -> RelayReading:
    return (
        await session.execute(
            select(RelayReading)
            .where(RelayReading.device_id == device_id)
            .order_by(RelayReading.time.desc())
            .limit(1)
        )
    ).scalar_one()


@nur_mit_db
async def test_der_subscriber_schreibt_die_empfangsdaten(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """**Der Verdrahtungstest.** Vorher gab es fuer den Relais-Zweig keinen.

    Drei Mal hat in genau diesem Pfad eine fertige, getestete Funktion
    ohne Aufrufer gestanden (Paragraph 5.87). Dieser Test sieht nicht in
    eine Funktion, sondern in die **Tabelle**.
    """
    device_id, dev_eui = await _relais(db_session)
    await _durch_den_subscriber(
        db_session,
        monkeypatch,
        _relais_payload(dev_eui, rx=[{"rssi": -112, "snr": -3.5}], fcnt=11),
    )

    zeile = await _juengste(db_session, device_id)
    assert zeile.rssi_dbm == -112, "der Subscriber reicht RSSI nicht durch"
    assert zeile.snr_db == Decimal("-3.5"), "der Subscriber reicht SNR nicht durch"
    # Und der bestehende Pfad ist unberuehrt.
    assert zeile.relay_on is True
    assert zeile.power_w == 1540


@nur_mit_db
async def test_fehlendes_snr_bei_vorhandenem_block_heisst_genau_null(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Die protojson-Luecke gilt fuer Relais genauso.

    ``"snr": 0.0`` steht nicht im JSON, weil protojson Default-Werte
    weglaesst. Ohne diese Regel bekaeme die Spalte NULL, und ein Relais mit
    **genau** 0 dB saehe aus wie eines, von dem wir nichts wissen.

    Geprueft wird hier die **Wirkung im Relais-Pfad**, nicht der Helfer —
    der ist im Thermostat-Pfad schon geprueft. Was dieser Test zusichert,
    ist, dass der Relais-Pfad ihn **benutzt** und nicht an ihm vorbeigeht.
    """
    device_id, dev_eui = await _relais(db_session)
    await _durch_den_subscriber(
        db_session,
        monkeypatch,
        _relais_payload(dev_eui, rx=[{"rssi": -98}], fcnt=12),
    )

    zeile = await _juengste(db_session, device_id)
    assert zeile.rssi_dbm == -98
    assert zeile.snr_db == Decimal("0"), (
        "Block da, Feld weg heisst genau 0 — NULL waere hier eine zweite "
        "Entscheidung derselben Frage (§5.53)"
    )


@nur_mit_db
async def test_ohne_rxinfo_bleiben_beide_spalten_leer(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Kein Block, keine Aussage.

    Die Null-Regel gilt **nur**, wenn der Block da ist. Fehlt er ganz,
    wissen wir nichts, und das muss sich von „genau 0 dB" unterscheiden
    lassen.
    """
    device_id, dev_eui = await _relais(db_session)
    await _durch_den_subscriber(db_session, monkeypatch, _relais_payload(dev_eui, rx=[], fcnt=13))

    zeile = await _juengste(db_session, device_id)
    assert zeile.rssi_dbm is None
    assert zeile.snr_db is None


@nur_mit_db
async def test_funkqualitaet_liest_die_relais_tabelle(db_session: AsyncSession) -> None:
    """Das Werkzeug gab fuer Relais bisher Striche zurueck, per Zweig.

    Vor dem 16.11.2026 stand in ``funkqualitaet`` ein ``if kind == RELAY:
    rssi = None`` — richtig, solange die Spalten fehlten, und still
    falsch, sobald sie da sind. Der Zweig ist weg; geprueft wird, dass
    das Werkzeug nun wirklich in ``relay_reading`` sieht.

    Der Median und nicht der Durchschnitt, wie dort: drei Werte, der
    mittlere gewinnt.
    """
    from heizung.models.enums import DeviceKind
    from heizung.scripts import funkqualitaet

    device_id, _ = await _relais(db_session)
    basis = datetime.now(tz=UTC) - timedelta(minutes=30)
    for i, (rssi, snr) in enumerate([(-120, "-8.0"), (-100, "1.0"), (-110, "-2.0")]):
        db_session.add(
            RelayReading(
                time=basis + timedelta(minutes=i),
                device_id=device_id,
                fcnt=100 + i,
                relay_on=True,
                rssi_dbm=rssi,
                snr_db=Decimal(snr),
            )
        )
    await db_session.flush()

    rssi_min, rssi_med, snr_min, snr_med = await funkqualitaet._empfangsdaten(
        db_session, device_id, basis - timedelta(minutes=1), art=DeviceKind.RELAY
    )
    assert rssi_min == -120, "der kleinste RSSI ist der schlechteste Empfang"
    assert rssi_med == -110, "Median von -120/-110/-100"
    assert snr_min == Decimal("-8.0")
    assert snr_med == Decimal("-2.0")
