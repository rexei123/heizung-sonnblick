"""Der Funk-Waechter (Sprint 25 T6) — Urteil, Schnittmenge, Gegenprobe.

**Die Gegenprobe ist der Zweck dieser Datei.** Der Waechter wurde gebaut,
weil der Befund vom 04.11.2026 erst einen Tag spaeter und zufaellig
aufgefallen ist. Die Anforderung des Betreibers lautet wortgleich: *„muss
um 09:00 ausloesen"*. Genau das prueft
``test_gegenprobe_04_11_loest_um_09_uhr_aus`` — mit den **gemessenen**
Zahlen, nicht mit erfundenen.

Die Zahlen stammen aus der stuendlichen Auswertung auf heizung-test:

| Zeitraum (Ortszeit) | SNR |
|---|---|
| 03.11. 21:00 bis 04.11. 06:00 | 8,6 bis 9,0 |
| 04.11. 08:00 und 09:00 | je 6,3 |

Die Grundlinie lag also bei rund **8,7**, das Messfenster um 09:00 bei
**6,3** — ein Abstand von **−2,4 dB** gegen eine Vorgabe von 2,0.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal

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
from heizung.models.sensor_reading import SensorReading
from heizung.services import funk_waechter
from heizung.services.funk_waechter import Kennzahlen, Schwellen, beurteile

DATABASE_URL = os.environ.get("DATABASE_URL")
SKIP_REASON = "DATABASE_URL nicht gesetzt - die Schnittmengen-Tests brauchen Test-DB"

#: Die Vorgabe aus den Settings, hier als Pruefstand-Wert wiederholt.
#: **Bewusst nicht importiert**: der Test soll festhalten, gegen welche
#: Zahl er geprueft hat. Zieht jemand die Vorgabe hoch, soll dieser Test
#: nicht stillschweigend mitwandern (§5.77 in Testform).
SCHWELLEN = Schwellen(warn_delta_db=Decimal("2.0"), min_meldungen=100, min_geraete=40)

#: Fuer die **Struktur**-Tests (Schnittmenge, Mittelbildung, Fensterlage).
#: Sie arbeiten mit zwei Geraeten, weil es dort um die Abfrage geht und
#: nicht um die Mindestmenge — die hat ihren eigenen Test. Mit den
#: Betriebsschwellen lautete das Urteil dort immer ``unbekannt``, und der
#: Test wuerde die Abfrage gar nicht mehr pruefen (§5.55: ein gruener
#: Lauf, der nichts geprueft hat).
SCHWELLEN_KLEIN = Schwellen(warn_delta_db=Decimal("2.0"), min_meldungen=1, min_geraete=1)


def _kennzahl(snr: str | None, *, meldungen: int = 1200, geraete: int = 103) -> Kennzahlen:
    return Kennzahlen(
        snr_db=Decimal(snr) if snr is not None else None,
        rssi_dbm=Decimal("-97"),
        meldungen=meldungen,
        geraete=geraete,
    )


# ---------------------------------------------------------------------------
# Das Urteil — ohne Datenbank, ohne Uhr
# ---------------------------------------------------------------------------


def test_gegenprobe_04_11_loest_aus() -> None:
    """Die gemessenen Zahlen vom 04.11. muessen eine Warnung ergeben.

    Grundlinie 8,7 (die Stunden vor dem Vorfall), Messfenster 6,3 (08:00
    und 09:00). Abstand −2,4 dB bei einer Vorgabe von 2,0.
    """
    befund = beurteile(_kennzahl("6.3"), _kennzahl("8.7"), SCHWELLEN)

    assert befund.stufe == "warnung", f"haette melden muessen: {befund}"
    assert befund.grund == funk_waechter.GRUND_UNTER_SCHWELLE
    assert befund.delta_snr_db == Decimal("-2.4")


def test_genau_auf_der_schwelle_loest_aus() -> None:
    """−2,0 dB bei Vorgabe 2,0 ist ein Befund, kein Grenzfall.

    Am 04.11. lagen die Stundenwerte zwischen −2,0 und −2,4. Waere die
    Schwelle exklusiv, haette eine Stunde mit genau −2,0 geschwiegen.
    """
    befund = beurteile(_kennzahl("6.7"), _kennzahl("8.7"), SCHWELLEN)

    assert befund.delta_snr_db == Decimal("-2.0")
    assert befund.stufe == "warnung"


def test_knapp_darueber_schweigt() -> None:
    """−1,9 dB ist keine Warnung — sonst meldet die normale Streuung."""
    befund = beurteile(_kennzahl("6.8"), _kennzahl("8.7"), SCHWELLEN)

    assert befund.delta_snr_db == Decimal("-1.9")
    assert befund.stufe == "im_rahmen"
    assert befund.grund == funk_waechter.GRUND_IM_RAHMEN


def test_besserer_funk_ist_keine_warnung() -> None:
    """Nach einer Behebung steigt der Wert. Das ist kein Alarm."""
    befund = beurteile(_kennzahl("8.9"), _kennzahl("6.3"), SCHWELLEN)

    assert befund.delta_snr_db == Decimal("2.6")
    assert befund.stufe == "im_rahmen"


def test_zu_wenige_meldungen_ist_unbekannt_und_nicht_warnung() -> None:
    """**Der wichtigste Test dieser Datei.**

    Nach einem Gateway-Ausfall ist das Messfenster duenn. Ein Melder, der
    dann Alarm schlaegt, meldet den Ausfall seines eigenen Messwegs — und
    ein Melder, der bei bekannter Ursache anschlaegt, verliert Gewicht
    (§5.79). Der Wert ist hier **sehr** schlecht; trotzdem ``unbekannt``.
    """
    befund = beurteile(_kennzahl("1.0", meldungen=12), _kennzahl("8.7"), SCHWELLEN)

    assert befund.stufe == "unbekannt"
    assert befund.grund == funk_waechter.GRUND_ZU_WENIG_DATEN
    assert befund.delta_snr_db is None


def test_zu_wenige_geraete_ist_unbekannt() -> None:
    """Viele Meldungen von drei Geraeten sind kein Hausmittel."""
    befund = beurteile(_kennzahl("1.0", geraete=3), _kennzahl("8.7"), SCHWELLEN)

    assert befund.stufe == "unbekannt"
    assert befund.grund == funk_waechter.GRUND_ZU_WENIG_DATEN


def test_ohne_grundlinie_ist_unbekannt() -> None:
    """Ein frisch aufgesetztes Haus hat keine Vorwoche."""
    befund = beurteile(_kennzahl("6.3"), _kennzahl(None), SCHWELLEN)

    assert befund.stufe == "unbekannt"
    assert befund.grund == funk_waechter.GRUND_KEINE_GRUNDLINIE


def test_der_text_sagt_zuerst_was_zu_tun_ist() -> None:
    """Wer nachts geweckt wird, soll in der ersten Zeile lesen, wohin.

    Und er soll **nicht** am Geraet anfangen: der Befund ist hausweit.
    """
    befund = beurteile(_kennzahl("6.3"), _kennzahl("8.7"), SCHWELLEN)
    text_ = funk_waechter.nachricht(befund, zeitzone="Europe/Vienna")

    assert "WAS ZU TUN IST" in text_
    assert text_.index("WAS ZU TUN IST") < text_.index("DIE ZAHLEN")
    assert "10ay" in text_
    assert "nie loesen, solange das Gateway Strom hat" in text_
    assert "-2.4 dB" in text_
    # Die Gegen-Erwartung gehoert in den Text: die Menge faellt NICHT.
    assert "605 auf 580" in text_


# ---------------------------------------------------------------------------
# Die Schnittmenge — gegen echtes Postgres
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    if not DATABASE_URL:
        pytest.skip(SKIP_REASON)
    engine: AsyncEngine = create_async_engine(DATABASE_URL)
    try:
        sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
        async with sessionmaker() as session:
            yield session
    finally:
        await engine.dispose()


async def _lege_geraete_an(session: AsyncSession, anzahl: int) -> tuple[list[int], int, int, int]:
    """``anzahl`` Geraete in einer Zone. Gibt IDs und die Aufraeum-IDs."""
    # schema_constraint: room.number max 20, device.dev_eui max 16 (§5.49)
    suffix = uuid.uuid4().hex[:8]
    rt = RoomType(name=f"fw-{suffix}", min_temp_celsius=15, max_temp_celsius=25)
    session.add(rt)
    await session.flush()
    room = Room(number=f"fw-{suffix}", room_type_id=rt.id)
    session.add(room)
    await session.flush()
    zone = HeatingZone(room_id=room.id, kind=HeatingZoneKind.BEDROOM, name="Schlafzimmer")
    session.add(zone)
    await session.flush()
    ids: list[int] = []
    for i in range(anzahl):
        geraet = Device(
            dev_eui=f"fa{i:02d}{suffix}fa{i:02d}"[:16],
            label=f"fw-{suffix}-{i}",
            kind=DeviceKind.THERMOSTAT,
            vendor=DeviceVendor.MCLIMATE,
            model="vicki",
            heating_zone_id=zone.id,
        )
        session.add(geraet)
        await session.flush()
        ids.append(geraet.id)
    await session.commit()
    return ids, zone.id, room.id, rt.id


async def _raeum_auf(
    session: AsyncSession, geraete: list[int], zone_id: int, room_id: int, rt_id: int
) -> None:
    for gid in geraete:
        await session.execute(text("DELETE FROM sensor_reading WHERE device_id = :i"), {"i": gid})
        await session.execute(text("DELETE FROM device WHERE id = :i"), {"i": gid})
    await session.execute(text("DELETE FROM heating_zone WHERE id = :i"), {"i": zone_id})
    await session.execute(text("DELETE FROM room WHERE id = :i"), {"i": room_id})
    await session.execute(text("DELETE FROM room_type WHERE id = :i"), {"i": rt_id})
    await session.commit()


def _messwert(device_id: int, zeit: datetime, snr: str, rssi: int) -> SensorReading:
    return SensorReading(
        device_id=device_id,
        time=zeit,
        temperature=Decimal("21.0"),
        snr_db=Decimal(snr),
        rssi_dbm=rssi,
    )


async def test_nur_im_fenster_vorhandenes_geraet_zaehlt_nicht(db_session: AsyncSession) -> None:
    """Ein Geraet ohne Grundlinie darf das Hausmittel nicht heben.

    **Warum das der Kern ist.** Ohne Schnittmenge waere das Hausmittel
    durch den Bestand manipulierbar: kommen Geraete in gut versorgten
    Zimmern dazu, steigt das Mittel und **verdeckt** eine
    Verschlechterung. Hier hat Geraet B nur im Messfenster Werte, und
    zwar sehr gute — es muss herausfallen.
    """
    jetzt = datetime.now(tz=UTC)
    ids, zone_id, room_id, rt_id = await _lege_geraete_an(db_session, 2)
    a, b = ids
    try:
        # A: in beiden Fenstern. Grundlinie 9,0 / Messfenster 6,0.
        for minuten in (30, 60, 90):
            db_session.add(_messwert(a, jetzt - timedelta(minutes=minuten), "6.0", -100))
        for tage in (2, 3, 4):
            db_session.add(_messwert(a, jetzt - timedelta(days=tage), "9.0", -96))
        # B: NUR im Messfenster, mit einem glaenzenden Wert.
        for minuten in (20, 40):
            db_session.add(_messwert(b, jetzt - timedelta(minutes=minuten), "12.0", -80))
        await db_session.commit()

        fenster, grundlinie = await funk_waechter.lade_kennzahlen(
            db_session, now=jetzt, fenster_stunden=2, grundlinie_tage=7
        )

        assert fenster.geraete == 1, "Geraet B haette herausfallen muessen"
        assert fenster.snr_db == Decimal("6.0"), f"B hat das Mittel gehoben: {fenster.snr_db}"
        assert grundlinie.snr_db == Decimal("9.0")
        assert beurteile(fenster, grundlinie, SCHWELLEN_KLEIN).delta_snr_db == Decimal("-3.0")
    finally:
        await _raeum_auf(db_session, ids, zone_id, room_id, rt_id)


async def test_haeufiger_sender_dominiert_das_mittel_nicht(db_session: AsyncSession) -> None:
    """Gemittelt wird ueber Geraete-Mittel, nicht ueber Zeilen.

    Sonst verschiebt ein **stilles** Geraet — also genau das Symptom —
    das Ergebnis in die falsche Richtung: das laute, gut versorgte Geraet
    bekaeme mehr Gewicht, und der Abfall des stillen verschwindet.

    Hier sendet A zehnmal mit 10,0 und B zweimal mit 0,0. Das Mittel der
    Geraete-Mittel ist 5,0; das Mittel der Zeilen waere 8,3.
    """
    jetzt = datetime.now(tz=UTC)
    ids, zone_id, room_id, rt_id = await _lege_geraete_an(db_session, 2)
    a, b = ids
    try:
        for i in range(10):
            db_session.add(_messwert(a, jetzt - timedelta(minutes=5 + i), "10.0", -90))
        for i in range(2):
            db_session.add(_messwert(b, jetzt - timedelta(minutes=5 + i), "0.0", -110))
        # Grundlinie fuer beide, damit die Schnittmenge beide enthaelt.
        for gid in (a, b):
            db_session.add(_messwert(gid, jetzt - timedelta(days=3), "9.0", -96))
        await db_session.commit()

        fenster, _ = await funk_waechter.lade_kennzahlen(
            db_session, now=jetzt, fenster_stunden=2, grundlinie_tage=7
        )

        assert fenster.geraete == 2
        assert fenster.snr_db == Decimal("5.0"), (
            f"ueber Zeilen gemittelt waere es 8,3 — ist {fenster.snr_db}"
        )
        assert fenster.meldungen == 12
    finally:
        await _raeum_auf(db_session, ids, zone_id, room_id, rt_id)


async def test_grundlinie_endet_vor_24_stunden(db_session: AsyncSession) -> None:
    """Die Stoerung darf nicht in ihrer eigenen Vergleichsgroesse stecken.

    **Das ist der Entwurfskern** (Modul-Kopf): ein gleitendes Mittel, das
    die Stoerung enthaelt, verduennt sich selbst. Hier liegen Werte 12
    Stunden zurueck — also **nach** dem Ende der Grundlinie. Sie duerfen
    sie nicht beeinflussen.
    """
    jetzt = datetime.now(tz=UTC)
    ids, zone_id, room_id, rt_id = await _lege_geraete_an(db_session, 1)
    (a,) = ids
    try:
        db_session.add(_messwert(a, jetzt - timedelta(minutes=30), "6.0", -100))
        # 12 Stunden zurueck: im Niemandsland zwischen Fenster und Grundlinie.
        for stunden in (10, 12, 14):
            db_session.add(_messwert(a, jetzt - timedelta(hours=stunden), "6.0", -100))
        # Echte Grundlinie, 3 Tage zurueck.
        db_session.add(_messwert(a, jetzt - timedelta(days=3), "9.0", -96))
        await db_session.commit()

        _, grundlinie = await funk_waechter.lade_kennzahlen(
            db_session, now=jetzt, fenster_stunden=2, grundlinie_tage=7
        )

        assert grundlinie.snr_db == Decimal("9.0"), (
            f"die Werte von vor 12 Stunden sind in die Grundlinie gelaufen — {grundlinie.snr_db}"
        )
        assert grundlinie.meldungen == 1
    finally:
        await _raeum_auf(db_session, ids, zone_id, room_id, rt_id)


async def test_gegenprobe_04_11_loest_um_09_uhr_aus(db_session: AsyncSession) -> None:
    """Die ganze Kette mit den Zahlen vom 04.11. — Anforderung des Betreibers.

    Nachgebaut sind die **Verhaeltnisse**, nicht die Anlage: 50 Geraete
    (ueber ``min_geraete``), die Grundlinie bei 8,7 ueber mehrere Tage,
    das Messfenster bei 6,3 in den letzten zwei Stunden. Das entspricht
    dem Stand am 04.11. um 09:00 Ortszeit.

    Die Zahl der Geraete ist bewusst **ueber** der Mindestmenge: der Test
    soll die Schwelle pruefen, nicht die Mindestmenge — die hat ihren
    eigenen Test.
    """
    jetzt = datetime.now(tz=UTC)
    ids, zone_id, room_id, rt_id = await _lege_geraete_an(db_session, 50)
    try:
        for gid in ids:
            # Messfenster: zwei Meldungen je Geraet in zwei Stunden.
            for minuten in (25, 85):
                db_session.add(_messwert(gid, jetzt - timedelta(minutes=minuten), "6.3", -100))
            # Grundlinie: je Geraet ein Wert an drei Tagen.
            for tage in (2, 3, 4):
                db_session.add(_messwert(gid, jetzt - timedelta(days=tage), "8.7", -96))
        await db_session.commit()

        befund = await funk_waechter.pruefe_funkqualitaet(
            db_session, SCHWELLEN, fenster_stunden=2, grundlinie_tage=7, now=jetzt
        )

        assert befund.stufe == "warnung", f"der Befund vom 04.11. wurde nicht gemeldet: {befund}"
        assert befund.delta_snr_db == Decimal("-2.4")
        assert befund.delta_rssi_db == Decimal("-4")
        assert befund.fenster.geraete == 50
        assert befund.fenster.meldungen == 100
    finally:
        await _raeum_auf(db_session, ids, zone_id, room_id, rt_id)
