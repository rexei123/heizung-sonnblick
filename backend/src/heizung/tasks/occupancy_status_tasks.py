"""Sprint 15g - Periodischer room.status-Sync (celery_beat-Task).

celery_beat ruft ``sync_room_statuses`` alle 60 s auf (siehe
``celery_app.beat_schedule``). Der Task leitet ``room.status`` aller Raeume
mit anstehendem Belegungs-Uebergang aus den aktiven Belegungen ab
(``occupancy_service.sync_active_rooms``). So werden die uhrzeitgenauen
Uebergaenge ohne neuen Import getroffen:

    Anreisetag vor 14:00 -> RESERVED · ab 14:00 -> OCCUPIED
    Abreisetag bis 11:00 -> OCCUPIED · ab 11:00 -> VACANT

Die Zeiten stecken als UTC-Timestamp in ``check_in``/``check_out`` (Import-
Defaults DEFAULT_CHECKIN_LOCAL 14:00 / CHECKOUT_LOCAL 11:00, via
GlobalConfig konfigurierbar). Der Task ist bewusst KEIN Engine-Tick-Anhang
(AE-68): die Belegungs-Domain bleibt aus der Engine, Drift-Fenster <= 60 s
ist fuer Check-in/out unkritisch (Vorheizen laeuft ueber Layer 2 vor
check_in).

Pattern uebernommen aus ``tasks/engine_tasks`` / ``override_cleanup_tasks``:
eigener Async-Engine pro Task-Run (Sprint 9.7a Pool-Pollution-Fix),
``asyncio.run`` umschliesst die Coroutine.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from heizung.celery_app import app
from heizung.config import get_settings
from heizung.services.occupancy_service import sync_active_rooms

logger = logging.getLogger(__name__)


@contextlib.asynccontextmanager
async def _task_session() -> AsyncIterator[AsyncSession]:
    """Eigene Engine + Session pro Task-Coroutine (vgl. engine_tasks._task_session).

    Jeder Celery-Task spawnt via ``asyncio.run`` einen NEUEN Event-Loop;
    eine global geteilte ``SessionLocal`` haelt Connections, die an einen
    fruehen Loop gebunden waren -> asyncpg ``cannot perform operation:
    another operation is in progress``. Eigene Engine + ``engine.dispose()``
    am Ende vermeidet das. (Backlog services/_common.py konsolidiert die
    drei Kopien.)
    """
    settings = get_settings()
    engine = create_async_engine(
        settings.database_url,
        echo=False,
        pool_pre_ping=False,
        pool_size=2,
        max_overflow=0,
    )
    try:
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with session_factory() as session:
            yield session
    finally:
        await engine.dispose()


async def _run() -> dict[str, int]:
    """Async-Koerper des Sync-Tasks. Public fuer Tests."""
    now = datetime.now(tz=UTC)
    async with _task_session() as session:
        count = await sync_active_rooms(session, now)
        await session.commit()
    logger.info("sync_room_statuses: synced=%d", count)
    return {"synced": count}


@app.task(name="heizung.sync_room_statuses", bind=True)
def sync_room_statuses(self: Any) -> dict[str, int]:  # noqa: ARG001 - bind=True
    """60-s celery_beat-Task: synchronisiert ``room.status`` aktiver Raeume.

    Returns ``{"synced": <count>}``.
    """
    return asyncio.run(_run())
