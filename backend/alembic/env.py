"""Alembic Environment (async).

Liest DATABASE_URL aus den Anwendungs-Settings und führt Migrationen
mit der asynchronen Engine aus.
"""

import asyncio
import os
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

# Modelle importieren, damit sie sich in Base.metadata registrieren.
import heizung.models  # noqa: F401
from alembic import context
from heizung.config import get_settings
from heizung.db import Base

# Alembic-Konfiguration
config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# URL aus den Anwendungs-Settings uebernehmen. Tests setzen
# TEST_DATABASE_URL und erwarten, dass Migrationen dort laufen — sonst
# trifft test_migrations_roundtrip die Produktiv-/Dev-DB (B-9.16-2).
settings = get_settings()
url = os.environ.get("TEST_DATABASE_URL") or settings.database_url
config.set_main_option("sqlalchemy.url", url)

# Ziel-Metadaten (alle deklarierten ORM-Modelle)
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Migrationen ohne DB-Verbindung (SQL-Ausgabe)."""
    context.configure(
        url=settings.database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def _do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """Migrationen gegen laufende DB."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(_do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
