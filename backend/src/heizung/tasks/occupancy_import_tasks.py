"""Sprint 15e (AE-66) — Staleness-Watchdog fuer den Belegungs-Import.

``celery_beat`` ruft ``check_occupancy_import_freshness`` einmal taeglich
auf (kurz nach ``OCCUPANCY_IMPORT_EXPECTED_BY_LOCAL``). Liegt fuer das
heutige Lokal-Datum kein erfolgreicher Import vor, wird ein
``OCCUPANCY_IMPORT_STALE``-Audit geschrieben. Es werden KEINE Zimmer
freigegeben — der letzte bekannte Stand bleibt eingefroren.

Eigene Engine + Session pro Task-Run (Sprint 9.7a Pool-Pollution-Fix,
§5.14), Vorbild ``tasks/override_cleanup_tasks``.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from heizung.celery_app import app
from heizung.config import get_settings
from heizung.services.occupancy_import_service import run_freshness_check

logger = logging.getLogger(__name__)


@contextlib.asynccontextmanager
async def _task_session() -> AsyncIterator[AsyncSession]:
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


async def _run() -> dict[str, Any]:
    """Async-Koerper des Watchdog-Tasks. Public fuer Tests."""
    settings = get_settings()
    async with _task_session() as session:
        result = await run_freshness_check(
            session,
            expected_by_local_str=settings.occupancy_import_expected_by_local,
        )
    logger.info("check_occupancy_import_freshness result=%s", result)
    return result


@app.task(name="heizung.check_occupancy_import_freshness", bind=True)
def check_occupancy_import_freshness(self: Any) -> dict[str, Any]:  # noqa: ARG001 - bind=True
    """Daily celery_beat-Task: STALE-Audit wenn heute kein Import vorliegt."""
    return asyncio.run(_run())
