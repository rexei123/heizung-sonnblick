"""Geraete-Sicherheit und die Fuehler-Rolle (Sprint 24b, Paket 4).

**Der Anlass kommt aus dem Betrieb, 24.10.2026.** In den Zimmern „Bar"
und „Rezeption" liegt je eine unmontierte Vicki als Fuehler (027 und
056). Der Schicht-Trace beider Zimmer zeigte
``Layer Geraete-Sicherheit`` mit ``detached_devices`` und einem
erzwungenen Sollwert von **10 °C** — zu Recht aus Sicht der Schicht, die
Vicki liegt ja auf dem Tisch, und falsch aus Sicht des Hauses: ein
Infrarot-Pilot, dessen Soll auf Frostschutz gezogen wird, heizt nie.

**Die Gegenprobe ist der wichtigere Teil dieser Datei.** Eine Ausnahme
fuer Fuehler darf die Schicht fuer echte Thermostate nicht aufweichen —
sonst bekaeme ein Geraet, das wirklich von der Wand faellt, keinen
Frostschutz mehr. Das ist Mutationsprobe **M13**, und ohne den zweiten
Test waere sie nicht zu fangen.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from heizung.models.device import Device
from heizung.models.enums import (
    CommandReason,
    DeviceKind,
    DeviceVendor,
    HeatingZoneKind,
    RoomStatus,
)
from heizung.models.heating_zone import HeatingZone
from heizung.models.room import Room
from heizung.models.room_type import RoomType
from heizung.models.sensor_reading import SensorReading
from heizung.rules.engine import layer_device_detached

TEST_DB_URL = os.environ.get("TEST_DATABASE_URL")
SKIP_REASON = "TEST_DATABASE_URL nicht gesetzt - DB-Tests brauchen Postgres"
PREFIX = "t24b"

pytestmark = pytest.mark.skipif(not TEST_DB_URL, reason=SKIP_REASON)

#: Der Wert, den die Schicht erzwingt, wenn alle Geraete abgenommen sind.
FROSTSCHUTZ_C = 10
#: Was vor der Schicht im Trace stand.
VORHER_C = 21


@pytest_asyncio.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(TEST_DB_URL or "", poolclass=None)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
        await session.rollback()
    await engine.dispose()


async def _raum_mit_geraet(
    session: AsyncSession,
    *,
    marker: str,
    measure_only: bool,
    abgenommen: bool,
) -> int:
    """Ein Zimmer mit einer Zone und **einem** Geraet.

    ``abgenommen=True`` schreibt zwei frische Frames mit
    ``attached_backplate=False`` — genau die Bedingung, die die Schicht
    als „abgenommen" liest (zwei frische, uebereinstimmende Frames).

    ``Room.number`` ist ``VARCHAR(20)`` (§5.49): ``t24b`` (4) + Marker
    (<= 4) + 4 Hex + zwei Trenner = hoechstens 14 Zeichen.
    """
    short = uuid.uuid4().hex[:4]
    rt = RoomType(name=f"{PREFIX}-rt-{marker}-{short}")
    session.add(rt)
    await session.flush()

    room = Room(number=f"{PREFIX}-{marker}-{short}", room_type_id=rt.id)
    session.add(room)
    await session.flush()

    zone = HeatingZone(room_id=room.id, kind=HeatingZoneKind.OTHER, name="Eingang")
    session.add(zone)
    await session.flush()

    dev = Device(
        dev_eui=f"beef{uuid.uuid4().hex[:12]}",
        kind=DeviceKind.THERMOSTAT,
        vendor=DeviceVendor.MCLIMATE,
        model="vicki",
        label=f"{marker}-vicki",
        heating_zone_id=zone.id,
        health_state="healthy",
        measure_only=measure_only,
    )
    session.add(dev)
    await session.flush()

    jetzt = datetime.now(tz=UTC)
    for minuten in (10, 5):
        session.add(
            SensorReading(
                time=jetzt - timedelta(minutes=minuten),
                device_id=dev.id,
                temperature=Decimal("20.0"),
                attached_backplate=not abgenommen,
            )
        )
    await session.flush()
    return room.id


async def _schicht(session: AsyncSession, room_id: int):
    return await layer_device_detached(
        session,
        room_id,
        prev_setpoint_c=VORHER_C,
        prev_reason=CommandReason.OCCUPIED_SETPOINT,
        room_status=RoomStatus.VACANT,
        now=datetime.now(tz=UTC),
    )


# ---------------------------------------------------------------------------
# Der Fall aus dem Betrieb
# ---------------------------------------------------------------------------


async def test_abgenommener_fuehler_erzwingt_keinen_frostschutz(
    db_session: AsyncSession,
) -> None:
    """**Der Befund vom 24.10., behoben.**

    Eine unmontierte Vicki mit der Rolle „nur messen" ist das einzige
    Geraet der Zone. Vorher: zwei Frames ``attached_backplate=False``,
    alle Geraete abgenommen, Trigger, 10 °C. Jetzt: das Geraet ist in
    dieser Schicht gar nicht dabei, die Liste bleibt leer, und der
    Sollwert geht unveraendert durch.
    """
    room_id = await _raum_mit_geraet(db_session, marker="fueh", measure_only=True, abgenommen=True)

    schritt = await _schicht(db_session, room_id)

    assert schritt.setpoint_c == VORHER_C, "kein Frostschutz-Zwang"
    assert schritt.detail == "no_devices_in_zone"
    assert schritt.extras["detached_devices"] == []


async def test_fuehler_taucht_nicht_als_abgenommen_auf(
    db_session: AsyncSession,
) -> None:
    """Auch die **Anzeige** soll ihn nicht als abgenommen fuehren.

    ``extras["detached_devices"]`` landet im Schicht-Trace, und der
    Hotelier liest ihn. Ein Fuehler, der dort als abgenommen steht, ist
    ein Befund, der keiner ist — und er verdeckt die echten.
    """
    room_id = await _raum_mit_geraet(db_session, marker="anz", measure_only=True, abgenommen=True)
    schritt = await _schicht(db_session, room_id)
    assert schritt.extras["detached_devices"] == []
    assert schritt.extras["sticky_devices"] == []


# ---------------------------------------------------------------------------
# Gegenprobe — M13
# ---------------------------------------------------------------------------


async def test_abgenommenes_normales_thermostat_erzwingt_weiter_frostschutz(
    db_session: AsyncSession,
) -> None:
    """**Mutationsprobe M13, und der Grund fuer diese Datei.**

    Dasselbe Geraet, dieselben Frames, nur **ohne** die Rolle: hier
    **muss** der Frostschutz greifen. Gilt die Ausnahme auch fuer normale
    Thermostate, bekommt ein Geraet, das wirklich von der Wand faellt,
    keinen Schutz mehr — und das waere eine Abschwaechung der Sicherheit
    zugunsten eines Geraets, das gar kein Ventil hat.
    """
    room_id = await _raum_mit_geraet(db_session, marker="gast", measure_only=False, abgenommen=True)

    schritt = await _schicht(db_session, room_id)

    assert schritt.setpoint_c == FROSTSCHUTZ_C, (
        "ein abgenommenes normales Thermostat muss weiter 10 °C erzwingen — "
        "sonst gilt die Fuehler-Ausnahme fuer alle Geraete (M13)"
    )
    assert schritt.reason == CommandReason.DEVICE_DETACHED
    assert len(schritt.extras["detached_devices"]) == 1


async def test_montiertes_normales_thermostat_bleibt_unberuehrt(
    db_session: AsyncSession,
) -> None:
    """Der Normalfall, zur Sicherheit mitgeprueft: nichts passiert."""
    room_id = await _raum_mit_geraet(
        db_session, marker="norm", measure_only=False, abgenommen=False
    )
    schritt = await _schicht(db_session, room_id)
    assert schritt.setpoint_c == VORHER_C
    assert schritt.extras["detached_devices"] == []


async def test_fuehler_verhindert_den_trigger_nicht(
    db_session: AsyncSession,
) -> None:
    """**Der Fall, der gegen „zaehlt als attached" entschieden hat.**

    Eine Zone mit einem abgenommenen **echten** Thermostat und einem
    Fuehler daneben. Zaehlte der Fuehler als attached, waere die
    UND-Bedingung („alle abgenommen") nie erfuellt, und das echte Geraet
    bekaeme keinen Frostschutz. Weil er herausgenommen wird, entscheidet
    das echte Geraet allein — und der Trigger greift.
    """
    short = uuid.uuid4().hex[:4]
    rt = RoomType(name=f"{PREFIX}-rt-mix-{short}")
    db_session.add(rt)
    await db_session.flush()
    room = Room(number=f"{PREFIX}-mix-{short}", room_type_id=rt.id)
    db_session.add(room)
    await db_session.flush()
    zone = HeatingZone(room_id=room.id, kind=HeatingZoneKind.OTHER, name="Eingang")
    db_session.add(zone)
    await db_session.flush()

    jetzt = datetime.now(tz=UTC)
    for rolle in (True, False):
        dev = Device(
            dev_eui=f"beef{uuid.uuid4().hex[:12]}",
            kind=DeviceKind.THERMOSTAT,
            vendor=DeviceVendor.MCLIMATE,
            model="vicki",
            heating_zone_id=zone.id,
            health_state="healthy",
            measure_only=rolle,
        )
        db_session.add(dev)
        await db_session.flush()
        for minuten in (10, 5):
            db_session.add(
                SensorReading(
                    time=jetzt - timedelta(minutes=minuten),
                    device_id=dev.id,
                    temperature=Decimal("20.0"),
                    attached_backplate=False,
                )
            )
    await db_session.flush()

    schritt = await _schicht(db_session, room.id)

    assert schritt.setpoint_c == FROSTSCHUTZ_C
    assert len(schritt.extras["detached_devices"]) == 1, (
        "nur das echte Thermostat zaehlt — der Fuehler ist gar nicht dabei"
    )
