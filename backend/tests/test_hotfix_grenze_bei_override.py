"""Die Obergrenze gilt auch bei aktivem Override (Hotfix 18.10.2026).

**Der Befund, gemessen vom Betreiber in Zimmer 306.** Obergrenze 25.
Um 07:37 Drehrad auf 29 → gekappt auf 25, zuletzt gesendet war 21, also
Delta 4 → Downlink, Gerät auf 25. Um 08:48 Drehrad auf 26 → wieder
gekappt auf 25, aber zuletzt gesendet ist jetzt **25**, Delta 0 → die
Hysterese schweigt. Der Engine-Abgleich (20f T3), der genau das fangen
soll, war wegen des aktiven Overrides **vollständig** abgeschaltet. Das
Gerät blieb auf 26 — über der Obergrenze — bis der Sechs-Stunden-
Heartbeat daran vorbeikam.

Die Kappung ist eine Zusicherung (Layer 5, §0 S4). Sie darf nicht davon
abhängen, ob sich der gekappte Wert gerade ändert.

**Vier Prüfungen, und die zweite ist die wichtigere:**

1. Gerät über der Obergrenze bei aktivem Override → Downlink mit dem
   gekappten Wert.
2. **Die Ausnahme hält weiter:** weicht das Gerät *innerhalb* der
   Grenzen ab, bleibt der Abgleich stumm. Ohne diese Prüfung wäre der
   Fix eine Einladung, die Ausnahme ganz zu entfernen — und dann
   überschreibt der Abgleich jede halbe Stunde den Gastwunsch, was
   genau der Grund für ihre Existenz war.
3. Dieselbe Sache nach unten, an der Untergrenze.
4. Ohne Override unverändert — die Bestandslogik aus 20f T3.

DB-Tests; skip ohne ``TEST_DATABASE_URL`` (§5.50, lokal gelaufen).

§5.59: alle Zeitpunkte sind **absolute** Werte gegen ``FROZEN_NOW``.

Der Redis-Doppelgänger kommt aus ``test_engine_abgleich`` statt als
zweite Kopie — eine Attrappe, zwei Dateien (§5.53).
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
import pytest_asyncio
from freezegun import freeze_time
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from heizung.models.control_command import ControlCommand
from heizung.models.device import Device
from heizung.models.enums import (
    CommandReason,
    DeviceKind,
    DeviceVendor,
    HeatingZoneKind,
    OverrideSource,
    RoomStatus,
)
from heizung.models.heating_zone import HeatingZone
from heizung.models.manual_override import ManualOverride
from heizung.models.occupancy import Occupancy
from heizung.models.room import Room
from heizung.models.room_type import RoomType
from heizung.models.sensor_reading import SensorReading
from heizung.rules.engine import evaluate_room
from heizung.services import engine_abgleich
from heizung.tasks import engine_tasks
from heizung.tasks.engine_tasks import _dispatch_downlinks_per_zone
from tests.conftest import purge_test_data_by_prefix
from tests.test_engine_abgleich import _FakeRedis

TEST_DB_URL = os.environ.get("TEST_DATABASE_URL")
SKIP_REASON = "TEST_DATABASE_URL nicht gesetzt - DB-Tests brauchen Postgres"

# schema_constraint: room.number = VARCHAR(20) -> "gr-" + 4 hex = 7
PREFIX = "gr"
DEV_EUI_PATTERN = "beefcafe%"

FROZEN_NOW = datetime(2026, 10, 18, 9, 0, tzinfo=UTC)

#: Die echten Grenzen des Hauses (Betreiber, 18.10.2026): Doppelzimmer
#: und Suite 15 bis 25 °C.
UNTEN, OBEN = 15, 25

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def fake_redis(monkeypatch: pytest.MonkeyPatch) -> _FakeRedis:
    """Ohne Redis sendet der Abgleich **nicht** — ein stiller Lauf wäre
    dann kein Beleg, sondern eine fehlende Abhängigkeit (§5.55)."""
    client = _FakeRedis()
    monkeypatch.setattr(engine_abgleich.redis_client, "get_redis_client", lambda: client)
    return client


@pytest_asyncio.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    if not TEST_DB_URL:
        pytest.skip(SKIP_REASON)
    engine = create_async_engine(TEST_DB_URL)
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    async with sessionmaker() as session:
        await purge_test_data_by_prefix(session, PREFIX, dev_eui_pattern=DEV_EUI_PATTERN)
        try:
            yield session
        finally:
            await session.rollback()
            await purge_test_data_by_prefix(session, PREFIX, dev_eui_pattern=DEV_EUI_PATTERN)
    await engine.dispose()


@pytest.fixture
def mock_send_setpoint(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, int]]:
    aufrufe: list[tuple[str, int]] = []

    async def _mock(dev_eui: str, setpoint_c: int) -> str:
        aufrufe.append((dev_eui, setpoint_c))
        return f"application/x/device/{dev_eui}/command/down"

    monkeypatch.setattr("heizung.tasks.engine_tasks.send_setpoint", _mock)
    return aufrufe


# ---------------------------------------------------------------------------
# Aufbau
# ---------------------------------------------------------------------------


async def _zimmer_306(
    session: AsyncSession,
    *,
    kind: HeatingZoneKind = HeatingZoneKind.BEDROOM,
) -> tuple[int, int]:
    """Belegtes Zimmer mit einer Zone. Gibt ``(room_id, zone_id)``."""
    marker = uuid.uuid4().hex[:4]
    zimmertyp = RoomType(
        name=f"{PREFIX}-dz-{marker}",
        default_t_occupied=Decimal("21.0"),
        default_t_vacant=Decimal("18.0"),
        default_t_night=Decimal("19.0"),
        min_temp_celsius=Decimal(UNTEN),
        max_temp_celsius=Decimal(OBEN),
    )
    session.add(zimmertyp)
    await session.flush()

    room = Room(
        number=f"{PREFIX}-{marker}",
        room_type_id=zimmertyp.id,
        status=RoomStatus.OCCUPIED,
    )
    session.add(room)
    await session.flush()
    session.add(
        Occupancy(
            room_id=room.id,
            check_in=FROZEN_NOW - timedelta(hours=14),
            check_out=FROZEN_NOW + timedelta(days=2),
            is_active=True,
        )
    )
    zone = HeatingZone(room_id=room.id, kind=kind, name="Schlafzimmer")
    session.add(zone)
    await session.flush()
    await session.commit()
    return room.id, zone.id


async def _geraet(
    session: AsyncSession,
    zone_id: int,
    *,
    meldet: int,
    zuletzt_gesendet: int,
) -> int:
    """Gesundes Gerät mit Messwert und Vorgeschichte.

    ``zuletzt_gesendet`` liegt zwei Stunden zurück — über
    ``ABGLEICH_MIN_ABSTAND_S`` (900 s), die Drosselung blockiert also
    nicht, und die Hysterese ist noch weit vom Sechs-Stunden-Heartbeat
    entfernt. Beides absichtlich: der Test soll am **Abgleich** hängen,
    nicht an einer der beiden Fristen.
    """
    marker = uuid.uuid4().hex[:8]
    dev = Device(
        dev_eui=f"beefcafe{marker}",
        kind=DeviceKind.THERMOSTAT,
        vendor=DeviceVendor.MCLIMATE,
        model="Vicki",
        heating_zone_id=zone_id,
        health_state="healthy",
    )
    session.add(dev)
    await session.flush()
    session.add(
        SensorReading(
            time=FROZEN_NOW - timedelta(minutes=5),
            device_id=dev.id,
            temperature=Decimal("23.0"),
            setpoint=Decimal(meldet),
        )
    )
    session.add(
        ControlCommand(
            issued_at=FROZEN_NOW - timedelta(hours=2),
            device_id=dev.id,
            target_setpoint=Decimal(zuletzt_gesendet),
            reason=CommandReason.OCCUPIED_SETPOINT,
            sent_to_gateway_at=FROZEN_NOW - timedelta(hours=2),
        )
    )
    await session.commit()
    return dev.id


async def _drehrad_override(session: AsyncSession, room_id: int, wert: int) -> None:
    """Ein Gast-Override, wie ihn die Drehrad-Erkennung anlegt (AE-45).

    Der gespeicherte Wert ist der **ungekappte** — gekappt wird erst in
    Layer 5. Genau deshalb kann das Gerät über der Grenze stehen.
    """
    session.add(
        ManualOverride(
            room_id=room_id,
            setpoint=Decimal(wert),
            source=OverrideSource.DEVICE,
            expires_at=FROZEN_NOW + timedelta(days=2),
        )
    )
    await session.commit()


# ---------------------------------------------------------------------------
# 1. Der Fall des Betreibers
# ---------------------------------------------------------------------------


@freeze_time(FROZEN_NOW)
async def test_geraet_ueber_der_obergrenze_wird_nachgezogen(
    db_session: AsyncSession,
    mock_send_setpoint: list[tuple[str, int]],
) -> None:
    """Override 26, Obergrenze 25, Gerät meldet 26, zuletzt gesendet 25.

    Die Hysterese schweigt (Delta 0). Der Abgleich muss trotz des
    aktiven Overrides senden, und zwar den **gekappten** Wert 25.
    """
    room_id, zone_id = await _zimmer_306(db_session)
    await _geraet(db_session, zone_id, meldet=26, zuletzt_gesendet=25)
    await _drehrad_override(db_session, room_id, 26)

    _, pro_zone = await _dispatch_downlinks_per_zone(
        session=db_session,
        room_id=room_id,
        target_setpoint_c=OBEN,  # das Ergebnis von Layer 5
        base_reason=CommandReason.GUEST_OVERRIDE,
        eval_id=uuid.uuid4(),
        clamp_grenzen_c=(UNTEN, OBEN),
    )

    assert [sp for _, sp in mock_send_setpoint] == [OBEN]
    assert next(z for z in pro_zone if z["zone_id"] == zone_id)["count_sent"] == 1


@freeze_time(FROZEN_NOW)
async def test_ohne_die_grenzen_bliebe_es_still(
    db_session: AsyncSession,
    mock_send_setpoint: list[tuple[str, int]],
) -> None:
    """Dieselbe Lage mit den **System**-Grenzen (bis 30) → kein Downlink.

    Die Gegenprobe zum Test oben: sie belegt, dass dort die Grenze den
    Downlink ausgelöst hat und nicht irgendetwas anderes im Aufbau. Mit
    einer Obergrenze von 30 liegt das Gerät bei 26 **innerhalb**, und
    die Ausnahme für den Gastwunsch greift wieder.

    Das ist gleichzeitig der Zustand vor dem 18.10. an Zimmern ohne
    gesetzte Raumtyp-Obergrenze — dort war das Verhalten nie falsch.
    """
    room_id, zone_id = await _zimmer_306(db_session)
    await _geraet(db_session, zone_id, meldet=26, zuletzt_gesendet=25)
    await _drehrad_override(db_session, room_id, 26)

    await _dispatch_downlinks_per_zone(
        session=db_session,
        room_id=room_id,
        target_setpoint_c=OBEN,
        base_reason=CommandReason.GUEST_OVERRIDE,
        eval_id=uuid.uuid4(),
        clamp_grenzen_c=(5, 30),
    )

    assert mock_send_setpoint == [], f"kein Downlink erwartet, war: {mock_send_setpoint}"


# ---------------------------------------------------------------------------
# 2. Die Ausnahme hält weiter
# ---------------------------------------------------------------------------


@freeze_time(FROZEN_NOW)
async def test_abweichung_innerhalb_der_grenzen_bleibt_unangetastet(
    db_session: AsyncSession,
    mock_send_setpoint: list[tuple[str, int]],
) -> None:
    """Gast auf 23, Gerät meldet 22 — kein Downlink.

    **Der wichtigste Test dieser Datei.** Der Grund für die Ausnahme in
    20f T3 ist unverändert richtig: ein Gast-Override ist der Fall, in
    dem das Gerät absichtlich abweicht, und ein Abgleich auf „Gerät ≠
    Soll" würde den Gastwunsch alle 15 Minuten überschreiben. Der Hotfix
    darf die Ausnahme **verengen**, nicht aufheben.

    Fällt dieser Test, ist aus einem Fix für eine Grenzverletzung ein
    Dauerstreit mit dem Drehrad geworden.
    """
    room_id, zone_id = await _zimmer_306(db_session)
    await _geraet(db_session, zone_id, meldet=22, zuletzt_gesendet=23)
    await _drehrad_override(db_session, room_id, 23)

    await _dispatch_downlinks_per_zone(
        session=db_session,
        room_id=room_id,
        target_setpoint_c=23,
        base_reason=CommandReason.GUEST_OVERRIDE,
        eval_id=uuid.uuid4(),
        clamp_grenzen_c=(UNTEN, OBEN),
    )

    assert mock_send_setpoint == [], f"kein Downlink erwartet, war: {mock_send_setpoint}"


@freeze_time(FROZEN_NOW)
async def test_geraet_genau_auf_der_obergrenze_ist_innerhalb(
    db_session: AsyncSession,
    mock_send_setpoint: list[tuple[str, int]],
) -> None:
    """Gast auf 23, Gerät meldet genau 25 → kein Downlink.

    Die Grenze ist **inklusiv**. Mit ``<`` statt ``<=`` gälte ein Gerät
    auf der Obergrenze als ausserhalb, und der Abgleich würde es alle 15
    Minuten anfunken — eine Motorbewegung je Lauf für einen Wert, der
    erlaubt ist (§0 S4).

    **Der Aufbau ist mit Absicht so und nicht einfacher.** Ein erster
    Versuch liess das Gerät 25 melden bei Ziel 25; der fiel durch keine
    Mutation, weil die Bedingung ohnehin ``ist != soll`` verlangt und
    beide gleich waren. Der Test prüfte also nichts. Jetzt weicht das
    Gerät ab (25 gegen Ziel 23) und liegt **trotzdem** innerhalb — damit
    hängt das Ergebnis wirklich am Vergleich.
    """
    room_id, zone_id = await _zimmer_306(db_session)
    await _geraet(db_session, zone_id, meldet=OBEN, zuletzt_gesendet=23)
    await _drehrad_override(db_session, room_id, 23)

    await _dispatch_downlinks_per_zone(
        session=db_session,
        room_id=room_id,
        target_setpoint_c=23,
        base_reason=CommandReason.GUEST_OVERRIDE,
        eval_id=uuid.uuid4(),
        clamp_grenzen_c=(UNTEN, OBEN),
    )

    assert mock_send_setpoint == [], f"kein Downlink erwartet, war: {mock_send_setpoint}"


# ---------------------------------------------------------------------------
# 3. Dieselbe Sache nach unten
# ---------------------------------------------------------------------------


@freeze_time(FROZEN_NOW)
async def test_geraet_unter_der_untergrenze_wird_nachgezogen(
    db_session: AsyncSession,
    mock_send_setpoint: list[tuple[str, int]],
) -> None:
    """Gast dreht auf 12, Untergrenze 15, Gerät meldet 12 → Downlink 15.

    Die Richtung ist nicht symmetrisch in ihrer Folge: nach oben zahlt
    das Haus Energie, nach unten friert die Leitung. Die Untergrenze ist
    der Frostschutz — hier wiegt der Fall schwerer als der des
    Betreibers.
    """
    room_id, zone_id = await _zimmer_306(db_session)
    await _geraet(db_session, zone_id, meldet=12, zuletzt_gesendet=UNTEN)
    await _drehrad_override(db_session, room_id, 12)

    await _dispatch_downlinks_per_zone(
        session=db_session,
        room_id=room_id,
        target_setpoint_c=UNTEN,
        base_reason=CommandReason.GUEST_OVERRIDE,
        eval_id=uuid.uuid4(),
        clamp_grenzen_c=(UNTEN, OBEN),
    )

    assert [sp for _, sp in mock_send_setpoint] == [UNTEN]


# ---------------------------------------------------------------------------
# 4. Ohne Override unveraendert
# ---------------------------------------------------------------------------


@freeze_time(FROZEN_NOW)
async def test_ohne_override_gilt_die_bestandslogik(
    db_session: AsyncSession,
    mock_send_setpoint: list[tuple[str, int]],
) -> None:
    """Kein Override, Gerät meldet 20 statt 21 → Downlink 21.

    Der Fall aus 20f T3 (Geräte 048 und 057 nach einer Montage-Drehung).
    Er hängt **nicht** an den Grenzen: 20 liegt innerhalb von 15 bis 25,
    und trotzdem muss gesendet werden, weil ohne Override jede
    Abweichung zählt. Hält dieser Test, ist die neue Bedingung wirklich
    nur ein Zusatz für den Override-Fall.
    """
    room_id, zone_id = await _zimmer_306(db_session)
    await _geraet(db_session, zone_id, meldet=20, zuletzt_gesendet=21)

    await _dispatch_downlinks_per_zone(
        session=db_session,
        room_id=room_id,
        target_setpoint_c=21,
        base_reason=CommandReason.OCCUPIED_SETPOINT,
        eval_id=uuid.uuid4(),
        clamp_grenzen_c=(UNTEN, OBEN),
    )

    assert [sp for _, sp in mock_send_setpoint] == [21]


# ---------------------------------------------------------------------------
# 5. Die Verdrahtung, nicht nur die Bedingung
# ---------------------------------------------------------------------------


@freeze_time(FROZEN_NOW)
async def test_die_grenzen_kommen_wirklich_bis_in_den_dispatch(
    db_session: AsyncSession,
    mock_send_setpoint: list[tuple[str, int]],
) -> None:
    """Derselbe Fall über den ganzen Weg: ``_evaluate_room_async``.

    **Warum dieser Test dazugehört.** Alle Prüfungen oben rufen den
    Dispatch direkt und geben die Grenzen als Argument mit. Sie können
    deshalb nicht sehen, ob die Aufrufstelle sie überhaupt übergibt —
    eine Mutationsprobe, die ``clamp_grenzen_c=result.clamp_grenzen_c``
    aus dem Aufruf entfernt, liess alle sechs grün. Der Dispatch fiele
    dann auf die System-Grenzen (5 bis 30) zurück, und der Fehler des
    Betreibers wäre unverändert da, während die Tests Entwarnung geben
    (§5.55).

    Hier macht die Engine den Lauf selbst: Raumtyp mit Obergrenze 25,
    Gast-Override 26, Gerät meldet 26 und hat zuletzt 25 bekommen. Die
    Engine muss auf 25 kommen und der Abgleich 25 senden.
    """
    room_id, zone_id = await _zimmer_306(db_session)
    await _geraet(db_session, zone_id, meldet=26, zuletzt_gesendet=25)
    await _drehrad_override(db_session, room_id, 26)

    ergebnis = await engine_tasks._evaluate_room_async(room_id)

    assert ergebnis["setpoint_c"] == OBEN, "Layer 5 muss den Override kappen"
    assert [sp for _, sp in mock_send_setpoint] == [OBEN]


@freeze_time(FROZEN_NOW)
async def test_ruleresult_traegt_die_grenzen_des_raumtyps(db_session: AsyncSession) -> None:
    """``evaluate_room`` liefert die wirksamen Grenzen mit.

    Die kleinere Hälfte derselben Verdrahtung, und sie sagt bei einem
    Fehler mehr: fällt dieser Test, fehlen die Grenzen schon im
    Ergebnis; fällt nur der Test darüber, liegt es an der Aufrufstelle.
    """
    room_id, _ = await _zimmer_306(db_session)

    result = await evaluate_room(db_session, room_id)

    assert result is not None
    assert result.clamp_grenzen_c == (UNTEN, OBEN)
