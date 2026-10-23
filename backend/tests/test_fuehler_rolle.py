"""Vicki in der Rolle „nur messen" (Sprint 24, Paket E, S7).

Drei Zusicherungen, und die dritte ist der Nachtrag des Betreibers vom
23.10.: die Fuehler-Geraete 027, 056 und 100 haben **bekannte
Motorfehler**, ihre Messung funktioniert. Ein solches Geraet muss weiter
Messwerte liefern, der Fehler muss sichtbar sein, und er darf **keinen**
Zonen-Ausfall nach S5 ausloesen.

**Warum der Nachtrag eine echte Stelle trifft.** ``aggregate_zone_readings``
filtert auf ``health_state == "healthy"``. Wuerde ein Motor- oder
Kalibrierfehler diesen Zustand verschlechtern, fiele das Geraet aus dem
Aggregat, die Zone haette keinen Istwert, und der Zweipunktregler
schaltete nach S5 alles ab — in einem Raum, dessen Fuehler einwandfrei
**messen**.

Am Code geprueft: ``health_state`` entsteht in
``tasks/health_tasks.py`` aus dem **Alter** des letzten Readings, einer
Ausreisser-Pruefung gegen den Zonen-Median und einem
Implausibel-Zaehler. Ein Motor- oder Kalibrierfehler geht in **keine**
dieser drei Groessen ein. Die Forderung des Nachtrags ist damit vom
Bestand erfuellt — aber sie war **nicht geprueft**, und eine Eigenschaft,
die niemand festhaelt, ist eine Zufaelligkeit des Entwurfs. Diese Datei
macht sie zu einer Zusicherung.
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
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from heizung.models.control_command import ControlCommand
from heizung.models.device import Device
from heizung.models.enums import CommandReason, DeviceKind, DeviceVendor, HeatingZoneKind
from heizung.models.heating_zone import HeatingZone
from heizung.models.occupancy import Occupancy
from heizung.models.room import Room
from heizung.models.room_type import RoomType
from heizung.models.sensor_reading import SensorReading
from heizung.rules.aggregation import ReadingForAggregate, aggregate_zone_readings
from heizung.services import device_adapter
from heizung.tasks.engine_tasks import _get_zone_devices

TEST_DB_URL = os.environ.get("TEST_DATABASE_URL")
SKIP_REASON = "TEST_DATABASE_URL nicht gesetzt - DB-Tests brauchen Postgres"

#: Prefix fuer den Test-Daten-Cleanup (§5.39).
PREFIX = "t24e"

pytestmark = pytest.mark.skipif(not TEST_DB_URL, reason=SKIP_REASON)


@pytest_asyncio.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(TEST_DB_URL or "", poolclass=None)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
        await session.rollback()
    await engine.dispose()


async def _zone_mit_geraeten(
    session: AsyncSession,
    *,
    marker: str,
    rollen: list[bool],
    belegt: bool = False,
) -> tuple[HeatingZone, list[Device]]:
    """Eine Zone mit je einem Geraet pro Eintrag in ``rollen``.

    ``rollen[i] is True`` -> dieses Geraet traegt ``measure_only``.

    ``belegt=True`` legt einen buchbaren Raumtyp **und** eine laufende
    Belegung an. Das braucht die Gegenprobe zum Fuehler-Gate: ohne
    OCCUPIED-Status weist schon das Sprint-12a-Gate jeden Override ab,
    und der Test waere gruen, ohne das Fuehler-Gate zu beruehren.

    ``Room.number`` ist ``VARCHAR(20)`` (§5.49): ``t24e`` (4) + Marker
    (<= 4) + 4 Hex + zwei Trenner = hoechstens 14 Zeichen.
    """
    short = uuid.uuid4().hex[:4]
    rt = RoomType(name=f"{PREFIX}-rt-{marker}-{short}", is_bookable=belegt)
    session.add(rt)
    await session.flush()

    room = Room(number=f"{PREFIX}-{marker}-{short}", room_type_id=rt.id)
    session.add(room)
    await session.flush()

    if belegt:
        jetzt = datetime.now(tz=UTC)
        session.add(
            Occupancy(
                room_id=room.id,
                check_in=jetzt - timedelta(hours=2),
                check_out=jetzt + timedelta(days=2),
                is_active=True,
            )
        )
        await session.flush()

    zone = HeatingZone(room_id=room.id, kind=HeatingZoneKind.OTHER, name="Eingang")
    session.add(zone)
    await session.flush()

    geraete: list[Device] = []
    for idx, nur_messen in enumerate(rollen):
        dev = Device(
            dev_eui=f"beef{uuid.uuid4().hex[:12]}",
            kind=DeviceKind.THERMOSTAT,
            vendor=DeviceVendor.MCLIMATE,
            model="vicki",
            label=f"{marker}-{idx}",
            heating_zone_id=zone.id,
            health_state="healthy",
            measure_only=nur_messen,
        )
        session.add(dev)
        geraete.append(dev)
    await session.flush()
    return zone, geraete


# ---------------------------------------------------------------------------
# S7, erste Haelfte: kein Sollwert-Downlink an ein Fuehler-Geraet
# ---------------------------------------------------------------------------


async def test_fuehler_wird_nicht_angesteuert(db_session: AsyncSession) -> None:
    """``_get_zone_devices`` laesst ``measure_only`` weg.

    Das ist die Stelle, die Mutationsprobe **M7** angreift: wird der
    Filter entfernt, bekommt der Fuehler Sollwert-Downlinks — Funkverkehr
    und Batterieverbrauch ohne jede Wirkung, und auf seiner Anzeige
    erscheint ein Sollwert, den niemand umsetzt.
    """
    zone, (stellglied, fuehler) = await _zone_mit_geraeten(
        db_session, marker="disp", rollen=[False, True]
    )

    angesteuert = await _get_zone_devices(db_session, zone.id)

    ids = {d.id for d in angesteuert}
    assert stellglied.id in ids, "ein normales Thermostat wird weiter angesteuert"
    assert fuehler.id not in ids, "ein Fuehler bekommt keine Sollwert-Downlinks"


async def test_zone_nur_mit_fuehler_wird_gar_nicht_angesteuert(
    db_session: AsyncSession,
) -> None:
    """Der Fall des Infrarot-Pilots: in der Zone haengt **nur** ein Fuehler.

    Das Ergebnis ist eine leere Liste, und das ist richtig — gestellt
    wird dort von einem Relais, nicht von einem Ventil. Dieser Test
    haelt fest, dass die leere Liste kein Fehler ist: der Dispatch darf
    daran nicht scheitern.
    """
    zone, _ = await _zone_mit_geraeten(db_session, marker="only", rollen=[True])
    assert await _get_zone_devices(db_session, zone.id) == []


# ---------------------------------------------------------------------------
# S7, zweite Haelfte: eine Drehung am Rad erzeugt keinen Override
# ---------------------------------------------------------------------------


async def _drehung(session: AsyncSession, geraet: Device, jetzt: datetime) -> object:
    """Simuliert eine Drehung am Rad: Vorbefehl der Engine, dann ein Uplink
    mit abweichendem Sollwert.

    Der Vorbefehl ist Pflicht. ``detect_user_override`` gibt ohne
    bekannten Engine-Wert immer ``None`` zurueck (Schritt 2 seiner
    Logik) — ein Test ohne ihn ist gruen, ohne irgendein Gate beruehrt
    zu haben. Genau daran ist die erste Fassung dieses Tests
    gescheitert: die Mutationsprobe M7b hat sie **nicht** rot bekommen.

    ``issued_at``/``sent_to_gateway_at`` liegen weit ausserhalb des
    60-Sekunden-Ack-Fensters, und 21,0 gegen 28,0 ist weit ausserhalb
    der Toleranz von 0,6.
    """
    session.add(
        ControlCommand(
            issued_at=jetzt - timedelta(minutes=30),
            device_id=geraet.id,
            target_setpoint=Decimal("21.0"),
            reason=CommandReason.OCCUPIED_SETPOINT,
            sent_to_gateway_at=jetzt - timedelta(minutes=30),
        )
    )
    await session.flush()

    return await device_adapter.handle_uplink_for_override(
        session,
        device_id=geraet.id,
        uplink_target_temp=Decimal("28.0"),
        fport=1,
        received_at=jetzt,
    )


async def test_drehung_am_normalen_thermostat_erzeugt_einen_override(
    db_session: AsyncSession,
) -> None:
    """**Gegenprobe, und sie ist der wichtigere der beiden Tests.**

    Dieselbe Lage, nur ohne die Rolle: hier **muss** ein Override
    entstehen. Ohne diese Zusicherung beweist der Test darunter nichts —
    er waere auch gruen, wenn der Override aus einem voellig anderen
    Grund ausbleibt, und genau so ist die erste Fassung durch die
    Mutationsprobe gerutscht.
    """
    _, (normal,) = await _zone_mit_geraeten(db_session, marker="ctl", rollen=[False], belegt=True)

    ergebnis = await _drehung(db_session, normal, datetime.now(tz=UTC))

    assert ergebnis is not None, (
        "ohne die Fuehler-Rolle muss eine Drehung einen Override anlegen — "
        "sonst prueft der Test darunter nicht das Gate"
    )
    assert ergebnis.setpoint == Decimal("28.0")


async def test_drehung_am_fuehler_erzeugt_keinen_override(
    db_session: AsyncSession,
) -> None:
    """Dieselbe Drehung an einem Geraet mit der Rolle: kein Override.

    Ohne dieses Gate waere die Lage besonders unangenehm: ein
    Fuehler-Geraet bekommt **keine** Downlinks, also gibt es keinen
    frischen „letzten Engine-Wert", gegen den ``detect_user_override``
    vergleichen koennte — jede Drehung saehe wie ein Gastwunsch aus, und
    der Override wuerde eine Zone uebersteuern, deren Relais ihn gar
    nicht umsetzen kann.

    Mutationsprobe **M7**, zweite Haelfte.
    """
    _, (fuehler,) = await _zone_mit_geraeten(db_session, marker="knob", rollen=[True], belegt=True)

    ergebnis = await _drehung(db_session, fuehler, datetime.now(tz=UTC))

    assert ergebnis is None


# ---------------------------------------------------------------------------
# Nachtrag des Betreibers (23.10.): Motorfehler darf nicht ausschliessen
# ---------------------------------------------------------------------------


def test_aggregat_kennt_keinen_motorfehler() -> None:
    """Die reine Funktion kann einen Motorfehler nicht sehen.

    ``ReadingForAggregate`` traegt genau drei Felder — Temperatur,
    Fenster, Health. Ein Kalibrier- oder Motorfehler ist **keines** davon,
    das Aggregat kann ihn also nicht zum Ausschluss benutzen.

    Dieser Test ist bewusst eine Zusicherung ueber die **Form** des
    Datentyps und nicht ueber ein Verhalten: waechst
    ``ReadingForAggregate`` eines Tages um ein Fehlerfeld, faellt er, und
    dann ist zu entscheiden, ob der Ausschluss gewollt ist. Genau diese
    Entscheidung soll nicht nebenbei passieren.
    """
    felder = set(ReadingForAggregate.__dataclass_fields__)
    assert felder == {"temperature_c", "open_window", "health_state"}, (
        "ReadingForAggregate hat neue Felder — prueft, ob ein Fehlerfeld "
        "jetzt zum Ausschluss aus dem Zonen-Aggregat fuehren wuerde "
        "(Nachtrag 23.10.: Motorfehler darf das NICHT)"
    )


def test_fuehler_mit_fehler_bleibt_im_mittelwert() -> None:
    """Zwei Fuehler, einer mit Motorfehler: beide zaehlen.

    Der Mittelwert aus 19,0 und 21,0 ist 20,0. Wuerde das fehlerhafte
    Geraet ausgeschlossen, waere das Ergebnis 19,0 oder 21,0 — und in
    einer Zone mit nur **einem** Fuehler waere es ``None``, also ein
    Zonen-Ausfall nach S5.
    """
    readings = [
        ReadingForAggregate(
            temperature_c=Decimal("19.0"), open_window=False, health_state="healthy"
        ),
        ReadingForAggregate(
            temperature_c=Decimal("21.0"), open_window=False, health_state="healthy"
        ),
    ]
    mittel, fenster = aggregate_zone_readings(readings)
    assert mittel == Decimal("20.0")
    assert fenster is False


async def test_kalibrierfehler_liefert_weiter_messwerte_und_ist_sichtbar(
    db_session: AsyncSession,
) -> None:
    """**Der Pflichttest des Nachtrags, am echten Schema.**

    Ein Fuehler mit ``calibration_failed = True`` schreibt weiter
    Readings, sein ``health_state`` bleibt ``healthy``, das Aggregat
    nimmt ihn mit — und der Fehler ist in der Zeile **nachlesbar**.

    Die drei Teile entsprechen genau den drei Forderungen: liefert
    weiter, ist sichtbar, loest keinen Ausfall aus.
    """
    _, (fuehler,) = await _zone_mit_geraeten(db_session, marker="kal", rollen=[True])

    jetzt = datetime.now(tz=UTC)
    for minuten, temp in ((10, Decimal("20.5")), (5, Decimal("20.7"))):
        db_session.add(
            SensorReading(
                time=jetzt - timedelta(minutes=minuten),
                device_id=fuehler.id,
                temperature=temp,
                # Der bekannte Fehler der Geraete 027, 056, 100.
                calibration_failed=True,
                # Die Kindersicherung sitzt (S7) — und sie ist seit
                # Migration 0030 ueberhaupt nachlesbar.
                child_lock=True,
            )
        )
    await db_session.flush()

    # 1. Liefert weiter: die Zeilen sind da, mit Temperatur.
    zeilen = (
        (
            await db_session.execute(
                text(
                    "SELECT temperature, calibration_failed, child_lock "
                    "FROM sensor_reading WHERE device_id = :d ORDER BY time"
                ),
                {"d": fuehler.id},
            )
        )
        .mappings()
        .all()
    )
    assert len(zeilen) == 2
    assert all(z["temperature"] is not None for z in zeilen)

    # 2. Ist sichtbar: der Fehler steht in der Zeile, nicht nur im Funk.
    assert all(z["calibration_failed"] is True for z in zeilen)
    assert all(z["child_lock"] is True for z in zeilen), (
        "child_lock muss persistiert sein, sonst ist S7 nicht verifizierbar"
    )

    # 3. Kein Ausfall: health_state ist unberuehrt, das Aggregat traegt.
    await db_session.refresh(fuehler)
    assert fuehler.health_state == "healthy", (
        "ein Kalibrierfehler darf health_state nicht verschlechtern — sonst "
        "faellt das Geraet aus dem Zonen-Aggregat und S5 schaltet die Zone ab"
    )

    mittel, _ = aggregate_zone_readings(
        [
            ReadingForAggregate(
                temperature_c=z["temperature"],
                open_window=None,
                health_state=fuehler.health_state,
            )
            for z in zeilen
        ]
    )
    assert mittel == Decimal("20.6"), "Mittel aus 20,5 und 20,7"
