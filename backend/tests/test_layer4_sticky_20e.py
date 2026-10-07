"""Sprint 20e T4 + T5 — der Montage-Nachweis schlaegt den Taster.

**Der Befund hinter dem Sprint.** Layer 4 fragte "sitzt das Geraet jetzt?"
und las dafuer ``attached_backplate`` der letzten zwei frischen Frames. Der
Taster meldet im Haus zu oft ``false``, obwohl das Geraet sitzt — und die
Engine schaltete daraufhin ein belegtes Zimmer in den Frostschutz. Ein
Melder, dem niemand glaubt, ueberwacht nichts (§5.79).

Seit T4 gilt: ein Geraet mit ``device.mounted_confirmed_at`` zaehlt als
montiert, egal was der Taster meldet.

Diese Datei prueft vier Dinge, und das erste ist das wichtigste:

1. **Fuer Geraete OHNE Nachweis ist nichts anders** — einschliesslich des
   Falls, den der Hotelier ausdruecklich sehen wollte: neu zugeordnet,
   Zimmer warm, Ventil wochenlang 0 %, also kein Nachweis. Kein
   Sicherheitsmodus, der aktuelle ``attached_backplate`` entscheidet wie vor
   20e.
2. **Mit Nachweis kippt das Zimmer nicht**, auch nicht bei zwei
   ``false``-Frames.
3. **Gemischtes Zimmer: Variante (a)** — ein Geraet mit Nachweis verhindert
   den Trigger fuer das ganze Zimmer. Entscheidung des Hoteliers vom
   07.10.2026.
4. **Die Oberflaeche urteilt aus derselben Quelle** (T5), damit Pille und
   Engine nicht verschiedene Dinge behaupten (§5.53).

Die zehn Bestandstests in ``test_engine_layer4_detached.py`` sind der
fuenfte Beleg und der strengste: sie setzen keinen Nachweis und muessen
**ohne Anpassung** gruen bleiben (§5.47). Diese Datei ergaenzt sie, sie
ersetzt sie nicht.

DB-Tests skippen ohne ``TEST_DATABASE_URL`` (§5.50).
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete as sa_delete
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from heizung.db import get_session
from heizung.models.device import Device
from heizung.models.enums import (
    CommandReason,
    DeviceKind,
    DeviceVendor,
    EventLogLayer,
    HeatingZoneKind,
)
from heizung.models.heating_zone import HeatingZone
from heizung.models.room import Room
from heizung.models.room_type import RoomType
from heizung.models.sensor_reading import SensorReading
from heizung.rules.engine import MIN_SETPOINT_C, LayerStep, evaluate_room

TEST_DB_URL = os.environ.get("TEST_DATABASE_URL")
SKIP_REASON = "TEST_DATABASE_URL nicht gesetzt - DB-Tests brauchen Postgres"

NACHWEIS_AM = datetime(2026, 10, 1, 9, 0, 0, tzinfo=UTC)

# Praefixe fuer die Cleanup-Fixture (§5.39). ``4a5e`` + 8 Hex + 1 = 13
# Zeichen, passt in ``device.dev_eui`` VARCHAR(16).
EUI_PREFIX = "4a5e"
RAUM_PREFIX = "l4s-"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    """Session mit Cleanup vor und nach dem Test.

    Die T4-Tests kaemen mit einem Rollback aus, die T5-Tests nicht: dort
    liest die App in einer **eigenen** Session, der Test muss also
    committen. Damit ist der Rollback wirkungslos und das Aufraeumen
    Pflicht — sonst sehen spaetere Tests, die ueber alle Geraete gehen
    (Health-Compute, Dashboard-Aggregate), diese Zeilen (§5.39).
    """
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
    """Test-Zeilen loeschen, FK-sicher sortiert."""
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
    # Zonen haengen per ON DELETE CASCADE am Raum.
    await session.execute(sa_delete(Room).where(Room.number.like(f"{RAUM_PREFIX}%")))
    await session.execute(sa_delete(RoomType).where(RoomType.name.like(f"{RAUM_PREFIX}rt-%")))


async def _setup(session: AsyncSession, *, zonen: int) -> dict[str, Any]:
    """Raum mit ``zonen`` Heizzonen und je einem Geraet.

    # schema_constraint: room.number max 20, room_type.name max 50
    # schema_constraint: device.dev_eui VARCHAR(16), heating_zone.kind NOT NULL

    ``l4s-`` + 8 Hex = 12 Zeichen (§5.18/§5.49). ``health_state="healthy"``
    wie in den Bestandstests: Layer 4 Window aggregiert nur ueber gesunde
    Geraete, und die Pipeline laeuft hier vollstaendig.
    """
    suffix = uuid.uuid4().hex[:8]
    rt = RoomType(name=f"{RAUM_PREFIX}rt-{suffix}")
    session.add(rt)
    await session.flush()

    room = Room(number=f"{RAUM_PREFIX}{suffix}", room_type_id=rt.id)
    session.add(room)
    await session.flush()

    arten = [HeatingZoneKind.BEDROOM, HeatingZoneKind.BATHROOM]
    geraete: list[Device] = []
    for i in range(zonen):
        zone = HeatingZone(room_id=room.id, kind=arten[i % 2], name=f"z{i}")
        session.add(zone)
        await session.flush()
        device = Device(
            dev_eui=f"{EUI_PREFIX}{suffix}{i}",
            kind=DeviceKind.THERMOSTAT,
            vendor=DeviceVendor.MCLIMATE,
            model="vicki",
            heating_zone_id=zone.id,
            health_state="healthy",
        )
        session.add(device)
        await session.flush()
        geraete.append(device)

    return {
        "room_id": room.id,
        "devices": geraete,
        "ids": [d.id for d in geraete],
        "euis": [d.dev_eui for d in geraete],
    }


async def _frame(
    session: AsyncSession,
    *,
    device_id: int,
    attached_backplate: bool | None,
    age_min: int,
    valve: int | None = None,
) -> None:
    session.add(
        SensorReading(
            time=datetime.now(tz=UTC) - timedelta(minutes=age_min),
            device_id=device_id,
            fcnt=age_min,
            temperature=Decimal("21.0"),
            valve_position=valve,
            attached_backplate=attached_backplate,
        )
    )
    await session.flush()


def _detached_step(layers: tuple[LayerStep, ...]) -> LayerStep:
    matches = [layer for layer in layers if layer.layer == EventLogLayer.DEVICE_DETACHED]
    assert len(matches) == 1, f"erwarte genau 1 Detached-Eintrag, gefunden {len(matches)}"
    return matches[0]


# ---------------------------------------------------------------------------
# 1. Ohne Nachweis: unveraendertes Verhalten
# ---------------------------------------------------------------------------


async def test_ohne_nachweis_ventil_wochenlang_zu_verhaelt_sich_wie_vor_20e(
    db_session: AsyncSession,
) -> None:
    """**Der Fall, den der Hotelier belegt sehen wollte.**

    Neu zugeordnet, Zimmer warm, Ventil seit Wochen 0 % — es entsteht also
    kein Montage-Nachweis, weil T3 beide Merkmale im selben Frame verlangt.
    Erwartung: kein Sicherheitsmodus, kein Sonderpfad; der aktuelle
    ``attached_backplate`` entscheidet wie vor 20e, hier also Trigger.

    Der eigentliche Beleg steckt im ``valve_position=0`` auf **allen**
    Frames: ``valve_position`` kommt in ``rules/engine.py`` nicht ein
    einziges Mal vor, das Ventil ist ausschliesslich Teil der
    Nachweis-Bedingung. Dieser Test haelt die Unabhaengigkeit fest, damit
    sie eine Entscheidung bleibt und nicht jemand spaeter annimmt, ein
    geschlossenes Ventil muesse Layer 4 etwas sagen.
    """
    s = await _setup(db_session, zonen=1)
    dev_id = s["ids"][0]
    await _frame(db_session, device_id=dev_id, attached_backplate=False, age_min=15, valve=0)
    await _frame(db_session, device_id=dev_id, attached_backplate=False, age_min=2, valve=0)

    result = await evaluate_room(db_session, s["room_id"])
    assert result is not None
    detached = _detached_step(result.layers)
    assert detached.reason == CommandReason.DEVICE_DETACHED
    assert detached.setpoint_c == MIN_SETPOINT_C
    assert result.setpoint_c == MIN_SETPOINT_C
    assert detached.extras is not None
    assert detached.extras["sticky_devices"] == [], "ohne Nachweis ist nichts sticky"


async def test_ohne_nachweis_frischer_true_frame_haelt_wie_vorher(
    db_session: AsyncSession,
) -> None:
    """Die Gegenrichtung desselben Falls: der Taster meldet, also gilt er."""
    s = await _setup(db_session, zonen=1)
    dev_id = s["ids"][0]
    await _frame(db_session, device_id=dev_id, attached_backplate=False, age_min=15, valve=0)
    await _frame(db_session, device_id=dev_id, attached_backplate=True, age_min=2, valve=0)

    result = await evaluate_room(db_session, s["room_id"])
    assert result is not None
    detached = _detached_step(result.layers)
    assert detached.detail == "device_attached"
    assert result.setpoint_c == 18


# ---------------------------------------------------------------------------
# 2. Mit Nachweis: das Zimmer kippt nicht
# ---------------------------------------------------------------------------


async def test_nachweis_verhindert_trigger_trotz_zweier_false_frames(
    db_session: AsyncSession,
) -> None:
    """**Der Kern von T4.** Genau die Lage, die 20e ausgeloest hat.

    Zwei frische ``false``-Frames waeren vor 20e der Frostschutz-Trigger
    gewesen. Mit Nachweis bleibt das Zimmer auf seinem Sollwert, und der
    Trace nennt den Grund: ``sticky_mounted``.
    """
    s = await _setup(db_session, zonen=1)
    device = s["devices"][0]
    device.mounted_confirmed_at = NACHWEIS_AM
    await db_session.flush()
    dev_id, dev_eui = device.id, device.dev_eui

    await _frame(db_session, device_id=dev_id, attached_backplate=False, age_min=15)
    await _frame(db_session, device_id=dev_id, attached_backplate=False, age_min=2)

    result = await evaluate_room(db_session, s["room_id"])
    assert result is not None
    detached = _detached_step(result.layers)
    assert detached.reason != CommandReason.DEVICE_DETACHED
    assert detached.detail == "sticky_mounted"
    assert detached.extras is not None
    assert detached.extras["sticky_devices"] == [dev_eui]
    assert detached.extras["detached_devices"] == [], "ein sticky Geraet gilt nicht als detached"
    assert result.setpoint_c == 18


async def test_nachweis_ohne_jeden_frame_haelt_ebenfalls(db_session: AsyncSession) -> None:
    """Der Nachweis wirkt auch, wenn im Fenster gar nichts ankommt.

    Vor 20e war das ``device_unclear`` — kein Trigger, aber auch keine
    Aussage. Jetzt ist es eine: das Geraet sitzt, es meldet nur gerade
    nicht. Das ist der Unterschied zwischen "wir wissen nichts" und "wir
    wissen es, und zwar seit dem ersten Beleg".
    """
    s = await _setup(db_session, zonen=1)
    device = s["devices"][0]
    device.mounted_confirmed_at = NACHWEIS_AM
    await db_session.flush()

    result = await evaluate_room(db_session, s["room_id"])
    assert result is not None
    detached = _detached_step(result.layers)
    assert detached.detail == "sticky_mounted"
    assert result.setpoint_c == 18


# ---------------------------------------------------------------------------
# 3. Gemischtes Zimmer — Variante (a)
# ---------------------------------------------------------------------------


async def test_gemischtes_zimmer_nachweis_schuetzt_das_ganze_zimmer(
    db_session: AsyncSession,
) -> None:
    """**Variante (a), Entscheidung des Hoteliers vom 07.10.2026.**

    Schlafzimmer mit Nachweis, Bad ohne, beide melden zwei ``false``-Frames.
    Das Zimmer kippt **nicht**.

    Variante (b) — das Geraet mit Nachweis aus der Liste nehmen — haette das
    Bad-Geraet allein entscheiden lassen, und ein einzelner unbewiesener
    Taster haette das ganze Zimmer in den Frostschutz geschickt. Genau diese
    Lage beendet 20e; dieser Test ist der Wachposten dagegen.
    """
    s = await _setup(db_session, zonen=2)
    mit_nachweis, ohne_nachweis = s["devices"]
    mit_nachweis.mounted_confirmed_at = NACHWEIS_AM
    await db_session.flush()
    eui_mit = mit_nachweis.dev_eui
    eui_ohne = ohne_nachweis.dev_eui

    for dev_id, alter in ((mit_nachweis.id, 15), (mit_nachweis.id, 2)):
        await _frame(db_session, device_id=dev_id, attached_backplate=False, age_min=alter)
    for dev_id, alter in ((ohne_nachweis.id, 14), (ohne_nachweis.id, 3)):
        await _frame(db_session, device_id=dev_id, attached_backplate=False, age_min=alter)

    result = await evaluate_room(db_session, s["room_id"])
    assert result is not None
    detached = _detached_step(result.layers)
    assert detached.reason != CommandReason.DEVICE_DETACHED
    assert detached.detail == "sticky_mounted"
    assert detached.extras is not None
    assert detached.extras["sticky_devices"] == [eui_mit]
    # Das Bad-Geraet bleibt als detached ausgewiesen — der Operator soll
    # sehen, dass dort etwas ist, auch wenn es nichts ausloest.
    assert detached.extras["detached_devices"] == [eui_ohne]
    assert result.setpoint_c == 18


async def test_frischer_true_frame_schlaegt_den_nachweis_im_trace(
    db_session: AsyncSession,
) -> None:
    """Reihenfolge des Trace-Details nach Beweiskraft, nicht nach Neuheit.

    Geraet A hat den Nachweis und meldet ``false``, Geraet B meldet frisch
    ``true``. Beide verhindern den Trigger. Im Trace steht
    ``device_attached``, weil ein aktueller True-Frame der bessere Beleg ist
    als ein Nachweis von vorletzter Woche — ``sticky_mounted`` soll genau
    dann erscheinen, wenn das Urteil **nur** am Nachweis haengt.
    """
    s = await _setup(db_session, zonen=2)
    mit_nachweis, anderes = s["devices"]
    mit_nachweis.mounted_confirmed_at = NACHWEIS_AM
    await db_session.flush()

    await _frame(db_session, device_id=mit_nachweis.id, attached_backplate=False, age_min=15)
    await _frame(db_session, device_id=mit_nachweis.id, attached_backplate=False, age_min=2)
    await _frame(db_session, device_id=anderes.id, attached_backplate=True, age_min=14)
    await _frame(db_session, device_id=anderes.id, attached_backplate=True, age_min=3)

    result = await evaluate_room(db_session, s["room_id"])
    assert result is not None
    detached = _detached_step(result.layers)
    assert detached.detail == "device_attached"
    assert detached.extras is not None
    assert detached.extras["sticky_devices"] == [mit_nachweis.dev_eui]


async def test_geloeschter_nachweis_laesst_den_trigger_zurueckkommen(
    db_session: AsyncSession,
) -> None:
    """**Die Hin- und Rueckrichtung in einem Test.**

    Erst mit Nachweis kein Trigger, dann Nachweis auf ``NULL`` und derselbe
    Datenstand kippt das Zimmer. Das belegt, dass die Haftung am Nachweis
    haengt und nicht an etwas anderem, das sich mit ihm geaendert hat — und
    gleichzeitig, dass T12 wirkt: ``detach`` loescht den Nachweis, und ein
    Pool-Rueckläufer traegt keine Montage-Behauptung mit sich.
    """
    s = await _setup(db_session, zonen=1)
    device = s["devices"][0]
    device.mounted_confirmed_at = NACHWEIS_AM
    await db_session.flush()

    await _frame(db_session, device_id=device.id, attached_backplate=False, age_min=15)
    await _frame(db_session, device_id=device.id, attached_backplate=False, age_min=2)

    vorher = await evaluate_room(db_session, s["room_id"])
    assert vorher is not None
    assert vorher.setpoint_c == 18

    device.mounted_confirmed_at = None
    await db_session.flush()

    nachher = await evaluate_room(db_session, s["room_id"])
    assert nachher is not None
    assert nachher.setpoint_c == MIN_SETPOINT_C
    assert _detached_step(nachher.layers).reason == CommandReason.DEVICE_DETACHED


# ---------------------------------------------------------------------------
# 4. T5 — /hardware-status urteilt aus derselben Quelle
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def client() -> AsyncIterator[AsyncClient]:
    """Client gegen die App, Session auf dieselbe Test-DB umgehaengt.

    Kein Login: mit ``AUTH_ENABLED=false`` (Test-Default) faellt
    ``get_current_user`` auf den ersten aktiven Admin zurueck, den
    ``conftest._ensure_test_admin`` anlegt. Pattern aus
    ``test_api_device_hardware_status``.

    Die App bekommt eine **eigene** Session — deshalb muss der Test vor
    dem Request committen, sonst sieht der Endpoint die Testdaten nicht.
    """
    if not TEST_DB_URL:
        pytest.skip(SKIP_REASON)
    from heizung.main import app

    engine = create_async_engine(TEST_DB_URL)
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)

    async def _override_get_session() -> AsyncIterator[AsyncSession]:
        async with sessionmaker() as session:
            yield session

    app.dependency_overrides[get_session] = _override_get_session
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()


async def test_hardware_status_zugeordnet_mit_nachweis_ist_montiert(
    db_session: AsyncSession, client: AsyncClient
) -> None:
    """**T5.** Kein True-Frame im Fenster, Urteil trotzdem ``active``.

    ``last_seen`` bleibt ``None`` und ``frames_in_window`` zaehlt weiter die
    Fenster-Frames: die Antwort behauptet nicht, der Taster habe gemeldet.
    Sie sagt, dass das Urteil aus dem Nachweis kommt (``source``) — und
    liefert die Fensterwerte als Diagnose daneben. Genau daraus baut die
    Pille ihre Unterzeile "Taster meldet aktuell nicht".
    """
    s = await _setup(db_session, zonen=1)
    device = s["devices"][0]
    device.mounted_confirmed_at = NACHWEIS_AM
    await db_session.flush()
    await _frame(db_session, device_id=device.id, attached_backplate=False, age_min=5)
    await db_session.commit()
    device_id = device.id

    resp = await client.get(f"/api/v1/devices/{device_id}/hardware-status")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "active"
    assert body["source"] == "mounted_confirmed"
    assert body["mounted_confirmed_at"] is not None
    assert body["last_seen"] is None, "kein True-Frame im Fenster"
    assert body["frames_in_window"] == 1


async def test_hardware_status_zugeordnet_ohne_nachweis_nutzt_das_fenster(
    db_session: AsyncSession, client: AsyncClient
) -> None:
    """Ohne Nachweis unveraendert: ``source="window"``, Urteil aus dem Frame."""
    s = await _setup(db_session, zonen=1)
    device = s["devices"][0]
    await _frame(db_session, device_id=device.id, attached_backplate=False, age_min=5)
    await db_session.commit()
    device_id = device.id

    resp = await client.get(f"/api/v1/devices/{device_id}/hardware-status")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["source"] == "window"
    assert body["status"] == "inactive"
    assert body["mounted_confirmed_at"] is None


async def test_hardware_status_pool_pfad_bleibt_unberuehrt(
    db_session: AsyncSession, client: AsyncClient
) -> None:
    """**Der Pool-Pfad ist die dritte Absicherung, nicht die erste.**

    Ein Pool-Geraet bekommt gar keinen Nachweis (T3 verlangt eine
    Zuordnung), und ``detach`` loescht ihn (T12). Hier wird der Nachweis
    trotzdem gesetzt **und** die Zuordnung entfernt — also ein Zustand, den
    die beiden Schreibpfade nicht erzeugen koennen. Die Antwort muss
    dennoch das Fenster nehmen.

    Der Test prueft damit nicht den Normalfall, sondern die Bedingung
    ``heating_zone_id is not None`` im Endpoint: ohne sie haenge der
    Pool-Pfad daran, dass die Schreibpfade vollstaendig bleiben — und das
    ist eine Annahme, die ein spaeterer Sprint brechen kann, ohne es zu
    merken.
    """
    s = await _setup(db_session, zonen=1)
    device = s["devices"][0]
    device.mounted_confirmed_at = NACHWEIS_AM
    device.heating_zone_id = None
    await db_session.flush()
    await _frame(db_session, device_id=device.id, attached_backplate=False, age_min=5)
    await db_session.commit()
    device_id = device.id

    resp = await client.get(f"/api/v1/devices/{device_id}/hardware-status")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["source"] == "window", "Pool-Geraet urteilt nie aus dem Nachweis"
    assert body["status"] == "inactive"
