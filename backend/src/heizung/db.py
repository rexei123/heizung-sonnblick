"""SQLAlchemy-Setup (Async).

Stellt Engine und Session-Factory bereit. Der Session-Lifecycle wird in
FastAPI-Routen über Dependency-Injection gesteuert (``Depends(get_session)``).

Sprint 9.6b: ``pool_pre_ping=False``. Im Celery-Worker erzeugt jede Task
ueber ``asyncio.run`` einen neuen Event-Loop; pool_pre_ping pingt die
Connections aber im urspruenglichen Loop -> ``RuntimeError: Future
attached to a different loop``. Der Worker hat fuer 9.7 ohnehin einen
eigenen Engine-Reset pro Forked-Process via Celery-Signal (siehe
``celery_app.py``). Im API-Container ist ein Re-Connect bei Pool-Stale
vernachlaessigbar (langlebige Connections, FastAPI-Healthcheck deckt es).
"""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from heizung.config import get_settings

_settings = get_settings()

engine = create_async_engine(
    _settings.database_url,
    echo=False,
    pool_pre_ping=False,
    pool_recycle=900,
)

SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    """Gemeinsame Basis für alle ORM-Modelle."""


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI-Dependency: liefert eine DB-Session pro Request."""
    async with SessionLocal() as session:
        yield session
