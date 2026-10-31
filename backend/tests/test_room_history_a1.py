"""Sprint 21 A1 — der Zimmer-Verlauf, und warum sein Beleg ein Test ist.

**Die Abnahme im Brief vom 10.10. ist nicht mehr pruefbar.** Sie lautete:
„Zimmer 101, 7 d zeigt Belegungen 05.-07.10. und 07.-08.10., Absenkung
nachts, Override 06.10. als Sollwert-Sprung." Am 10.10. reichte ein
Sieben-Tage-Fenster bis zum 03.10. — vier Tage spaeter beginnt es am 07.10.,
und die genannten Ereignisse liegen davor.

Dieselbe Lage wie bei Regel 3c, wo die defekten Koepfe vor der Live-Abnahme
im Lager landeten: **der Beleg gehoert in ein festes Fenster**, hier mit
synthetischen Daten. Ein Beleg, der jeden Tag weiterwandert, ist in einer
Woche kein Beleg mehr. Die Sichtprobe des Hoteliers prueft danach, was
heute da ist — nicht, was im Brief stand.

Was hier gepinnt ist
--------------------

1. **Der Sollwert-Sprung** (ein Override am 06.10. im festen Fenster) ist in
   der Reihe sichtbar und nicht geglaettet. Dafuer steht ``max`` je Eimer:
   bei ``avg`` wuerde ein Sprung verschliffen, solange ein zweites Geraet
   den Downlink noch nicht abgeholt hat (Class A, §5.71).
2. **Das Nachtfenster** kommt aufgeloest durch die Kette
   ROOM > ROOM_TYPE > GLOBAL — also derselbe Wert, nach dem die Engine
   regelt, und nicht einer, den die Oberflaeche nachbaut (§5.53).
3. **Die Zusammenfassung** in Zehn-Minuten- bzw. Stunden-Eimer, mit der
   Punktzahl als Zusage.
4. **Die Grenze des Fensters** ist halboffen — ein Messwert liegt in genau
   einem Eimer.
5. **Das stillgelegte Geraet bleibt im Verlauf, das getauschte nicht.** Das
   ist die eine Stelle, an der diese Datei eine *Einschraenkung* festhaelt
   und nicht eine Zusage.
"""

from __future__ import annotations

import itertools
import os
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import delete as sa_delete
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from heizung.models.device import Device
from heizung.models.enums import DeviceKind, DeviceVendor, HeatingZoneKind, RuleConfigScope
from heizung.models.heating_zone import HeatingZone
from heizung.models.room import Room
from heizung.models.room_type import RoomType
from heizung.models.rule_config import RuleConfig
from heizung.models.sensor_reading import SensorReading
from heizung.services.room_history import BEREICHE, lade_verlauf

TEST_DB_URL = os.environ.get("TEST_DATABASE_URL")
SKIP_REASON = "TEST_DATABASE_URL nicht gesetzt — DB-Tests brauchen Postgres"

EUI_PREFIX = "7e21a100"
RAUM_PREFIX = "vh-"

# Das feste Fenster dieser Datei. Es endet am 08.10.2026 um 10:00 UTC, also
# genau am Ende der Zeitspanne, die der Brief nennt — damit die
# Ereignis-Daten aus dem Brief (05.-08.10.) im Sieben-Tage-Fenster liegen.
JETZT = datetime(2026, 10, 8, 10, 0, 0, tzinfo=UTC)

# ``(time, device_id, fcnt)`` ist UNIQUE; ein Zaehler ist einfacher als
# eine Formel, die bei negativen Abstaenden kippt (§5.49-Familie).
_fcnt = itertools.count(1)

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Huelle
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    if not TEST_DB_URL:
        pytest.skip(SKIP_REASON)
    engine = create_async_engine(TEST_DB_URL)
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    async with sessionmaker() as session:
        try:
            await _purge(session)
            await session.commit()
            yield session
        finally:
            await session.rollback()
            await _purge(session)
            await session.commit()
    await engine.dispose()


async def _purge(session: AsyncSession) -> None:
    device_ids = list(
        (await session.execute(select(Device.id).where(Device.dev_eui.like(f"{EUI_PREFIX}%"))))
        .scalars()
        .all()
    )
    if device_ids:
        await session.execute(
            sa_delete(SensorReading).where(SensorReading.device_id.in_(device_ids))
        )
        await session.execute(sa_delete(Device).where(Device.id.in_(device_ids)))
    raum_ids = select(Room.id).where(Room.number.like(f"{RAUM_PREFIX}%"))
    await session.execute(sa_delete(RuleConfig).where(RuleConfig.room_id.in_(raum_ids)))
    await session.execute(sa_delete(HeatingZone).where(HeatingZone.room_id.in_(raum_ids)))
    await session.execute(sa_delete(Room).where(Room.number.like(f"{RAUM_PREFIX}%")))
    await session.execute(sa_delete(RoomType).where(RoomType.name.like(f"{RAUM_PREFIX}%")))


async def _zimmer(session: AsyncSession, *, zonen: int = 1) -> tuple[Room, list[HeatingZone]]:
    suffix = uuid.uuid4().hex[:6]
    rt = RoomType(name=f"{RAUM_PREFIX}rt-{suffix}")
    session.add(rt)
    await session.flush()
    room = Room(number=f"{RAUM_PREFIX}{suffix}", room_type_id=rt.id)
    session.add(room)
    await session.flush()
    zs: list[HeatingZone] = []
    for i in range(zonen):
        # ``kind`` ist NOT NULL ohne Default (§5.49).
        z = HeatingZone(room_id=room.id, kind=HeatingZoneKind.BEDROOM, name=f"z{i}")
        session.add(z)
        await session.flush()
        zs.append(z)
    return room, zs


async def _geraet(
    session: AsyncSession,
    zone_id: int | None,
    *,
    retired: bool = False,
) -> Device:
    suffix = uuid.uuid4().hex[:8]
    d = Device(
        dev_eui=f"{EUI_PREFIX}{suffix}",
        kind=DeviceKind.THERMOSTAT,
        vendor=DeviceVendor.MCLIMATE,
        model="vicki",
        heating_zone_id=zone_id,
        retired_at=JETZT - timedelta(days=1) if retired else None,
    )
    session.add(d)
    await session.flush()
    return d


async def _messwert(
    session: AsyncSession,
    device_id: int,
    *,
    t: datetime,
    temperatur: str,
    sollwert: str | None,
) -> None:
    session.add(
        SensorReading(
            time=t,
            device_id=device_id,
            fcnt=next(_fcnt),
            temperature=Decimal(temperatur),
            setpoint=Decimal(sollwert) if sollwert is not None else None,
        )
    )
    await session.flush()


# ---------------------------------------------------------------------------
# 1. Der datierte Beleg im festen Fenster
# ---------------------------------------------------------------------------


async def test_fester_beleg_sollwert_sprung_und_nachtfenster(db_session: AsyncSession) -> None:
    """**Die Abnahme von A1, reproduzierbar.**

    Gefahren wird die Lage aus dem Brief, nur mit eigenen Daten: eine
    Woche Verlauf, in der Mitte (06.10. 14:00 UTC) ein Sollwert-Sprung von
    21 auf 18 Grad, und ein konfiguriertes Nachtfenster 22:00-06:00.

    Gepruefte Zusagen: der Sprung ist in der Reihe sichtbar, er liegt am
    richtigen Tag, das Nachtfenster kommt aufgeloest mit, und die Grenzen
    des Fensters stehen in der Antwort.
    """
    room, zonen = await _zimmer(db_session)
    dev = await _geraet(db_session, zonen[0].id)
    db_session.add(
        RuleConfig(
            scope=RuleConfigScope.ROOM,
            room_id=room.id,
            night_start=time(22, 0),
            night_end=time(6, 0),
        )
    )
    await db_session.flush()

    sprung = datetime(2026, 10, 6, 14, 0, tzinfo=UTC)
    # Je Tag ein Messwert um 12:00, damit die Reihe im Stunden-Eimer
    # eindeutig ist; dazu zwei Werte um den Sprung herum.
    for tag in range(2, 8):
        t = datetime(2026, 10, tag, 12, 0, tzinfo=UTC)
        await _messwert(
            db_session,
            dev.id,
            t=t,
            temperatur="21.0" if t < sprung else "19.5",
            sollwert="21.0" if t < sprung else "18.0",
        )
    await _messwert(db_session, dev.id, t=sprung, temperatur="21.0", sollwert="18.0")

    verlauf = await lade_verlauf(db_session, room=room, bereich="7d", jetzt=JETZT)

    assert verlauf.von == JETZT - timedelta(days=7)
    assert verlauf.bis == JETZT
    assert verlauf.bucket_minutes == 60
    assert verlauf.night_start == time(22, 0)
    assert verlauf.night_end == time(6, 0)

    punkte = verlauf.zones[0].points
    # Der 02.10. liegt vor dem Fensterbeginn (01.10. 10:00 + 7 d = 08.10.):
    # er ist drin. Entscheidend ist die Reihenfolge und der Sprung.
    #
    # **Gelesen wird ``geraet_setpoint``, seit dem 31.10.2026.** Dieser
    # Aufbau schreibt nur Messwerte und keine Engine-Zeilen; der Sprung,
    # den er prueft, ist also der im **gemeldeten** Wert, und der steht
    # seither in seinem eigenen Feld. ``setpoint`` traegt den
    # Engine-Sollwert und ist hier deshalb leer — ausdruecklich geprueft,
    # damit die Bedeutung der beiden Felder nicht wieder verrutscht.
    assert {p.setpoint for p in punkte} == {None}, "ohne Engine-Zeile kein Sollwert"
    sollwerte = [(p.t, p.geraet_setpoint) for p in punkte]
    assert sollwerte == sorted(sollwerte), "Reihe muss nach Zeit sortiert sein"

    vor_sprung = [sp for t, sp in sollwerte if t < sprung]
    ab_sprung = [sp for t, sp in sollwerte if t >= sprung]
    assert set(vor_sprung) == {Decimal("21.00")}, vor_sprung
    assert set(ab_sprung) == {Decimal("18.00")}, ab_sprung
    assert len(ab_sprung) >= 2, "Sprung und die Tage danach"


# ---------------------------------------------------------------------------
# 2. Zusammenfassung
# ---------------------------------------------------------------------------


async def test_24h_fasst_zehn_minuten_zu_einem_punkt_zusammen(db_session: AsyncSession) -> None:
    """Sechs Messwerte zweier Geraete in einem Eimer werden **ein** Punkt.

    Temperatur als Mittel (AE-51: so liest die Engine eine Zone),
    Sollwert als Maximum — der Sprung soll sichtbar sein, sobald er an
    einem Geraet ankommt.
    """
    room, zonen = await _zimmer(db_session)
    a = await _geraet(db_session, zonen[0].id)
    b = await _geraet(db_session, zonen[0].id)
    basis = datetime(2026, 10, 8, 9, 0, tzinfo=UTC)  # 09:00-09:10 = ein Eimer
    for i, (dev, temp, soll) in enumerate(
        [
            (a, "20.0", "18.0"),
            (a, "21.0", "18.0"),
            (a, "22.0", "18.0"),
            (b, "20.0", "21.0"),
            (b, "21.0", "21.0"),
            (b, "22.0", "21.0"),
        ]
    ):
        await _messwert(
            db_session,
            dev.id,
            t=basis + timedelta(seconds=i * 90),
            temperatur=temp,
            sollwert=soll,
        )

    verlauf = await lade_verlauf(db_session, room=room, bereich="24h", jetzt=JETZT)

    assert verlauf.bucket_minutes == 10
    punkte = verlauf.zones[0].points
    assert len(punkte) == 1, [p.t for p in punkte]
    assert punkte[0].temperature == Decimal("21.00"), "Mittel aus 20,21,22 beidseitig"
    # Maximum ueber die Geraete, nicht Mittel — und seit dem 31.10.2026 im
    # Feld ``geraet_setpoint``: die Zusage gilt fuer den **gemeldeten**
    # Wert, und nur den schreibt dieser Aufbau.
    assert punkte[0].geraet_setpoint == Decimal("21.00"), "Maximum, nicht Mittel"
    assert punkte[0].setpoint is None, "ohne Engine-Zeile kein Sollwert"


async def test_7d_nutzt_stunden_eimer(db_session: AsyncSession) -> None:
    """Zwei Messwerte in derselben Stunde: ein Punkt. In der naechsten
    Stunde: ein zweiter."""
    room, zonen = await _zimmer(db_session)
    dev = await _geraet(db_session, zonen[0].id)
    basis = datetime(2026, 10, 7, 8, 5, tzinfo=UTC)
    for minuten in (0, 30, 65):
        await _messwert(
            db_session,
            dev.id,
            t=basis + timedelta(minutes=minuten),
            temperatur="20.0",
            sollwert="20.0",
        )

    verlauf = await lade_verlauf(db_session, room=room, bereich="7d", jetzt=JETZT)
    assert verlauf.bucket_minutes == 60
    assert len(verlauf.zones[0].points) == 2


async def test_punktzahl_je_zone_bleibt_lesbar(db_session: AsyncSession) -> None:
    """Die eigentliche Zusage der Zusammenfassung: 144 bzw. 168 Punkte.

    Gefahren mit einem Messwert alle zwei Minuten ueber zwei Stunden — roh
    waeren das 60 Punkte, zusammengefasst sind es 12. Der Test rechnet die
    Obergrenze mit, damit sie nicht stillschweigend waechst, wenn jemand
    die Eimergroesse aendert.
    """
    room, zonen = await _zimmer(db_session)
    dev = await _geraet(db_session, zonen[0].id)
    start = JETZT - timedelta(hours=2)
    for i in range(60):
        await _messwert(
            db_session,
            dev.id,
            t=start + timedelta(minutes=2 * i),
            temperatur="20.0",
            sollwert="20.0",
        )

    verlauf = await lade_verlauf(db_session, room=room, bereich="24h", jetzt=JETZT)
    assert len(verlauf.zones[0].points) == 12

    fenster, minuten = BEREICHE["24h"]
    obergrenze = int(fenster.total_seconds() // 60 // minuten)
    assert obergrenze == 144
    assert len(verlauf.zones[0].points) <= obergrenze


# ---------------------------------------------------------------------------
# 3. Grenzen
# ---------------------------------------------------------------------------


async def test_fenster_ist_halboffen(db_session: AsyncSession) -> None:
    """``>= von`` und ``< bis``: der Wert auf der Untergrenze ist drin, der
    auf der Obergrenze nicht. Sonst liegt ein Messwert an der Grenze in
    zwei Fenstern oder in keinem."""
    room, zonen = await _zimmer(db_session)
    dev = await _geraet(db_session, zonen[0].id)
    von = JETZT - timedelta(hours=24)
    await _messwert(db_session, dev.id, t=von, temperatur="20.0", sollwert="20.0")
    await _messwert(db_session, dev.id, t=JETZT, temperatur="30.0", sollwert="30.0")
    await _messwert(
        db_session,
        dev.id,
        t=von - timedelta(seconds=1),
        temperatur="40.0",
        sollwert="40.0",
    )

    verlauf = await lade_verlauf(db_session, room=room, bereich="24h", jetzt=JETZT)
    temperaturen = {p.temperature for p in verlauf.zones[0].points}
    assert Decimal("20.00") in temperaturen, "Untergrenze gehoert dazu"
    assert Decimal("30.00") not in temperaturen, "Obergrenze nicht"
    assert Decimal("40.00") not in temperaturen, "davor schon gar nicht"


async def test_zone_ohne_messwerte_bleibt_in_der_antwort(db_session: AsyncSession) -> None:
    """Eine stumme Zone verschwindet nicht aus der Legende.

    Sonst liest sich „zwei Zonen, eine Linie" wie „es gibt nur eine Zone",
    und der Unterschied zwischen *nicht vorhanden* und *meldet nichts* ist
    genau der, den man im Verlauf sehen will.
    """
    room, zonen = await _zimmer(db_session, zonen=2)
    dev = await _geraet(db_session, zonen[0].id)
    await _messwert(
        db_session, dev.id, t=JETZT - timedelta(hours=1), temperatur="21.0", sollwert="21.0"
    )

    verlauf = await lade_verlauf(db_session, room=room, bereich="24h", jetzt=JETZT)
    assert [z.zone_id for z in verlauf.zones] == [zonen[0].id, zonen[1].id]
    assert len(verlauf.zones[0].points) == 1
    assert verlauf.zones[1].points == []


async def test_nachtfenster_nur_bei_vollstaendiger_konfiguration(
    db_session: AsyncSession,
) -> None:
    """Halbe Konfiguration ist kein Fenster.

    Erst die Vorbedingung: ohne Eintrag kommt ``None``. Faellt diese
    Zusicherung, hat die Datenbank einen GLOBAL-Eintrag mit Nachtzeiten,
    und dann ist der zweite Teil des Tests nicht aussagekraeftig — deshalb
    steht sie hier und nicht im Kommentar.
    """
    room, _zonen = await _zimmer(db_session)

    verlauf = await lade_verlauf(db_session, room=room, bereich="24h", jetzt=JETZT)
    assert verlauf.night_start is None, "Vorbedingung: kein geerbtes Nachtfenster"
    assert verlauf.night_end is None

    db_session.add(RuleConfig(scope=RuleConfigScope.ROOM, room_id=room.id, night_start=time(22, 0)))
    await db_session.flush()

    verlauf = await lade_verlauf(db_session, room=room, bereich="24h", jetzt=JETZT)
    assert verlauf.night_start is None, "nur Beginn gesetzt -> kein Band"
    assert verlauf.night_end is None


async def test_stillgelegtes_geraet_bleibt_getauschtes_nicht(db_session: AsyncSession) -> None:
    """**Eine Zusage und eine Einschraenkung, in einem Test.**

    Zusage: ein ohne Ersatz stillgelegtes Geraet bleibt im Verlauf.
    ``retire_device`` behaelt ``heating_zone_id`` ausdruecklich als
    „Historie-Anker fuer sensor_reading" (AE-57) — ein Lifecycle-Filter
    nach §5.58 wuerde hier genau die Zeilen wegwerfen, fuer die der Anker
    gedacht ist. §5.58 schuetzt Steuer- und Alarmpfade; dieser Endpunkt
    gibt kein Geraet weiter, er zeigt Vergangenheit.

    Einschraenkung: ``replace_device`` setzt beim Getauschten
    ``heating_zone_id = None``. Dessen Messwerte sind damit ueber die Zone
    nicht mehr erreichbar — nach einem Tausch beginnt der Verlauf
    praktisch beim neuen Geraet. Die Zeilen sind nicht geloescht, nur nicht
    mehr zugeordnet. Das ist hier festgehalten, damit es niemand fuer einen
    Fehler haelt und mit einem Filter „behebt" (RUNBOOK §10x).
    """
    room, zonen = await _zimmer(db_session)
    stillgelegt = await _geraet(db_session, zonen[0].id, retired=True)
    getauscht = await _geraet(db_session, None, retired=True)  # Zone weg, wie beim Tausch
    await _messwert(
        db_session,
        stillgelegt.id,
        t=JETZT - timedelta(hours=3),
        temperatur="19.0",
        sollwert="19.0",
    )
    await _messwert(
        db_session,
        getauscht.id,
        t=JETZT - timedelta(hours=2),
        temperatur="25.0",
        sollwert="25.0",
    )

    verlauf = await lade_verlauf(db_session, room=room, bereich="24h", jetzt=JETZT)
    temperaturen = {p.temperature for p in verlauf.zones[0].points}
    assert Decimal("19.00") in temperaturen, "stillgelegt, aber zugeordnet -> Historie"
    assert Decimal("25.00") not in temperaturen, "getauscht -> Zone weg -> unerreichbar"
