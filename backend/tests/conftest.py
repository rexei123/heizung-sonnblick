"""Gemeinsame Test-Fixtures.

Helper-Funktionen (Sprint 12 T0, aus Sprint 11 T7-Backlog):

- ``enable_heizung_log_propagation``: Workaround fuer caplog-Quirk
  (§5.36 + §5.37) — erzwingt ``propagate=True`` + ``disabled=False``
  auf einem ``heizung.*``-Logger, damit caplog Records auch in voller
  Suite zuverlaessig sieht. Bisheriges Inline-Pattern aus
  ``test_mqtt_subscriber.py`` konsolidiert.
- ``purge_test_data_by_prefix``: Cleanup-Helper fuer DB-Tests gegen
  globale Compute-Tasks (§5.39). Loescht Room + RoomType nach
  Prefix-Pattern und zugehoerige SensorReadings nach
  ``device.dev_eui``-LIKE-Pattern. Bisheriges Inline-Pattern aus
  ``test_health_compute.py`` (``_purge_t11t5``) konsolidiert.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
import pytest_asyncio
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import delete as sa_delete
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from alembic import command
from heizung.config import get_settings
from heizung.main import app


@pytest.fixture(autouse=True)
def _ensure_test_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stellt sicher, dass ENVIRONMENT + ALLOW_DEFAULT_SECRETS in jedem
    Test gesetzt sind. ENVIRONMENT ist seit H-5 Pflichtfeld (kein Default
    in Settings), daher muss auch der Test-Run die env-Var setzen, sonst
    crasht jeder Settings()-Call ohne explicit environment-kwarg.

    Tests, die explicit ENVIRONMENT testen (z.B. K-3-Validator), nutzen
    monkeypatch.setenv/delenv und ueberschreiben damit diesen Default.
    """
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setenv("ALLOW_DEFAULT_SECRETS", "1")
    # Settings-Cache leeren, damit nachfolgende get_settings() die
    # frischen env-Vars lesen.
    get_settings.cache_clear()


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as c:
        yield c


@pytest_asyncio.fixture(scope="module", autouse=True)
async def _ensure_test_admin() -> AsyncIterator[None]:
    """Sprint 9.17 (AE-50): Alle mutierenden Endpoints erfordern Auth.
    Bei ``AUTH_ENABLED=false`` faellt ``get_current_user`` auf den ersten
    aktiven Admin in der DB zurueck. Diese Fixture stellt sicher, dass
    so ein User in der Test-DB existiert — idempotent.

    Skippt wenn ``DATABASE_URL`` nicht gesetzt ist (Pure-Function-Tests).
    """
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        yield
        return

    backend_root = Path(__file__).resolve().parents[1]
    cfg = Config(str(backend_root / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend_root / "alembic"))
    cfg.set_main_option("sqlalchemy.url", db_url)
    await asyncio.to_thread(command.upgrade, cfg, "head")

    # Lokale Imports nach Migration: das Auth-Modul braucht zur Importzeit
    # vollstaendige Settings (ENVIRONMENT etc.), die ``_ensure_test_env``
    # erst gesetzt hat.
    from heizung.models.enums import UserRole
    from heizung.models.user import User

    engine = create_async_engine(db_url)
    sm = async_sessionmaker(engine, expire_on_commit=False)
    async with sm() as session:
        existing = (
            await session.execute(select(User).where(User.role == UserRole.ADMIN).limit(1))
        ).scalar_one_or_none()
        if existing is None:
            session.add(
                User(
                    email="test-admin@local",
                    password_hash="test-hash-not-used",
                    role=UserRole.ADMIN,
                    is_active=True,
                    must_change_password=False,
                )
            )
            await session.commit()
    await engine.dispose()
    yield


# ---------------------------------------------------------------------------
# Helper-Funktionen (Sprint 12 T0)
# ---------------------------------------------------------------------------


def enable_heizung_log_propagation(
    monkeypatch: pytest.MonkeyPatch,
    logger_name: str = "heizung",
) -> None:
    """Erzwingt ``propagate=True`` + ``disabled=False`` auf einem
    ``heizung.*``-Logger, damit ``caplog`` Records auch in voller Suite
    zuverlaessig sieht (§5.36 + §5.37 — caplog-Quirk betrifft sync und
    async-Tests gleichermassen, Repo-weite Logger-Konfiguration in
    ``heizung.main``-Import-Pfad ueberschreibt sonst Propagate).

    Aufruf in einem Test (Beispiel):
        from tests.conftest import enable_heizung_log_propagation
        enable_heizung_log_propagation(monkeypatch, "heizung.services.mqtt_subscriber")
        caplog.set_level(logging.WARNING, logger="heizung.services.mqtt_subscriber")

    Reset via ``monkeypatch``-Fixture-Teardown automatisch.
    """
    sub_logger = logging.getLogger(logger_name)
    monkeypatch.setattr(sub_logger, "propagate", True)
    monkeypatch.setattr(sub_logger, "disabled", False)


async def purge_test_data_by_prefix(
    session: AsyncSession,
    prefix: str,
    *,
    dev_eui_pattern: str | None = None,
) -> None:
    """Cleanup-Helper fuer DB-Tests gegen globale Compute-Tasks (§5.39).

    Loescht in dieser Reihenfolge:
    1. ``SensorReading`` mit ``device_id`` aus Devices matching
       ``dev_eui_pattern`` (LIKE, z.B. ``"deadbeef%"``). Nur wenn
       ``dev_eui_pattern`` gesetzt ist.
    2. ``Room`` mit ``number LIKE f"{prefix}-%"`` — CASCADE raeumt
       ``HeatingZone`` und ``Device``.
    3. ``RoomType`` mit ``name LIKE f"{prefix}-%"``.

    Im Anschluss ``session.commit()``. Sicher gegen Reihenfolge-
    Probleme (FK), produktive Daten bleiben unangetastet (Hotel-Vickis
    haben echte MAC-Adressen, keine ``deadbeef``-Pattern; produktive
    Room-Numbers nutzen keine Test-Prefixes).

    Beispiel-Aufruf (analog ``_purge_t11t5`` aus
    ``test_health_compute.py``):
        await purge_test_data_by_prefix(session, "t12t4", dev_eui_pattern="deadbeef%")
    """
    from heizung.models.device import Device
    from heizung.models.room import Room
    from heizung.models.room_type import RoomType
    from heizung.models.sensor_reading import SensorReading

    if dev_eui_pattern:
        devices_to_purge = list(
            (await session.execute(select(Device.id).where(Device.dev_eui.like(dev_eui_pattern))))
            .scalars()
            .all()
        )
        if devices_to_purge:
            await session.execute(
                sa_delete(SensorReading).where(SensorReading.device_id.in_(devices_to_purge))
            )
    rooms = list(
        (await session.execute(select(Room).where(Room.number.like(f"{prefix}-%")))).scalars().all()
    )
    for room in rooms:
        await session.delete(room)
    room_types = list(
        (await session.execute(select(RoomType).where(RoomType.name.like(f"{prefix}-%"))))
        .scalars()
        .all()
    )
    for room_type in room_types:
        await session.delete(room_type)
    await session.commit()
