"""Sprint 20 T1+T3 — DB-Tests zur Batterie-Spannung und ihrer Bewertung (AE-72).

Zwei Teile:

* **T1** — die Spalte selbst: Raster-Roundtrip, NULL bleibt NULL, Rundung.
* **T3** — ``battery_verdicts``: Median ueber 24 h, obere Rundungskante,
  Mindest-Stichprobe, Sprung-Regel nach einem Batteriewechsel.


Migration 0024 fuegt die Spalte als ``Numeric(3, 1)`` NULL hinzu. Dieser
Test ist der §5.50-Verify, den ich lokal nicht fahren kann (Docker Desktop
startet auf dem Arbeitsrechner nicht, B-18-5) — er laeuft in CI gegen die
echte TimescaleDB und beantwortet drei Fragen:

1. Nimmt die Spalte das 0.1-V-Raster verlustfrei auf und gibt es als
   ``Decimal`` zurueck?
2. Bleibt ``NULL`` NULL — also unterscheidbar von 0.0 V?
3. Rundet ``Numeric(3, 1)`` einen zweistelligen Wert, statt zu werfen?

Frage 3 ist nicht akademisch: der Codec rundet selbst auf zwei Stellen
(``toFixed(2)``), und ein zukuenftiger Sensor mit feinerem Raster wuerde
seine Werte hier stillschweigend auf 0.1 V gerundet sehen. Der Test haelt
das Verhalten fest, damit es eine Entscheidung ist und keine Entdeckung.

DB-Tests skippen ohne ``TEST_DATABASE_URL`` (§5.50).
"""

from __future__ import annotations

import os
import time
import uuid
from collections.abc import AsyncIterator, Iterator, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import Select, event, func, select, text
from sqlalchemy import delete as sa_delete
from sqlalchemy import insert as sa_insert
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from heizung.models.device import Device
from heizung.models.enums import DeviceKind, DeviceVendor
from heizung.models.sensor_reading import SensorReading
from heizung.services.battery_health import (
    BATTERY_WINDOW_H,
    battery_verdicts,
    oberer_median,
)

TEST_DB_URL = os.environ.get("TEST_DATABASE_URL")
SKIP_REASON = "TEST_DATABASE_URL nicht gesetzt — DB-Tests brauchen Postgres"

# Eindeutiges DevEUI-Prefix fuer die Cleanup-Fixture (§5.39). 8 Hex-Zeichen
# Prefix + 8 Zeichen Suffix = 16 = VARCHAR(16) exakt voll (§5.18).
EUI_PREFIX = "5290a024"

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    if not TEST_DB_URL:
        pytest.skip(SKIP_REASON)
    engine = create_async_engine(TEST_DB_URL)
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    async with sessionmaker() as session:
        # Die Engine mitgeben: der Performance-Test haengt einen
        # ``before_cursor_execute``-Horcher daran, um Statements zu zaehlen.
        session.info["engine"] = engine
        try:
            await _purge(session)
            await session.commit()
            yield session
        finally:
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


async def _make_device(session: AsyncSession) -> int:
    device = Device(
        dev_eui=f"{EUI_PREFIX}{uuid.uuid4().hex[:8]}",
        kind=DeviceKind.THERMOSTAT,
        vendor=DeviceVendor.MCLIMATE,
        model="vicki",
    )
    session.add(device)
    await session.flush()
    return device.id


async def test_battery_voltage_raster_roundtrip(db_session: AsyncSession) -> None:
    """Alle 16 Codec-Schritte 2.0-3.5 V kommen unveraendert zurueck."""
    device_id = await _make_device(db_session)
    base = datetime(2026, 9, 30, 12, 0, 0, tzinfo=UTC)

    erwartet: dict[datetime, Decimal] = {}
    for nibble in range(16):
        volts = Decimal("2.0") + Decimal(nibble) / 10
        ts = base + timedelta(minutes=nibble)
        db_session.add(
            SensorReading(
                time=ts,
                device_id=device_id,
                fcnt=nibble,
                battery_voltage=volts,
            )
        )
        erwartet[ts] = volts
    await db_session.flush()
    db_session.expire_all()

    # ORM-Objekte statt Spalten-Tupel: die gemappten Attribute sind typisiert,
    # Row-Unpacking ist es unter SQLAlchemy 2.1 nicht mehr verlaesslich (§5.80).
    rows = list(
        (
            await db_session.execute(
                select(SensorReading)
                .where(SensorReading.device_id == device_id)
                .order_by(SensorReading.time)
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 16
    for row in rows:
        assert isinstance(row.battery_voltage, Decimal)
        assert row.battery_voltage == erwartet[row.time], (
            f"{row.time}: {row.battery_voltage} != {erwartet[row.time]}"
        )


async def test_battery_voltage_null_bleibt_null(db_session: AsyncSession) -> None:
    """Kein ``server_default`` — eine Zeile ohne Spannung hat NULL, nicht 0.

    Das ist die Unterscheidung, an der die Bewertung haengt: NULL heisst
    "kein Messwert" und wird nicht mitgezaehlt; 0.0 V hiesse "Geraet tot"
    und waere ein Befund.
    """
    device_id = await _make_device(db_session)
    db_session.add(
        SensorReading(
            time=datetime(2026, 9, 30, 12, 0, 0, tzinfo=UTC),
            device_id=device_id,
            fcnt=1,
            temperature=Decimal("21.0"),
        )
    )
    await db_session.flush()
    db_session.expire_all()

    volts = (
        await db_session.execute(
            select(SensorReading.battery_voltage).where(SensorReading.device_id == device_id)
        )
    ).scalar_one()
    assert volts is None


async def test_battery_voltage_zweite_stelle_wird_gerundet(
    db_session: AsyncSession,
) -> None:
    """``Numeric(3, 1)`` rundet auf eine Dezimalstelle, es wirft nicht.

    Postgres rundet beim Cast auf die Spalten-Skala (half-up). Der Codec
    liefert heute nur 0.1-Schritte, aber der Erwartungswert steht hier aus
    der Spezifikation, nicht aus einem Lauf (§5.79) — falls ein Frame je
    2.85 V traegt, wird daraus 2.9 und nicht ein Fehler.
    """
    device_id = await _make_device(db_session)
    db_session.add(
        SensorReading(
            time=datetime(2026, 9, 30, 12, 0, 0, tzinfo=UTC),
            device_id=device_id,
            fcnt=1,
            battery_voltage=Decimal("2.85"),
        )
    )
    await db_session.flush()
    db_session.expire_all()

    volts = (
        await db_session.execute(
            select(SensorReading.battery_voltage).where(SensorReading.device_id == device_id)
        )
    ).scalar_one()
    assert volts == Decimal("2.9")


# ---------------------------------------------------------------------------
# Sprint 20 T3 — Bewertung ueber den 24-h-Median (AE-72)
# ---------------------------------------------------------------------------

JETZT = datetime(2026, 9, 30, 12, 0, 0, tzinfo=UTC)


async def _seed(
    session: AsyncSession,
    device_id: int,
    volts: Sequence[str | None],
    *,
    abstand_min: int = 10,
    bis: datetime = JETZT,
) -> None:
    """Legt Messwerte rueckwaerts von ``bis`` an — letzter Wert zuletzt.

    ``volts[-1]`` ist damit der juengste Messwert. Absolute Zeitstempel,
    keine ``datetime.now()``-Ableitung (§5.59: Fixtures mit Real-Now
    schluepfen an einer gefrorenen Zeit vorbei).
    """
    for i, v in enumerate(reversed(volts)):
        session.add(
            SensorReading(
                time=bis - timedelta(minutes=abstand_min * i),
                device_id=device_id,
                fcnt=1000 + i,
                battery_voltage=None if v is None else Decimal(v),
            )
        )
    await session.flush()


async def test_median_bei_gerader_stichprobe_nimmt_den_hoeheren_wert(
    db_session: AsyncSession,
) -> None:
    """T4a — vier Werte, der obere der beiden mittleren gewinnt.

    2.8 / 2.9 / 3.0 / 3.1 hat den ueblichen Median 2.95 — ein Wert, den das
    0.1-V-Raster nicht kennt und der zwischen "schwach" und "OK" liegt.
    Genommen wird 3.0, also "OK": volle Batterie nie als leer, auch an der
    Rundungskante.
    """
    device_id = await _make_device(db_session)
    await _seed(db_session, device_id, ["2.8", "2.9", "3.0", "3.1"])

    verdicts = await battery_verdicts(db_session, [device_id], now=JETZT)

    assert verdicts[device_id].median_v == Decimal("3.0")
    assert verdicts[device_id].stage == "ok"
    assert verdicts[device_id].samples == 4


async def test_sql_median_und_python_median_sind_identisch(
    db_session: AsyncSession,
) -> None:
    """Die Zusicherung aus dem Docstring von ``oberer_median``, geprueft.

    Der Normalpfad rechnet in Postgres (``percentile_disc`` mit
    absteigender Ordnung), der Pfad nach einem Batteriewechsel in Python.
    Beide muessen dieselbe Auswahl treffen, sonst springt die Stufe beim
    Wechsel zwischen den Pfaden.
    """
    reihen = [
        ["2.7", "2.8", "2.9", "3.0"],  # gerade
        ["2.7", "2.8", "2.9", "3.0", "3.1"],  # ungerade
        ["3.0", "3.0", "3.0", "2.6"],  # Lastabfall am Rand
        ["2.9", "3.1"],  # zwei Werte
    ]
    for reihe in reihen:
        device_id = await _make_device(db_session)
        await _seed(db_session, device_id, reihe)
        verdicts = await battery_verdicts(db_session, [device_id], now=JETZT)
        erwartet = oberer_median([Decimal(v) for v in reihe])
        assert verdicts[device_id].median_v == erwartet, reihe


async def test_lastabfall_bewegt_die_stufe_nicht(db_session: AsyncSession) -> None:
    """Der Anlass des Sprints: ein Einbruch unter Motorlast zaehlt nicht.

    Geraet 001 stand am 29.09. auf "kritisch", obwohl es 3.0 V meldete. Die
    Anzeige stammte aus dem letzten Frame, und das Ventil klemmte mit
    ``lowMotorConsumption`` — ein schwaches Alkaline-Paar bricht dabei ein.

    Hier: 23 Messwerte 3.0 V, der juengste 2.6 V. Der Median bleibt 3.0,
    die Stufe "OK". Die alte Logik haette 2.6 V gelesen und 0 % gezeigt,
    also "kritisch".
    """
    device_id = await _make_device(db_session)
    await _seed(db_session, device_id, ["3.0"] * 23 + ["2.6"])

    verdict = (await battery_verdicts(db_session, [device_id], now=JETZT))[device_id]

    assert verdict.median_v == Decimal("3.0")
    assert verdict.stage == "ok"
    assert verdict.jump_at is None


async def test_batteriewechsel_wirkt_in_einer_auswertung(
    db_session: AsyncSession,
) -> None:
    """T4c — Sprung 2.8 -> 3.5 V, sofort hoch, alter Median aus dem Fenster.

    Zehn Messwerte auf 2.8 V (kritisch), dann vier auf 3.5 V. Der 24-h-
    Median ueber alles waere 2.8 — die Mehrheit ist noch alt. Die
    Sprung-Regel vergleicht deshalb den **juengsten** Wert gegen den Median
    (3.5 - 2.8 = 0.7 >= 0.3) und rechnet dann nur ueber die Reihe ab dem
    Sprung.
    """
    device_id = await _make_device(db_session)
    await _seed(db_session, device_id, ["2.8"] * 10 + ["3.5"] * 4)

    verdict = (await battery_verdicts(db_session, [device_id], now=JETZT))[device_id]

    assert verdict.stage == "ok"
    assert verdict.median_v == Decimal("3.5")
    # Nur die vier neuen Werte, nicht die 14 im Fenster.
    assert verdict.samples == 4
    # Der Sprung liegt beim aeltesten der vier neuen Werte: 3 Abstaende
    # vor jetzt (der juengste liegt auf JETZT).
    assert verdict.jump_at == JETZT - timedelta(minutes=30)


async def test_nach_dem_wechsel_erst_ab_drei_werten_eine_stufe(
    db_session: AsyncSession,
) -> None:
    """Die halbe Stunde Ehrlichkeit nach einem Batteriewechsel.

    Zwei neue Messwerte reichen nicht fuer einen Median. Statt die alte
    Stufe weiterzuzeigen (die fuer die alte Batterie galt) steht
    ``unbekannt`` — aber mit ``jump_at``, damit die Oberflaeche den Grund
    nennen kann.
    """
    device_id = await _make_device(db_session)
    await _seed(db_session, device_id, ["2.8"] * 10 + ["3.5"] * 2)

    verdict = (await battery_verdicts(db_session, [device_id], now=JETZT))[device_id]

    assert verdict.stage == "unbekannt"
    assert verdict.samples == 2
    assert verdict.jump_at == JETZT - timedelta(minutes=10)


async def test_zwei_messwerte_sind_keine_stichprobe(db_session: AsyncSession) -> None:
    """T4d — unter ``BATTERY_MIN_SAMPLES`` gibt es keine Stufe.

    Ein frisch gepaartes Geraet am Tisch hat nach dem ersten Uplink einen
    Messwert. "unbekannt" ist dort die Wahrheit; "kritisch" waere eine
    erfundene Aussage, und "ok" eine ungedeckte.
    """
    device_id = await _make_device(db_session)
    await _seed(db_session, device_id, ["2.6", "2.6"])

    verdict = (await battery_verdicts(db_session, [device_id], now=JETZT))[device_id]

    assert verdict.stage == "unbekannt"
    assert verdict.samples == 2
    # Der Median wird trotzdem mitgegeben — die Zahl ist da, nur nicht
    # belastbar. Die Oberflaeche zeigt bei "unbekannt" keine Spannung.
    assert verdict.median_v == Decimal("2.6")


async def test_werte_aelter_als_das_fenster_zaehlen_nicht(
    db_session: AsyncSession,
) -> None:
    """Das Fenster ist 24 h, nicht "alles was da ist"."""
    device_id = await _make_device(db_session)
    # Drei frische auf 3.0, drei alte (36 h zurueck) auf 2.6.
    await _seed(db_session, device_id, ["3.0"] * 3)
    await _seed(
        db_session,
        device_id,
        ["2.6"] * 3,
        bis=JETZT - timedelta(hours=36),
    )

    verdict = (await battery_verdicts(db_session, [device_id], now=JETZT))[device_id]

    assert verdict.samples == 3
    assert verdict.median_v == Decimal("3.0")
    assert verdict.stage == "ok"


async def test_null_spannungen_zaehlen_nicht_mit(db_session: AsyncSession) -> None:
    """Bestandszeilen ohne Spannung (vor Migration 0024) sind keine Nullen.

    Vier NULL-Zeilen plus drei mit 2.9 V: die Stichprobe ist 3, nicht 7,
    und der Median 2.9 — nicht 0.0 V und damit nicht "kritisch".
    """
    device_id = await _make_device(db_session)
    await _seed(db_session, device_id, [None, None, "2.9", None, "2.9", None, "2.9"])

    verdict = (await battery_verdicts(db_session, [device_id], now=JETZT))[device_id]

    assert verdict.samples == 3
    assert verdict.median_v == Decimal("2.9")
    assert verdict.stage == "warn"


async def test_jede_angefragte_id_kommt_zurueck(db_session: AsyncSession) -> None:
    """Kein fehlender Schluessel — sonst wird ein Geraet still zu "ok".

    Ein Geraet ohne jeden Messwert (frisch angelegt, noch nie gemeldet)
    muss als ``unbekannt`` im Ergebnis stehen, nicht fehlen.
    """
    mit_werten = await _make_device(db_session)
    ohne_werte = await _make_device(db_session)
    await _seed(db_session, mit_werten, ["3.1"] * 3)

    verdicts = await battery_verdicts(db_session, [mit_werten, ohne_werte], now=JETZT)

    assert set(verdicts) == {mit_werten, ohne_werte}
    assert verdicts[mit_werten].stage == "ok"
    assert verdicts[ohne_werte].stage == "unbekannt"
    assert verdicts[ohne_werte].median_v is None
    assert verdicts[ohne_werte].samples == 0


async def test_leere_id_liste_fragt_die_datenbank_nicht(
    db_session: AsyncSession,
) -> None:
    """Das Dashboard-Aggregat ruft mit leerer Liste, wenn kein Geraet aktiv ist."""
    assert await battery_verdicts(db_session, [], now=JETZT) == {}


async def test_entladung_nach_unten_wirkt_ohne_verzoegerung(
    db_session: AsyncSession,
) -> None:
    """Nach unten gibt es keine Hysterese — der Median ist die Bremse.

    Die Streak-Regel aus dem ersten Entwurf (drei Meldungen in Folge) ist
    entfallen: sie braeuchte persistierten Zustand, und ein 24-h-Median
    bewegt sich ohnehin nur, wenn die Mehrheit der Messwerte gekippt ist.
    Hier: 20 Werte auf 2.8 V, vier auf 3.0 -> Median 2.8, kritisch.
    """
    device_id = await _make_device(db_session)
    await _seed(db_session, device_id, ["3.0"] * 4 + ["2.8"] * 20)

    verdict = (await battery_verdicts(db_session, [device_id], now=JETZT))[device_id]

    assert verdict.median_v == Decimal("2.8")
    assert verdict.stage == "kritisch"


async def test_kein_sprung_bei_zwei_rasterschritten(db_session: AsyncSession) -> None:
    """0.2 V ist kein Wechsel — die Schwelle ist 0.3 V.

    Zwischen zwei Nibble-Stufen ist ein Unterschied von 0.2 V noch als
    Messrauschen erklaerbar. Der Test haelt die Grenze fest: der Sprung-Pfad
    darf hier nicht greifen, die Bewertung laeuft ueber das ganze Fenster.
    """
    device_id = await _make_device(db_session)
    await _seed(db_session, device_id, ["2.9"] * 10 + ["3.1"] * 2)

    verdict = (await battery_verdicts(db_session, [device_id], now=JETZT))[device_id]

    assert verdict.jump_at is None
    assert verdict.samples == 12
    assert verdict.median_v == Decimal("2.9")
    assert verdict.stage == "warn"


# ---------------------------------------------------------------------------
# Nie ein Badge ohne Spannung (Befund heizung-test 30.09.2026)
# ---------------------------------------------------------------------------
#
# "Batterie unbekannt" ohne Zahl ist fuer den Hotelier wertlos — er weiss
# danach so viel wie vorher. Die Regel lautet deshalb: eine Stufe braucht
# drei Messwerte, aber **eine Zahl gibt es immer, wenn irgendeine bekannt
# ist.** "unbekannt" bleibt fuer den einen Fall, in dem es zutrifft.


async def test_letzter_wert_auch_ohne_stufe(db_session: AsyncSession) -> None:
    """Zwei Messwerte: keine Stufe, aber der letzte Wert steht im Verdict.

    Genau der Fall, der auf heizung-test als nutzloses "Batterie unbekannt"
    erschien. Die Stufe bleibt "unbekannt" — sie ist wirklich nicht
    berechenbar —, aber ``last_v`` und ``last_at`` tragen die Auskunft.
    """
    device_id = await _make_device(db_session)
    await _seed(db_session, device_id, ["3.4", "3.5"])

    verdict = (await battery_verdicts(db_session, [device_id], now=JETZT))[device_id]

    assert verdict.stage == "unbekannt"
    assert verdict.last_v == Decimal("3.5")
    assert verdict.last_at == JETZT


async def test_letzter_wert_auch_bei_vorhandener_stufe(
    db_session: AsyncSession,
) -> None:
    """Das Feldpaar wird immer gefuellt, nicht nur im Ausnahmefall.

    Sonst muesste die Oberflaeche zwei Quellen unterscheiden, und der
    naechste, der eine Anzeige baut, greift zur falschen.
    """
    device_id = await _make_device(db_session)
    await _seed(db_session, device_id, ["3.1", "3.1", "3.1"])

    verdict = (await battery_verdicts(db_session, [device_id], now=JETZT))[device_id]

    assert verdict.stage == "ok"
    assert verdict.median_v == Decimal("3.1")
    assert verdict.last_v == Decimal("3.1")
    assert verdict.last_at == JETZT


async def test_letzter_wert_auch_ausserhalb_des_bewertungs_fensters(
    db_session: AsyncSession,
) -> None:
    """Der letzte Wert wird auch gefunden, wenn er aelter als 24 h ist.

    Ein Geraet, das seit drei Tagen schweigt, hat keine Stufe — aber seine
    letzte gemeldete Spannung ist eine Auskunft, und zwar eine, aus der man
    etwas ableiten kann ("voll und stumm" ist ein anderer Fall als "leer").
    """
    device_id = await _make_device(db_session)
    await _seed(db_session, device_id, ["3.5"] * 5, bis=JETZT - timedelta(days=3))

    verdict = (await battery_verdicts(db_session, [device_id], now=JETZT))[device_id]

    # Im 24-h-Fenster liegt nichts -> keine Stufe, kein Median.
    assert verdict.stage == "unbekannt"
    assert verdict.median_v is None
    assert verdict.samples == 0
    # Aber der letzte bekannte Wert steht da, mit seinem Alter.
    assert verdict.last_v == Decimal("3.5")
    assert verdict.last_at == JETZT - timedelta(days=3)


async def test_nie_gemeldet_bleibt_ohne_zahl(db_session: AsyncSession) -> None:
    """Der einzige Fall, in dem "unbekannt" ohne Zahl richtig ist."""
    device_id = await _make_device(db_session)

    verdict = (await battery_verdicts(db_session, [device_id], now=JETZT))[device_id]

    assert verdict.stage == "unbekannt"
    assert verdict.last_v is None
    assert verdict.last_at is None


async def test_nur_null_spannungen_bleibt_ohne_zahl(db_session: AsyncSession) -> None:
    """Bestandszeilen ohne Spannung sind keine gemeldete Spannung.

    Ein Geraet, das seit Monaten meldet, aber dessen Zeilen alle von vor
    Migration 0024 stammen, hat **nie** eine Spannung gemeldet. "unbekannt"
    ohne Zahl ist dort die Wahrheit.
    """
    device_id = await _make_device(db_session)
    await _seed(db_session, device_id, [None] * 6)

    verdict = (await battery_verdicts(db_session, [device_id], now=JETZT))[device_id]

    assert verdict.stage == "unbekannt"
    assert verdict.last_v is None


async def test_werte_jenseits_des_rueckblicks_zaehlen_nicht(
    db_session: AsyncSession,
) -> None:
    """Aelter als 30 Tage -> "unbekannt" ohne Zahl, bewusst.

    Eine Spannung von vor drei Monaten sagt nichts ueber die Batterie von
    heute; sie waere eine Zahl, die falsche Sicherheit gibt. Und eine
    unbegrenzte Suche waere ein ``DISTINCT ON`` ohne Chunk-Exclusion — genau
    die Kosten, die AE-72 §4 vermieden hat.
    """
    device_id = await _make_device(db_session)
    await _seed(db_session, device_id, ["3.5"] * 3, bis=JETZT - timedelta(days=45))

    verdict = (await battery_verdicts(db_session, [device_id], now=JETZT))[device_id]

    assert verdict.stage == "unbekannt"
    assert verdict.last_v is None


async def test_letzter_wert_ist_der_juengste_nicht_der_hoechste(
    db_session: AsyncSession,
) -> None:
    """Ordnung nach Zeit, nicht nach Wert.

    Bei einem entladenden Geraet ist der juengste Wert der niedrigste. Wer
    hier nach Wert sortiert, zeigt dem Hotelier dauerhaft die hoechste je
    gemessene Spannung — und der Badge wuerde nie schlechter.
    """
    device_id = await _make_device(db_session)
    await _seed(db_session, device_id, ["3.5", "3.2", "2.8"])

    verdict = (await battery_verdicts(db_session, [device_id], now=JETZT))[device_id]

    assert verdict.last_v == Decimal("2.8")
    assert verdict.last_at == JETZT


# ---------------------------------------------------------------------------
# Sprint 20 T4 — Performance-Beleg fuer die Geraeteliste (104 Geraete)
# ---------------------------------------------------------------------------
#
# Was dieser Test beweisen kann und was nicht:
#
# BEWEISBAR ist die Struktur — **eine** Aggregat-Query fuer 104 Geraete
# statt einer pro Geraet. Das ist die Eigenschaft, die mit dem Bestand
# skaliert, und sie ist hier hart zugesichert.
#
# NICHT beweisbar ist die Laufzeit im Betrieb. Ein Fixture-Bestand von
# 16 000 Zeilen sagt nichts ueber eine Hypertable, die nach einem Jahr
# 104 * 144 * 365 = 5.5 Mio Zeilen haelt. Die Schwelle unten ist deshalb
# eine **Reissleine** gegen einen strukturellen Fehler (etwa eine Query
# pro Geraet, die ueber die Verbindungslatenz sofort in Sekunden laeuft),
# kein Zielwert. Eine Schwelle, die man bei jeder Messung nachzieht,
# vergleicht nichts (CLAUDE.md §5.82).
#
# Der eigentliche Beleg ist der ausgegebene Plan: er steht im CI-Log des
# Laufs und wird im PR-Text zitiert. Zugesichert wird er nicht — Plan-Text
# haengt an Postgres- und Timescale-Version, und eine Zusicherung auf einen
# aus einem Lauf kopierten Text prueft nur, dass sich nichts geaendert hat
# (§5.79).

GERAETE = 104
FRAMES_IM_FENSTER = 144  # 24 h bei einem Uplink alle 10 min
FRAMES_AUSSERHALB = 10  # 30 Tage alt, muessen ausgeschlossen werden
REISSLEINE_S = 2.0


@contextmanager
def _zaehle_statements(session: AsyncSession) -> Iterator[list[str]]:
    """Sammelt die SQL-Statements, die ueber diese Session laufen."""
    sync_engine = session.info["engine"].sync_engine
    gesehen: list[str] = []

    def _log(
        conn: Any,
        cursor: Any,
        statement: str,
        parameters: Any,
        context: Any,
        executemany: bool,
    ) -> None:
        gesehen.append(statement)

    event.listen(sync_engine, "before_cursor_execute", _log)
    try:
        yield gesehen
    finally:
        event.remove(sync_engine, "before_cursor_execute", _log)


async def _seed_bestand(session: AsyncSession) -> list[int]:
    """104 Geraete mit realistischer Messwert-Dichte, per Bulk-Insert."""
    device_ids = [await _make_device(session) for _ in range(GERAETE)]

    zeilen: list[dict[str, object]] = []
    for idx, device_id in enumerate(device_ids):
        # Leicht unterschiedliche Spannungen, damit der Median echte Arbeit
        # hat und nicht ueber 144 identische Werte laeuft.
        basis = Decimal("2.9") + Decimal(idx % 7) / 10
        for i in range(FRAMES_IM_FENSTER):
            zeilen.append(
                {
                    "time": JETZT - timedelta(minutes=10 * i),
                    "device_id": device_id,
                    "fcnt": i,
                    "battery_voltage": basis if i % 3 else basis - Decimal("0.1"),
                }
            )
        for i in range(FRAMES_AUSSERHALB):
            zeilen.append(
                {
                    "time": JETZT - timedelta(days=30, minutes=10 * i),
                    "device_id": device_id,
                    "fcnt": 90000 + i,
                    "battery_voltage": Decimal("2.0"),
                }
            )

    await session.execute(sa_insert(SensorReading), zeilen)
    await session.flush()
    return device_ids


def _aggregat_query(device_ids: Sequence[int]) -> Select[Any]:
    """Dieselbe Query, die ``battery_verdicts`` im Normalpfad stellt.

    Bewusst hier nachgebaut statt aus dem Service exportiert: der Service
    soll seine Query nicht fuer einen Test nach aussen geben. Weicht die
    eine von der anderen ab, fallen die Zusicherungen in
    ``test_geraeteliste_braucht_eine_query_fuer_alle_104`` — dort laeuft der
    echte Service.
    """
    seit = JETZT - timedelta(hours=BATTERY_WINDOW_H)
    return (
        select(
            SensorReading.device_id,
            func.percentile_disc(0.5)
            .within_group(SensorReading.battery_voltage.desc())
            .label("median_v"),
            func.count().label("samples"),
        )
        .where(SensorReading.device_id.in_(list(device_ids)))
        .where(SensorReading.time >= seit)
        .where(SensorReading.battery_voltage.is_not(None))
        .group_by(SensorReading.device_id)
    )


async def test_geraeteliste_braucht_eine_query_fuer_alle_104(
    db_session: AsyncSession, capsys: pytest.CaptureFixture[str]
) -> None:
    """Struktur-Zusicherung: EIN Statement, unabhaengig von der Geraetezahl.

    Ohne diese Eigenschaft wuerde die Batterie-Stufe die Geraeteliste um
    104 Roundtrips verlaengern — zusaetzlich zu den zwei pro Geraet, die
    ``_build_device_read`` heute schon macht und die dort als N+1 bewusst
    akzeptiert sind (``api/v1/devices.py:127``).
    """
    device_ids = await _seed_bestand(db_session)

    with _zaehle_statements(db_session) as statements:
        start = time.perf_counter()
        verdicts = await battery_verdicts(db_session, device_ids, now=JETZT)
        dauer = time.perf_counter() - start

    assert len(verdicts) == GERAETE
    # Zwei Statements: das Aggregat ueber das 24-h-Fenster und die Abfrage des
    # juengsten bekannten Spannungswerts. Beide sind EINE Query fuer alle
    # Geraete — das ist die Eigenschaft, die mit dem Bestand skaliert. Stuende
    # hier eine Zahl in der Groessenordnung von GERAETE, waere die Bewertung
    # ein dritter N+1-Pfad in der Geraeteliste.
    assert len(statements) == 2, f"{len(statements)} Statements:\n" + "\n".join(statements)

    # Das Fenster hat gegriffen: die 30 Tage alten Zeilen sind nicht in der
    # Stichprobe. Das ist gleichzeitig der Korrektheits-Beleg dafuer, dass
    # der Plan die alten Chunks ueberhaupt ausschliessen kann.
    assert {v.samples for v in verdicts.values()} == {FRAMES_IM_FENSTER}
    assert all(v.jump_at is None for v in verdicts.values())

    # capsys.disabled(): pytest verwirft die Ausgabe bestehender Tests. Der
    # Messwert soll aber im CI-Log desselben Laufs stehen, der ihn erzeugt hat
    # — dieselbe Begruendung wie fuer --durations=15 (§5.82).
    with capsys.disabled():
        print(f"\n[T4] battery_verdicts({GERAETE} Geraete): {dauer * 1000:.0f} ms")
    assert dauer < REISSLEINE_S, (
        f"{dauer:.2f}s fuer {GERAETE} Geraete — Reissleine bei {REISSLEINE_S}s. "
        "Das ist kein Zielwert, sondern der Verdacht auf einen strukturellen "
        "Fehler; erst die Ursache suchen, dann ueber die Zahl reden (§5.82)."
    )


async def test_zweiter_durchgang_nur_fuer_getauschte_geraete(
    db_session: AsyncSession,
) -> None:
    """Der Sprung-Pfad kostet nur dort, wo wirklich getauscht wurde.

    Bei 104 Geraeten und einem frischen Batteriewechsel sind es drei
    Statements, nicht 106: das Aggregat, ein Nachschlag fuer das eine
    betroffene Geraet, und die Abfrage der letzten Spannungen. Im
    Normalbetrieb bleibt es bei zwei.
    """
    device_ids = await _seed_bestand(db_session)
    getauscht = device_ids[0]
    # Vier frische Werte weit ueber dem Median dieses Geraets.
    for i in range(4):
        db_session.add(
            SensorReading(
                time=JETZT + timedelta(minutes=10 * (i + 1)),
                device_id=getauscht,
                fcnt=95000 + i,
                battery_voltage=Decimal("3.5"),
            )
        )
    await db_session.flush()

    spaeter = JETZT + timedelta(minutes=50)
    with _zaehle_statements(db_session) as statements:
        verdicts = await battery_verdicts(db_session, device_ids, now=spaeter)

    assert len(statements) == 3, f"{len(statements)} Statements:\n" + "\n".join(statements)
    assert verdicts[getauscht].jump_at is not None
    assert verdicts[getauscht].samples == 4
    assert all(verdicts[d].jump_at is None for d in device_ids[1:])
    # Auch das getauschte Geraet traegt den letzten bekannten Wert.
    assert verdicts[getauscht].last_v == Decimal("3.5")


async def test_explain_plan_der_aggregat_query(
    db_session: AsyncSession, capsys: pytest.CaptureFixture[str]
) -> None:
    """Gibt ``EXPLAIN (ANALYZE, BUFFERS)`` ins Log — der Beleg zum Mitlesen.

    Ohne Zusicherung auf den Plan-Text (§5.79). Der Test faellt nur, wenn
    ``EXPLAIN`` selbst scheitert; sein Wert liegt in der Ausgabe, die im
    CI-Log desselben Laufs steht, der die Laufzeit gemeldet hat — dieselbe
    Begruendung wie fuer ``--durations=15`` (§5.82).
    """
    device_ids = await _seed_bestand(db_session)

    compiled = _aggregat_query(device_ids).compile(
        dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
    )
    plan_rows = (await db_session.execute(text(f"EXPLAIN (ANALYZE, BUFFERS) {compiled}"))).all()

    plan = "\n".join(str(row[0]) for row in plan_rows)
    with capsys.disabled():
        print(f"\n[T4] EXPLAIN der Aggregat-Query ueber {GERAETE} Geraete:\n{plan}")
    assert plan
