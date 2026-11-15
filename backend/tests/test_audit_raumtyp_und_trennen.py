"""Zwei Schreibpfade ohne Spur (14.11.2026).

**Befund 1, 13.11.2026.** Der Betreiber hat den Grundsollwert der
Rezeption dreimal geaendert — 07:21 auf 22, 07:53 auf 20, 08:09 auf 21.
In ``config_audit`` stand aus **36 Stunden** genau **eine** Zeile, und die
betraf die hausweite Regel. Die drei Aenderungen liessen sich nur ueber
den Engine-Trace rekonstruieren.

Und es sind nicht irgendwelche Werte: fuer einen **nicht buchbaren**
Raumtyp hebt ``rules.engine.bereichs_kette`` die drei Spalten auf
ROOM_TYPE-Rang, womit sie die hausweite Zeile schlagen. Rezeption und Bar
werden nach diesen Zahlen geregelt.

**Befund 2, 12.11.2026.** Beim Tausch der vertauschten Relais stehen in
``business_audit`` zwei ``DEVICE_ZONE_ASSIGNED``-Zeilen, beide mit
``vorher: {"heating_zone_id": null}``. Dass Relais 109 vorher in der Zone
Eingang hing, steht **nirgends** — im Audit sieht es aus, als waere es
aus dem Nichts an die Bar gekommen.

Beide Male war das Verhalten richtig und die Spur fehlte. Ein Audit, das
nur Zuordnungen kennt und keine Trennungen, erzaehlt die halbe
Geschichte — und die fehlende Haelfte ist genau die, die man bei einer
Verwechslung braucht.

Aufbau nach der DB-Skip-Konvention von ``test_api_device_zone``:
eigene Engine fuer das Setup, ``dependency_override`` teilt sie mit der
App. Lokal-Lauf gegen echtes Postgres ist Pflicht (§5.19, §5.50).
"""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncIterator
from decimal import Decimal
from pathlib import Path
from typing import Any, TypedDict

import httpx
import pytest
import pytest_asyncio
from alembic.config import Config
from httpx import ASGITransport
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from alembic import command
from heizung.db import get_session
from heizung.main import app
from heizung.models.device import Device
from heizung.models.enums import DeviceKind, DeviceVendor, HeatingZoneKind
from heizung.models.heating_zone import HeatingZone
from heizung.models.room import Room
from heizung.models.room_type import RoomType

DATABASE_URL = os.environ.get("DATABASE_URL")
SKIP_REASON = "DATABASE_URL nicht gesetzt - API-Tests brauchen Test-DB"


class _Aufbau(TypedDict):
    suffix: str
    room_type_id: int
    room_id: int
    zone_id: int
    zone_zwei_id: int


@pytest_asyncio.fixture(scope="module", autouse=True)
async def _migrate_db() -> None:
    if not DATABASE_URL:
        return
    backend_root = Path(__file__).resolve().parents[1]
    cfg = Config(str(backend_root / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend_root / "alembic"))
    cfg.set_main_option("sqlalchemy.url", DATABASE_URL)
    await asyncio.to_thread(command.upgrade, cfg, "head")


@pytest_asyncio.fixture
async def setup_engine() -> AsyncIterator[AsyncEngine]:
    if not DATABASE_URL:
        pytest.skip(SKIP_REASON)
    engine = create_async_engine(DATABASE_URL)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def http_client(setup_engine: AsyncEngine) -> AsyncIterator[httpx.AsyncClient]:
    sessionmaker = async_sessionmaker(setup_engine, expire_on_commit=False)

    async def _override_get_session() -> AsyncIterator[AsyncSession]:
        async with sessionmaker() as session:
            yield session

    app.dependency_overrides[get_session] = _override_get_session
    try:
        transport = ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            yield client
    finally:
        app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def aufbau(setup_engine: AsyncEngine) -> AsyncIterator[_Aufbau]:
    """Ein **nicht buchbarer** Raumtyp mit Zimmer und zwei Zonen.

    Nicht buchbar, weil das der Fall aus dem Betrieb ist: Rezeption und
    Bar sind Allgemeinbereiche, und nur fuer sie hebt
    ``bereichs_kette`` die Raumtyp-Spalten auf ROOM_TYPE-Rang. Der
    Unterschied ist auch fuer die Gleichziehung in
    ``_betrieb_gleichziehen`` entscheidend.
    """
    sessionmaker = async_sessionmaker(setup_engine, expire_on_commit=False)
    suffix = uuid.uuid4().hex[:8]
    async with sessionmaker() as session:
        # schema_constraint: room_type.name max 100, room.number max 20 (§5.49)
        rt = RoomType(
            name=f"audit-rt-{suffix}",
            is_bookable=False,
            default_t_occupied=Decimal("19.0"),
            default_t_vacant=Decimal("19.0"),
            default_t_night=Decimal("17.0"),
        )
        session.add(rt)
        await session.flush()
        room = Room(number=f"audit-{suffix}", room_type_id=rt.id)
        session.add(room)
        await session.flush()
        zone = HeatingZone(room_id=room.id, kind=HeatingZoneKind.OTHER, name=f"eingang-{suffix}")
        zone_zwei = HeatingZone(room_id=room.id, kind=HeatingZoneKind.OTHER, name=f"bar-{suffix}")
        session.add_all([zone, zone_zwei])
        await session.commit()
        daten: _Aufbau = {
            "suffix": suffix,
            "room_type_id": rt.id,
            "room_id": room.id,
            "zone_id": zone.id,
            "zone_zwei_id": zone_zwei.id,
        }

    try:
        yield daten
    finally:
        async with sessionmaker() as session:
            await session.execute(
                text(
                    "DELETE FROM config_audit WHERE table_name = 'room_type' "
                    "AND scope_qualifier = :q"
                ),
                {"q": str(daten["room_type_id"])},
            )
            await session.execute(
                text(
                    "DELETE FROM business_audit WHERE target_type = 'device' "
                    "AND target_id IN (SELECT id FROM device WHERE dev_eui LIKE :pat)"
                ),
                {"pat": f"%{daten['suffix']}"},
            )
            await session.execute(
                text("DELETE FROM device WHERE dev_eui LIKE :pat"),
                {"pat": f"%{daten['suffix']}"},
            )
            await session.execute(
                text("DELETE FROM rule_config WHERE room_type_id = :r"),
                {"r": daten["room_type_id"]},
            )
            await session.execute(
                text("DELETE FROM heating_zone WHERE room_id = :r"), {"r": daten["room_id"]}
            )
            await session.execute(text("DELETE FROM room WHERE id = :r"), {"r": daten["room_id"]})
            await session.execute(
                text("DELETE FROM room_type WHERE id = :r"), {"r": daten["room_type_id"]}
            )
            await session.commit()


async def _config_audit(engine: AsyncEngine, room_type_id: int) -> list[dict[str, Any]]:
    """Die ``config_audit``-Zeilen dieses Raumtyps, aelteste zuerst."""
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    async with sessionmaker() as session:
        zeilen = (
            await session.execute(
                text(
                    "SELECT column_name, old_value, new_value, source, user_id "
                    "FROM config_audit WHERE table_name = 'room_type' "
                    "AND scope_qualifier = :q ORDER BY ts, id"
                ),
                {"q": str(room_type_id)},
            )
        ).all()
    return [
        {
            "column_name": z[0],
            "old_value": z[1],
            "new_value": z[2],
            "source": z[3],
            "user_id": z[4],
        }
        for z in zeilen
    ]


async def _business_audit(engine: AsyncEngine, device_id: int) -> list[dict[str, Any]]:
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    async with sessionmaker() as session:
        zeilen = (
            await session.execute(
                text(
                    "SELECT action, old_value, new_value, user_id FROM business_audit "
                    "WHERE target_type = 'device' AND target_id = :d ORDER BY ts, id"
                ),
                {"d": device_id},
            )
        ).all()
    return [{"action": z[0], "old_value": z[1], "new_value": z[2], "user_id": z[3]} for z in zeilen]


async def _geraet(engine: AsyncEngine, suffix: str, zone_id: int | None) -> int:
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    async with sessionmaker() as session:
        # schema_constraint: device.dev_eui max 16 (§5.49)
        geraet = Device(
            dev_eui=f"deadbeef{suffix}",
            kind=DeviceKind.THERMOSTAT,
            vendor=DeviceVendor.MCLIMATE,
            model="vicki",
            label=f"audit-{suffix}",
            heating_zone_id=zone_id,
        )
        session.add(geraet)
        await session.commit()
        await session.refresh(geraet)
        return geraet.id


# ---------------------------------------------------------------------------
# PATCH /api/v1/room-types/{id} — config_audit je Feld
# ---------------------------------------------------------------------------


async def test_eine_aenderung_schreibt_eine_zeile(
    http_client: httpx.AsyncClient, setup_engine: AsyncEngine, aufbau: _Aufbau
) -> None:
    resp = await http_client.patch(
        f"/api/v1/room-types/{aufbau['room_type_id']}",
        json={"default_t_night": 18.0},
    )
    assert resp.status_code == 200, resp.text

    zeilen = await _config_audit(setup_engine, aufbau["room_type_id"])
    nacht = [z for z in zeilen if z["column_name"] == "default_t_night"]
    assert len(nacht) == 1, f"erwartet eine Zeile fuer default_t_night, bekommen: {zeilen}"
    assert nacht[0]["old_value"] == "17.0"
    assert nacht[0]["new_value"] == "18.0"
    assert nacht[0]["source"] == "api"
    assert nacht[0]["user_id"] is not None, "ohne Benutzer ist die Spur halb wertlos"


async def test_ein_unveraendertes_feld_schreibt_nichts(
    http_client: httpx.AsyncClient, setup_engine: AsyncEngine, aufbau: _Aufbau
) -> None:
    """Die Oberflaeche schickt das ganze Formular, auch das Unveraenderte.

    Ohne diese Pruefung entstuende bei jedem Speichern eine Zeile je
    Feld — und eine Spur, in der alles steht, zeigt nichts.
    """
    resp = await http_client.patch(
        f"/api/v1/room-types/{aufbau['room_type_id']}",
        json={"default_t_night": 17.0, "default_t_vacant": 19.0},
    )
    assert resp.status_code == 200, resp.text
    assert await _config_audit(setup_engine, aufbau["room_type_id"]) == []


async def test_die_gleichziehung_wird_mitgeschrieben(
    http_client: httpx.AsyncClient, setup_engine: AsyncEngine, aufbau: _Aufbau
) -> None:
    """``_betrieb_gleichziehen`` aendert eine Spalte, die niemand anfasste.

    Bei einem Allgemeinbereich zieht das Speichern
    ``default_t_occupied`` auf den Frei-Wert nach. Ohne eigene Zeile
    waere diese Aenderung im Audit unsichtbar — und beim naechsten
    Vergleich stimmte der ``old_value`` nicht mehr.
    """
    resp = await http_client.patch(
        f"/api/v1/room-types/{aufbau['room_type_id']}",
        json={"default_t_vacant": 21.0},
    )
    assert resp.status_code == 200, resp.text

    zeilen = await _config_audit(setup_engine, aufbau["room_type_id"])
    spalten = [z["column_name"] for z in zeilen]
    assert "default_t_vacant" in spalten
    assert "default_t_occupied" in spalten, f"die Gleichziehung fehlt in der Spur: {spalten}"
    mitgezogen = next(z for z in zeilen if z["column_name"] == "default_t_occupied")
    assert mitgezogen["old_value"] == "19.0"
    assert mitgezogen["new_value"] == "21.0"


async def test_gegenprobe_13_11_drei_aenderungen_drei_zeilen(
    http_client: httpx.AsyncClient, setup_engine: AsyncEngine, aufbau: _Aufbau
) -> None:
    """**Die Gegenprobe zum Befund: der Vormittag des 13.11.2026.**

    07:21 auf 22, 07:53 auf 20, 08:09 auf 21 — drei Aenderungen am
    Grundsollwert der Rezeption, und in ``config_audit`` stand keine
    einzige Zeile. Diese Reihe muss **drei** ergeben, mit lueckenloser
    Kette von alt zu neu.
    """
    for wert in (22.0, 20.0, 21.0):
        resp = await http_client.patch(
            f"/api/v1/room-types/{aufbau['room_type_id']}",
            json={"default_t_vacant": wert},
        )
        assert resp.status_code == 200, resp.text

    frei = [
        z
        for z in await _config_audit(setup_engine, aufbau["room_type_id"])
        if z["column_name"] == "default_t_vacant"
    ]
    assert len(frei) == 3, f"drei Aenderungen muessen drei Zeilen ergeben: {frei}"
    assert [(z["old_value"], z["new_value"]) for z in frei] == [
        ("19.0", "22.0"),
        ("22.0", "20.0"),
        ("20.0", "21.0"),
    ], "die Kette alt->neu muss lueckenlos sein"


# ---------------------------------------------------------------------------
# DELETE /api/v1/devices/{id}/heating-zone — business_audit
# ---------------------------------------------------------------------------


async def test_trennen_schreibt_die_vorherige_zone(
    http_client: httpx.AsyncClient, setup_engine: AsyncEngine, aufbau: _Aufbau
) -> None:
    device_id = await _geraet(setup_engine, aufbau["suffix"], aufbau["zone_id"])

    resp = await http_client.delete(f"/api/v1/devices/{device_id}/heating-zone")
    assert resp.status_code == 200, resp.text

    zeilen = await _business_audit(setup_engine, device_id)
    getrennt = [z for z in zeilen if z["action"] == "DEVICE_ZONE_DETACHED"]
    assert len(getrennt) == 1, f"erwartet eine Trenn-Zeile, bekommen: {zeilen}"
    assert getrennt[0]["old_value"]["heating_zone_id"] == aufbau["zone_id"], (
        "die Zone, aus der getrennt wurde, ist der ganze Zweck dieser Zeile"
    )
    assert getrennt[0]["new_value"]["heating_zone_id"] is None
    assert getrennt[0]["new_value"]["dev_eui"] == f"deadbeef{aufbau['suffix']}"
    assert getrennt[0]["user_id"] is not None


async def test_trennen_ohne_zone_schreibt_nichts(
    http_client: httpx.AsyncClient, setup_engine: AsyncEngine, aufbau: _Aufbau
) -> None:
    """Ein Geraet ohne Zone zu trennen ist keine Aenderung.

    Der Endpunkt kehrt frueh zurueck. Eine Zeile dafuer waere ein
    Vorgang, der nicht stattgefunden hat.
    """
    device_id = await _geraet(setup_engine, aufbau["suffix"], None)

    resp = await http_client.delete(f"/api/v1/devices/{device_id}/heating-zone")
    assert resp.status_code == 200, resp.text
    assert await _business_audit(setup_engine, device_id) == []


async def test_der_montage_nachweis_steht_in_der_spur(
    http_client: httpx.AsyncClient, setup_engine: AsyncEngine, aufbau: _Aufbau
) -> None:
    """Das Trennen setzt ihn zurueck — also gehoert er in die Zeile.

    Sonst steht spaeter ein Nachweis auf ``null``, dessen Verschwinden
    keine Zeile erklaert.
    """
    device_id = await _geraet(setup_engine, aufbau["suffix"], aufbau["zone_id"])
    sessionmaker = async_sessionmaker(setup_engine, expire_on_commit=False)
    async with sessionmaker() as session:
        await session.execute(
            text("UPDATE device SET mounted_confirmed_at = now() WHERE id = :d"),
            {"d": device_id},
        )
        await session.commit()

    resp = await http_client.delete(f"/api/v1/devices/{device_id}/heating-zone")
    assert resp.status_code == 200, resp.text

    getrennt = [
        z
        for z in await _business_audit(setup_engine, device_id)
        if z["action"] == "DEVICE_ZONE_DETACHED"
    ]
    assert len(getrennt) == 1
    assert getrennt[0]["old_value"]["mounted_confirmed_at"] is not None, (
        "der Nachweis war gesetzt und muss in der Spur stehen"
    )
    assert getrennt[0]["new_value"]["mounted_confirmed_at"] is None


async def test_gegenprobe_12_11_der_tausch_ist_rekonstruierbar(
    http_client: httpx.AsyncClient, setup_engine: AsyncEngine, aufbau: _Aufbau
) -> None:
    """**Die Gegenprobe zum Befund vom 12.11.2026.**

    Relais 109 hing in der Zone Eingang, wurde getrennt und der Bar
    zugeordnet. Im Audit standen danach nur zwei Zuordnungen mit
    ``vorher: null`` — die alte Zone war nicht mehr auffindbar.

    Nach dieser Reihe muss sie es sein: Zuordnung, Trennen, Zuordnung,
    und aus der Spur allein lesbar, wo das Geraet vorher hing.
    """
    device_id = await _geraet(setup_engine, aufbau["suffix"], None)

    assign = await http_client.put(
        f"/api/v1/devices/{device_id}/heating-zone",
        json={"heating_zone_id": aufbau["zone_id"]},
    )
    assert assign.status_code == 200, assign.text
    trennen = await http_client.delete(f"/api/v1/devices/{device_id}/heating-zone")
    assert trennen.status_code == 200, trennen.text
    assign_zwei = await http_client.put(
        f"/api/v1/devices/{device_id}/heating-zone",
        json={"heating_zone_id": aufbau["zone_zwei_id"]},
    )
    assert assign_zwei.status_code == 200, assign_zwei.text

    zeilen = await _business_audit(setup_engine, device_id)
    assert [z["action"] for z in zeilen] == [
        "DEVICE_ZONE_ASSIGNED",
        "DEVICE_ZONE_DETACHED",
        "DEVICE_ZONE_ASSIGNED",
    ], f"die Kette ist unvollstaendig: {[z['action'] for z in zeilen]}"

    # Und die eigentliche Frage: wo hing es vor der zweiten Zuordnung?
    assert zeilen[1]["old_value"]["heating_zone_id"] == aufbau["zone_id"], (
        "genau diese Angabe fehlte am 12.11."
    )
    assert zeilen[2]["new_value"]["heating_zone_id"] == aufbau["zone_zwei_id"]
