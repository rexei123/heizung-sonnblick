"""Stundengrenze und Gehaeusetemperatur im Relais-Verlauf (27.11.2026).

**Der Anlass steht in einer Zahl:** am 18.11.2026 zeigte eine Stundenzeile
**0 Prozent Einschaltanteil und 193 Wh**. Beides war aus derselben Spanne
gerechnet und beides landete in derselben Stunde — der Zustand kam vom
Anfang der Spanne (um 10:57 stand das Relais auf AUS), der Zaehlersprung
von deren Ende (zwischen 10:57 und 11:07 lief es, naemlich ab 11:00). Eine
Zeile, die zwei Dinge sagt, die sich widersprechen.

Hier steht der Prueffall dazu, und zwar **mit genau dieser Zahl**: eine
Meldung um :57, die naechste um :07 der Folgestunde, 193 Wh dazwischen.

**Warum die Pruefung am Dienst haengt und nicht am Endpunkt.**
``lade_relais_verlauf`` nimmt ``jetzt`` als Argument, der Endpunkt nicht.
Mit festem ``jetzt`` liegt das Fenster fest, und die Zeilen liegen sicher
darin — ohne Abhaengigkeit von der Tageszeit, zu der die Suite laeuft
(Paragraph 5.59). Der Endpunkt wird dort geprueft, wo er etwas Eigenes
tut: in den CSV-Spalten und in der Form der Zahlen.

**Die Zeiten kommen aus der echten Uhr, sagen aber nur Abstaende.** Der
Pruefstand liegt auf 10:00 und 11:00 **Ortszeit** des Vortages — zwei
Stunden, die nie ueber Mitternacht reichen, womit die Tageszeile
unabhaengig von der Tageszeit des Laufs dieselbe bleibt. Ein festes Datum
waere ein Ablaufdatum (Paragraph 5.59, Nachtrag vom 01.11.2026).
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path as FsPath
from typing import Any
from zoneinfo import ZoneInfo

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
from heizung.models.enums import DeviceKind, DeviceVendor, HeatingZoneKind, UserRole
from heizung.models.heating_zone import HeatingZone
from heizung.models.relay_reading import RelayReading
from heizung.models.room import Room
from heizung.models.room_type import RoomType
from heizung.models.user import User
from heizung.services import relais_verlauf

WIEN = "Europe/Vienna"


# ---------------------------------------------------------------------------
# Reine Rechnung: die Tageszeile aus Stunden.
# ---------------------------------------------------------------------------


def _stunde(
    stunde: datetime,
    *,
    gehaeuse_max: int | None = None,
    gehaeuse_mittel: str | None = None,
    gehaeuse_max_ein: int | None = None,
    gehaeuse_mittel_ein: str | None = None,
    anzahl: int = 0,
    anzahl_ein: int = 0,
) -> relais_verlauf.Stunde:
    return relais_verlauf.Stunde(
        stunde=stunde,
        ein_prozent=50,
        erfasste_minuten=60,
        einschaltungen=1,
        ist_mittel=Decimal("21.0"),
        ist_min=Decimal("20.0"),
        ist_max=Decimal("22.0"),
        soll=Decimal("23.0"),
        ein_minuten=30,
        gehaeuse_max=gehaeuse_max,
        gehaeuse_mittel=Decimal(gehaeuse_mittel) if gehaeuse_mittel else None,
        gehaeuse_max_ein=gehaeuse_max_ein,
        gehaeuse_mittel_ein=Decimal(gehaeuse_mittel_ein) if gehaeuse_mittel_ein else None,
        gehaeuse_anzahl=anzahl,
        gehaeuse_anzahl_ein=anzahl_ein,
    )


def test_das_tagesmittel_wiegt_nach_der_zahl_der_meldungen() -> None:
    """Eine Stunde mit einer Meldung zaehlt ein Sechstel einer mit sechs.

    Ohne Gewichtung waere das Mittel ``(30 + 42) / 2 = 36`` — der
    Mittelwert ueber „Stunden, in denen zufaellig etwas gemeldet wurde".
    Mit Gewichtung ``(30 * 1 + 42 * 6) / 7 = 40,3``.
    """
    basis = datetime(2026, 11, 20, 8, 0, tzinfo=UTC)
    tage = relais_verlauf.tage_aus_stunden(
        [
            _stunde(basis, gehaeuse_mittel="30.0", gehaeuse_max=31, anzahl=1),
            _stunde(basis + timedelta(hours=1), gehaeuse_mittel="42.0", gehaeuse_max=45, anzahl=6),
        ],
        WIEN,
    )
    assert len(tage) == 1
    assert tage[0].gehaeuse_mittel == Decimal("40.3")
    assert tage[0].gehaeuse_max == 45


def test_eine_stunde_ohne_gehaeusewert_zieht_den_tag_nicht_nach_unten() -> None:
    """``None`` ist kein Messwert und darf nicht als 0 mitwiegen."""
    basis = datetime(2026, 11, 20, 8, 0, tzinfo=UTC)
    tage = relais_verlauf.tage_aus_stunden(
        [
            _stunde(basis, gehaeuse_mittel="40.0", gehaeuse_max=41, anzahl=3),
            _stunde(basis + timedelta(hours=1)),
        ],
        WIEN,
    )
    assert tage[0].gehaeuse_mittel == Decimal("40.0")
    assert tage[0].gehaeuse_max == 41


def test_ohne_jede_meldung_gibt_es_keinen_gehaeusewert_und_keine_null() -> None:
    basis = datetime(2026, 11, 20, 8, 0, tzinfo=UTC)
    tage = relais_verlauf.tage_aus_stunden([_stunde(basis)], WIEN)
    assert tage[0].gehaeuse_mittel is None
    assert tage[0].gehaeuse_max is None
    assert tage[0].gehaeuse_mittel_ein is None
    assert tage[0].gehaeuse_max_ein is None


def test_die_eingeschalteten_meldungen_wiegen_eigenstaendig() -> None:
    """Die ``_ein``-Spalte hat ihr eigenes Gewicht.

    Stunde 1 hat drei Meldungen, davon **eine** eingeschaltet; Stunde 2
    hat sechs, davon **alle**. Das Gesamtmittel wiegt 3:6, das
    ``_ein``-Mittel 1:6 — zwei verschiedene Gewichte in derselben Zeile,
    und das ist richtig: es sind zwei verschiedene Stichproben.
    """
    basis = datetime(2026, 11, 20, 8, 0, tzinfo=UTC)
    tage = relais_verlauf.tage_aus_stunden(
        [
            _stunde(
                basis,
                gehaeuse_mittel="30.0",
                gehaeuse_max=36,
                gehaeuse_mittel_ein="36.0",
                gehaeuse_max_ein=36,
                anzahl=3,
                anzahl_ein=1,
            ),
            _stunde(
                basis + timedelta(hours=1),
                gehaeuse_mittel="44.0",
                gehaeuse_max=46,
                gehaeuse_mittel_ein="44.0",
                gehaeuse_max_ein=46,
                anzahl=6,
                anzahl_ein=6,
            ),
        ],
        WIEN,
    )
    # (30*3 + 44*6) / 9 = 39,3
    assert tage[0].gehaeuse_mittel == Decimal("39.3")
    # (36*1 + 44*6) / 7 = 42,9
    assert tage[0].gehaeuse_mittel_ein == Decimal("42.9")


def test_das_gehaeuse_mittel_rundet_auf_eine_stelle() -> None:
    basis = datetime(2026, 11, 20, 8, 0, tzinfo=UTC)
    tage = relais_verlauf.tage_aus_stunden(
        [
            _stunde(basis, gehaeuse_mittel="30.0", anzahl=1),
            _stunde(basis + timedelta(hours=1), gehaeuse_mittel="31.0", anzahl=2),
        ],
        WIEN,
    )
    # (30 + 62) / 3 = 30,666... -> 30,7
    assert tage[0].gehaeuse_mittel == Decimal("30.7")


# ---------------------------------------------------------------------------
# Gegen die Datenbank: die geteilte Spanne.
# ---------------------------------------------------------------------------

DATABASE_URL = os.environ.get("DATABASE_URL")
PREFIX = "t-grenz"

pytestmark = pytest.mark.skipif(
    not DATABASE_URL, reason="DATABASE_URL nicht gesetzt - DB-Tests brauchen Postgres"
)

#: Die Zahl aus dem Befund vom 18.11.2026. Sie steht als Konstante da,
#: damit der Test sie nennt und nicht nur rechnet.
SPRUNG_WH = 193


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
    def __init__(self, room_id: int, zone_id: int, relais_id: int, basis: datetime) -> None:
        self.room_id = room_id
        self.zone_id = zone_id
        self.relais_id = relais_id
        #: Anfang der **ersten** Stunde, 10:00 Ortszeit des Vortages.
        self.basis = basis

    @property
    def jetzt(self) -> datetime:
        """Der Augenblick, aus dem das Fenster gerechnet wird."""
        return self.basis + timedelta(hours=3)


def _pruefstand() -> datetime:
    """10:00 Ortszeit des Vortages, als UTC-Augenblick.

    Zwei Stunden ab hier liegen sicher in **einem** lokalen Kalendertag —
    unabhaengig davon, wann die Suite laeuft, und auch an einem Tag mit
    Zeitumstellung (die faellt nachts).
    """
    tz = ZoneInfo(WIEN)
    vortag = datetime.now(tz=tz).date() - timedelta(days=1)
    return datetime.combine(vortag, time(10, 0), tzinfo=tz).astimezone(UTC)


#: Eine Meldung: Abstand zum Pruefstand, Zustand, Zaehlerstand, Gehaeuse.
Meldung = tuple[timedelta, bool, int, int]


@contextlib.asynccontextmanager
async def _zone_mit_meldungen(
    engine: AsyncEngine, meldungen: list[Meldung]
) -> AsyncIterator[Aufbau]:
    """Eine Relais-Zone mit genau diesen Meldungen, danach aufgeraeumt.

    **Ein Helfer und zwei Fixtures.** Die beiden Prueffaelle brauchen
    verschiedene Meldungen, aber denselben Aufbau; ihn zweimal
    hinzuschreiben waere die Stelle, an der beim ersten Nachziehen nur
    eine Haelfte mitwandert (Paragraph 5.53).
    """
    maker = async_sessionmaker(engine, expire_on_commit=False)
    short = uuid.uuid4().hex[:4]
    basis = _pruefstand()

    async with maker() as session:
        rt = RoomType(
            name=f"{PREFIX}-rt-{short}", is_bookable=False, default_t_occupied=Decimal("23.0")
        )
        session.add(rt)
        await session.flush()
        room = Room(number=f"{PREFIX}-{short}", room_type_id=rt.id)
        session.add(room)
        await session.flush()
        zone = HeatingZone(room_id=room.id, kind=HeatingZoneKind.OTHER, name="Bar")
        session.add(zone)
        await session.flush()

        relais = Device(
            dev_eui=f"beef{uuid.uuid4().hex[:12]}",
            kind=DeviceKind.RELAY,
            vendor=DeviceVendor.MCLIMATE,
            model="16ASPM",
            label=f"{PREFIX}-110",
            heating_zone_id=zone.id,
            health_state="healthy",
            commissioned_at=basis - timedelta(days=1),
        )
        session.add(relais)
        await session.flush()

        session.add_all(
            [
                RelayReading(
                    time=basis + abstand,
                    device_id=relais.id,
                    relay_on=ein,
                    power_w=1560 if ein else 0,
                    energy_wh=wh,
                    internal_temperature_raw=grad,
                )
                for abstand, ein, wh, grad in meldungen
            ]
        )
        await session.commit()
        ids = Aufbau(room.id, zone.id, relais.id, basis)

    try:
        yield ids
    finally:
        # Von Hand aufraeumen (Paragraph 5.39): die Zeilen sind
        # festgeschrieben, ein ``rollback`` nimmt sie nicht zurueck.
        async with maker() as session:
            await session.execute(
                text("DELETE FROM relay_reading WHERE device_id = :d"), {"d": ids.relais_id}
            )
            await session.execute(text("DELETE FROM room WHERE id = :r"), {"r": ids.room_id})
            await session.execute(text("DELETE FROM device WHERE id = :d"), {"d": ids.relais_id})
            await session.execute(
                text("DELETE FROM room_type WHERE name = :n"), {"n": f"{PREFIX}-rt-{short}"}
            )
            await session.commit()


@pytest_asyncio.fixture
async def haus(setup_engine: AsyncEngine) -> AsyncIterator[Aufbau]:
    """Vier Meldungen, deren erste Spanne ueber die Stundengrenze reicht.

    ======== ===== ======= ========
    Ortszeit Stand Zaehler Gehaeuse
    ======== ===== ======= ========
    10:57    AUS   1000    30
    11:07    EIN   1193    31
    11:17    EIN   1200    44
    11:27    AUS   1210    45
    ======== ===== ======= ========

    Die Spanne 10:57-11:07 traegt den Zustand **AUS** und den Sprung von
    193 Wh. Vor dem 27.11.2026 landete beides in Stunde 10 — der Befund
    vom 18.11.
    """
    async with _zone_mit_meldungen(
        setup_engine,
        [
            (timedelta(minutes=57), False, 1000, 30),
            (timedelta(hours=1, minutes=7), True, 1000 + SPRUNG_WH, 31),
            (timedelta(hours=1, minutes=17), True, 1200, 44),
            (timedelta(hours=1, minutes=27), False, 1210, 45),
        ],
    ) as aufbau:
        yield aufbau


@pytest_asyncio.fixture
async def haus_einschalten(setup_engine: AsyncEngine) -> AsyncIterator[Aufbau]:
    """Eine Spanne, die **eingeschaltet** ueber die Stundengrenze reicht.

    ======== ===== ======= ========
    Ortszeit Stand Zaehler Gehaeuse
    ======== ===== ======= ========
    10:47    AUS   500     20
    10:57    EIN   500     21
    11:07    EIN   600     22
    ======== ===== ======= ========

    **Warum es diesen zweiten Aufbau gibt.** Im ersten traegt die
    geteilte Spanne den Zustand AUS, und das Einschalten um 11:07 liegt in
    einer Spanne, die ganz in einer Stunde steckt. Damit blieb die Probe
    „zaehle das Einschalten in jedem Stueck" **gruen** — der Test hat
    gepasst, ohne zu pruefen, was er behauptet (Paragraph 5.55). Hier
    faellt das Einschalten mit der Teilung zusammen: um 10:57 geht das
    Relais an, und die Spanne reicht bis 11:07.
    """
    async with _zone_mit_meldungen(
        setup_engine,
        [
            (timedelta(minutes=47), False, 500, 20),
            (timedelta(minutes=57), True, 500, 21),
            (timedelta(hours=1, minutes=7), True, 600, 22),
        ],
    ) as aufbau:
        yield aufbau


async def _verlauf(haus: Aufbau, engine: AsyncEngine) -> relais_verlauf.RelaisVerlauf:
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        geraet = await session.get(Device, haus.relais_id)
        assert geraet is not None
        verlauf = await relais_verlauf.lade_relais_verlauf(
            session, geraet=geraet, bereich="24h", tz_name=WIEN, jetzt=haus.jetzt
        )
    assert verlauf is not None
    return verlauf


async def test_die_spanne_wird_an_der_stundengrenze_geteilt(
    haus: Aufbau, setup_engine: AsyncEngine
) -> None:
    """Drei Minuten in der ersten Stunde, sieben in der zweiten.

    Vor dem Fix trug Stunde 10 die ganzen zehn Minuten und Stunde 11
    keine davon.
    """
    verlauf = await _verlauf(haus, setup_engine)
    je_stunde = {s.stunde: s for s in verlauf.stunden}
    erste = je_stunde[haus.basis]
    zweite = je_stunde[haus.basis + timedelta(hours=1)]

    assert erste.erfasste_minuten == 3
    # Sieben Minuten aus der geteilten Spanne, dazu zwei ganze von je 10.
    assert zweite.erfasste_minuten == 27


async def test_die_energie_geht_zeitproportional_mit(
    haus: Aufbau, setup_engine: AsyncEngine
) -> None:
    """Der Fall aus dem Befund: 193 Wh werden 58 und 135.

    Vorher stand in der ersten Stunde die ganze Zahl, obwohl der Strom
    erst in der zweiten geflossen ist.
    """
    verlauf = await _verlauf(haus, setup_engine)
    je_stunde = {s.stunde: s for s in verlauf.stunden}

    # 193 * 3/10 = 57,9
    assert je_stunde[haus.basis].energie_wh == 58
    # 193 * 7/10 = 135,1, dazu 7 und 10 aus den beiden ganzen Spannen
    assert je_stunde[haus.basis + timedelta(hours=1)].energie_wh == 152
    # Und die Summe bleibt der Zaehlerdifferenz treu: 1210 - 1000.
    assert verlauf.energie_wh_gesamt == 210


async def test_die_erste_stunde_bleibt_bei_null_prozent(
    haus: Aufbau, setup_engine: AsyncEngine
) -> None:
    """Die Einschaltdauer kommt vom Zustand am Anfang des Stuecks.

    Um 10:57 stand das Relais auf AUS; beide Stuecke der Spanne tragen
    deshalb 0 Minuten Heizdauer. Dass in Stunde 10 trotzdem 58 Wh stehen,
    ist die verbleibende Unschaerfe der Zehn-Minuten-Auflösung — und sie
    ist jetzt klein statt 193.
    """
    verlauf = await _verlauf(haus, setup_engine)
    je_stunde = {s.stunde: s for s in verlauf.stunden}
    erste = je_stunde[haus.basis]
    zweite = je_stunde[haus.basis + timedelta(hours=1)]

    assert erste.ein_prozent == 0
    assert erste.ein_minuten == 0
    # Stunde 11: 20 von 27 erfassten Minuten ein -> 74 Prozent.
    assert zweite.ein_minuten == 20
    assert zweite.ein_prozent == 74


async def test_ein_einschalten_wird_nur_einmal_gezaehlt(
    haus_einschalten: Aufbau, setup_engine: AsyncEngine
) -> None:
    """Ein Einschalten auf einer **geteilten** Spanne zaehlt einmal.

    Um 10:57 geht das Relais an, die Spanne reicht bis 11:07 und wird
    geteilt. Ohne die Bedingung ``von = spanne_von`` zaehlte dasselbe
    Einschalten in Stunde 10 **und** in Stunde 11 — zwei Anlaeufe, die es
    nicht gab, und bei der Frage nach der Motorbelastung eine Zahl, die in
    die falsche Richtung zeigt.

    **Dieser Aufbau existiert wegen einer Probe, die gruen blieb.** Im
    ersten Aufbau faellt das Einschalten nicht mit einer Teilung zusammen;
    die Bedingung war dort folgenlos, und der Test hat sie nicht geprueft
    (Paragraph 5.55).
    """
    verlauf = await _verlauf(haus_einschalten, setup_engine)
    je_stunde = {s.stunde: s for s in verlauf.stunden}

    assert verlauf.einschaltungen_gesamt == 1
    assert je_stunde[haus_einschalten.basis].einschaltungen == 1
    assert je_stunde[haus_einschalten.basis + timedelta(hours=1)].einschaltungen == 0


async def test_die_heizdauer_einer_geteilten_spanne_geht_mit(
    haus_einschalten: Aufbau, setup_engine: AsyncEngine
) -> None:
    """Drei Minuten Heizdauer in Stunde 10, sieben in Stunde 11.

    Das ist die andere Haelfte des Fixes: nicht nur die Energie wird
    geteilt, auch die Dauer. Vorher trug Stunde 10 alle zehn Minuten — und
    Stunde 11, in der das Panel die meiste Zeit lief, keine einzige.
    """
    verlauf = await _verlauf(haus_einschalten, setup_engine)
    je_stunde = {s.stunde: s for s in verlauf.stunden}
    erste = je_stunde[haus_einschalten.basis]
    zweite = je_stunde[haus_einschalten.basis + timedelta(hours=1)]

    # Stunde 10: zehn Minuten AUS (10:47-10:57) und drei Minuten EIN.
    assert erste.erfasste_minuten == 13
    assert erste.ein_minuten == 3
    assert erste.ein_prozent == 23
    # Stunde 11: nur die sieben Minuten der geteilten Spanne, alle EIN.
    assert zweite.erfasste_minuten == 7
    assert zweite.ein_minuten == 7
    assert zweite.ein_prozent == 100
    # Die 100 Wh der Spanne gehen 30/70 mit.
    assert erste.energie_wh == 30
    assert zweite.energie_wh == 70


async def test_das_einschalten_im_ersten_aufbau_zaehlt_auch_einmal(
    haus: Aufbau, setup_engine: AsyncEngine
) -> None:
    """Dieselbe Zusicherung fuer die ungeteilte Spanne.

    Das Einschalten um 11:07 liegt ganz in Stunde 11. Die Zeile steht
    hier, damit der haeufige Fall nicht nur im Schatten des seltenen
    geprueft ist.
    """
    verlauf = await _verlauf(haus, setup_engine)
    je_stunde = {s.stunde: s for s in verlauf.stunden}
    assert verlauf.einschaltungen_gesamt == 1
    assert je_stunde[haus.basis].einschaltungen == 0
    assert je_stunde[haus.basis + timedelta(hours=1)].einschaltungen == 1


# ---------------------------------------------------------------------------
# Die Gehaeusetemperatur.
# ---------------------------------------------------------------------------


async def test_die_gehaeusetemperatur_steht_je_stunde(
    haus: Aufbau, setup_engine: AsyncEngine
) -> None:
    """Eine Meldung gehoert **einer** Stunde — ungeteilt.

    Kaeme der Wert aus derselben Abfrage wie die Dauer, zaehlte die
    Meldung von 10:57 in zwei Stunden.
    """
    verlauf = await _verlauf(haus, setup_engine)
    je_stunde = {s.stunde: s for s in verlauf.stunden}
    erste = je_stunde[haus.basis]
    zweite = je_stunde[haus.basis + timedelta(hours=1)]

    assert erste.gehaeuse_max == 30
    assert erste.gehaeuse_mittel == Decimal("30.0")
    assert erste.gehaeuse_anzahl == 1
    # 31, 44, 45 -> Mittel 40,0
    assert zweite.gehaeuse_max == 45
    assert zweite.gehaeuse_mittel == Decimal("40.0")
    assert zweite.gehaeuse_anzahl == 3


async def test_nur_die_eingeschalteten_meldungen_zaehlen_fuer_ein(
    haus: Aufbau, setup_engine: AsyncEngine
) -> None:
    """Der groesste Wert des Tages (45) kam, als das Relais **aus** war.

    Genau das ist der Unterschied, um den es geht: 45 steht in der
    Gesamtspalte, aber nicht in der ``_ein``-Spalte. Ohne den Filter
    waeren beide Zahlen gleich und die Spalte waere Zierde.
    """
    verlauf = await _verlauf(haus, setup_engine)
    je_stunde = {s.stunde: s for s in verlauf.stunden}
    erste = je_stunde[haus.basis]
    zweite = je_stunde[haus.basis + timedelta(hours=1)]

    # 10:57 war AUS -> keine eingeschaltete Meldung in dieser Stunde.
    assert erste.gehaeuse_max_ein is None
    assert erste.gehaeuse_mittel_ein is None
    assert erste.gehaeuse_anzahl_ein == 0
    # 11:07 (31, EIN) und 11:17 (44, EIN); 11:27 (45) war AUS.
    assert zweite.gehaeuse_max_ein == 44
    assert zweite.gehaeuse_mittel_ein == Decimal("37.5")
    assert zweite.gehaeuse_anzahl_ein == 2


async def test_die_tageszeile_traegt_beide_gehaeusewerte(
    haus: Aufbau, setup_engine: AsyncEngine
) -> None:
    """Beide Stunden liegen in **einem** lokalen Kalendertag.

    Gesamt: ``(30*1 + 40*3) / 4 = 37,5``, groesster Wert 45.
    Eingeschaltet: nur Stunde 11 sagt etwas -> 37,5, groesster Wert 44.
    """
    verlauf = await _verlauf(haus, setup_engine)
    assert len(verlauf.tage) == 1
    tag = verlauf.tage[0]
    assert tag.tag == haus.basis.astimezone(ZoneInfo(WIEN)).date()
    assert tag.gehaeuse_max == 45
    assert tag.gehaeuse_mittel == Decimal("37.5")
    assert tag.gehaeuse_max_ein == 44
    assert tag.gehaeuse_mittel_ein == Decimal("37.5")


# ---------------------------------------------------------------------------
# Durch den Endpunkt: die CSV-Spalten und die Form der Zahlen.
# ---------------------------------------------------------------------------


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


async def test_die_csv_traegt_die_vier_gehaeusespalten(
    haus: Aufbau, client: httpx.AsyncClient
) -> None:
    """Die Datei ist der Teil, den der Betreiber weitergibt.

    Geprueft wird der **Kopf** und dass die Spalten am Ende stehen — die
    Zahlen selbst haengen am Fenster des Endpunkts, der ``jetzt`` nicht
    kennt, und sind oben am Dienst belegt.
    """
    antwort = await client.get(f"/api/v1/devices/{haus.relais_id}/relay/history.csv?range=7d")
    assert antwort.status_code == 200
    kopf = antwort.text.lstrip("﻿").splitlines()[0].split(";")
    assert kopf[-4:] == [
        "Gehaeuse max",
        "Gehaeuse Mittel",
        "Gehaeuse max (ein)",
        "Gehaeuse Mittel (ein)",
    ]


async def test_der_endpunkt_liefert_die_gehaeusewerte_je_tag(
    haus: Aufbau, client: httpx.AsyncClient
) -> None:
    """Die Tageszeile der Antwort traegt die vier Felder — als **Zahl**.

    ``Decimal`` ohne ``field_serializer`` geht als String hinaus; genau
    daran ist am 18.11.2026 die Relais-Karte verschwunden (Paragraph
    5.63/5.93). Deshalb steht hier ``isinstance(..., float)``.
    """
    antwort = await client.get(f"/api/v1/devices/{haus.relais_id}/relay/history?range=7d")
    assert antwort.status_code == 200
    tage = antwort.json()["tage"]
    unser = [t for t in tage if t["gehaeuse_max"] is not None]
    assert unser, "kein Tag mit Gehaeusewert in der Antwort"
    zeile = unser[0]
    assert zeile["gehaeuse_max"] == 45
    assert isinstance(zeile["gehaeuse_mittel"], float)
    assert zeile["gehaeuse_mittel"] == 37.5
    assert zeile["gehaeuse_max_ein"] == 44
    assert isinstance(zeile["gehaeuse_mittel_ein"], float)
