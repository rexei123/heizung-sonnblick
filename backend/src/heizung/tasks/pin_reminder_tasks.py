"""Sprint 20g (H-6 T10) — Beat-Task fuer die Rueckfallpunkt-Erinnerung.

``celery_beat`` ruft ``check_pin_reminder`` **stuendlich**. Die Mail kommt
davon hoechstens einmal pro Woche; der stuendliche Takt ist nur die
Gelegenheit, nachzusehen.

**Warum stuendlich und nicht einmal am Tag.** Ein fester Tages-Slot ist der
Fehler aus §5.79: dort prueffte ein ``crontab(hour=8, minute=15)`` eine
Schwelle, die spaeter am Tag lag, und konnte deshalb nie etwas melden. Hier
gibt es keine Schwelle, die man verstellen koennte — aber derselbe Takt wie
beim Belegungs-Waechter (``crontab(minute=20)``) kostet nichts und hat
keinen Slot, der verpasst werden kann.

Eigene Engine + Session pro Task-Run (§5.14), Vorbild
``tasks/occupancy_import_tasks``.
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
from heizung.services.pin_reminder import run_pin_reminder

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
    """Async-Koerper des Tasks. Public fuer Tests."""
    async with _task_session() as session:
        result = await run_pin_reminder(session)
        # Der Service committet nicht (§5.61) — und er schreibt die Uhr.
        # Ohne diesen Commit startet sie bei jedem Lauf neu, und die
        # Erinnerung kaeme nie.
        await session.commit()
    logger.info("check_pin_reminder result=%s", result)
    return result


@app.task(name="heizung.check_pin_reminder", bind=True)
def check_pin_reminder(self: Any) -> dict[str, Any]:  # noqa: ARG001 - bind=True
    """Stuendlicher celery_beat-Task: erinnert an einen gesetzten PIN_SHA."""
    return asyncio.run(_run())
