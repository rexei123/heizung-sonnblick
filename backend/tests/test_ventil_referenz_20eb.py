"""Sprint 20e-b T5/T6 — die Referenz von Regel 3b, und die Messung als Testwand.

**Der Befund, um den es geht.** Am 07.10.2026, 14:58, Kessel aus, meldete die
Kachel „Zimmer zu warm" **14** Geraete. Echt waren zwei. Leere Zimmer standen
bei Herbstwetter ohne Heizung bei 22-24 °C ueber einem Sollwert von 18 °C —
das absolute Kriterium kann Wetter nicht von einem klemmenden Ventil
unterscheiden. Ein Melder, dem niemand mehr glaubt, ueberwacht nichts
(§5.79).

Seit 20e-b verlangt 3b **zwei** Bedingungen mit UND: ueber dem Sollwert und
ueber vergleichbaren Zimmern. Diese Datei haelt beide Richtungen fest — dass
das Wetter herausfaellt, **und** dass ein echter Fall nicht mit herausfaellt.

Was hier gepinnt ist
--------------------

1. **Die vier Kombinationen** der beiden Bedingungen. Ein Hinweis entsteht
   nur, wenn beide zutreffen.
2. **G1** (Brief §2): zu wenige Zimmer in der Referenzmenge -> kein
   relatives Urteil, also kein Hinweis. Und das Verdict sagt warum.
3. **G2**: Hochsaison, fast alles belegt -> Rueckfall auf alle Zimmer, mit
   dem **groesseren** Delta und benannt als ``alle``.
4. **G4**: die 50-%-Grenze des Medians. Drei von sieben heissen Zimmern
   halten ihn, fuenf von sieben nicht. Das ist die Annahme, auf der das
   ganze Kriterium steht, und sie gehoert gemessen statt behauptet.
5. **AK 2**: ein echter Fall wird weiter gemeldet, auch wenn das ganze Haus
   warm ist. Das ist die Gegenrichtung zu Punkt 1 und die wichtigere: ein
   Filter, der zu viel filtert, ist schlimmer als keiner, weil er
   Sicherheit vorspiegelt.
6. **T6, die Messung vom 08.10. als Testwand** — siehe unten.

Warum die Fixtures Zimmer anlegen
---------------------------------

Die Referenz ist **hausweit** und entsteht aus Zimmern: ein Geraet ohne
Zimmer traegt nichts dazu bei. Jeder Test hier baut sich sein Haus selbst.

Das hat eine Folge, die man kennen muss: die Referenz sieht **jede** Zeile
im Fenster, auch fremde (§5.39). Deshalb liegt das Fenster dieser Datei auf
dem 08.10.2026 (dem Zeitpunkt der T0-Messung) und damit auf keinem anderen
Testdatum, die Fixture raeumt vor und nach jedem Test, und die Tests pinnen
den **Median** mit. Eine Verunreinigung faellt damit als benannte
Fehlmeldung auf und nicht als Flattern.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import delete as sa_delete
from sqlalchemy import select
from sqlalchemy import update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from heizung.config import get_settings
from heizung.models.device import Device
from heizung.models.enums import DeviceKind, DeviceVendor, HeatingZoneKind, RoomStatus
from heizung.models.heating_zone import HeatingZone
from heizung.models.room import Room
from heizung.models.room_type import RoomType
from heizung.models.sensor_reading import SensorReading
from heizung.services.valve_health import VALVE_MIN_SAMPLES, valve_verdicts

TEST_DB_URL = os.environ.get("TEST_DATABASE_URL")
SKIP_REASON = "TEST_DATABASE_URL nicht gesetzt — DB-Tests brauchen Postgres"

EUI_PREFIX = "7e20eb00"
RAUM_PREFIX = "rb-"
# Der Zeitpunkt der T0-Messung. Bewusst ein anderer als in
# ``test_ventil_hinweise_20e.py`` (07.10. 12:00) — zwei Dateien, die beide
# hausweite Referenzen bilden, sollen sich nicht dasselbe Fenster teilen.
JETZT = datetime(2026, 10, 8, 9, 48, 0, tzinfo=UTC)

SOLL = Decimal("18.0")

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
    """Geraete, Messwerte, Zonen, Zimmer, Raumtypen — in FK-sicherer Folge.

    Vollstaendig und nicht nur die Geraete: ein zurueckgelassenes Zimmer mit
    Messwerten im Fenster verschiebt den Median des naechsten Laufs.
    """
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


async def _zimmer_mit_geraet(
    session: AsyncSession,
    raumtyp_id: int,
    *,
    ist: Decimal,
    soll: Decimal = SOLL,
    belegt: bool = False,
    anzahl: int = VALVE_MIN_SAMPLES,
) -> int:
    """Ein Zimmer mit einer Zone, einem Geraet und ``anzahl`` Messwerten.

    Gibt die Geraete-ID zurueck. Alle Messwerte gleich, damit der Median
    ueber die Messwerte eine Zahl ist, mit der man rechnen kann, und keine
    Schaetzung.
    """
    suffix = uuid.uuid4().hex[:10]
    room = Room(
        number=f"{RAUM_PREFIX}{suffix}",
        room_type_id=raumtyp_id,
        status=RoomStatus.OCCUPIED if belegt else RoomStatus.VACANT,
    )
    session.add(room)
    await session.flush()
    # ``kind`` ist NOT NULL ohne Default (§5.49).
    zone = HeatingZone(room_id=room.id, kind=HeatingZoneKind.BEDROOM, name="z0")
    session.add(zone)
    await session.flush()
    device = Device(
        dev_eui=f"{EUI_PREFIX}{suffix[:8]}",
        kind=DeviceKind.THERMOSTAT,
        vendor=DeviceVendor.MCLIMATE,
        model="vicki",
        heating_zone_id=zone.id,
    )
    session.add(device)
    await session.flush()
    for i in range(anzahl):
        session.add(
            SensorReading(
                time=JETZT - timedelta(minutes=10 * (i + 1)),
                device_id=device.id,
                fcnt=i + 1,
                setpoint=soll,
                temperature=ist,
                # Bewusst halb offen: die Ventilstellung ist fuer 3b keine
                # Bedingung (AE-74), und 50 % schliesst Regel 3 aus.
                valve_position=50,
            )
        )
    await session.flush()
    return device.id


def _delta(monkeypatch: pytest.MonkeyPatch, **werte: str) -> None:
    """Schwellen fuer einen Test setzen. ``get_settings`` ist gecacht."""
    for schluessel, wert in werte.items():
        monkeypatch.setenv(schluessel, wert)
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _settings_sauber() -> AsyncIterator[None]:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


# ---------------------------------------------------------------------------
# 1. Die vier Kombinationen
# ---------------------------------------------------------------------------


async def test_beide_bedingungen_zusammen_ergeben_den_hinweis(
    db_session: AsyncSession, raumtyp_id: int
) -> None:
    """Soll 18, Median 20, Ist 24: 6 K ueber Soll und 4 K ueber der Referenz."""
    for _ in range(5):
        await _zimmer_mit_geraet(db_session, raumtyp_id, ist=Decimal("20.0"))
    auffaellig = await _zimmer_mit_geraet(db_session, raumtyp_id, ist=Decimal("24.0"))

    v = (await valve_verdicts(db_session, [auffaellig], now=JETZT))[auffaellig]

    assert v.state == "zimmer_zu_warm"
    assert v.referenz == "unbelegt"
    assert v.referenz_median_c == Decimal("20.000"), "fremde Messwerte im Fenster?"
    assert v.delta_k == Decimal("6.00")
    assert v.referenz_delta_k == Decimal("4.000")


async def test_absolut_warm_aber_nicht_relativ_ist_kein_hinweis(
    db_session: AsyncSession, raumtyp_id: int
) -> None:
    """**Der Fall vom 07.10.** Das ganze Haus ist warm, keiner faellt auf.

    Alle Zimmer 24 °C bei Soll 18: jedes einzelne ist 6 K ueber dem
    Sollwert, also absolut auffaellig. Relativ ist keines auffaellig, weil
    der Median mitgewandert ist. Genau diese 14 Meldungen sollen weg.

    Der Abstand zur Referenz steht trotzdem im Verdict (0,0 K) — das ist die
    Zahl, die den Unterschied erklaert. Ohne sie saehe die Lage aus wie
    "nichts gemessen".
    """
    geraete = [
        await _zimmer_mit_geraet(db_session, raumtyp_id, ist=Decimal("24.0")) for _ in range(6)
    ]

    urteile = await valve_verdicts(db_session, geraete, now=JETZT)

    assert {v.state for v in urteile.values()} == {"ok"}
    beispiel = urteile[geraete[0]]
    assert beispiel.referenz == "unbelegt"
    assert beispiel.referenz_median_c == Decimal("24.000")
    assert beispiel.referenz_delta_k == Decimal("0.000")


async def test_relativ_auffaellig_aber_nicht_absolut_ist_kein_hinweis(
    db_session: AsyncSession, raumtyp_id: int
) -> None:
    """Kaltes Haus, ein waermeres Zimmer — aber nicht ueber dem Sollwert.

    Median 14 °C (ungeheiztes Haus im Herbst), ein Zimmer auf 20 °C: 6 K
    ueber der Referenz, aber bei Soll 22 noch **unter** dem Sollwert. Das
    ist ein Zimmer, das heizt, und kein Befund.

    Ohne die UND-Verknuepfung waere das ein Hinweis — und zwar fuer jedes
    Zimmer, das als erstes aufheizt.
    """
    for _ in range(5):
        await _zimmer_mit_geraet(db_session, raumtyp_id, ist=Decimal("14.0"), soll=Decimal("22.0"))
    waermer = await _zimmer_mit_geraet(
        db_session, raumtyp_id, ist=Decimal("20.0"), soll=Decimal("22.0")
    )

    v = (await valve_verdicts(db_session, [waermer], now=JETZT))[waermer]

    assert v.state == "ok"
    assert v.referenz_median_c == Decimal("14.000")
    # Kein relativer Abstand im Verdict: das Zimmer ist nicht absolut zu
    # warm, die Frage stellt sich also nicht.
    assert v.referenz_delta_k is None


# ---------------------------------------------------------------------------
# 2. G1 — zu wenige Zimmer
# ---------------------------------------------------------------------------


async def test_g1_zu_wenige_zimmer_ergeben_kein_urteil(
    db_session: AsyncSession, raumtyp_id: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Vier Zimmer bei ``REF_MIN_ROOMS = 5``: kein relatives Urteil.

    Ein Median ueber vier Werten ist das Mittel der beiden mittleren, also
    ein Einzelwert mit Zufallsanteil. Darunter gibt es **keinen** Hinweis —
    und ausdruecklich keinen Rueckfall auf das absolute Kriterium. Das waere
    der Zustand vom 07.10., nur seltener und damit unberechenbar.

    Das Verdict sagt ``keine``, damit die Oberflaeche "warum kein Hinweis"
    beantworten kann statt zu schweigen.
    """
    # Ausdruecklich gesetzt und nicht aus der Vorgabe genommen: senkt
    # jemand die Mindestzahl, soll dieser Test weiter pruefen, was sein
    # Name sagt, und nicht still etwas anderes.
    _delta(monkeypatch, REF_MIN_ROOMS="5")
    for _ in range(3):
        await _zimmer_mit_geraet(db_session, raumtyp_id, ist=Decimal("20.0"))
    heiss = await _zimmer_mit_geraet(db_session, raumtyp_id, ist=Decimal("30.0"))

    v = (await valve_verdicts(db_session, [heiss], now=JETZT))[heiss]

    # 30 °C bei Soll 18 ist 12 K darueber — absolut so auffaellig wie es
    # geht. Trotzdem kein Hinweis, weil die Referenz fehlt.
    assert v.state == "ok"
    assert v.referenz == "keine"
    assert v.referenz_median_c is None


# ---------------------------------------------------------------------------
# 3. G2 — Hochsaison, Rueckfall auf alle Zimmer
# ---------------------------------------------------------------------------


async def test_g2_rueckfall_auf_alle_zimmer(
    db_session: AsyncSession, raumtyp_id: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fast alles belegt: Stufe 2 greift, mit dem groesseren Delta.

    Vier nicht belegte Zimmer (unter der Mindestzahl) und vier belegte.
    Stufe 1 faellt aus, Stufe 2 nimmt **alle** acht — und das Verdict nennt
    sie ``alle``, damit der Hinweistext nicht "vergleichbare Zimmer"
    behauptet, wo gegen belegte mitverglichen wurde.

    Das groessere Delta ist hier nicht Kosmetik: belegte Zimmer stehen auf
    22-24 °C, der Median liegt also hoeher, und mit demselben Delta waere
    3b stumpf (Brief §2 G5).
    """
    _delta(monkeypatch, ROOM_REL_DELTA_ALL_K="4.0")
    for _ in range(4):
        await _zimmer_mit_geraet(db_session, raumtyp_id, ist=Decimal("20.0"))
    for _ in range(4):
        await _zimmer_mit_geraet(db_session, raumtyp_id, ist=Decimal("20.0"), belegt=True)
    auffaellig = await _zimmer_mit_geraet(db_session, raumtyp_id, ist=Decimal("24.5"), belegt=True)

    v = (await valve_verdicts(db_session, [auffaellig], now=JETZT))[auffaellig]

    assert v.referenz == "alle"
    assert v.referenz_median_c == Decimal("20.000")
    # 4,5 K ueber dem Median — reicht fuer das groessere Delta von 4,0.
    assert v.state == "zimmer_zu_warm"
    assert v.referenz_delta_k == Decimal("4.500")


async def test_g2_stufe_zwei_ist_vorsichtiger_als_stufe_eins(
    db_session: AsyncSession, raumtyp_id: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Dieselbe Lage, 3,8 K ueber dem Median: Stufe 1 ja, Stufe 2 nein.

    Der Unterschied zwischen den beiden Deltas ist damit keine Zahl in den
    Einstellungen, sondern eine Aussage: in der Hochsaison ist derselbe
    Abstand **kein** Befund mehr.
    """
    _delta(monkeypatch, ROOM_REL_DELTA_K="3.5", ROOM_REL_DELTA_ALL_K="4.0")

    # Erst Stufe 1: fuenf nicht belegte Zimmer.
    for _ in range(5):
        await _zimmer_mit_geraet(db_session, raumtyp_id, ist=Decimal("20.0"))
    knapp = await _zimmer_mit_geraet(db_session, raumtyp_id, ist=Decimal("23.8"))

    v1 = (await valve_verdicts(db_session, [knapp], now=JETZT))[knapp]
    assert v1.referenz == "unbelegt"
    assert v1.state == "zimmer_zu_warm", "3,8 K reichen fuer Stufe 1 (3,5)"

    # Jetzt dieselben Zimmer belegen: Stufe 1 faellt aus, Stufe 2 greift.
    await db_session.execute(
        sa_update(Room)
        .where(Room.number.like(f"{RAUM_PREFIX}%"))
        .values(status=RoomStatus.OCCUPIED)
    )
    await db_session.flush()

    v2 = (await valve_verdicts(db_session, [knapp], now=JETZT))[knapp]
    assert v2.referenz == "alle"
    assert v2.state == "ok", "3,8 K reichen nicht fuer Stufe 2 (4,0)"
    assert v2.referenz_delta_k == Decimal("3.800")


# ---------------------------------------------------------------------------
# 4. G4 — die 50-%-Grenze des Medians
# ---------------------------------------------------------------------------


async def test_g4_median_traegt_drei_von_sieben(db_session: AsyncSession, raumtyp_id: int) -> None:
    """Drei heisse Zimmer von sieben: der Median haelt, alle drei gemeldet.

    Der Fall nach einer Reinigungsrunde, bei der ein paar Koepfe abgesetzt
    wurden. Unter 50 % Verunreinigung bleibt der Median bei den kuehlen
    Zimmern stehen, und die heissen fallen auf.
    """
    kuehl = [
        await _zimmer_mit_geraet(db_session, raumtyp_id, ist=Decimal("20.0")) for _ in range(4)
    ]
    heiss = [
        await _zimmer_mit_geraet(db_session, raumtyp_id, ist=Decimal("25.0")) for _ in range(3)
    ]

    urteile = await valve_verdicts(db_session, kuehl + heiss, now=JETZT)

    assert urteile[heiss[0]].referenz_median_c == Decimal("20.000")
    assert {urteile[d].state for d in heiss} == {"zimmer_zu_warm"}
    assert {urteile[d].state for d in kuehl} == {"ok"}


async def test_g4_median_kippt_bei_fuenf_von_sieben(
    db_session: AsyncSession, raumtyp_id: int
) -> None:
    """**Die Grenze der Methode, als Messung statt als Behauptung.**

    Fuenf heisse Zimmer von sieben: der Median wandert zu ihnen, und keines
    faellt mehr auf. Das Kriterium ist in dieser Lage **blind**, und kein
    Code aendert das — ein Median ist genau bis zur Haelfte robust.

    Dieser Test ist die unangenehme Haelfte von G4 und steht hier, damit die
    Annahme eine Aussage bleibt und nicht ein Nebeneffekt, den irgendwann
    jemand fuer eine Zusicherung haelt. Wer die Methode aendert, muss diesen
    Test aendern — und merkt dabei, was er aufgibt.

    Der Trost ist klein, aber real: die beiden kuehlen Zimmer werden jetzt
    nicht faelschlich gemeldet. Der Fehler geht in die stille Richtung, und
    das ist bei einem Hinweis die richtige (§5.79).
    """
    kuehl = [
        await _zimmer_mit_geraet(db_session, raumtyp_id, ist=Decimal("20.0")) for _ in range(2)
    ]
    heiss = [
        await _zimmer_mit_geraet(db_session, raumtyp_id, ist=Decimal("25.0")) for _ in range(5)
    ]

    urteile = await valve_verdicts(db_session, kuehl + heiss, now=JETZT)

    assert urteile[heiss[0]].referenz_median_c == Decimal("25.000")
    assert {urteile[d].state for d in heiss} == {"ok"}
    assert {urteile[d].state for d in kuehl} == {"ok"}


# ---------------------------------------------------------------------------
# 5. AK 2 — ein echter Fall faellt nicht mit heraus
# ---------------------------------------------------------------------------


async def test_ak2_echter_fall_bleibt_im_warmen_haus_sichtbar(
    db_session: AsyncSession, raumtyp_id: int
) -> None:
    """Das ganze Haus 5 K hoeher, ein Zimmer zusaetzlich: wird gemeldet.

    **Die wichtigere Richtung.** Ein Filter, der zu viel filtert, ist
    schlimmer als keiner: er spiegelt Sicherheit vor. Dieser Test hebt alle
    Zimmer um 5 K an — Hochsommer, Heizperiode, was auch immer — und prueft,
    dass der eine echte Fall trotzdem heraussticht.
    """
    for _ in range(5):
        await _zimmer_mit_geraet(db_session, raumtyp_id, ist=Decimal("25.0"))
    abgefallen = await _zimmer_mit_geraet(db_session, raumtyp_id, ist=Decimal("29.0"))

    v = (await valve_verdicts(db_session, [abgefallen], now=JETZT))[abgefallen]

    assert v.state == "zimmer_zu_warm"
    assert v.referenz_median_c == Decimal("25.000")
    assert v.referenz_delta_k == Decimal("4.000")


# ---------------------------------------------------------------------------
# 6. T6 — die Messung vom 08.10. als Testwand
# ---------------------------------------------------------------------------
#
# Nachgebaut sind die **Aggregate** der T0-Messung, nicht die 46 einzelnen
# Zimmertemperaturen — die liegen nicht vor. Gemessen wurde:
#
#     median_unbelegt 21.7 | zimmer_unbelegt 44 | heute_gemeldet 15 |
#     mit_relativ_uebrig 1
#
# Uebrig blieb allein 102/406 mit ``ueber_median`` **genau 3,0**. Daraus kam
# die Entscheidung fuer 3,5 statt 3,0: die Vorgabe braucht Luft zum
# knappsten gemessenen Fall.
#
# Der Nachbau: 30 Zimmer auf 21,7 °C (3,7 K ueber Soll 18, also absolut
# **nicht** auffaellig), 15 Zimmer auf 23,5 °C (5,5 K darueber, absolut
# auffaellig) und eines auf 24,7 °C — das ist 21,7 + 3,0, also der Fall
# 102/406. Der Median ueber alle Messwerte bleibt dabei 21,7, weil die
# kuehlen 30 Zimmer die Mitte halten (30 von 46 ist unter der 50-%-Grenze
# aus G4).


async def _datenstand_0810(session: AsyncSession, raumtyp_id: int) -> tuple[list[int], int]:
    """Der nachgebaute Datenstand. Gibt (absolut auffaellige, der knappe Fall)."""
    for _ in range(30):
        await _zimmer_mit_geraet(session, raumtyp_id, ist=Decimal("21.7"))
    absolut = [
        await _zimmer_mit_geraet(session, raumtyp_id, ist=Decimal("23.5")) for _ in range(15)
    ]
    knapp = await _zimmer_mit_geraet(session, raumtyp_id, ist=Decimal("24.7"))
    return absolut, knapp


async def test_t6_mit_35_bleibt_nichts_uebrig(
    db_session: AsyncSession, raumtyp_id: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Der Datenstand vom 08.10. mit der gewaehlten Vorgabe: **0 Meldungen**.

    16 Geraete sind absolut zu warm — das waeren die 14 bis 15 Meldungen,
    die der Hotelier gesehen hat. Mit dem relativen Kriterium bei 3,5 K
    bleibt **keines** uebrig, und das deckt sich mit der Messung: AK 1 sagt
    "bei ausgeschaltetem Kessel hoechstens 0-1".

    Und der Median wird mitgeprueft. Ohne diese Zeile waere der Test auch
    gruen, wenn die Referenz ganz woanders laege — zum Beispiel weil ein
    anderer Test Messwerte im Fenster hinterlassen hat.
    """
    _delta(monkeypatch, ROOM_REL_DELTA_K="3.5")
    absolut, knapp = await _datenstand_0810(db_session, raumtyp_id)

    urteile = await valve_verdicts(db_session, [*absolut, knapp], now=JETZT)

    assert urteile[knapp].referenz_median_c == Decimal("21.700")
    assert {v.state for v in urteile.values()} == {"ok"}
    # Alle 16 sind absolut zu warm — das steht im Verdict, auch ohne
    # Hinweis. Sonst saehe die Lage aus wie "nichts gemessen".
    assert all(urteile[d].referenz_delta_k is not None for d in [*absolut, knapp])
    assert urteile[knapp].referenz_delta_k == Decimal("3.000")


async def test_t6_mit_30_bleibt_genau_einer_uebrig(
    db_session: AsyncSession, raumtyp_id: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Derselbe Datenstand mit 3,0 K: **genau einer**, und zwar der knappe.

    Das ist die Messung vom 08.10. (``mit_relativ_uebrig 1``) und zugleich
    die Begruendung fuer die Vorgabe 3,5: bei 3,0 haengt das Kriterium
    exakt auf einem Wert, von dem wir wissen, dass er vorkommt. Eine
    Schwelle, die einen bekannten Fall genau trifft, ist keine Schwelle,
    sondern ein Zufall.

    Wer die Vorgabe wieder auf 3,0 senken will, bekommt hier die Zahl dazu.
    """
    _delta(monkeypatch, ROOM_REL_DELTA_K="3.0")
    absolut, knapp = await _datenstand_0810(db_session, raumtyp_id)

    urteile = await valve_verdicts(db_session, [*absolut, knapp], now=JETZT)

    gemeldet = [d for d, v in urteile.items() if v.state == "zimmer_zu_warm"]
    assert gemeldet == [knapp]
    assert {urteile[d].state for d in absolut} == {"ok"}
