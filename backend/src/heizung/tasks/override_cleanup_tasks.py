"""Sprint 9.9 T7 - Daily-Cleanup-Job fuer abgelaufene Manual-Overrides.

celery_beat ruft ``cleanup_expired_overrides`` einmal taeglich um 03:00
UTC auf. Markiert alle Overrides mit ``expires_at < now`` und
``revoked_at IS NULL`` als revoked (``revoked_at = expires_at``,
``revoked_reason = "auto: expired"``). Records bleiben fuer Audit
erhalten.

Pattern uebernommen aus ``tasks/engine_tasks``: eigener Async-Engine pro
Task-Run (Sprint 9.7a Pool-Pollution-Fix), ``asyncio.run`` umschliesst
die Coroutine.
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
from heizung.services import override_service

logger = logging.getLogger(__name__)


@contextlib.asynccontextmanager
async def _task_session() -> AsyncIterator[AsyncSession]:
    """Eigene Engine + Session pro Task-Coroutine (vgl. engine_tasks._task_session).

    Jeder Celery-Task spawnt via ``asyncio.run`` einen NEUEN Event-Loop;
    eine global geteilte ``SessionLocal`` haelt Connections, die an einen
    fruehen Loop gebunden waren -> asyncpg ``cannot perform operation:
    another operation is in progress``. Eigene Engine + ``engine.dispose()``
    am Ende vermeidet das.
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
    """Async-Koerper des Cleanup-Tasks. Public fuer Tests."""
    async with _task_session() as session:
        count = await override_service.cleanup_expired(session)
        await session.commit()
    logger.info("cleanup_expired_overrides revoked=%d", count)
    return {"revoked": count}


@app.task(name="heizung.cleanup_expired_overrides", bind=True)
def cleanup_expired_overrides(self: Any) -> dict[str, int]:  # noqa: ARG001 - bind=True
    """Daily celery_beat-Task: setzt revoked_at fuer abgelaufene Overrides.

    Returns ``{"revoked": <count>}``.
    """
    return asyncio.run(_run())
