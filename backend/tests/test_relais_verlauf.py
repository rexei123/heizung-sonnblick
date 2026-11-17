"""Relais-Verlauf: Tageszeilen, Energie, Endpunkte und CSV (17.11.2026).

**Was hier NICHT geprueft wird:** die Stundenrechnung selbst. Die steht
seit dem 15.11. in ``test_relais_auswertung`` und ist dort mit fuenfzehn
Tests belegt — unveraendert, obwohl die Rechnung in
``services/relais_verlauf`` gewandert ist. Genau das ist der Beleg, dass
die Verlagerung verhaltensneutral war (Paragraph 5.46/5.47); sie hier ein
zweites Mal zu pruefen waere eine zweite Zusicherung fuer dieselbe
Rechnung.

Geprueft wird das **Neue**: der Ortszeit-Kalendertag, die Gewichtung der
Tageszeile, die Energie mit Ruecksprung und die beiden Endpunkte.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path as FsPath
from typing import Any

import httpx
import pytest
import pytest_asyncio
from alembic.config import Config
from httpx import ASGITransport
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from alembic import command
from heizung.auth.dependencies import get_current_user
from heizung.db import get_session
from heizung.main import app
from heizung.models.device import Device
from heizung.models.enums import (
    CommandReason,
    DeviceKind,
    DeviceVendor,
    EventLogLayer,
    HeatingZoneKind,
    UserRole,
)
from heizung.models.event_log import EventLog
from heizung.models.heating_zone import HeatingZone
from heizung.models.relay_reading import RelayReading
from heizung.models.room import Room
from heizung.models.room_type import RoomType
from heizung.models.sensor_reading import SensorReading
from heizung.models.user import User
from heizung.services import relais_verlauf

WIEN = "Europe/Vienna"


# ---------------------------------------------------------------------------
# Der Kalendertag — die Stelle, an der eine Tageszeile stillschweigend
# die falsche Frage beantwortet.
# ---------------------------------------------------------------------------


def _stunde(
    t: datetime,
    *,
    anteil: int | None = 50,
    minuten: int = 60,
    ein_minuten: int | None = 30,
    einschaltungen: int = 1,
    energie: int | None = None,
    ruecksprunge: int = 0,
    ist: str | None = None,
    soll: str | None = None,
) -> relais_verlauf.Stunde:
    return relais_verlauf.Stunde(
        stunde=t,
        ein_prozent=anteil,
        erfasste_minuten=minuten,
        einschaltungen=einschaltungen,
        ist_mittel=Decimal(ist) if ist else None,
        ist_min=Decimal(ist) if ist else None,
        ist_max=Decimal(ist) if ist else None,
        soll=Decimal(soll) if soll else None,
        ein_minuten=ein_minuten,
        energie_wh=energie,
        ruecksprunge=ruecksprunge,
    )


def test_der_kalendertag_ist_der_ortszeit_tag_winter() -> None:
    """23:00 UTC im November ist in Wien **schon der naechste Tag**.

    Ein ``date_trunc('day', ...)`` in UTC haette hier den 16. stehen —
    und damit eine Tageszeile, die um 01:00 Ortszeit beginnt. Das ist die
    Falle aus Paragraph 5.65, nur in der Anzeige statt in der Engine.
    """
    tage = relais_verlauf.tage_aus_stunden(
        [_stunde(datetime(2026, 11, 16, 23, 0, tzinfo=UTC))], WIEN
    )
    assert [t.tag for t in tage] == [date(2026, 11, 17)]


def test_der_kalendertag_ist_der_ortszeit_tag_sommer() -> None:
    """Im Sommer verschiebt sich die Grenze um eine weitere Stunde.

    22:00 UTC ist in Wien bereits 00:00 des Folgetags. Eine feste
    Verschiebung um eine Stunde (statt ``zoneinfo``) waere im Winter
    richtig und hier falsch — ein halbes Jahr lang unauffaellig.
    """
    tage = relais_verlauf.tage_aus_stunden(
        [_stunde(datetime(2026, 6, 30, 22, 0, tzinfo=UTC))], WIEN
    )
    assert [t.tag for t in tage] == [date(2026, 7, 1)]


def test_stunden_eines_tages_kommen_in_eine_zeile() -> None:
    basis = datetime(2026, 11, 17, 8, 0, tzinfo=UTC)
    tage = relais_verlauf.tage_aus_stunden(
        [_stunde(basis), _stunde(basis + timedelta(hours=1)), _stunde(basis + timedelta(days=1))],
        WIEN,
    )
    assert [(t.tag, t.einschaltungen) for t in tage] == [
        (date(2026, 11, 17), 2),
        (date(2026, 11, 18), 1),
    ]


# ---------------------------------------------------------------------------
# Die Gewichtung der Tageszeile — dieselbe Falle wie beim Gesamtanteil.
# ---------------------------------------------------------------------------


def test_der_tagesanteil_wiegt_nach_erfasster_zeit() -> None:
    """Eine Randstunde mit sechs Minuten zaehlt nicht wie eine volle.

    100 Prozent in sechs Minuten neben 60 Prozent in sechzig: der
    Mittelwert waere 80, richtig sind 64. Am Rand des Fensters ist die
    erste Stunde **immer** kurz, der Fehler traete also an jedem Tag auf.
    """
    basis = datetime(2026, 11, 17, 8, 0, tzinfo=UTC)
    tage = relais_verlauf.tage_aus_stunden(
        [
            _stunde(basis, anteil=100, minuten=6),
            _stunde(basis + timedelta(hours=1), anteil=60, minuten=60),
        ],
        WIEN,
    )
    assert [t.ein_prozent for t in tage] == [64]


def test_eine_stunde_ohne_meldung_zieht_den_tag_nicht_nach_unten() -> None:
    """Eine Luecke ist keine Null — auch nicht in der Tageszeile."""
    basis = datetime(2026, 11, 17, 8, 0, tzinfo=UTC)
    tage = relais_verlauf.tage_aus_stunden(
        [
            _stunde(basis, anteil=None, minuten=0, ein_minuten=None),
            _stunde(basis + timedelta(hours=1), anteil=60, minuten=60),
        ],
        WIEN,
    )
    assert [t.ein_prozent for t in tage] == [60]


def test_ein_tag_ohne_jede_meldung_hat_keinen_anteil() -> None:
    tage = relais_verlauf.tage_aus_stunden(
        [_stunde(datetime(2026, 11, 17, 8, 0, tzinfo=UTC), anteil=None, minuten=0)], WIEN
    )
    assert tage[0].ein_prozent is None


def test_die_heizdauer_wird_addiert_und_nicht_aus_prozent_gerechnet() -> None:
    """Minuten kommen aus Minuten.

    Aus 50 Prozent von 60 Minuten zurueckzurechnen gibt hier dieselbe
    Zahl; bei einer Randstunde mit 7 erfassten Minuten und 43 Prozent
    nicht mehr. Deshalb traegt die Stunde ihre Minuten selbst.
    """
    basis = datetime(2026, 11, 17, 8, 0, tzinfo=UTC)
    tage = relais_verlauf.tage_aus_stunden(
        [_stunde(basis, ein_minuten=7), _stunde(basis + timedelta(hours=1), ein_minuten=43)], WIEN
    )
    assert tage[0].ein_minuten == 50


# ---------------------------------------------------------------------------
# Energie — ein Zaehler, kein Messwert.
# ---------------------------------------------------------------------------


def _bericht(stunden: list[relais_verlauf.Stunde]) -> relais_verlauf.Zonenbericht:
    return relais_verlauf.Zonenbericht(
        zone_id=299,
        room_id=139,
        zone_name="Eingang",
        zimmer="Rezeption",
        relais=["108"],
        stunden=stunden,
    )


def test_ohne_zaehlerstand_gibt_es_keine_energie_und_keine_null() -> None:
    """``None`` und nicht 0.

    Eine 0 kWh waere eine Aussage: „es lief und hat nichts verbraucht".
    Fuer jede Zeile vor der Migration 0041 ist das Gegenteil wahr — wir
    wissen es nur nicht.
    """
    basis = datetime(2026, 11, 17, 8, 0, tzinfo=UTC)
    stunden = [_stunde(basis), _stunde(basis + timedelta(hours=1))]
    assert _bericht(stunden).energie_wh_gesamt is None
    assert relais_verlauf.tage_aus_stunden(stunden, WIEN)[0].energie_wh is None


def test_die_energie_summiert_was_gemeldet_ist() -> None:
    basis = datetime(2026, 11, 17, 8, 0, tzinfo=UTC)
    stunden = [
        _stunde(basis, energie=260),
        _stunde(basis + timedelta(hours=1), energie=None),
        _stunde(basis + timedelta(hours=2), energie=1300),
    ]
    assert _bericht(stunden).energie_wh_gesamt == 1560
    assert relais_verlauf.tage_aus_stunden(stunden, WIEN)[0].energie_wh == 1560


def test_ruecksprunge_werden_gezaehlt_und_nicht_verrechnet() -> None:
    """Der Ruecksprung steht neben dem Verbrauch, nicht darin.

    Dasselbe Muster wie bei ``paketverlust``, das Geraete-Neustarts
    ausweist: eine Zahl, die kleiner ist als erwartet, muss **erklaerbar**
    sein. Zoege man den Ruecksprung ab, waere das Ergebnis still falsch.
    """
    basis = datetime(2026, 11, 17, 8, 0, tzinfo=UTC)
    stunden = [_stunde(basis, energie=260, ruecksprunge=1)]
    bericht = _bericht(stunden)
    assert bericht.energie_wh_gesamt == 260
    assert bericht.ruecksprunge_gesamt == 1
    assert relais_verlauf.tage_aus_stunden(stunden, WIEN)[0].ruecksprunge == 1


def test_die_zonenwerte_des_tages_kommen_aus_den_stunden() -> None:
    """Mittel aus den Stundenmitteln, Spanne aus den Stundenspannen."""
    basis = datetime(2026, 11, 17, 8, 0, tzinfo=UTC)
    tage = relais_verlauf.tage_aus_stunden(
        [
            _stunde(basis, ist="20.0", soll="23.0"),
            _stunde(basis + timedelta(hours=1), ist="22.0", soll="23.0"),
        ],
        WIEN,
    )
    assert tage[0].ist_mittel == Decimal("21.0")
    assert tage[0].ist_min == Decimal("20.0")
    assert tage[0].ist_max == Decimal("22.0")
    assert tage[0].soll_mittel == Decimal("23.0")


# ---------------------------------------------------------------------------
# Gegen die Datenbank und durch den ASGI-Stack.
# ---------------------------------------------------------------------------

DATABASE_URL = os.environ.get("DATABASE_URL")
PREFIX = "t-verl"

pytestmark = pytest.mark.skipif(
    not DATABASE_URL, reason="DATABASE_URL nicht gesetzt - DB-Tests brauchen Postgres"
)


@pytest_asyncio.fixture(scope="module", autouse=True)
async def _migrate_db() -> None:
    if not DATABASE_URL:
        return
    backend_root = FsPath(__file__).resolve().parents[1]
    cfg = Config(str(backend_root / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend_root / "alembic"))
    cfg.set_main_option("sqlalchemy.url", DATABASE_URL)
    await asyncio.to_thread(command.upgrade, cfg, "head")


@pytest_asyncio.fixture
async def setup_engine() -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(DATABASE_URL or "", poolclass=None)
    yield engine
    await engine.dispose()


class Aufbau:
    def __init__(
        self, room_id: int, zone_id: int, fuehler_id: int, relais_id: int, frei_id: int
    ) -> None:
        self.room_id = room_id
        self.zone_id = zone_id
        self.fuehler_id = fuehler_id
        self.relais_id = relais_id
        #: Ein Relais **ohne** Heizzone — der 422-Fall.
        self.frei_id = frei_id


@pytest_asyncio.fixture
async def haus(setup_engine: AsyncEngine) -> AsyncIterator[Aufbau]:
    """Eine Relais-Zone mit zwei Stunden Geschichte **und Zaehlerstaenden**.

    Stunde 1: durchgehend EIN, der Zaehler laeuft in 10-Minuten-Schritten
    von 1000 auf 1260 Wh (260 Wh in der Stunde, passend zu 1560 W).
    Stunde 2: drei Meldungen EIN, dann AUS — und **ein Ruecksprung**: die
    vierte Meldung steht auf 0, wie nach einem ``0x26``. Danach laeuft er
    von 0 weiter.
    """
    maker = async_sessionmaker(setup_engine, expire_on_commit=False)
    short = uuid.uuid4().hex[:4]
    basis = datetime.now(tz=UTC).replace(minute=0, second=0, microsecond=0) - timedelta(hours=3)

    async with maker() as session:
        rt = RoomType(
            name=f"{PREFIX}-rt-{short}", is_bookable=False, default_t_occupied=Decimal("23.0")
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
            dev_eui=f"cafe{uuid.uuid4().hex[:12]}",
            kind=DeviceKind.THERMOSTAT,
            vendor=DeviceVendor.MCLIMATE,
            model="vicki",
            label=f"{PREFIX}-056",
            heating_zone_id=zone.id,
            health_state="healthy",
            measure_only=True,
        )
        relais = Device(
            dev_eui=f"cafe{uuid.uuid4().hex[:12]}",
            kind=DeviceKind.RELAY,
            vendor=DeviceVendor.MCLIMATE,
            model="16ASPM",
            label=f"{PREFIX}-108",
            heating_zone_id=zone.id,
            health_state="healthy",
            commissioned_at=basis - timedelta(hours=1),
        )
        frei = Device(
            dev_eui=f"cafe{uuid.uuid4().hex[:12]}",
            kind=DeviceKind.RELAY,
            vendor=DeviceVendor.MCLIMATE,
            model="16ASPM",
            label=f"{PREFIX}-ohne-zone",
            health_state="healthy",
        )
        session.add_all([fuehler, relais, frei])
        await session.flush()

        meldungen: list[tuple[datetime, bool, int]] = []
        for i in range(6):
            meldungen.append((basis + timedelta(minutes=10 * i), True, 1000 + 43 * i))
        # Stunde 2: EIN, EIN, EIN, dann AUS — und der Zaehler fangt bei
        # der vierten Meldung wieder bei 0 an.
        for i in range(6):
            stand = 1258 + 43 * i if i < 3 else 43 * (i - 3)
            meldungen.append((basis + timedelta(hours=1, minutes=10 * i), i < 3, stand))
        meldungen.append((basis + timedelta(hours=2), False, 129))
        session.add_all(
            [
                RelayReading(
                    time=t,
                    device_id=relais.id,
                    relay_on=ein,
                    power_w=1560 if ein else 0,
                    energy_wh=wh,
                )
                for t, ein, wh in meldungen
            ]
        )
        session.add_all(
            [
                SensorReading(
                    time=basis + timedelta(minutes=30),
                    device_id=fuehler.id,
                    temperature=Decimal("20.0"),
                    attached_backplate=False,
                ),
                SensorReading(
                    time=basis + timedelta(hours=1, minutes=30),
                    device_id=fuehler.id,
                    temperature=Decimal("22.0"),
                    attached_backplate=False,
                ),
            ]
        )
        session.add_all(
            [
                EventLog(
                    time=basis + timedelta(minutes=30) + timedelta(hours=h),
                    room_id=room.id,
                    evaluation_id=uuid.uuid4(),
                    layer=EventLogLayer.HARD_CLAMP,
                    setpoint_in=Decimal("23.0"),
                    setpoint_out=Decimal("23.0"),
                    reason=CommandReason.VACANT_SETPOINT,
                    details={"downlink_zone_status": [{"zone_id": zone.id, "setpoint_c": 23}]},
                )
                for h in (0, 1)
            ]
        )
        await session.commit()
        ids = Aufbau(room.id, zone.id, fuehler.id, relais.id, frei.id)

    try:
        yield ids
    finally:
        # **Aufraeumen von Hand** (Paragraph 5.39): die Zeilen sind
        # festgeschrieben, ein ``rollback`` der Test-Session nimmt sie
        # nicht zurueck. Am 16.11. haben genau drei zurueckgebliebene
        # Geraete fuenf fremde Tests kippen lassen.
        async with maker() as session:
            await session.execute(
                text("DELETE FROM event_log WHERE room_id = :r"), {"r": ids.room_id}
            )
            await session.execute(
                text("DELETE FROM relay_reading WHERE device_id = ANY(:d)"),
                {"d": [ids.relais_id, ids.frei_id]},
            )
            await session.execute(
                text("DELETE FROM sensor_reading WHERE device_id = ANY(:d)"),
                {"d": [ids.fuehler_id, ids.relais_id]},
            )
            await session.execute(text("DELETE FROM room WHERE id = :r"), {"r": ids.room_id})
            await session.execute(
                text("DELETE FROM device WHERE id = ANY(:d)"),
                {"d": [ids.fuehler_id, ids.relais_id, ids.frei_id]},
            )
            await session.execute(
                text("DELETE FROM room_type WHERE name LIKE :p"), {"p": f"{PREFIX}-%"}
            )
            await session.commit()


@pytest_asyncio.fixture
async def client(setup_engine: AsyncEngine) -> AsyncIterator[httpx.AsyncClient]:
    maker = async_sessionmaker(setup_engine, expire_on_commit=False)

    async def _session() -> AsyncIterator[Any]:
        async with maker() as session:
            yield session

    app.dependency_overrides[get_session] = _session
    app.dependency_overrides[get_current_user] = lambda: User(
        id=1,
        email="mitarbeiter@example.invalid",
        password_hash="x",
        role=UserRole.MITARBEITER,
        is_active=True,
    )
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.pop(get_session, None)
    app.dependency_overrides.pop(get_current_user, None)


async def test_der_zaehler_wird_nur_nach_oben_gerechnet(
    haus: Aufbau, setup_engine: AsyncEngine
) -> None:
    """Der Ruecksprung in Stunde 2 darf den Verbrauch nicht verkleinern.

    Gemeldet sind 1000 -> 1258 in der ersten Stunde (258 Wh, die letzte
    Meldung zaehlt in die zweite) und danach ein Sprung auf 0. Summiert
    werden nur die positiven Schritte; der Sprung nach unten steht als
    ``ruecksprunge`` daneben.

    **Ohne diese Behandlung** waere die Summe um 1387 Wh zu klein — und
    niemand saehe, warum.
    """
    maker = async_sessionmaker(setup_engine, expire_on_commit=False)
    async with maker() as session:
        geraet = await session.get(Device, haus.relais_id)
        assert geraet is not None
        verlauf = await relais_verlauf.lade_relais_verlauf(
            session, geraet=geraet, bereich="24h", tz_name=WIEN
        )

    assert verlauf is not None
    assert verlauf.ruecksprunge_gesamt == 1
    # 12 positive Schritte a 43 Wh: 5 in Stunde 1, 3 ueber die Grenze und
    # in Stunde 2, dann 3 nach dem Ruecksprung. Der Sprung selbst (-1387)
    # ist nicht dabei.
    assert verlauf.energie_wh_gesamt == 43 * 11
    assert all(s.energie_wh is None or s.energie_wh >= 0 for s in verlauf.stunden)


async def test_die_heizdauer_steht_in_minuten(haus: Aufbau, setup_engine: AsyncEngine) -> None:
    """Erste Stunde voll, zweite halb — 60 und 30 Minuten.

    Die Probe auf die Minuten neben dem Prozentwert: ein Fehler in der
    Umrechnung (Sekunden statt Minuten) waere in Prozent **unsichtbar**.
    """
    maker = async_sessionmaker(setup_engine, expire_on_commit=False)
    async with maker() as session:
        geraet = await session.get(Device, haus.relais_id)
        assert geraet is not None
        verlauf = await relais_verlauf.lade_relais_verlauf(
            session, geraet=geraet, bereich="24h", tz_name=WIEN
        )

    assert verlauf is not None
    mit_dauer = [s.ein_minuten for s in verlauf.stunden if s.ein_prozent is not None]
    assert mit_dauer == [60, 30]
    assert verlauf.ein_minuten_gesamt == 90


async def test_ohne_heizzone_gibt_es_keinen_verlauf(
    haus: Aufbau, setup_engine: AsyncEngine
) -> None:
    """``None`` ist kein Fehler, sondern der Zustand eines neuen Geraets."""
    maker = async_sessionmaker(setup_engine, expire_on_commit=False)
    async with maker() as session:
        geraet = await session.get(Device, haus.frei_id)
        assert geraet is not None
        verlauf = await relais_verlauf.lade_relais_verlauf(
            session, geraet=geraet, bereich="24h", tz_name=WIEN
        )
    assert verlauf is None


async def test_der_endpunkt_liefert_stunden_und_tage(
    haus: Aufbau, client: httpx.AsyncClient
) -> None:
    antwort = await client.get(f"/api/v1/devices/{haus.relais_id}/relay/history?range=24h")
    assert antwort.status_code == 200
    daten = antwort.json()

    assert daten["range"] == "24h"
    assert daten["zone_name"] == "Eingang"
    assert daten["relais"] == [f"{PREFIX}-108"]
    assert daten["timezone"]
    mit_anteil = [s for s in daten["stunden"] if s["ein_prozent"] is not None]
    assert [s["ein_prozent"] for s in mit_anteil] == [100, 50]
    assert [s["ein_minuten"] for s in mit_anteil] == [60, 30]
    assert daten["ein_minuten_gesamt"] == 90
    assert daten["ruecksprunge"] == 1
    assert daten["energie_wh_gesamt"] == 43 * 11
    # Ist und Soll stehen nebeneinander — der Grund, aus dem es diese
    # Ansicht gibt.
    assert mit_anteil[0]["ist_mittel"] == "20.00"
    assert mit_anteil[0]["soll"] == "23"
    assert daten["tage"], "mindestens eine Tageszeile"
    assert sum(t["ein_minuten"] for t in daten["tage"]) == 90


async def test_jeder_bereich_wird_angenommen(haus: Aufbau, client: httpx.AsyncClient) -> None:
    """24h, 7d und 30d — und nichts sonst."""
    for bereich in ("24h", "7d", "30d"):
        antwort = await client.get(
            f"/api/v1/devices/{haus.relais_id}/relay/history?range={bereich}"
        )
        assert antwort.status_code == 200, bereich
        assert antwort.json()["range"] == bereich

    schlecht = await client.get(f"/api/v1/devices/{haus.relais_id}/relay/history?range=90d")
    assert schlecht.status_code == 422


async def test_ein_fremdes_geraet_bekommt_keinen_verlauf(
    haus: Aufbau, client: httpx.AsyncClient
) -> None:
    """Ein Thermostat ist kein Relais, und die Meldung nennt **kein** ``device_id``.

    Vorgabe des Betreibers vom 16.11.2026: Etikett und Art, nie die
    Nummer — Geraet 109 traegt das Etikett „108".
    """
    antwort = await client.get(f"/api/v1/devices/{haus.fuehler_id}/relay/history")
    assert antwort.status_code == 422
    assert f"{PREFIX}-056" in antwort.json()["detail"]

    fehlt = await client.get("/api/v1/devices/99999999/relay/history")
    assert fehlt.status_code == 404
    assert "Nummer 99999999" in fehlt.json()["detail"]


async def test_ohne_zone_sagt_der_endpunkt_warum(haus: Aufbau, client: httpx.AsyncClient) -> None:
    antwort = await client.get(f"/api/v1/devices/{haus.frei_id}/relay/history")
    assert antwort.status_code == 422
    assert "keiner Heizzone" in antwort.json()["detail"]


async def test_die_csv_ist_fuer_excel_gebaut(haus: Aufbau, client: httpx.AsyncClient) -> None:
    """Semikolon, Dezimalkomma, BOM — und beide Zeiten.

    Jede dieser vier Eigenschaften ist eine Entscheidung und keine
    Gewohnheit: ohne Semikolon steht in Excel alles in Spalte A, ohne
    Dezimalkomma ist „20.00" Text, ohne BOM wird ein Umlaut
    Kauderwelsch, und ohne die UTC-Spalte ist die Datei nicht wieder
    maschinell einzulesen (Paragraph 5.92).
    """
    antwort = await client.get(f"/api/v1/devices/{haus.relais_id}/relay/history.csv?range=24h")
    assert antwort.status_code == 200
    assert antwort.headers["content-type"].startswith("text/csv")
    assert "attachment" in antwort.headers["content-disposition"]
    assert ".csv" in antwort.headers["content-disposition"]

    roh = antwort.content.decode("utf-8")
    assert roh.startswith("﻿"), "ohne BOM liest Excel Windows-1252"
    zeilen = roh.lstrip("﻿").rstrip("\r\n").split("\r\n")
    assert zeilen[0].split(";")[:3] == ["Stunde (Ortszeit)", "Zeitzone", "Stunde (UTC)"]
    assert len(zeilen) >= 3, "Kopf und mindestens zwei Stundenzeilen"

    felder = zeilen[1].split(";")
    assert felder[1] == "Europe/Vienna"
    # Ist-Mittel: Dezimalkomma, nicht Punkt.
    assert "20,00" in zeilen[1] or "20,00" in zeilen[2]
    assert "20.00" not in roh
