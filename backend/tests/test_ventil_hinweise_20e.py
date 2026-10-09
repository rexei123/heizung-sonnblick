"""Sprint 20e T7 + T10 — Regel 3 und 3b, die Ersatz-Melder fuer Layer 4.

**Warum diese Regeln nicht optional sind.** 20e T4 hat Engine-Layer 4 fuer
Geraete mit Montage-Nachweis stillgelegt — also fuer genau die Geraete, bei
denen er haette anschlagen sollen. Ein montiertes, belegt nachgewiesenes
Geraet, das spaeter tatsaechlich abfaellt, erkennt Layer 4 nicht mehr. Das
war der bewusst eingegangene Preis der Entscheidung vom 07.10.2026, und
diese beiden Regeln sind der Ersatz.

Der Ersatz misst die **Wirkung** statt der Mechanik (§5.76), denn der
Backplate-Taster bleibt unzuverlaessig:

- **Regel 3b** — ein Ventil ohne Kopf steht voll offen, das Zimmer wird
  also **heiss**, nicht kalt. Das ist ohne Taster messbar.
- **Regel 3** — die Gegenrichtung: Sollwert deutlich ueber Ist, Ventil ueber
  das ganze Fenster zu.

Geprueft wird in drei Gruppen:

1. **Die Bedingungen an ihren Grenzen**, mit Datenbank. Dazu gehoert die
   Vollstaendigkeit des Fensters: ein einziger Messwert, der die Bedingung
   nicht erfuellt, faellt das ganze Urteil — sonst waere ein
   Aufheiz-Peak nach der Nachtabsenkung ein Befund.
2. **Die Ausschliesslichkeit beider Regeln.** Sie koennen nicht zugleich
   zutreffen, der Code braucht also keine Vorrangregel. Das ist eine
   Eigenschaft, die man festhalten muss, sonst wird die Reihenfolge der
   Abfragen im Code zu einer stillen Entscheidung.
3. **Der Start-Validator**, ohne Datenbank.

DB-Tests skippen ohne ``TEST_DATABASE_URL`` (§5.50).
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
import pytest_asyncio
from pydantic import ValidationError
from sqlalchemy import delete as sa_delete
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from heizung.config import Settings, get_settings
from heizung.models.device import Device
from heizung.models.enums import DeviceKind, DeviceVendor, HeatingZoneKind
from heizung.models.heating_zone import HeatingZone
from heizung.models.room import Room
from heizung.models.room_type import RoomType
from heizung.models.sensor_reading import SensorReading
from heizung.schemas.device import DeviceRead
from heizung.services.valve_health import (
    VALVE_MIN_SAMPLES,
    ValveState,
    valve_schwellen,
    valve_verdicts,
)

TEST_DB_URL = os.environ.get("TEST_DATABASE_URL")
SKIP_REASON = "TEST_DATABASE_URL nicht gesetzt — DB-Tests brauchen Postgres"

EUI_PREFIX = "7e14a020"
# Eigenes Praefix fuer die Referenz-Zimmer, damit ``_purge`` sie findet.
# ``room.number`` ist VARCHAR(20) (§5.49): 4 + 8 Hex = 12 Zeichen.
RAUM_PREFIX = "v3b-"
JETZT = datetime(2026, 10, 7, 12, 0, 0, tzinfo=UTC)

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Fixtures
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
    # Die Referenz-Zimmer aus ``_referenz_zimmer`` muessen mit weg, sonst
    # bildet der naechste Lauf seinen Median ueber Leichen: die Referenz in
    # ``valve_health`` ist hausweit und sieht jede Zeile im Fenster, auch
    # fremde (§5.39).
    await session.execute(
        sa_delete(HeatingZone).where(
            HeatingZone.room_id.in_(select(Room.id).where(Room.number.like(f"{RAUM_PREFIX}%")))
        )
    )
    await session.execute(sa_delete(Room).where(Room.number.like(f"{RAUM_PREFIX}%")))
    await session.execute(sa_delete(RoomType).where(RoomType.name.like(f"{RAUM_PREFIX}%")))


async def _device(session: AsyncSession) -> int:
    device = Device(
        dev_eui=f"{EUI_PREFIX}{uuid.uuid4().hex[:8]}",
        kind=DeviceKind.THERMOSTAT,
        vendor=DeviceVendor.MCLIMATE,
        model="vicki",
    )
    session.add(device)
    await session.flush()
    return device.id


async def _fenster(
    session: AsyncSession,
    device_id: int,
    *,
    soll: Decimal,
    ist: Decimal,
    ventil: int | None,
    anzahl: int = VALVE_MIN_SAMPLES,
) -> None:
    """``anzahl`` gleichartige Messwerte im Fenster, 10 min auseinander.

    Zehn Minuten ist die regulaere Keep-alive-Kadenz der Vicki; sechs Werte
    decken damit eine Stunde ab und liegen vollstaendig im 2-h-Fenster.
    """
    for i in range(anzahl):
        session.add(
            SensorReading(
                time=JETZT - timedelta(minutes=10 * (i + 1)),
                device_id=device_id,
                fcnt=i + 1,
                setpoint=soll,
                temperature=ist,
                valve_position=ventil,
            )
        )
    await session.flush()


async def _referenz_zimmer(
    session: AsyncSession,
    *,
    ist: Decimal,
    anzahl: int = 5,
) -> None:
    """``anzahl`` nicht belegte Zimmer mit je einem Geraet auf ``ist`` Grad.

    **Warum 3b-Tests das brauchen.** Seit 20e-b verlangt Regel 3b zwei
    Bedingungen: ueber dem Sollwert **und** ueber vergleichbaren Zimmern.
    Die Referenz ist hausweit und entsteht aus Zimmern — ein Geraet ohne
    Zimmer (wie ``_device`` es anlegt) traegt nichts dazu bei. Ohne diese
    Fixture gibt es keine Referenzmenge, die Kette landet auf Stufe 3
    ("keine") und **kein** 3b-Hinweis kommt. Das ist richtig so und war der
    Grund, warum die vier 3b-Tests mit 20e-b angepasst werden mussten.

    ``anzahl`` ist die Vorgabe von ``REF_MIN_ROOMS`` (5). Alle Geraete
    melden denselben Wert, der Median ist damit exakt ``ist`` — die Tests
    rechnen also mit einer Zahl und nicht mit einer Schaetzung.

    Zimmer sind im Modell-Default ``vacant``, die Kette landet also auf
    Stufe 1 (``unbelegt``). Wer Stufe 2 pruefen will, setzt ``status``
    nachtraeglich.
    """
    suffix = uuid.uuid4().hex[:8]
    raumtyp = RoomType(name=f"{RAUM_PREFIX}rt-{suffix[:4]}")
    session.add(raumtyp)
    await session.flush()

    for i in range(anzahl):
        room = Room(number=f"{RAUM_PREFIX}{suffix[:4]}{i:02d}", room_type_id=raumtyp.id)
        session.add(room)
        await session.flush()
        # ``kind`` ist NOT NULL ohne Default (§5.49).
        zone = HeatingZone(room_id=room.id, kind=HeatingZoneKind.BEDROOM, name="z0")
        session.add(zone)
        await session.flush()
        device = Device(
            dev_eui=f"{EUI_PREFIX}{suffix[:6]}{i:02d}",
            kind=DeviceKind.THERMOSTAT,
            vendor=DeviceVendor.MCLIMATE,
            model="vicki",
            heating_zone_id=zone.id,
        )
        session.add(device)
        await session.flush()
        # Soll gleich Ist: diese Zimmer sollen die Referenz bilden und
        # selbst kein Urteil tragen.
        await _fenster(session, device.id, soll=ist, ist=ist, ventil=50)


async def _urteil(session: AsyncSession, device_id: int) -> ValveState:
    return (await valve_verdicts(session, [device_id], now=JETZT))[device_id].state


# ---------------------------------------------------------------------------
# 1. Regel 3 — Ventil klemmt zu
# ---------------------------------------------------------------------------


async def test_regel3_soll_weit_ueber_ist_und_ventil_zu(db_session: AsyncSession) -> None:
    """Der Fall: die Engine heizt, das Zimmer wird nicht warm.

    Soll 22, Ist 18 — also 4 K Abstand bei einer Schwelle von 3 K — und das
    Ventil meldet ueber das ganze Fenster 0 %.
    """
    device_id = await _device(db_session)
    await _fenster(db_session, device_id, soll=Decimal("22.0"), ist=Decimal("18.0"), ventil=0)

    assert await _urteil(db_session, device_id) == "ventil_klemmt_zu"


async def test_regel3_an_der_schwelle(db_session: AsyncSession) -> None:
    """Genau 3 K loest aus, 2.9 K nicht. Die Grenze ist inklusiv.

    Die 0.1-K-Schritte sind der eigentliche Test: ein ``>`` statt ``>=``
    waere mit runden Werten allein nicht zu unterscheiden.
    """
    knapp_drueber = await _device(db_session)
    await _fenster(db_session, knapp_drueber, soll=Decimal("21.0"), ist=Decimal("18.0"), ventil=0)
    knapp_drunter = await _device(db_session)
    await _fenster(db_session, knapp_drunter, soll=Decimal("20.9"), ist=Decimal("18.0"), ventil=0)

    assert await _urteil(db_session, knapp_drueber) == "ventil_klemmt_zu"
    assert await _urteil(db_session, knapp_drunter) == "ok"


async def test_regel3_offenes_ventil_ist_kein_befund(db_session: AsyncSession) -> None:
    """Dasselbe Temperaturbild, aber das Ventil arbeitet.

    Ohne diesen Test waere die Ventil-Bedingung weglassbar, und jedes
    aufheizende Zimmer traege den Hinweis.
    """
    device_id = await _device(db_session)
    await _fenster(db_session, device_id, soll=Decimal("22.0"), ist=Decimal("18.0"), ventil=60)

    assert await _urteil(db_session, device_id) == "ok"


async def test_regel3_ohne_ventilwerte_kein_befund(db_session: AsyncSession) -> None:
    """**``bool_and`` ueber lauter NULL ist NULL, nicht wahr.**

    Ein Geraet, das im ganzen Fenster keine Ventilstellung gemeldet hat
    (alter Codec, Reply-Frames), darf keinen Hinweis bekommen — wir wissen
    nichts ueber sein Ventil. Der Code prueft deshalb ``is True`` und nicht
    die Wahrheit des Werts; ohne diesen Test waere der Unterschied nicht
    bemerkbar, denn ``if None:`` ist ebenfalls falsch — aber erst, wenn
    jemand die Bedingung umdreht, faellt genau dieser Fall auf.

    Regel 3b bleibt davon unberuehrt: sie braucht die Ventilstellung nicht.
    """
    device_id = await _device(db_session)
    await _fenster(db_session, device_id, soll=Decimal("22.0"), ist=Decimal("18.0"), ventil=None)

    assert await _urteil(db_session, device_id) == "ok"


# ---------------------------------------------------------------------------
# 2. Regel 3b — Zimmer zu warm
# ---------------------------------------------------------------------------


async def test_regel3b_zimmer_deutlich_zu_warm(db_session: AsyncSession) -> None:
    """**Der Ersatz fuer Layer 4.** Ein Ventil ohne Kopf steht voll offen.

    Soll 18, Ist 24 — 6 K bei einer Schwelle von 5 K. Das ist das Bild
    eines abgenommenen Thermostatkopfs: der Stift wird von der Feder
    herausgedrueckt, das Ventil steht offen, das Zimmer heizt durch.
    """
    await _referenz_zimmer(db_session, ist=Decimal("20.0"))
    device_id = await _device(db_session)
    await _fenster(db_session, device_id, soll=Decimal("18.0"), ist=Decimal("24.0"), ventil=0)

    verdict = (await valve_verdicts(db_session, [device_id], now=JETZT))[device_id]
    assert verdict.state == "zimmer_zu_warm"
    # Beide Abstaende, benannt: 6 K ueber Soll und 4 K ueber der Referenz.
    assert verdict.delta_k == Decimal("6.00")
    assert verdict.referenz == "unbelegt"
    assert verdict.referenz_median_c == Decimal("20.000"), (
        "Median verschoben — fremde Messwerte im Fenster? Die Referenz ist hausweit."
    )
    assert verdict.referenz_delta_k == Decimal("4.000")


async def test_regel3b_ventilstellung_ist_keine_bedingung(db_session: AsyncSession) -> None:
    """**Der Hauptfall, und er haette verloren gehen koennen.**

    Naheliegend waere "Hinweis nur, wenn das Ventil auch offen gemeldet
    wird". Ein abgenommener Kopf meldet aber die Motorposition, die er
    zuletzt angefahren hat — stand der Sollwert niedrig, meldet er
    **geschlossen**, waehrend das Ventil mechanisch voll offen ist.

    Dieser Test faehrt genau diese Lage: Ventil meldet 0 %, Zimmer ist 6 K
    zu warm. Eine Ventil-Bedingung haette den Melder gegen seinen eigenen
    Zweck abgedichtet.
    """
    await _referenz_zimmer(db_session, ist=Decimal("20.0"))
    device_id = await _device(db_session)
    await _fenster(db_session, device_id, soll=Decimal("18.0"), ist=Decimal("24.0"), ventil=0)

    assert await _urteil(db_session, device_id) == "zimmer_zu_warm"


async def test_regel3b_an_der_schwelle(db_session: AsyncSession) -> None:
    """5 K loest aus, 4.9 K nicht — und 4.9 K ist **nicht** Regel 3.

    Der Zwischenbereich gehoert keiner Regel: ein Zimmer, das 4 K ueber dem
    Sollwert liegt, ist warm, aber im Rahmen. Die Schwelle liegt hoeher als
    bei Regel 3, weil der interne Vicki-Sensor in diese Richtung verzerrt
    (§5.27).
    """
    # Referenz bewusst **tief** (18 Grad), damit hier die absolute Schwelle
    # entscheidet und nicht die relative: 23 liegt 5 K ueber dem Median,
    # 22,9 noch 4,9 K. Beide erfuellen die relative Bedingung (>= 3,5 K) —
    # der Unterschied liegt also allein am Sollwert-Abstand, und genau das
    # soll dieser Test pruefen.
    await _referenz_zimmer(db_session, ist=Decimal("18.0"))
    knapp_drueber = await _device(db_session)
    await _fenster(db_session, knapp_drueber, soll=Decimal("18.0"), ist=Decimal("23.0"), ventil=50)
    knapp_drunter = await _device(db_session)
    await _fenster(db_session, knapp_drunter, soll=Decimal("18.0"), ist=Decimal("22.9"), ventil=50)

    assert await _urteil(db_session, knapp_drueber) == "zimmer_zu_warm"
    assert await _urteil(db_session, knapp_drunter) == "ok"


# ---------------------------------------------------------------------------
# 3. Das Fenster vollstaendig, nicht im Mittel
# ---------------------------------------------------------------------------


async def test_ein_abweichender_messwert_faellt_das_urteil(db_session: AsyncSession) -> None:
    """**Die Formulierung aus dem Brief, als Test.**

    Fuenf Messwerte zeigen das Bild "Ventil klemmt", einer nicht. Kein
    Hinweis.

    Der Grund ist der Aufheiz-Peak nach einer Nachtabsenkung: dort steht
    der Sollwert kurz weit ueber dem Ist, und das Ventil braucht einen
    Moment, bis es oeffnet. Ein Mittelwert haette daraus einen Befund
    gemacht — jede Nacht, in jedem Zimmer.
    """
    device_id = await _device(db_session)
    await _fenster(
        db_session,
        device_id,
        soll=Decimal("22.0"),
        ist=Decimal("18.0"),
        ventil=0,
        anzahl=VALVE_MIN_SAMPLES,
    )
    # Ein einziger Messwert mit offenem Ventil, juenger als die anderen.
    db_session.add(
        SensorReading(
            time=JETZT - timedelta(minutes=5),
            device_id=device_id,
            fcnt=99,
            setpoint=Decimal("22.0"),
            temperature=Decimal("18.0"),
            valve_position=40,
        )
    )
    await db_session.flush()

    assert await _urteil(db_session, device_id) == "ok"


async def test_zu_wenige_messwerte_sind_unbekannt(db_session: AsyncSession) -> None:
    """``unbekannt`` ist nicht ``ok`` — und das ist der Punkt.

    Ein Geraet mit einem einzigen Messwert erfuellt die Bedingung formal
    "im ganzen Fenster". Ohne Mindest-Stichprobe waere jedes Geraet, das
    gerade erst wieder funkt, sofort ein Befund.

    Dass das Ergebnis ``unbekannt`` heisst und nicht ``ok``, ist ebenfalls
    Absicht: ein Geraet ohne Aussage ist kein Geraet, dessen Ventil in
    Ordnung ist.
    """
    device_id = await _device(db_session)
    await _fenster(
        db_session,
        device_id,
        soll=Decimal("22.0"),
        ist=Decimal("18.0"),
        ventil=0,
        anzahl=VALVE_MIN_SAMPLES - 1,
    )

    verdict = (await valve_verdicts(db_session, [device_id], now=JETZT))[device_id]
    assert verdict.state == "unbekannt"
    assert verdict.samples == VALVE_MIN_SAMPLES - 1


async def test_messwerte_vor_dem_fenster_zaehlen_nicht(db_session: AsyncSession) -> None:
    """Das Fenster ist 2 h. Aelteres gehoert nicht dazu.

    Ohne diese Grenze waere der Hinweis ein Dauerzustand: ein Ventil, das
    vorgestern klemmte und inzwischen laeuft, traege ihn weiter.
    """
    device_id = await _device(db_session)
    for i in range(VALVE_MIN_SAMPLES):
        db_session.add(
            SensorReading(
                time=JETZT - timedelta(hours=5, minutes=10 * i),
                device_id=device_id,
                fcnt=i + 1,
                setpoint=Decimal("22.0"),
                temperature=Decimal("18.0"),
                valve_position=0,
            )
        )
    await db_session.flush()

    assert await _urteil(db_session, device_id) == "unbekannt"


async def test_frames_ohne_temperatur_verwaessern_das_fenster_nicht(
    db_session: AsyncSession,
) -> None:
    """Reply-Frames ohne Ist-Temperatur sind fuer diese Bewertung keine Messwerte.

    Sie werden ausgefiltert, bevor ``bool_and`` sie sieht. Beides waere
    falsch: sie mitzuzaehlen wuerde die Stichprobe aufblasen, und
    ``bool_and`` ueber ihr NULL-Ergebnis wuerde das Urteil kippen.
    """
    device_id = await _device(db_session)
    await _fenster(db_session, device_id, soll=Decimal("22.0"), ist=Decimal("18.0"), ventil=0)
    for i in range(4):
        db_session.add(
            SensorReading(
                time=JETZT - timedelta(minutes=1 + i),
                device_id=device_id,
                fcnt=200 + i,
                setpoint=Decimal("22.0"),
                temperature=None,
                valve_position=None,
            )
        )
    await db_session.flush()

    verdict = (await valve_verdicts(db_session, [device_id], now=JETZT))[device_id]
    assert verdict.state == "ventil_klemmt_zu"
    assert verdict.samples == VALVE_MIN_SAMPLES, "die Reply-Frames zaehlen nicht mit"


# ---------------------------------------------------------------------------
# 4. Beide Regeln schliessen sich aus
# ---------------------------------------------------------------------------


async def test_beide_regeln_koennen_nicht_zugleich_zutreffen(db_session: AsyncSession) -> None:
    """**Deshalb braucht der Code keine Vorrangregel.**

    ``soll >= ist + 3`` und ``ist >= soll + 5`` sind bei positiven Deltas
    unvereinbar. Der Test faehrt beide Richtungen durch und prueft, dass
    jedes Geraet genau ein Urteil hat — ohne ihn waere die Reihenfolge der
    beiden ``elif`` im Code eine stille Entscheidung, die erst auffaellt,
    wenn jemand ein Delta auf 0 stellt (was der Start-Validator verbietet).
    """
    await _referenz_zimmer(db_session, ist=Decimal("20.0"))
    kalt = await _device(db_session)
    await _fenster(db_session, kalt, soll=Decimal("22.0"), ist=Decimal("18.0"), ventil=0)
    warm = await _device(db_session)
    await _fenster(db_session, warm, soll=Decimal("18.0"), ist=Decimal("24.0"), ventil=0)

    verdicts = await valve_verdicts(db_session, [kalt, warm], now=JETZT)
    assert verdicts[kalt].state == "ventil_klemmt_zu"
    assert verdicts[warm].state == "zimmer_zu_warm"
    # Und die Diagnose-Zahl gehoert zum jeweiligen Urteil.
    assert verdicts[kalt].delta_k == Decimal("4.00")
    assert verdicts[warm].delta_k == Decimal("6.00")


async def test_jede_angefragte_id_bekommt_einen_eintrag(db_session: AsyncSession) -> None:
    """Ein Geraet ohne jeden Messwert fehlt nicht, es ist ``unbekannt``.

    Sonst wuerde ein fehlender Schluessel beim Aufrufer zu einem
    ``KeyError`` — oder, schlimmer, mit einem ``.get(id, "ok")`` still zu
    "in Ordnung".
    """
    ohne_werte = await _device(db_session)

    verdicts = await valve_verdicts(db_session, [ohne_werte], now=JETZT)
    assert verdicts[ohne_werte].state == "unbekannt"
    assert verdicts[ohne_werte].samples == 0


async def test_leere_liste_macht_keine_query(db_session: AsyncSession) -> None:
    """Die Geraeteliste einer leeren Seite soll nicht gegen die Hypertable gehen."""
    assert await valve_verdicts(db_session, [], now=JETZT) == {}


# ---------------------------------------------------------------------------
# 5. Schwellen und Validator — ohne Datenbank
# ---------------------------------------------------------------------------


async def test_vorgaben_sind_drei_und_fuenf_kelvin(monkeypatch: pytest.MonkeyPatch) -> None:
    """Die Vorgaben aus dem Gate, als Wachposten.

    3 K fuer Regel 3, **5 K** fuer 3b. Die Asymmetrie ist die eigentliche
    Aussage: der interne Vicki-Sensor verzerrt nur in Richtung 3b, also
    braucht diese Richtung mehr Abstand. Ein gemeinsames Delta waere
    entweder fuer 3 zu grob oder fuer 3b zu empfindlich.
    """
    for name in (
        "VALVE_STUCK_DELTA_K",
        "ROOM_TOO_WARM_DELTA_K",
        "VALVE_STUCK_OPENNESS_MAX",
        "VALVE_WINDOW_H",
    ):
        monkeypatch.delenv(name, raising=False)
    get_settings.cache_clear()

    s = valve_schwellen()
    assert s.stuck_delta_k == Decimal("3.0")
    assert s.too_warm_delta_k == Decimal("5.0")
    assert s.stuck_openness_max == 0
    assert s.window_h == 2

    get_settings.cache_clear()


@pytest.mark.parametrize(
    ("felder", "warum"),
    [
        ({"valve_stuck_delta_k": Decimal("0")}, "Delta 0 macht jedes gehaltene Zimmer zum Befund"),
        ({"valve_stuck_delta_k": Decimal("-1")}, "negatives Delta"),
        ({"room_too_warm_delta_k": Decimal("0")}, "3b-Delta 0"),
        ({"valve_stuck_openness_max": 101}, "Prozent ueber 100"),
        ({"valve_stuck_openness_max": -1}, "Prozent unter 0"),
        ({"valve_window_h": 0}, "Fenster ohne Dauer"),
    ],
)
async def test_unsinnige_schwellen_verhindern_den_start(
    felder: dict[str, object], warum: str
) -> None:
    """Start-Fehler, nicht Warnung — wie bei den anderen Schwellen.

    Beim Delta 0 haengt daran mehr als Plausibilitaet: die
    Ausschliesslichkeit der beiden Regeln gilt nur fuer positive Deltas.
    Mit 0 braeuchte der Code eine Vorrangregel, und welche es waere,
    entschiede die Reihenfolge der Abfragen.
    """
    with pytest.raises(ValidationError) as exc:
        Settings(environment="test", **felder)  # type: ignore[arg-type]
    text = str(exc.value)
    assert ("VALVE_" in text) or ("ROOM_TOO_WARM" in text), warum


async def test_schema_spiegelt_die_service_zustaende() -> None:
    """``DeviceRead.valve_state`` und ``ValveState`` muessen dieselben vier sein.

    Das Schema nutzt ein Inline-``Literal`` (damit die Schema-Schicht nicht
    von der Service-Schicht abhaengt, wie bei ``battery_state``). Der Preis
    ist eine zweite Liste, und dieser Test ist der Ausgleich dafuer: ohne
    ihn koennte ein neuer Zustand im Service entstehen, den die API nie
    ausliefert — und der Fehler faellt erst in der Oberflaeche auf.
    """
    from typing import get_args

    schema_werte = set(get_args(DeviceRead.model_fields["valve_state"].annotation))
    service_werte = set(get_args(ValveState))
    assert schema_werte == service_werte
