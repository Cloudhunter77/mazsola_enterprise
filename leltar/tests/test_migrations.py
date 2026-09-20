"""The migrations and the models have to describe the same database.

The failure this prevents is quiet and expensive: a column added to a model with no
migration written for it. Every test here passes, because the test database is built from
the models with `create_all` - and the NAS, which builds its database from the migrations,
gets a 500 on the first request that touches the new column.

So this compares the two directly: upgrade an empty database with the migrations, then ask
Alembic to autogenerate against the models and require that it finds nothing to do.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from leltar.models import Base
from tests.conftest import TEST_DATABASE_URL, requires_db

pytestmark = requires_db

ROOT = Path(__file__).resolve().parent.parent


def _config() -> Config:
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "leltar" / "migrations"))
    # ConfigParser reads `%` as interpolation; a password containing one would otherwise
    # take the whole run down before it touched the database.
    config.set_main_option("sqlalchemy.url", (TEST_DATABASE_URL or "").replace("%", "%%"))
    config.attributes["configure_logger"] = False
    return config


@pytest.fixture
async def blank_database():
    """A schema built by the migrations alone, with nothing the models put there."""
    engine = create_async_engine(TEST_DATABASE_URL)
    async with engine.begin() as connection:
        # asyncpg prepares every statement, and a prepared statement holds one command,
        # so these go one at a time rather than as a single script.
        await connection.execute(text("DROP SCHEMA public CASCADE"))
        await connection.execute(text("CREATE SCHEMA public"))
    yield engine
    await engine.dispose()


async def test_the_migrations_build_the_schema_the_models_describe(blank_database):
    await asyncio.to_thread(command.upgrade, _config(), "head")

    def _compare(connection) -> list:
        context = MigrationContext.configure(
            connection, opts={"compare_type": True, "compare_server_default": True}
        )
        return compare_metadata(context, Base.metadata)

    async with blank_database.connect() as connection:
        differences = await connection.run_sync(_compare)

    assert differences == [], (
        "the models and the migrations have drifted apart; "
        "run `alembic revision --autogenerate` and commit the result"
    )


async def test_every_migration_can_be_rolled_back(blank_database):
    """A migration you cannot undo is one you cannot safely deploy on a Sunday evening."""
    await asyncio.to_thread(command.upgrade, _config(), "head")
    await asyncio.to_thread(command.downgrade, _config(), "base")

    async with blank_database.connect() as connection:
        tables = (
            await connection.execute(
                text(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = 'public' AND table_name <> 'alembic_version'"
                )
            )
        ).scalars().all()
    assert list(tables) == []
