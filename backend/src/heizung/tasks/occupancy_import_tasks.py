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
from heizung.services.occupancy_import_service import run_freshness_check, run_gap_check

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
    async with _task_session() as session:
        # Schwelle kommt aus global_config (Migration 0022) — der Service laedt
        # sie selbst, damit es nur eine Quelle gibt.
        result = await run_freshness_check(session)
        # Sprint 23 T3: derselbe stuendliche Lauf prueft auch den
        # **Abstand** zur letzten Liste. Zwei Beats fuer zwei Fragen an
        # dieselben Daten waeren zwei Taktgeber, die auseinanderlaufen
        # koennen.
        #
        # Die Reihenfolge ist Absicht: der Stale-Waechter zuerst. An einem
        # Tag ohne jede Liste ist „heute kam keine" die Aussage, die
        # zaehlt; der Abstands-Waechter haelt sich dann heraus
        # (``never_imported``).
        gap = await run_gap_check(session)
    logger.info("check_occupancy_import_freshness result=%s gap=%s", result, gap)
    return {**result, "gap_check": gap}


@app.task(name="heizung.check_occupancy_import_freshness", bind=True)
def check_occupancy_import_freshness(self: Any) -> dict[str, Any]:  # noqa: ARG001 - bind=True
    """Daily celery_beat-Task: STALE-Audit wenn heute kein Import vorliegt."""
    return asyncio.run(_run())
