"""Befunde aus dem Realbetrieb und die Zeitumstellung (Sprint 24e, PR B).

Drei Nähte:

1. **Der Verlauf bei einer Fühler-Zone** (P3). Im Zimmer „Bar" zeigte
   „Barbereich (Soll)" durchgehend 10 °C, während die Engine 21 bzw. 19
   rechnete. Der Wert war echt — er stand im Gerät, aus der Zeit der
   erzwungenen Frostschutz-Phase — und sagte nichts mehr: eine Vicki mit
   der Rolle „nur messen" bekommt keine Sollwerte (S7), ihr gespeicherter
   Wert friert ein.

2. **Die Zeitumstellung** (P6). Betriebszeiten und Nachtfenster an beiden
   Umstellungstagen, in Ortszeit geprüft. **Mutationsprobe M29** greift
   hier an: eine feste UTC-Verschiebung statt der Zeitzone.

3. **Die doppelte Stunde** (P6/P7). Am Rückstelltag gibt es 02:30 zweimal.
   Beide Auslegungen müssen zu einem **definierten** Ergebnis führen — und
   zum selben, wenn das Fenster sie beide einschließt.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
import pytest_asyncio
from freezegun import freeze_time
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from heizung.models.device import Device
from heizung.models.enums import (
    CommandReason,
    DeviceKind,
    DeviceVendor,
    EventLogLayer,
    HeatingZoneKind,
    RoomStatus,
    RuleConfigScope,
)
from heizung.models.event_log import EventLog
from heizung.models.heating_zone import HeatingZone
from heizung.models.room import Room
from heizung.models.room_type import RoomType
from heizung.models.rule_config import RuleConfig
from heizung.models.sensor_reading import SensorReading
from heizung.rules.engine import evaluate_room
from heizung.services import betriebszeit
from heizung.services.room_history import lade_verlauf

TEST_DB_URL = os.environ.get("TEST_DATABASE_URL")
SKIP_REASON = "TEST_DATABASE_URL nicht gesetzt - DB-Tests brauchen Postgres"
PREFIX = "t24e"

pytestmark = pytest.mark.skipif(not TEST_DB_URL, reason=SKIP_REASON)

WIEN = ZoneInfo("Europe/Vienna")

BETRIEB = 21
ABSENKUNG = 17

#: Die beiden Umstellungstage 2026 in Europe/Vienna.
#: Vorstellung: letzter Sonntag im Maerz, 02:00 -> 03:00.
#: Ruecksttellung: letzter Sonntag im Oktober, 03:00 -> 02:00.
VORSTELLUNG = date(2026, 3, 29)
RUECKSTELLUNG = date(2026, 10, 25)


@pytest_asyncio.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(TEST_DB_URL or "", poolclass=None)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
        await session.rollback()
    await engine.dispose()


def ortszeit(tag: date, uhr: time, *, fold: int = 0) -> datetime:
    """Der UTC-Augenblick, an dem in Wien ``uhr`` ist.

    **Die Umrechnung läuft hier in der Gegenrichtung** zu der, die geprüft
    wird: der Test baut aus einer Ortszeit einen UTC-Augenblick, die Engine
    rechnet aus UTC die Ortszeit. Beide benutzen ``zoneinfo``, und das ist
    kein Zirkel — geprüft wird nicht die Bibliothek, sondern dass die
    Engine sie überhaupt benutzt. Genau das nimmt Mutationsprobe M29 weg.

    ``fold`` wählt an der Rückstellung zwischen den zwei Auslegungen
    derselben Ortszeit: ``0`` ist die erste (noch Sommerzeit), ``1`` die
    zweite (schon Winterzeit).
    """
    lokal = datetime.combine(tag, uhr, tzinfo=WIEN).replace(fold=fold)
    return lokal.astimezone(UTC)


async def _hausstandard_leeren(session: AsyncSession) -> None:
    """Hausweite Sollwerte und Fenster für die Dauer des Tests entfernen.

    Sonst entscheidet die Einstellung des Hauses mit, und der Test prüfte
    sie statt der Rangfolge (§5.39 — nur dass die Verschmutzung hier aus
    dem Seed kommt und nicht aus einem anderen Test).
    """
    zeile = (
        await session.execute(
            select(RuleConfig)
            .where(RuleConfig.scope == RuleConfigScope.GLOBAL)
            .where(RuleConfig.room_type_id.is_(None))
            .where(RuleConfig.room_id.is_(None))
            .where(RuleConfig.season_id.is_(None))
        )
    ).scalar_one_or_none()
    if zeile is None:
        return
    zeile.t_occupied = None
    zeile.t_vacant = None
    zeile.t_night = None
    zeile.night_start = None
    zeile.night_end = None
    await session.flush()


async def _bereich(
    session: AsyncSession, *, von: str | None = None, bis: str | None = None
) -> tuple[int, int]:
    """Ein Allgemeinbereich mit einer Zone, optional mit Betriebszeit."""
    short = uuid.uuid4().hex[:6]
    rt = RoomType(
        name=f"{PREFIX}-b-{short}",
        is_bookable=False,
        default_t_occupied=Decimal(BETRIEB),
        default_t_vacant=Decimal(BETRIEB),
        default_t_night=Decimal(ABSENKUNG),
    )
    session.add(rt)
    await session.flush()
    room = Room(number=f"{PREFIX}-{short}", room_type_id=rt.id)
    session.add(room)
    await session.flush()
    zone = HeatingZone(room_id=room.id, kind=HeatingZoneKind.COMMON_AREA, name="Bereich")
    session.add(zone)
    await session.flush()
    if von is not None and bis is not None:
        await betriebszeit.setze(
            session,
            room.id,
            von=betriebszeit.parse_uhrzeit(von),
            bis=betriebszeit.parse_uhrzeit(bis),
        )
    return room.id, zone.id


# ---------------------------------------------------------------------------
# P3: Verlauf bei einer Fühler-Zone
# ---------------------------------------------------------------------------


async def _zone_mit_geraet(
    session: AsyncSession, *, measure_only: bool, geraete_sollwert: int
) -> tuple[Room, int]:
    """Eine Zone mit einem Thermostat, das einen Sollwert meldet."""
    short = uuid.uuid4().hex[:6]
    rt = RoomType(
        name=f"{PREFIX}-v-{short}",
        is_bookable=False,
        default_t_occupied=Decimal(BETRIEB),
        default_t_vacant=Decimal(BETRIEB),
        default_t_night=Decimal(BETRIEB),
    )
    session.add(rt)
    await session.flush()
    room = Room(number=f"{PREFIX}v{short}", room_type_id=rt.id)
    session.add(room)
    await session.flush()
    zone = HeatingZone(room_id=room.id, kind=HeatingZoneKind.COMMON_AREA, name="Bereich")
    session.add(zone)
    await session.flush()
    dev = Device(
        dev_eui=f"beef{uuid.uuid4().hex[:12]}",
        kind=DeviceKind.THERMOSTAT,
        vendor=DeviceVendor.MCLIMATE,
        model="vicki",
        label=f"{PREFIX}-{short}",
        heating_zone_id=zone.id,
        health_state="healthy",
        measure_only=measure_only,
    )
    session.add(dev)
    await session.flush()

    jetzt = datetime.now(tz=UTC)
    for minuten in (30, 20, 10):
        session.add(
            SensorReading(
                time=jetzt - timedelta(minutes=minuten),
                device_id=dev.id,
                temperature=Decimal("20.0"),
                # Der Wert, der im Gerät steht — bei einem Fühler der
                # eingefrorene aus der Frostschutz-Zeit.
                setpoint=Decimal(geraete_sollwert),
            )
        )
    # Und der Engine-Sollwert derselben Minuten, wie ihn Layer 5 schreibt.
    for minuten in (30, 20, 10):
        session.add(
            EventLog(
                time=jetzt - timedelta(minutes=minuten),
                room_id=room.id,
                evaluation_id=uuid.uuid4(),
                layer=EventLogLayer.HARD_CLAMP,
                setpoint_in=Decimal(BETRIEB),
                setpoint_out=Decimal(BETRIEB),
                reason=CommandReason.VACANT_SETPOINT,
                details={"detail": "within [10,30]"},
            )
        )
    await session.flush()
    return room, zone.id


async def test_verlauf_einer_fuehler_zone_zeigt_den_engine_sollwert(
    db_session: AsyncSession,
) -> None:
    """**Der Befund vom 25.10.2026.** 10 °C im Gerät, 21 °C in der Engine.

    Gezeigt wird der Engine-Wert: der Fühler stellt nichts, sein Sollwert
    ist ein Überrest und kein Zustand der Zone.

    **Seit dem 31.10.2026 gilt das für jede Zone**, nicht nur für eine
    ohne Stellglied — der Sonderfall, den dieser Test ursprünglich
    abgesichert hat, ist durch die Regel ersetzt. Der Test bleibt, weil
    seine Lage die konkrete war: ein eingefrorener Gerätewert, weit vom
    Soll, in einem Zimmer, das der Betreiber angesehen hat.
    """
    room, zone_id = await _zone_mit_geraet(db_session, measure_only=True, geraete_sollwert=10)

    verlauf = await lade_verlauf(db_session, room=room, bereich="24h")

    zone = next(z for z in verlauf.zones if z.zone_id == zone_id)
    sollwerte = {p.setpoint for p in zone.points if p.setpoint is not None}
    assert sollwerte == {Decimal(BETRIEB)}, (
        f"erwartet {BETRIEB} aus dem event_log, bekommen {sollwerte}"
    )


async def test_abweichung_eines_stellenden_geraets_bleibt_sichtbar(
    db_session: AsyncSession,
) -> None:
    """**Die Gegenprobe, und sie ist die wichtigere.**

    Der Zweck von AE-74 bleibt: ein nicht angekommener Downlink soll im
    Diagramm **sichtbar** sein und nicht geglättet. Ohne diesen Test wäre
    die Änderung vom 31.10.2026 auch grün, wenn der Gerätewert ganz
    verschwunden wäre — und dann hätte sie eine Aussage weggenommen.

    **Was sich geändert hat, ist die Stelle, nicht die Aussage.** Bis dahin
    stand der Gerätewert in ``setpoint`` und damit unter der Beschriftung
    „Soll"; genau daran ist Zimmer 107 aufgefallen, wo eine abgewiesene
    Drehung als Sollwert dastand. Jetzt steht der Soll der Engine in
    ``setpoint`` und der gemeldete Wert in ``geraet_setpoint`` — sichtbar
    wie vorher, aber als das, was er ist.

    Hieß bis zum 31.10.2026 ``test_verlauf_mit_stellglied_zeigt_weiter_das_geraet``.
    """
    room, zone_id = await _zone_mit_geraet(db_session, measure_only=False, geraete_sollwert=10)

    verlauf = await lade_verlauf(db_session, room=room, bereich="24h")

    zone = next(z for z in verlauf.zones if z.zone_id == zone_id)
    sollwerte = {p.setpoint for p in zone.points if p.setpoint is not None}
    gemeldet = {p.geraet_setpoint for p in zone.points if p.geraet_setpoint is not None}
    assert sollwerte == {Decimal(BETRIEB)}, "der Sollwert ist der der Engine"
    assert gemeldet == {Decimal(10)}, (
        "und der gemeldete Wert bleibt sichtbar, in seiner eigenen Reihe"
    )


async def test_ohne_engine_eintrag_bleibt_der_sollwert_leer(
    db_session: AsyncSession,
) -> None:
    """Kein Rückfall auf den eingefrorenen Wert.

    Gibt es für einen Eimer keinen ``event_log``-Eintrag, bleibt der
    Sollwert leer. Ein Rückfall auf den Gerätewert wäre genau der Befund
    von oben — nur seltener und damit schwerer zu sehen.
    """
    room, zone_id = await _zone_mit_geraet(db_session, measure_only=True, geraete_sollwert=10)
    await db_session.execute(EventLog.__table__.delete().where(EventLog.room_id == room.id))
    await db_session.flush()

    verlauf = await lade_verlauf(db_session, room=room, bereich="24h")

    zone = next(z for z in verlauf.zones if z.zone_id == zone_id)
    assert zone.points, "die Temperatur-Reihe soll bleiben"
    assert all(p.setpoint is None for p in zone.points)


# ---------------------------------------------------------------------------
# P6: die Zeitumstellung
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("tag", "uhr", "erwartet", "warum"),
    [
        # Vorstellung: vor dem Sprung ist es Winterzeit, danach Sommerzeit.
        (VORSTELLUNG, time(6, 30), ABSENKUNG, "vor der Oeffnung, Sommerzeit"),
        (VORSTELLUNG, time(7, 30), BETRIEB, "nach der Oeffnung, Sommerzeit"),
        (VORSTELLUNG, time(1, 30), ABSENKUNG, "vor dem Sprung, noch Winterzeit"),
        (VORSTELLUNG, time(3, 30), ABSENKUNG, "nach dem Sprung"),
        (VORSTELLUNG, time(21, 59), BETRIEB, "letzte Minute des Betriebs"),
        (VORSTELLUNG, time(22, 1), ABSENKUNG, "nach dem Schliessen"),
        # Ruecksttellung: 02:30 gibt es zweimal, 06:30/07:30 sind eindeutig.
        (RUECKSTELLUNG, time(6, 30), ABSENKUNG, "vor der Oeffnung, Winterzeit"),
        (RUECKSTELLUNG, time(7, 30), BETRIEB, "nach der Oeffnung, Winterzeit"),
        (RUECKSTELLUNG, time(21, 59), BETRIEB, "letzte Minute des Betriebs"),
        (RUECKSTELLUNG, time(22, 1), ABSENKUNG, "nach dem Schliessen"),
    ],
)
async def test_rezeption_ueber_die_umstellung(
    db_session: AsyncSession, tag: date, uhr: time, erwartet: int, warum: str
) -> None:
    """Betriebszeit 07:00–22:00 an beiden Umstellungstagen.

    **02:30 fehlt mit Absicht.** Am Vorstellungstag gibt es diese Ortszeit
    **nicht**, am Rückstelltag **zweimal** — beide Fälle stehen in eigenen
    Tests darunter, weil sie eine andere Frage beantworten als „liegt die
    Grenze richtig".

    **Mutationsprobe M29** greift hier an: mit einer festen
    UTC-Verschiebung statt der Zeitzone ist 07:30 am Vorstellungstag
    (Sommerzeit, UTC+2) noch Absenkung.
    """
    await _hausstandard_leeren(db_session)
    room_id, _ = await _bereich(db_session, von="07:00", bis="22:00")

    with freeze_time(ortszeit(tag, uhr)):
        ergebnis = await evaluate_room(db_session, room_id)

    assert ergebnis is not None
    assert ergebnis.setpoint_c == erwartet, f"{tag} {uhr} ({warum})"


@pytest.mark.parametrize("fold", [0, 1])
async def test_die_doppelte_stunde_ist_eindeutig(db_session: AsyncSession, fold: int) -> None:
    """02:30 am Rückstelltag — zweimal dieselbe Ortszeit, ein Ergebnis.

    Beide Auslegungen liegen außerhalb der Betriebszeit 07:00–22:00, das
    Ergebnis muss also in beiden Fällen die Absenkung sein. Eine Engine,
    die an dieser Stelle rät, liefert hier zweimal etwas anderes — und
    zwar einmal im Jahr, in einer Stunde, in der niemand hinsieht.
    """
    await _hausstandard_leeren(db_session)
    room_id, _ = await _bereich(db_session, von="07:00", bis="22:00")

    with freeze_time(ortszeit(RUECKSTELLUNG, time(2, 30), fold=fold)):
        ergebnis = await evaluate_room(db_session, room_id)

    assert ergebnis is not None
    assert ergebnis.setpoint_c == ABSENKUNG


@pytest.mark.parametrize("fold", [0, 1])
async def test_die_doppelte_stunde_im_betrieb_einer_bar(
    db_session: AsyncSession, fold: int
) -> None:
    """Dieselbe Stunde, aber mit einem Fenster, das sie **einschließt**.

    Eine Bar mit Betriebszeit 00:00–24:00 ist rund um die Uhr in Betrieb.
    Beide Auslegungen von 02:30 müssen Betrieb ergeben — eine fehlende
    oder doppelte Stunde würde hier als Absenkung auffallen.
    """
    await _hausstandard_leeren(db_session)
    room_id, _ = await _bereich(db_session, von="00:00", bis="24:00")

    with freeze_time(ortszeit(RUECKSTELLUNG, time(2, 30), fold=fold)):
        ergebnis = await evaluate_room(db_session, room_id)

    assert ergebnis is not None
    assert ergebnis.setpoint_c == BETRIEB


@pytest.mark.parametrize(
    ("tag", "uhr", "erwartet"),
    [
        (VORSTELLUNG, time(14, 59), ABSENKUNG),
        (VORSTELLUNG, time(15, 1), BETRIEB),
        (VORSTELLUNG, time(23, 59), BETRIEB),
        (VORSTELLUNG, time(0, 1), ABSENKUNG),
        (RUECKSTELLUNG, time(14, 59), ABSENKUNG),
        (RUECKSTELLUNG, time(15, 1), BETRIEB),
        (RUECKSTELLUNG, time(23, 59), BETRIEB),
        (RUECKSTELLUNG, time(0, 1), ABSENKUNG),
    ],
)
async def test_bar_ueber_die_umstellung(
    db_session: AsyncSession, tag: date, uhr: time, erwartet: int
) -> None:
    """Betriebszeit 15:00–24:00 an beiden Umstellungstagen.

    Das Fenster der Absenkung läuft hier **nicht** über Mitternacht
    (``[00:00, 15:00)``) — die Mitternachts-Frage liegt auf der anderen
    Seite als bei der Rezeption, und beide Fälle gehören über die
    Umstellung geprüft.
    """
    await _hausstandard_leeren(db_session)
    room_id, _ = await _bereich(db_session, von="15:00", bis="24:00")

    with freeze_time(ortszeit(tag, uhr)):
        ergebnis = await evaluate_room(db_session, room_id)

    assert ergebnis is not None
    assert ergebnis.setpoint_c == erwartet


async def test_das_nachtfenster_eines_gaestezimmers_ueber_die_umstellung(
    db_session: AsyncSession,
) -> None:
    """Dasselbe für ein **belegtes** Gästezimmer.

    Die Zeitsteuerung ist dieselbe Rechnung; sie an der Umstellung nur für
    Bereiche zu prüfen hieße, die Hälfte der Konsumenten ungeprüft zu
    lassen. Geprüft wird die Grenze: 05:59 noch Nacht, 06:01 nicht mehr.
    """
    await _hausstandard_leeren(db_session)
    short = uuid.uuid4().hex[:6]
    rt = RoomType(
        name=f"{PREFIX}-g-{short}",
        is_bookable=True,
        default_t_occupied=Decimal(BETRIEB),
        default_t_vacant=Decimal(18),
        default_t_night=Decimal(ABSENKUNG),
    )
    db_session.add(rt)
    await db_session.flush()
    room = Room(number=f"{PREFIX}g{short}", room_type_id=rt.id, status=RoomStatus.OCCUPIED)
    db_session.add(room)
    await db_session.flush()
    db_session.add(
        RuleConfig(
            scope=RuleConfigScope.ROOM,
            room_id=room.id,
            night_start=time(22, 0),
            night_end=time(6, 0),
        )
    )
    await db_session.flush()

    with freeze_time(ortszeit(VORSTELLUNG, time(5, 59))):
        nacht = await evaluate_room(db_session, room.id)
    with freeze_time(ortszeit(VORSTELLUNG, time(6, 1))):
        tag = await evaluate_room(db_session, room.id)

    assert nacht is not None and tag is not None
    assert nacht.setpoint_c == ABSENKUNG
    assert tag.setpoint_c == BETRIEB
