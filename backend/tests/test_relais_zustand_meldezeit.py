"""``seit`` und ``gemeldet`` sind zwei Zeiten (14.11.2026).

**Warum das eine eigene Datei ist.** Der Waechter hat seit dem 14.11. ein
Haltbarkeitsdatum fuer den Schaltzustand, und er braucht dafuer den
Zeitpunkt der **jüngsten Meldung**. Daneben steht der Beginn des
Zustands, an dem der Zweipunktregler seine Mindestlaufzeit rechnet. Die
beiden sehen sich aehnlich und sagen Verschiedenes:

| | ``seit`` | ``gemeldet`` |
|---|---|---|
| antwortet auf | seit wann gilt es | wann haben wir es gehoert |
| Verbraucher | Mindestlauf, Mindestpause | Veraltung des Zustands |
| bei EIN seit 2 h, Meldung vor 10 min | vor 2 h | vor 10 min |
| bei EIN gemeldet vor 2 h, seither still | vor 2 h | vor 2 h |

Die ersten beiden Zeilen zeigen den Unterschied, die dritte zeigt, warum
er nicht aus ``seit`` allein zu rekonstruieren ist: **zwei verschiedene
Lagen mit derselben ``seit``**. Wer die Frische daran misst, haelt ein
laufendes Panel fuer stumm und ein stummes fuer laufend.

Rollback-Session, keine Commits (§5.39) — diese Datei liest nur.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from heizung.models.device import Device
from heizung.models.enums import DeviceKind, DeviceVendor, HeatingZoneKind
from heizung.models.heating_zone import HeatingZone
from heizung.models.relay_reading import RelayReading
from heizung.models.room import Room
from heizung.models.room_type import RoomType
from heizung.services import relay_state

TEST_DB_URL = os.environ.get("TEST_DATABASE_URL")
SKIP_REASON = "TEST_DATABASE_URL nicht gesetzt - DB-Tests brauchen Postgres"
PREFIX = "t2cmz"

pytestmark = pytest.mark.skipif(not TEST_DB_URL, reason=SKIP_REASON)

#: Absolute Bezugszeit, keine Uhr im Test (§5.59). Die Datei prueft
#: Abstaende zwischen Zeilen, nicht das Alter gegen jetzt — damit hat sie
#: kein Ablaufdatum.
BEZUG = datetime(2026, 11, 14, 8, 0, tzinfo=UTC)


@pytest_asyncio.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(TEST_DB_URL or "", poolclass=None)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
        await session.rollback()
    await engine.dispose()


async def _relais(session: AsyncSession) -> Device:
    short = uuid.uuid4().hex[:4]
    rt = RoomType(name=f"{PREFIX}-rt-{short}", is_bookable=False)
    session.add(rt)
    await session.flush()
    room = Room(number=f"{PREFIX}-{short}", room_type_id=rt.id)
    session.add(room)
    await session.flush()
    zone = HeatingZone(room_id=room.id, kind=HeatingZoneKind.OTHER, name="Barbereich")
    session.add(zone)
    await session.flush()
    dev = Device(
        dev_eui=f"beef{uuid.uuid4().hex[:12]}",
        kind=DeviceKind.RELAY,
        vendor=DeviceVendor.MCLIMATE,
        model="16ASPM",
        label="Panel",
        heating_zone_id=zone.id,
        health_state="healthy",
    )
    session.add(dev)
    await session.flush()
    return dev


async def _meldet(session: AsyncSession, device_id: int, ein: bool | None, *, minute: int) -> None:
    """Eine Zeile zum Zeitpunkt ``BEZUG + minute``."""
    session.add(
        RelayReading(
            time=BEZUG + timedelta(minutes=minute),
            device_id=device_id,
            relay_on=ein,
            power_w=1600 if ein else 0,
        )
    )
    await session.flush()


async def test_laufendes_panel_hat_alten_beginn_und_frische_meldung(
    db_session: AsyncSession,
) -> None:
    """EIN seit zwei Stunden, zuletzt gehoert vor zehn Minuten."""
    dev = await _relais(db_session)
    await _meldet(db_session, dev.id, False, minute=0)
    await _meldet(db_session, dev.id, True, minute=10)
    for m in (20, 30, 40):
        await _meldet(db_session, dev.id, True, minute=m)

    z = await relay_state.bestaetigter_zustand(db_session, dev.id)

    assert z.ein is True
    assert z.seit == BEZUG + timedelta(minutes=10), "der Beginn ist der Wechsel"
    assert z.gemeldet == BEZUG + timedelta(minutes=40), "die Meldung ist die jüngste"


async def test_stummes_panel_hat_denselben_beginn_und_alte_meldung(
    db_session: AsyncSession,
) -> None:
    """**Die Gegenprobe zum Test darueber.**

    Dieselbe ``seit``, ein anderes ``gemeldet``: das Relais hat um 08:10
    EIN gemeldet und seither geschwiegen. Wer nur ``seit`` liest, sieht
    keinen Unterschied zu einem Panel, das im Zehn-Minuten-Takt weiter
    meldet — und genau diesen Unterschied braucht der Waechter.
    """
    dev = await _relais(db_session)
    await _meldet(db_session, dev.id, False, minute=0)
    await _meldet(db_session, dev.id, True, minute=10)

    z = await relay_state.bestaetigter_zustand(db_session, dev.id)

    assert z.ein is True
    assert z.seit == BEZUG + timedelta(minutes=10)
    assert z.gemeldet == BEZUG + timedelta(minutes=10), (
        "ohne Folgemeldung sind Beginn und jüngste Meldung dieselbe Zeile"
    )


async def test_zeilen_ohne_zustand_zaehlen_auch_fuer_die_meldezeit_nicht(
    db_session: AsyncSession,
) -> None:
    """Eine Zeile ohne ``relay_on`` macht einen alten Zustand nicht frisch.

    Eine reine Befehlsantwort ohne Keepalive-Schwanz sagt nichts darueber,
    ob das Relais schaltet. Zaehlte sie als Meldung, waere der Zustand
    wieder „frisch" — und der Waechter wuerde einem Wert glauben, den
    diese Zeile nie bestaetigt hat.
    """
    dev = await _relais(db_session)
    await _meldet(db_session, dev.id, True, minute=0)
    await _meldet(db_session, dev.id, None, minute=30)

    z = await relay_state.bestaetigter_zustand(db_session, dev.id)

    assert z.ein is True
    assert z.gemeldet == BEZUG, "die Zeile ohne Zustand verschiebt nichts"


async def test_ohne_jede_zeile_ist_alles_unbekannt(db_session: AsyncSession) -> None:
    dev = await _relais(db_session)

    z = await relay_state.bestaetigter_zustand(db_session, dev.id)

    assert z.ein is None
    assert z.seit is None
    assert z.gemeldet is None, "kein Zustand heisst auch keine Meldezeit"
