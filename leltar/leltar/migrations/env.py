"""Alembic environment.

The database URL comes from application settings rather than alembic.ini, so there is one
place to configure it and no chance of the two disagreeing.
"""

from __future__ import annotations

import asyncio

from alembic import context
from sqlalchemy.ext.asyncio import async_engine_from_config
from sqlalchemy.pool import NullPool

from leltar.config import get_settings
from leltar.models import Base

config = context.config
# A caller that has already set a URL on the Config wins - that is how the migration tests
# point a run at a throwaway database. Everything else, the app included, gets the one URL
# the application settings define, so the two can never disagree.
config.set_main_option(
    "sqlalchemy.url",
    config.get_main_option("sqlalchemy.url", None) or get_settings().database_url,
)
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def _do_run_migrations(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata,
                      compare_type=True, compare_server_default=True)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(_do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
