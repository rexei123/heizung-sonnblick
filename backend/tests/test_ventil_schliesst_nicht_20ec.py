"""Sprint 20e-c T5 — Regel 3c in der Breite, und die Messung als Testwand.

**Der Befund, um den es geht.** Am 10.10.2026 lief der Kessel, und Regel 3b
fand **einen** der beiden defekten Köpfe: 027/110 mit 7,2 K über Soll und
3,7 K über dem Median wurde gemeldet, 100/405 mit 3,1 K über dem Median
nicht — die Schwelle liegt bei 3,5. Beide klemmten offen.

Die Ursache war die Jahreszeit, nicht die Schwelle: im Herbst hebt die
Eigenwärme der heizenden Zimmer den Median, und der Abstand eines defekten
Zimmers dazu schrumpft. **Regel 3b erkennt im Herbst also nur die stark
heizenden Defekte.**

3c umgeht das, statt es zu bekämpfen: es vergleicht das Gerät mit **sich
selbst** — seiner eigenen Zielvorgabe und seiner eigenen gemeldeten
Stellung. Ein funktionierendes Vicki, dessen Zimmer über dem eigenen
Sollwert liegt, schließt.

Was hier gepinnt ist
--------------------

1. **Die Testwand aus der echten Messung** (§6): der Datenstand vom 10.10.
   mit den Zahlen aus Abfrage A. 027 und 100 werden gemeldet, sonst keiner.
   Das ist seit dem 12.10. **das Akzeptanzkriterium AK 1** — die Köpfe
   liegen ohne Batterie im Lager, eine Live-Abnahme gibt es nicht mehr.
2. **G1, die Absenkung**: ein einziger Messwert unter der Schwelle fällt
   das Urteil. Die gemessene Zahl dazu steht im Brief (Gerät 049: 74 % →
   0 % in unter zehn Minuten).
3. **G2, offenes Fenster / Frostschutz**: 3c meldet, und das ist richtig.
   Als Verhalten festgehalten, nicht als Ausnahme.
4. **Die Pool-Abgrenzung in beide Richtungen**: 3c ja, 3b nein.
5. **Die Mindest-Stichprobe**, mit der Zahl aus der Messung (100/405 hatte
   acht Messwerte — knapp über der Grenze, und das ist der interessante
   Fall).
"""

from __future__ import annotations

import itertools
import os
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import delete as sa_delete
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from heizung.config import get_settings
from heizung.models.device import Device
from heizung.models.enums import DeviceKind, DeviceVendor, HeatingZoneKind
from heizung.models.heating_zone import HeatingZone
from heizung.models.room import Room
from heizung.models.room_type import RoomType
from heizung.models.sensor_reading import SensorReading
from heizung.services.valve_health import VALVE_MIN_SAMPLES, ValveState, valve_verdicts

TEST_DB_URL = os.environ.get("TEST_DATABASE_URL")
SKIP_REASON = "TEST_DATABASE_URL nicht gesetzt — DB-Tests brauchen Postgres"

EUI_PREFIX = "7e20ec00"
RAUM_PREFIX = "vc-"
# Eigenes Fenster, damit sich diese Datei mit keiner anderen dasselbe
# teilt: die Referenz von Regel 3b ist hausweit und sieht jede Zeile im
# Fenster, auch fremde (§5.39).
JETZT = datetime(2026, 10, 10, 11, 30, 0, tzinfo=UTC)

SOLL = Decimal("18.0")

# ``(time, device_id, fcnt)`` ist UNIQUE. Ein Zaehler ist einfacher als
# eine Formel aus ``offset_min``, die bei negativen Werten kippt.
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
    await session.execute(sa_delete(HeatingZone).where(HeatingZone.room_id.in_(raum_ids)))
    await session.execute(sa_delete(Room).where(Room.number.like(f"{RAUM_PREFIX}%")))
    await session.execute(sa_delete(RoomType).where(RoomType.name.like(f"{RAUM_PREFIX}%")))


@pytest_asyncio.fixture
async def raumtyp_id(db_session: AsyncSession) -> int:
    rt = RoomType(name=f"{RAUM_PREFIX}rt-{uuid.uuid4().hex[:6]}")
    db_session.add(rt)
    await db_session.flush()
    return rt.id


async def _geraet(
    session: AsyncSession,
    raumtyp_id: int | None = None,
    *,
    label: str | None = None,
) -> int:
    """Ein Geraet, mit Zimmer und Zone wenn ``raumtyp_id`` gegeben ist."""
    suffix = uuid.uuid4().hex[:8]
    zone_id: int | None = None
    if raumtyp_id is not None:
        room = Room(number=f"{RAUM_PREFIX}{suffix}", room_type_id=raumtyp_id)
        session.add(room)
        await session.flush()
        # ``kind`` ist NOT NULL ohne Default (§5.49).
        zone = HeatingZone(room_id=room.id, kind=HeatingZoneKind.BEDROOM, name="z0")
        session.add(zone)
        await session.flush()
        zone_id = zone.id
    device = Device(
        dev_eui=f"{EUI_PREFIX}{suffix}",
        kind=DeviceKind.THERMOSTAT,
        vendor=DeviceVendor.MCLIMATE,
        model="vicki",
        label=label,
        heating_zone_id=zone_id,
    )
    session.add(device)
    await session.flush()
    return device.id


async def _werte(
    session: AsyncSession,
    device_id: int,
    *,
    soll: Decimal = SOLL,
    ist: Decimal,
    ventil: int | None,
    anzahl: int = VALVE_MIN_SAMPLES,
    offset_min: int = 0,
) -> None:
    """``anzahl`` gleichartige Messwerte, 10 min auseinander.

    ``offset_min`` verschiebt den Block nach hinten — damit lassen sich
    zwei Bloecke mit verschiedenen Werten in ein Fenster legen (G1).
    """
    for i in range(anzahl):
        session.add(
            SensorReading(
                time=JETZT - timedelta(minutes=offset_min + 10 * (i + 1)),
                device_id=device_id,
                fcnt=next(_fcnt),
                setpoint=soll,
                temperature=ist,
                valve_position=ventil,
            )
        )
    await session.flush()


async def _urteil(session: AsyncSession, device_id: int) -> ValveState:
    return (await valve_verdicts(session, [device_id], now=JETZT))[device_id].state


@pytest.fixture(autouse=True)
def _settings_sauber() -> AsyncIterator[None]:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


# ---------------------------------------------------------------------------
# 1. Die Testwand: der Datenstand vom 10.10.2026
# ---------------------------------------------------------------------------
#
# Aus Abfrage A (festes Fenster 09:30-11:30 UTC, LEFT JOIN, Kessel an):
#
#  geraet | zimmer | n  | ueber_soll | ventil_min | ventil_max | kalib | regel3c
#  -------+--------+----+------------+------------+------------+-------+--------
#  027    |        | 11 |        7.2 |        100 |        100 | f     | t
#  100    |        |  8 |        6.1 |        100 |        100 | f     | t
#
# Beide ohne Zimmer: sie waren am 12.10. schon aus ihren Zonen genommen
# (getauscht 005 -> 405, 008 -> 110), der Join laeuft ueber die heutige
# Zuordnung. Genau deshalb braucht 3c keine Zone.


async def test_testwand_1010_meldet_genau_027_und_100(
    db_session: AsyncSession, raumtyp_id: int
) -> None:
    """**Das ist seit dem 12.10. das Akzeptanzkriterium AK 1.**

    Die Koepfe 027 und 100 liegen ohne Batterie im Lager — es gibt keinen
    Defekt mehr, an dem sich die Regel live beweisen koennte. Dieser Test
    ist der Beleg, und er haengt an den Daten vom 10.10., die weiter in der
    Datenbank liegen (``sensor_reading`` hat keine Retention; siehe
    B-17-2).

    Nachgebaut sind die Zahlen aus Abfrage A, inklusive der
    Stichprobengroessen: 027 mit elf Messwerten, 100 mit **acht** — knapp
    ueber ``VALVE_MIN_SAMPLES``, und damit der interessantere der beiden.

    Dazu fuenf gesunde Zimmer, die die Referenz bilden und selbst nichts
    melden duerfen. Ohne sie wuerde der Test auch dann gruen sein, wenn 3b
    versehentlich jedes warme Zimmer melden wuerde.
    """
    # Fuenf gesunde, nicht belegte Zimmer auf 21,7 °C — der gemessene
    # Median des 10.10. Sie heizen (Ventil halb offen) und liegen 3,7 K
    # ueber dem Sollwert, also unter der absoluten Schwelle von 5 K.
    gesund = [await _geraet(db_session, raumtyp_id) for _ in range(5)]
    for d in gesund:
        await _werte(db_session, d, ist=Decimal("21.7"), ventil=50)

    # Die beiden defekten Koepfe: ohne Zone (Pool), Ventil voll offen.
    kopf_027 = await _geraet(db_session, label="027")
    await _werte(db_session, kopf_027, ist=Decimal("25.2"), ventil=100, anzahl=11)
    kopf_100 = await _geraet(db_session, label="100")
    await _werte(db_session, kopf_100, ist=Decimal("24.1"), ventil=100, anzahl=8)

    urteile = await valve_verdicts(db_session, [*gesund, kopf_027, kopf_100], now=JETZT)

    assert urteile[kopf_027].state == "ventil_schliesst_nicht"
    assert urteile[kopf_100].state == "ventil_schliesst_nicht"
    # Die gemessenen Abstaende, auf 0,1 K wie in der Abfrage.
    assert urteile[kopf_027].delta_k == Decimal("7.20")
    assert urteile[kopf_100].delta_k == Decimal("6.10")
    # Und sonst keiner — das ist die Haelfte des Kriteriums.
    assert {urteile[d].state for d in gesund} == {"ok"}


async def test_testwand_acht_messwerte_reichen_sieben_nicht(
    db_session: AsyncSession, raumtyp_id: int
) -> None:
    """100/405 hatte **acht** Messwerte. Fuenf waeren zu wenig.

    Die Grenze liegt bei ``VALVE_MIN_SAMPLES`` (6) und ist eine Eigenschaft
    der Messung, keine Betriebspraeferenz. Der Test haelt fest, dass der
    echte Fall sie nicht nur knapp erfuellt, sondern dass die Grenze auch
    greift — sonst waere sie eine Zahl ohne Wirkung.
    """
    knapp = await _geraet(db_session)
    await _werte(db_session, knapp, ist=Decimal("24.1"), ventil=100, anzahl=VALVE_MIN_SAMPLES)
    assert await _urteil(db_session, knapp) == "ventil_schliesst_nicht"

    zu_wenig = await _geraet(db_session)
    await _werte(
        db_session, zu_wenig, ist=Decimal("24.1"), ventil=100, anzahl=VALVE_MIN_SAMPLES - 1
    )
    assert await _urteil(db_session, zu_wenig) == "unbekannt"


# ---------------------------------------------------------------------------
# 2. G1 — die Absenkung
# ---------------------------------------------------------------------------


async def test_g1_ein_messwert_unter_der_schwelle_faellt_das_urteil(
    db_session: AsyncSession,
) -> None:
    """**Der Fall, der jede Nacht eintritt.**

    Der Sollwert fällt (Nachtabsenkung, Abreise), das Zimmer liegt über dem
    neuen Wert, und das Ventil ist noch offen. Würde 3c dann melden, käme
    jede Nacht das halbe Haus.

    ``bool_and`` traegt das: ein einziger Messwert unter der Schwelle faellt
    das ganze Urteil. Hier melden fuenf Werte 100 % und einer 30 % — das
    Bild eines Geraets, das gerade geschlossen hat.

    **Gemessen am echten Geraet** (Brief §6): 049 ging am 05.10. nach einer
    Absenkung von 25 auf 18 in unter zehn Minuten von 74 % auf 0 %. Die
    Mechanik hier, die Zahl dort.
    """
    schliesst_gerade = await _geraet(db_session)
    await _werte(db_session, schliesst_gerade, ist=Decimal("24.0"), ventil=100, anzahl=5)
    # Der juengste Messwert, fuenf Minuten alt: das Ventil ist auf dem Weg
    # zu. Negativer Offset, damit er VOR dem ersten Block liegt — der
    # beginnt bei zehn Minuten.
    await _werte(
        db_session, schliesst_gerade, ist=Decimal("24.0"), ventil=30, anzahl=1, offset_min=-5
    )

    assert await _urteil(db_session, schliesst_gerade) == "ok"


async def test_g1_das_uebergangsfenster_schuetzt_sich_selbst(
    db_session: AsyncSession,
) -> None:
    """Der alte, hoehere Sollwert im Fenster faellt das Urteil ebenfalls.

    Vor der Absenkung lag das Zimmer **unter** seinem Sollwert (25 °C Soll,
    24 °C Ist) — diese Messwerte erfuellen die Temperatur-Bedingung nicht,
    und ``bool_and`` ueber das Fenster ist damit falsch. Solange also noch
    ein Wert von vor dem Sprung im Fenster liegt, kann 3c nicht melden.

    Das ist die zweite, unabhaengige Sicherung gegen G1 — und sie wirkt
    ohne jede Schwelle.
    """
    device_id = await _geraet(db_session)
    # Nach der Absenkung: Soll 18, Zimmer 24, Ventil noch offen.
    await _werte(
        db_session, device_id, soll=Decimal("18.0"), ist=Decimal("24.0"), ventil=100, anzahl=3
    )
    # Davor: Soll 25, dasselbe Zimmer — 24 liegt darunter.
    await _werte(
        db_session,
        device_id,
        soll=Decimal("25.0"),
        ist=Decimal("24.0"),
        ventil=100,
        anzahl=3,
        offset_min=30,
    )

    assert await _urteil(db_session, device_id) == "ok"


# ---------------------------------------------------------------------------
# 3. G2 — offenes Fenster und Frostschutz
# ---------------------------------------------------------------------------


async def test_g2_bei_gesenktem_sollwert_meldet_3c_und_das_ist_richtig(
    db_session: AsyncSession,
) -> None:
    """Frostschutz oder offenes Fenster: der Sollwert faellt stark.

    Die Engine senkt auf Frostschutz, das Zimmer bleibt warm, und ein
    Geraet, das weiter offen meldet, **ist** ein Defekt — ein Ventil, das
    bei Frostschutz offen bleibt, heizt gegen das offene Fenster.

    **Als Verhalten festgehalten, nicht als Ausnahme.** T0 am 10.10. zeigte
    ``fenster_offen = f`` bei beiden gemeldeten Geraeten, der Fall traegt
    heute also nichts zu Fehlalarmen bei. Sollte er es spaeter tun, ist
    ``open_window`` im Fenster der Ausschluss — und dieser Test die Stelle,
    an der die Entscheidung umgedreht wird.
    """
    device_id = await _geraet(db_session)
    await _werte(db_session, device_id, soll=Decimal("7.0"), ist=Decimal("21.0"), ventil=100)

    assert await _urteil(db_session, device_id) == "ventil_schliesst_nicht"


# ---------------------------------------------------------------------------
# 4. Die Pool-Abgrenzung, in beide Richtungen
# ---------------------------------------------------------------------------


async def test_pool_geraet_bekommt_3c_aber_nicht_3b(
    db_session: AsyncSession, raumtyp_id: int
) -> None:
    """Dasselbe Geraet, einmal mit und einmal ohne Zone — zwei Urteile.

    **Die Unterscheidung ist die ganze Entscheidung vom 12.10.:** 3c ist
    eine Aussage ueber das **Geraet** ("meldet offen, obwohl es schliessen
    muesste") und gilt am Tisch genauso wie im Zimmer. 3b ist eine Aussage
    ueber ein **Zimmer**, und ein Geraet im Pool sitzt in keinem.

    Gefahren wird die Lage, in der sich beide unterscheiden: Ventil
    geschlossen gemeldet (3c trifft nicht), Zimmer absolut und relativ zu
    warm (3b wuerde treffen).
    """
    # Referenz: fuenf nicht belegte Zimmer auf 20 °C.
    for _ in range(5):
        d = await _geraet(db_session, raumtyp_id)
        await _werte(db_session, d, ist=Decimal("20.0"), ventil=50)

    # Mit Zone: 3b trifft (24 >= 18+5 und 24 >= 20+3,5), 3c nicht (Ventil 0).
    mit_zone = await _geraet(db_session, raumtyp_id)
    await _werte(db_session, mit_zone, ist=Decimal("24.0"), ventil=0)
    assert await _urteil(db_session, mit_zone) == "zimmer_zu_warm"

    # Ohne Zone: dieselben Messwerte, aber kein Zimmer — also kein Hinweis.
    ohne_zone = await _geraet(db_session)
    await _werte(db_session, ohne_zone, ist=Decimal("24.0"), ventil=0)
    assert await _urteil(db_session, ohne_zone) == "ok"

    # Und mit offenem Ventil greift 3c auch ohne Zone.
    ohne_zone_offen = await _geraet(db_session)
    await _werte(db_session, ohne_zone_offen, ist=Decimal("24.0"), ventil=100)
    assert await _urteil(db_session, ohne_zone_offen) == "ventil_schliesst_nicht"


async def test_regel3_gilt_weiter_fuer_pool_geraete(db_session: AsyncSession) -> None:
    """Regel 3 bleibt im Pool gueltig — das ist das Lager-Residuum.

    Ein Geraet mit eingelegten Batterien im **kalten** Lager meldet Soll 18
    bei Ist 10 und ein geschlossenes Ventil. Das erfuellt Regel 3, und die
    Kachel "Ventil pruefen" zaehlt es mit.

    **Akzeptiert** (Entscheidung vom 12.10., RUNBOOK §10t): die Regel ist
    eine Aussage ueber das Geraet, und am Tisch ist genau das die Auskunft,
    die ein Eingangstest braucht. Der Test steht hier, damit die
    Entscheidung sichtbar bleibt und nicht beim naechsten Aufraeumen
    stillschweigend kippt.
    """
    im_lager = await _geraet(db_session)
    await _werte(db_session, im_lager, soll=Decimal("18.0"), ist=Decimal("10.0"), ventil=0)

    assert await _urteil(db_session, im_lager) == "ventil_klemmt_zu"


# ---------------------------------------------------------------------------
# 5. Die Schwellen wirken
# ---------------------------------------------------------------------------


async def test_schwellen_kommen_aus_den_einstellungen(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Dieselbe Lage, andere Marke: 70 % statt 80 % aendert das Urteil.

    Der Sinn der Einstellung ist das Nachjustieren ohne Code-Aenderung. Ein
    Test, der nur die Vorgabe prueft, laesst offen, ob der Wert ueberhaupt
    gelesen wird.
    """
    device_id = await _geraet(db_session)
    await _werte(db_session, device_id, ist=Decimal("24.0"), ventil=75)

    # Mit der Vorgabe 80 %: 75 reicht nicht.
    assert await _urteil(db_session, device_id) == "ok"

    monkeypatch.setenv("VALVE_OPEN_MIN_PCT", "70")
    get_settings.cache_clear()
    assert await _urteil(db_session, device_id) == "ventil_schliesst_nicht"


async def test_nicht_belegtes_zimmer_mit_offenem_ventil_und_kaltem_raum_ist_ok(
    db_session: AsyncSession, raumtyp_id: int
) -> None:
    """Der Normalfall im Winter: Ventil offen, Zimmer heizt noch.

    Soll 21, Ist 19, Ventil 100 % — das Geraet arbeitet. Ohne die
    Temperatur-Bedingung waere 3c ein Hinweis fuer jeden heizenden
    Heizkoerper im Haus, also fuer das halbe Haus an jedem kalten Morgen.
    """
    device_id = await _geraet(db_session, raumtyp_id)
    await _werte(db_session, device_id, soll=Decimal("21.0"), ist=Decimal("19.0"), ventil=100)

    assert await _urteil(db_session, device_id) == "ok"
