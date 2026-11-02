"""GET /api/v1/devices/{id}/paketverlust (02.11.2026).

Zwei Geraetearten, zwei Tabellen, **eine** Rechnung: ein Relais schreibt
nach ``relay_reading``, ein Thermostat nach ``sensor_reading``. Die
Tests belegen, dass der Endpunkt die richtige Tabelle liest — genau der
Fehler, der sonst erst am Relais auffaellt, weil ein Relais keine
``sensor_reading``-Zeilen hat und die Antwort dann leer aussieht statt
falsch.

DB-Skip-Konvention wie ``test_api_device_hardware_status`` (§5.50).
"""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

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
from heizung.models.enums import DeviceKind, DeviceVendor
from heizung.models.relay_reading import RelayReading
from heizung.models.sensor_reading import SensorReading

DATABASE_URL = os.environ.get("DATABASE_URL")
SKIP_REASON = "DATABASE_URL nicht gesetzt - API-Tests brauchen Test-DB"


@pytest_asyncio.fixture(scope="module", autouse=True)
async def _migrate_db() -> None:
    if not DATABASE_URL:
        return
    backend_root = Path(__file__).resolve().parents[1]
    cfg = Config(str(backend_root / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend_root / "alembic"))
    cfg.set_main_option("sqlalchemy.url", DATABASE_URL or "")
    await asyncio.to_thread(command.upgrade, cfg, "head")


@pytest_asyncio.fixture
async def setup_engine() -> AsyncIterator[AsyncEngine]:
    if not DATABASE_URL:
        pytest.skip(SKIP_REASON)
    engine = create_async_engine(DATABASE_URL or "")
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


async def _geraet(engine: AsyncEngine, kind: DeviceKind) -> AsyncIterator[int]:
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    suffix = uuid.uuid4().hex[:8]
    async with sessionmaker() as session:
        geraet = Device(
            dev_eui=f"deadbeef{suffix}",
            kind=kind,
            vendor=DeviceVendor.MCLIMATE,
            model="16ASPM" if kind == DeviceKind.RELAY else "vicki",
            label=f"pv-{suffix}",
        )
        session.add(geraet)
        await session.commit()
        device_id = geraet.id

    yield device_id

    async with sessionmaker() as session:
        for tabelle in ("relay_reading", "sensor_reading"):
            await session.execute(
                text(f"DELETE FROM {tabelle} WHERE device_id = :d"), {"d": device_id}
            )
        await session.execute(text("DELETE FROM device WHERE id = :d"), {"d": device_id})
        await session.commit()


@pytest_asyncio.fixture
async def vicki_id(setup_engine: AsyncEngine) -> AsyncIterator[int]:
    async for device_id in _geraet(setup_engine, DeviceKind.THERMOSTAT):
        yield device_id


@pytest_asyncio.fixture
async def relais_id(setup_engine: AsyncEngine) -> AsyncIterator[int]:
    async for device_id in _geraet(setup_engine, DeviceKind.RELAY):
        yield device_id


async def _sensor_zeilen(engine: AsyncEngine, device_id: int, fcnts: list[int]) -> None:
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    jetzt = datetime.now(tz=UTC)
    async with sessionmaker() as session:
        for i, fcnt in enumerate(fcnts):
            session.add(
                SensorReading(
                    time=jetzt - timedelta(minutes=len(fcnts) - i),
                    device_id=device_id,
                    fcnt=fcnt,
                )
            )
        await session.commit()


async def _relais_zeilen(engine: AsyncEngine, device_id: int, fcnts: list[int]) -> None:
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    jetzt = datetime.now(tz=UTC)
    async with sessionmaker() as session:
        for i, fcnt in enumerate(fcnts):
            session.add(
                RelayReading(
                    time=jetzt - timedelta(minutes=len(fcnts) - i),
                    device_id=device_id,
                    fcnt=fcnt,
                    relay_on=False,
                )
            )
        await session.commit()


async def test_vicki_rechnet_auf_sensor_reading(
    http_client: httpx.AsyncClient, setup_engine: AsyncEngine, vicki_id: int
) -> None:
    await _sensor_zeilen(setup_engine, vicki_id, [1, 2, 5, 6])

    antwort = await http_client.get(f"/api/v1/devices/{vicki_id}/paketverlust")

    assert antwort.status_code == 200, antwort.text
    body = antwort.json()
    assert body["empfangen"] == 4
    assert body["erwartet"] == 6
    assert body["verloren"] == 2
    assert body["anteil_prozent"] == pytest.approx(33.3)
    assert body["stunden"] == 24
    assert body["von"] is not None
    assert body["bis"] is not None


async def test_relais_rechnet_auf_relay_reading(
    http_client: httpx.AsyncClient, setup_engine: AsyncEngine, relais_id: int
) -> None:
    """**Der Fall vom Relais 109**: ``fCnt`` 8, dann 13.

    Lese der Endpunkt hier ``sensor_reading``, waere die Antwort leer —
    und eine leere Antwort sieht nach „nichts verloren" aus und nicht
    nach „falsche Tabelle".
    """
    await _relais_zeilen(setup_engine, relais_id, [5, 6, 7, 8, 13, 14])

    antwort = await http_client.get(f"/api/v1/devices/{relais_id}/paketverlust")

    assert antwort.status_code == 200, antwort.text
    body = antwort.json()
    assert body["empfangen"] == 6
    assert body["erwartet"] == 10
    assert body["verloren"] == 4
    assert body["anteil_prozent"] == pytest.approx(40.0)


async def test_der_anteil_kommt_als_zahl_nicht_als_zeichenkette(
    http_client: httpx.AsyncClient, setup_engine: AsyncEngine, relais_id: int
) -> None:
    """``Decimal`` geht ohne Serialisierer als String nach draussen.

    Im Hinweistext wirft dann ``.toFixed()`` — der Vorfall vom
    07.10.2026, dessen Wachposten in ``test_decimal_serialisierung``
    steht. Hier noch einmal am echten Weg durch FastAPI.
    """
    await _relais_zeilen(setup_engine, relais_id, [1, 3])

    body = (await http_client.get(f"/api/v1/devices/{relais_id}/paketverlust")).json()
    assert isinstance(body["anteil_prozent"], (int, float))


async def test_ohne_zeilen_kein_anteil_und_keine_null(
    http_client: httpx.AsyncClient, setup_engine: AsyncEngine, relais_id: int
) -> None:
    """Ein frisches Geraet hat keinen Verlust von 0 %, sondern keinen."""
    body = (await http_client.get(f"/api/v1/devices/{relais_id}/paketverlust")).json()
    assert body["anteil_prozent"] is None
    assert body["empfangen"] == 0
    assert body["von"] is None


async def test_das_fenster_ist_waehlbar_und_begrenzt(
    http_client: httpx.AsyncClient, setup_engine: AsyncEngine, relais_id: int
) -> None:
    """Eine Woche ist das Maximum: mehr liest niemand mehr als Diagnose.

    Und ``0`` waere ein Fenster ohne Inhalt, aber mit einer Antwort.
    """
    await _relais_zeilen(setup_engine, relais_id, [1, 2, 3])

    assert (await http_client.get(f"/api/v1/devices/{relais_id}/paketverlust?stunden=12")).json()[
        "stunden"
    ] == 12
    assert (
        await http_client.get(f"/api/v1/devices/{relais_id}/paketverlust?stunden=0")
    ).status_code == 422
    assert (
        await http_client.get(f"/api/v1/devices/{relais_id}/paketverlust?stunden=169")
    ).status_code == 422
