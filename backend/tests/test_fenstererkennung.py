"""Sprint 23 T2 — Ziele, Ausnahmen und Befund der Fenstererkennung.

Drei Dinge werden geprueft, und das zweite ist das wichtigste:

1. **Die Bytes** von ``0x45`` fuer den Betriebswert und fuer die Messung.
   Reine Funktion, keine Hardware.
2. **Die Ausnahmen.** Ergaenzung 2 des Auftrags verlangt ausdruecklich,
   dass Geraete auf „nur messen" (027, 056) und der Reserve-Pool (100)
   von Rollouts ausgenommen sind — **mit Test**. Das ist dieser Test. Vor
   Sprint 23 T2 lautete die Auswahl im Bulk-Skript „Thermostat mit Zone",
   und ein Fuehler auf „nur messen" haette ein 0x45 bekommen.
3. **Der Befund.** Das Abbruchkriterium haengt an einer einzigen Frage:
   hat die Erkennung in **unserer** Absenkung ausgeloest? Wer den
   Zeitvergleich in UTC rechnet, liegt ein bis zwei Stunden daneben und
   ordnet einen Fehlalarm um 20:30 als „ausserhalb" ein — damit waere das
   Kriterium stillschweigend ausgehebelt (§5.65).

Der 306-Verlauf vom 22.10.2026 steht als Fixture im letzten Abschnitt:
es ist der einzige belegte Fall eines echten offenen Fensters im Haus.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from heizung.models.device import Device
from heizung.models.enums import DeviceKind, DeviceVendor, HeatingZoneKind
from heizung.models.heating_zone import HeatingZone
from heizung.models.room import Room
from heizung.models.room_type import RoomType
from heizung.services.downlink_adapter import DownlinkError, ow_set_bytes
from heizung.services.fenstererkennung import (
    GRUND_AUSGEMUSTERT,
    GRUND_KEIN_THERMOSTAT,
    GRUND_NUR_MESSEN,
    GRUND_OHNE_ZONE,
    OW_DAUER_MIN_BETRIEB,
    OW_DELTA_BETRIEB,
    OW_DELTA_MESSUNG,
    Ausnahme,
    Zielgeraet,
    ausnahme_grund,
    episoden,
    in_nachtfenster,
    lade_ziele,
    nicht_gefunden,
)

DATABASE_URL = os.environ.get("DATABASE_URL")
SKIP_REASON = "DATABASE_URL nicht gesetzt - der Abfrage-Test braucht Test-DB"

ZONE = "Europe/Vienna"
WIEN = ZoneInfo(ZONE)
NACHT_START = time(20, 0)
NACHT_ENDE = time(6, 0)


def ortszeit(jahr: int, monat: int, tag: int, stunde: int, minute: int = 0) -> datetime:
    """Ein Zeitpunkt in Wiener Ortszeit, als UTC-bewusstes ``datetime``.

    **Nicht von Hand in UTC umgerechnet.** Beim ersten Entwurf stand hier
    „18:00 UTC = 20:00 Ortszeit", und das war am 25.10.2026 falsch: die
    Umstellung auf Winterzeit ist in der Nacht zum 26.10., am 25.10. gilt
    also schon MEZ (UTC+1). Sechs Tests sind daran gefallen — am Code lag
    es nicht.

    Die Lehre steht in §5.65 und §5.74 und gilt fuer Tests genauso wie
    fuer Produktionscode: eine Uhrzeit ohne ausdrueckliche Zone ist eine
    Rechnung, die jemand im Kopf macht. ``ZoneInfo`` macht sie richtig,
    auch am Umstellungstag.
    """
    return datetime(jahr, monat, tag, stunde, minute, tzinfo=WIEN)


# ---------------------------------------------------------------------------
# 1. Die Bytes
# ---------------------------------------------------------------------------


def test_betriebswert_ergibt_die_erwarteten_bytes() -> None:
    """1,0 °C und 10 min -> ``45 01 02 0a``.

    Byte 2 ist die Dauer in 5-Minuten-Schritten (10/5 = 2), Byte 3 das
    Delta mal zehn (1,0 -> 10 = 0x0a). Die Erwartung kommt aus der
    Vendor-Doku und nicht aus dem Lauf des Codes (§5.79): Quelle ist
    ``docs/vendor/mclimate-vicki/01-open-window-detection.md``.
    """
    assert ow_set_bytes(True, OW_DAUER_MIN_BETRIEB, OW_DELTA_BETRIEB).hex() == "4501020a"


def test_messwert_ergibt_die_erwarteten_bytes() -> None:
    """0,2 °C ist das Minimum der Spanne -> Byte 3 = 2."""
    assert ow_set_bytes(True, OW_DAUER_MIN_BETRIEB, OW_DELTA_MESSUNG).hex() == "45010202"


def test_ausschalten_setzt_byte_1_auf_null() -> None:
    """Der Rueckweg des Abbruchkriteriums.

    Dass er derselbe Befehl ist, ist der Grund, warum das Kriterium
    ueberhaupt so scharf sein kann: kein Neustart, keine
    Datenbankaenderung.
    """
    assert ow_set_bytes(False, OW_DAUER_MIN_BETRIEB, OW_DELTA_BETRIEB).hex() == "4500020a"


def test_delta_unter_dem_minimum_wird_abgewiesen() -> None:
    with pytest.raises(DownlinkError):
        ow_set_bytes(True, 10, Decimal("0.05"))


def test_dauer_ohne_fuenfer_schritt_wird_abgewiesen() -> None:
    with pytest.raises(DownlinkError):
        ow_set_bytes(True, 7, OW_DELTA_BETRIEB)


# ---------------------------------------------------------------------------
# 2. Die Ausnahmen (Ergaenzung 2 des Auftrags)
# ---------------------------------------------------------------------------


def _geraet(
    *,
    measure_only: bool = False,
    zone_id: int | None = 7,
    retired: bool = False,
    kind: DeviceKind = DeviceKind.THERMOSTAT,
) -> Device:
    """Ein Geraete-Objekt ohne Datenbank — ``ausnahme_grund`` ist rein."""
    return Device(
        dev_eui=f"deadbeef{uuid.uuid4().hex[:8]}",
        label="Pruefgeraet",
        kind=kind,
        measure_only=measure_only,
        heating_zone_id=zone_id,
        retired_at=datetime.now(tz=UTC) if retired else None,
    )


def test_nur_messen_ist_ausgenommen() -> None:
    """Vicki 027 und 056: Fuehler im Raum, bekommen keine Befehle (S7).

    Das ist der Fall, den Ergaenzung 2 ausdruecklich nennt. Ein 0x45 an
    ein solches Geraet waere nicht nur sinnlos — es widerspricht der
    Rolle, und die Rolle ist der Grund, warum das Drehrad dort gesperrt
    ist.
    """
    assert ausnahme_grund(_geraet(measure_only=True)) == GRUND_NUR_MESSEN


def test_reserve_pool_ist_ausgenommen() -> None:
    """Geraet 100 liegt ohne Zone im Lager."""
    assert ausnahme_grund(_geraet(zone_id=None)) == GRUND_OHNE_ZONE


def test_ausgemustertes_geraet_ist_ausgenommen() -> None:
    """Und zwar vor allen anderen Gruenden — es ist nicht mehr da."""
    assert ausnahme_grund(_geraet(retired=True)) == GRUND_AUSGEMUSTERT
    # Auch wenn es noch eine Zone traegt und nicht auf „nur messen" steht.
    assert ausnahme_grund(_geraet(retired=True, measure_only=True)) == GRUND_AUSGEMUSTERT


def test_relais_ist_ausgenommen() -> None:
    """Ein Relais misst nicht und hat kein Drehrad."""
    assert ausnahme_grund(_geraet(kind=DeviceKind.RELAY)) == GRUND_KEIN_THERMOSTAT


def test_montiertes_thermostat_ist_ein_ziel() -> None:
    assert ausnahme_grund(_geraet()) is None


def test_jeder_grund_hat_einen_test() -> None:
    """Spiegel-Test: eine neue Ausnahme ohne Test faellt hier auf.

    Ohne ihn waere die Ergaenzung-2-Zusicherung an den Fleiss des
    naechsten Durchgangs gebunden — und eine Zusicherung, die niemand
    prueft, ist eine Behauptung (§5.68).
    """
    geprueft = {
        GRUND_NUR_MESSEN,
        GRUND_OHNE_ZONE,
        GRUND_AUSGEMUSTERT,
        GRUND_KEIN_THERMOSTAT,
    }
    aus_modul = {
        wert
        for name, wert in vars(
            __import__("heizung.services.fenstererkennung", fromlist=["x"])
        ).items()
        if name.startswith("GRUND_") and isinstance(wert, str)
    }
    assert aus_modul == geprueft, f"ungeprueft: {aus_modul - geprueft}"


def test_nicht_gefundene_bezeichnung_wird_gemeldet() -> None:
    """Ein Tippfehler darf nicht als „alles ausgenommen" durchgehen."""
    ziele = [
        Zielgeraet(
            device_id=1,
            dev_eui="deadbeef00000001",
            label="A",
            firmware_version="4.5",
            zone_name="Schlafzimmer",
            room_number="306",
        )
    ]
    ausnahmen = [Ausnahme(dev_eui="deadbeef00000002", label="B", grund=GRUND_NUR_MESSEN)]

    assert nicht_gefunden(["306 Schlafzimmer"], ziele, ausnahmen) == []
    assert nicht_gefunden(["B"], ziele, ausnahmen) == []
    assert nicht_gefunden(["305 Schlafzimmer"], ziele, ausnahmen) == ["305 Schlafzimmer"]


# ---------------------------------------------------------------------------
# 3. Der Befund
# ---------------------------------------------------------------------------


def test_nachtfenster_rechnet_in_ortszeit() -> None:
    """20:00–06:00 ist Wanduhrzeit des Hauses, nicht UTC.

    Am 25.10.2026 gilt in Wien bereits MEZ (UTC+1) — die Umstellung ist
    in der Nacht zum 26.10. 20:30 Ortszeit sind also 19:30 UTC; wer die
    UTC-Wanduhr vergleicht, sieht 19:30 und urteilt dennoch richtig, am
    Vortag mit MESZ aber nicht. Genau so wird ein Abbruchkriterium
    stillschweigend ausgehebelt — und genau diese Rechnung habe ich im
    ersten Entwurf dieses Tests selbst falsch gemacht (siehe
    ``ortszeit``).
    """
    drin = ortszeit(2026, 10, 25, 20, 30)
    draussen = ortszeit(2026, 10, 25, 18, 30)

    assert in_nachtfenster(drin, start=NACHT_START, ende=NACHT_ENDE, zone=ZONE) is True
    assert in_nachtfenster(draussen, start=NACHT_START, ende=NACHT_ENDE, zone=ZONE) is False


def test_nachtfenster_ueber_mitternacht() -> None:
    """Das Fenster hat zwei Teile, und 03:00 liegt im zweiten."""
    nachts = ortszeit(2026, 10, 25, 3, 0)
    morgens = ortszeit(2026, 10, 25, 7, 0)
    assert in_nachtfenster(nachts, start=NACHT_START, ende=NACHT_ENDE, zone=ZONE) is True
    assert in_nachtfenster(morgens, start=NACHT_START, ende=NACHT_ENDE, zone=ZONE) is False


class _Messwert:
    """Doppelgaenger fuer ``SensorReading`` — nur die drei Felder.

    Ein vollstaendiges ORM-Objekt braeuchte eine Datenbank, und
    ``episoden`` liest nur ``device_id``, ``time``, ``temperature`` und
    ``open_window``. Der Doppelgaenger ist **vollstaendig** fuer das, was
    die Funktion anfasst — ein duennerer waere die Falle aus 24e.
    """

    def __init__(
        self,
        device_id: int,
        zeit: datetime,
        temperatur: Decimal | None,
        offen: bool | None,
    ) -> None:
        self.device_id = device_id
        self.time = zeit
        self.temperature = temperatur
        self.open_window = offen


def _reihe(
    beginn: datetime,
    werte: list[tuple[int, Decimal | None, bool | None]],
    *,
    schritt: timedelta = timedelta(minutes=5),
) -> list[_Messwert]:
    return [
        _Messwert(1, beginn + i * schritt, temp, offen)
        for i, (_minute, temp, offen) in enumerate(werte)
    ]


def test_episode_wird_zusammengefasst_und_eingeordnet() -> None:
    beginn = ortszeit(2026, 10, 25, 6, 0)
    werte = _reihe(
        beginn,
        [
            (0, Decimal("25.0"), False),
            (5, Decimal("24.0"), False),
            (10, Decimal("22.0"), True),
            (15, Decimal("20.5"), True),
            (20, Decimal("21.0"), False),
        ],
    )
    gefunden = episoden(
        werte,
        nacht_start=NACHT_START,
        nacht_ende=NACHT_ENDE,
        zone=ZONE,  # type: ignore[arg-type]
    )
    assert len(gefunden) == 1
    e = gefunden[0]
    assert e.ende - e.beginn == timedelta(minutes=5)
    # 06:10 Ortszeit — die Absenkung endet um 06:00, also ausserhalb.
    assert e.in_absenkung is False
    assert e.trifft_abbruchkriterium is False
    # Zehn Minuten vor dem Beginn stand es bei 25,0; beim Beginn 22,0.
    assert e.temp_davor == Decimal("25.0")
    assert e.temp_beginn == Decimal("22.0")
    assert e.abfall_k == Decimal("3.0")


def test_ausloesung_in_der_absenkung_trifft_das_abbruchkriterium() -> None:
    """Der Fall, der die Testwoche beendet.

    20:05 Ortszeit, fuenf Minuten nach Beginn der Absenkung. Die Vorgabe
    des Betreibers ist ausdruecklich: „loest die Erkennung um 20:05 aus,
    ist das ein Treffer des Kriteriums und kein Zufall". Wer die
    Absenkung erst ab 22:00 rechnet, haette zwei Stunden, in denen ein
    Fehlalarm als „unklar" durchgeht.
    """
    beginn = ortszeit(2026, 10, 25, 20, 0)
    werte = _reihe(
        beginn,
        [
            (0, Decimal("22.0"), False),
            (5, Decimal("20.5"), True),
            (10, Decimal("20.0"), True),
        ],
    )
    gefunden = episoden(
        werte,
        nacht_start=NACHT_START,
        nacht_ende=NACHT_ENDE,
        zone=ZONE,  # type: ignore[arg-type]
    )
    assert len(gefunden) == 1
    assert gefunden[0].in_absenkung is True
    assert gefunden[0].trifft_abbruchkriterium is True


def test_zeile_ohne_das_feld_beendet_keine_episode() -> None:
    """``NULL`` sagt nichts ueber das Fenster.

    Eine reine Befehlsantwort fuehrt ``open_window`` nicht. Sie als „zu"
    auszulegen wuerde eine Episode in zwei zerlegen — und aus einem
    Fehlalarm zwei machen. Dieselbe Regel wie bei der Kindersicherung
    (24c) und beim Backplate-Zustand.
    """
    beginn = ortszeit(2026, 10, 25, 12, 0)
    werte = _reihe(
        beginn,
        [
            (0, Decimal("22.0"), True),
            (5, None, None),
            (10, Decimal("21.0"), True),
            (15, Decimal("22.0"), False),
        ],
    )
    gefunden = episoden(
        werte,
        nacht_start=NACHT_START,
        nacht_ende=NACHT_ENDE,
        zone=ZONE,  # type: ignore[arg-type]
    )
    assert len(gefunden) == 1, "NULL hat die Episode zerlegt"
    assert gefunden[0].ende - gefunden[0].beginn == timedelta(minutes=10)


def test_noch_offene_episode_wird_gezeigt() -> None:
    """Ein gerade laufender Fehlalarm ist der dringendere Fall."""
    beginn = ortszeit(2026, 10, 25, 20, 10)
    werte = _reihe(beginn, [(0, Decimal("21.0"), True), (5, Decimal("20.0"), True)])
    gefunden = episoden(
        werte,
        nacht_start=NACHT_START,
        nacht_ende=NACHT_ENDE,
        zone=ZONE,  # type: ignore[arg-type]
    )
    assert len(gefunden) == 1
    assert gefunden[0].in_absenkung is True


def test_ohne_ausloesung_keine_episode() -> None:
    beginn = ortszeit(2026, 10, 25, 12, 0)
    werte = _reihe(beginn, [(0, Decimal("22.0"), False), (5, Decimal("21.9"), False)])
    assert (
        episoden(werte, nacht_start=NACHT_START, nacht_ende=NACHT_ENDE, zone=ZONE)  # type: ignore[arg-type]
        == []
    )


# ---------------------------------------------------------------------------
# Der Realdaten-Fall: Zimmer 306 am 22.10.2026
# ---------------------------------------------------------------------------


def test_306_verlauf_vom_22_10_wird_als_echtes_fenster_eingeordnet() -> None:
    """Der einzige belegte Fall eines offenen Fensters im Haus.

    Beobachtung des Betreibers: am 22.10. gegen 06:00 Ortszeit wurde in
    306 gelueftet, Schlafzimmer von 25 °C auf 18,5 °C in rund 30 Minuten
    (≈ 0,217 K/min).

    **Was dieser Test prueft und was nicht.** Er prueft die Einordnung:
    ein Abfall dieser Groesse ab 06:00 Ortszeit liegt **ausserhalb** der
    Absenkung (die endet um 06:00) und trifft das Abbruchkriterium
    deshalb nicht. Er prueft **nicht**, ob die Geraeteerkennung dabei
    ausgeloest haette — das ist unbelegt, weil die Hersteller-Doku die
    Bezugsgroesse des Deltas offenlaesst (Stand 22.10.2026), und es wird
    durch die Messung T2.5 entschieden und nicht durch Lesen.
    """
    # Die Reihe beginnt eine Viertelstunde **vor** dem Lueften. Ohne
    # diese Vorgeschichte gibt es keinen Wert „zehn Minuten davor", und
    # der Abfall — die Zahl, die den Befund traegt — bliebe leer. Im Haus
    # stand das Zimmer stundenlang bei 25 °C; die Fixture bildet das ab
    # statt beim Ereignis anzufangen.
    start = ortszeit(2026, 10, 22, 5, 45)
    verlauf: list[tuple[int, Decimal | None, bool | None]] = [
        (0, Decimal("25.0"), False),
        (5, Decimal("25.0"), False),
        (10, Decimal("25.0"), False),
    ]
    temperatur = Decimal("25.0")
    for i in range(7):  # 06:00, 06:05, ..., 06:30
        offen = i >= 1  # das Geraet meldet ab der zweiten Messung
        verlauf.append((15 + i * 5, temperatur, offen))
        temperatur -= Decimal("1.08")  # ≈ 0,217 K/min über 5 min
    verlauf.append((50, Decimal("18.5"), False))  # Fenster zu

    gefunden = episoden(
        _reihe(start, verlauf),  # type: ignore[arg-type]
        nacht_start=NACHT_START,
        nacht_ende=NACHT_ENDE,
        zone=ZONE,
    )
    assert len(gefunden) == 1
    e = gefunden[0]
    # Beginn 06:05 Ortszeit — nach dem Ende der Absenkung.
    assert e.in_absenkung is False
    assert e.trifft_abbruchkriterium is False
    # Der Abfall der zehn Minuten davor ist die Zahl, die den Befund traegt.
    assert e.abfall_k is not None
    assert e.abfall_k > Decimal("1.0")


def test_nachtabsenkung_ohne_fenster_waere_der_fehlalarm() -> None:
    """Die Zusicherung, die den Entwurf traegt (Brief: „die mittlere").

    Derselbe Abfall, nur um 20:05 Ortszeit statt um 06:05 — also durch
    **unsere** Absenkung. Der Befund muss ihn als Treffer des
    Abbruchkriteriums ausweisen, sonst beendet niemand die Testwoche.
    """
    start = ortszeit(2026, 10, 25, 20, 0)
    verlauf: list[tuple[int, Decimal | None, bool | None]] = [(0, Decimal("22.0"), False)]
    temperatur = Decimal("22.0")
    for i in range(1, 5):
        temperatur -= Decimal("1.0")
        verlauf.append((i * 5, temperatur, True))

    gefunden = episoden(
        _reihe(start, verlauf),  # type: ignore[arg-type]
        nacht_start=NACHT_START,
        nacht_ende=NACHT_ENDE,
        zone=ZONE,
    )
    assert len(gefunden) == 1
    assert gefunden[0].trifft_abbruchkriterium is True


# ---------------------------------------------------------------------------
# Die Ausnahmen in der Abfrage, nicht nur in der reinen Funktion
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    """Eine Sitzung gegen die Test-Datenbank.

    Eigene Huelle statt einer globalen: das Repo hat keine, und die
    bestehenden DB-Tests bauen sie je Modul (Pattern aus
    ``test_gast_sperre.py``).
    """
    if not DATABASE_URL:
        pytest.skip(SKIP_REASON)
    engine: AsyncEngine = create_async_engine(DATABASE_URL)
    try:
        sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
        async with sessionmaker() as session:
            yield session
    finally:
        await engine.dispose()


async def test_lade_ziele_nimmt_nur_messen_und_pool_wirklich_aus(
    db_session: AsyncSession,
) -> None:
    """Ergaenzung 2, auf Abfrage-Ebene geprueft.

    ``ausnahme_grund`` ist eine reine Funktion und beweist, dass die
    **Regel** stimmt. Dass die **Abfrage** sie anwendet, ist eine andere
    Aussage — und genau die Luecke, durch die das Bulk-Skript jahrelang
    Fuehler mitgenommen hat. §5.83: eine Zusicherung gilt nur auf der
    Ebene, auf der sie geprueft wurde.
    """
    suffix = uuid.uuid4().hex[:8]
    rt = RoomType(name=f"t2-{suffix}")
    db_session.add(rt)
    await db_session.flush()
    room = Room(number=f"t2-{suffix}", room_type_id=rt.id)
    db_session.add(room)
    await db_session.flush()
    zone = HeatingZone(room_id=room.id, kind=HeatingZoneKind.BEDROOM, name="Schlafzimmer")
    db_session.add(zone)
    await db_session.flush()

    montiert = Device(
        dev_eui=f"aa00{suffix}aa00",
        label=f"montiert-{suffix}",
        kind=DeviceKind.THERMOSTAT,
        vendor=DeviceVendor.MCLIMATE,
        model="vicki",
        heating_zone_id=zone.id,
        measure_only=False,
        firmware_version="4.5",
    )
    fuehler = Device(
        dev_eui=f"bb00{suffix}bb00",
        label=f"nurmessen-{suffix}",
        kind=DeviceKind.THERMOSTAT,
        vendor=DeviceVendor.MCLIMATE,
        model="vicki",
        heating_zone_id=zone.id,
        measure_only=True,
    )
    pool = Device(
        dev_eui=f"cc00{suffix}cc00",
        label=f"pool-{suffix}",
        kind=DeviceKind.THERMOSTAT,
        vendor=DeviceVendor.MCLIMATE,
        model="vicki",
        heating_zone_id=None,
        measure_only=False,
    )
    db_session.add_all([montiert, fuehler, pool])
    await db_session.commit()

    try:
        ziele, ausnahmen = await lade_ziele(db_session)
        eigene_ziele = {z.dev_eui for z in ziele} & {
            montiert.dev_eui,
            fuehler.dev_eui,
            pool.dev_eui,
        }
        assert eigene_ziele == {montiert.dev_eui}

        gruende = {a.dev_eui: a.grund for a in ausnahmen}
        assert gruende.get(fuehler.dev_eui) == GRUND_NUR_MESSEN
        assert gruende.get(pool.dev_eui) == GRUND_OHNE_ZONE

        # Die Bezeichnung aus dem Testplan ("306 Schlafzimmer") muss als
        # Auswahl funktionieren — eine DevEUI tippt niemand ab.
        nur_dieses, _ = await lade_ziele(db_session, nur=[f"t2-{suffix} Schlafzimmer"])
        assert [z.dev_eui for z in nur_dieses] == [montiert.dev_eui]
        assert nur_dieses[0].bezeichnung == f"t2-{suffix} Schlafzimmer"
    finally:
        for d in (montiert, fuehler, pool):
            await db_session.execute(text("DELETE FROM device WHERE id = :i"), {"i": d.id})
        await db_session.execute(text("DELETE FROM heating_zone WHERE id = :i"), {"i": zone.id})
        await db_session.execute(text("DELETE FROM room WHERE id = :i"), {"i": room.id})
        await db_session.execute(text("DELETE FROM room_type WHERE id = :i"), {"i": rt.id})
        await db_session.commit()
