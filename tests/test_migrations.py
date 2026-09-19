"""Upgrading a database that already has a year of receipts in it.

Every other test here starts from an empty schema built by `create_all`, which is exactly
the case a migration cannot get wrong. The case that matters is the other one: a database
with real rows in it, upgraded in place while the app starts. There is no undo for that -
the receipts are the point of the app, and losing them to a bad migration would be losing
the thing itself.

So these tests seed a database at the revision before head, run the upgrade the container
runs, and check the rows are still there afterwards - the same values, still joined to each
other, and (for the fingerprint column) *backfilled*, because a new column that only fills
itself for future receipts would leave everything already stored unmatched.
"""

from __future__ import annotations

import ast
import asyncio
import uuid
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.models import Base
from tests.conftest import TEST_DATABASE_URL, requires_db

ROOT = Path(__file__).resolve().parent.parent
VERSIONS = ROOT / "app" / "migrations" / "versions"


def _config() -> Config:
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "app" / "migrations"))
    # ConfigParser reads `%` as interpolation; a password containing one would otherwise
    # take the whole run down before it touched the database.
    config.set_main_option("sqlalchemy.url", (TEST_DATABASE_URL or "").replace("%", "%%"))
    config.attributes["configure_logger"] = False
    return config


async def _alembic(subcommand, revision: str) -> None:
    """Run Alembic the way the app does: in a thread, because env.py owns its event loop."""
    await asyncio.to_thread(subcommand, _config(), revision)


def _revisions() -> list[str]:
    """Every revision, oldest first."""
    script = ScriptDirectory.from_config(_config())
    return [rev.revision for rev in reversed(list(script.walk_revisions()))]


# --- what a migration is allowed to do ---------------------------------------
# A static check, so it fails on the pull request rather than on the NAS. It cannot prove a
# migration is safe, but the one shape that destroys data without any way back is exactly
# the one that is easy to spot.

DESTRUCTIVE = {"drop_table", "drop_column"}


def _upgrade_calls(path: Path) -> set[str]:
    tree = ast.parse(path.read_text())
    upgrade = next(
        (n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "upgrade"), None
    )
    if upgrade is None:
        return set()
    return {
        node.func.attr
        for node in ast.walk(upgrade)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }


@pytest.mark.parametrize("path", sorted(VERSIONS.glob("*.py")), ids=lambda p: p.stem[:12])
def test_no_migration_drops_anything_on_the_way_up(path: Path):
    """Dropping a table or column is unrecoverable, and never what a new feature needs.

    If one day it genuinely is, this test is the conversation about backing up first -
    which is the point of it failing here rather than at 2am on the NAS.
    """
    assert not (_upgrade_calls(path) & DESTRUCTIVE), (
        f"{path.name} drops something in upgrade(); that destroys stored receipts"
    )


def test_the_revisions_form_one_chain():
    """Two heads means `upgrade head` fails at start-up, and the app never comes back."""
    script = ScriptDirectory.from_config(_config())
    assert len(script.get_heads()) == 1, script.get_heads()


# --- upgrading over real rows ------------------------------------------------

IDS = {name: uuid.uuid4() for name in (
    "category", "merchant", "product", "receipt", "mapped", "unmapped", "rule"
)}

# Written as SQL rather than through the ORM on purpose: at the revision being seeded, the
# ORM's idea of the schema is a version ahead, and inserting through it would fail on the
# very column the upgrade is supposed to add.
SEED = (
    "INSERT INTO categories (id, name, slug, sort_order) "
    "VALUES (:category, 'Élelmiszer', 'elelmiszer', 1)",
    "INSERT INTO merchants (id, name, slug) VALUES (:merchant, 'Lidl', 'lidl')",
    "INSERT INTO products (id, canonical_name, category_id) "
    "VALUES (:product, 'Pepsi 1,5 l', :category)",
    "INSERT INTO product_aliases (id, product_id, raw_name) "
    "VALUES (gen_random_uuid(), :product, 'PEPSI 1,5L')",
    "INSERT INTO receipts (id, merchant_id, purchased_at, total_gross, currency, "
    "payment_method, status, source, image_mime, attempts) "
    "VALUES (:receipt, :merchant, '2026-03-04 10:00+01', 1798.00, 'HUF', 'card', "
    "'confirmed', 'web', 'image/jpeg', 1)",
    "INSERT INTO receipt_items (id, receipt_id, line_no, raw_name, gross_amount, kind, "
    "product_id, category_id) "
    "VALUES (:mapped, :receipt, 1, 'PEPSI 1,5L', 899.00, 'item', :product, :category)",
    "INSERT INTO receipt_items (id, receipt_id, line_no, raw_name, gross_amount, kind) "
    "VALUES (:unmapped, :receipt, 2, 'PEPSI 1500ML', 899.00, 'item')",
    "INSERT INTO recurring_payments (id, name, merchant_name, amount, currency, cadence, "
    "day_of_month, payment_method, starts_on, active) "
    "VALUES (:rule, 'Spotify', 'Spotify', 1999.00, 'HUF', 'monthly', 5, 'card', "
    "'2026-01-05', true)",
)


async def _seeded_then_upgraded(start: str):
    """Build a database at `start`, fill it with rows, then upgrade it to head."""
    engine = create_async_engine(TEST_DATABASE_URL, poolclass=None)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.execute(text("DROP TABLE IF EXISTS alembic_version"))

    await _alembic(command.upgrade, start)

    async with engine.begin() as conn:
        for statement in SEED:
            # UUID objects rather than strings: asyncpg types a parameter from the
            # prepared statement, and a uuid column wants a uuid.
            await conn.execute(text(statement), IDS)

    await _alembic(command.upgrade, "head")
    try:
        yield engine
    finally:
        # The other database tests build their schema with `create_all` and expect no
        # `alembic_version` table; leaving one behind would change their answers.
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.execute(text("DROP TABLE IF EXISTS alembic_version"))
        await engine.dispose()


@pytest.fixture
async def upgraded():
    """Seeded at whatever revision precedes head, then upgraded.

    Deliberately relative: this fixture asks "does the newest migration lose anything",
    so it has to follow head as migrations are added.
    """
    async for engine in _seeded_then_upgraded(_revisions()[-2]):
        yield engine


# The revision before the fingerprint column existed. Pinned by name on purpose: a test
# about one migration's behaviour has to start from the schema that migration ran against.
# Written as "head minus one" it silently stopped testing anything the moment an unrelated
# migration landed on top - it seeded a database that already had the column, so there was
# nothing left to backfill and the test failed for a reason that had nothing to do with
# what it was checking.
BEFORE_FINGERPRINTS = "c2f83a41b6d7"


@pytest.fixture
async def upgraded_from_before_fingerprints():
    async for engine in _seeded_then_upgraded(BEFORE_FINGERPRINTS):
        yield engine


@requires_db
class TestYourReceiptsSurviveAnUpgrade:
    async def test_every_row_is_still_there(self, upgraded):
        async with upgraded.connect() as conn:
            for table, expected in (
                ("categories", 1), ("merchants", 1), ("products", 1), ("product_aliases", 1),
                ("receipts", 1), ("receipt_items", 2), ("recurring_payments", 1),
            ):
                count = await conn.scalar(text(f"SELECT count(*) FROM {table}"))
                assert count == expected, f"{table} lost rows in the upgrade"

    async def test_the_money_is_unchanged(self, upgraded):
        async with upgraded.connect() as conn:
            total = await conn.scalar(
                text("SELECT total_gross FROM receipts WHERE id = :id"), {"id": IDS["receipt"]}
            )
        assert str(total) == "1798.00", "a receipt total must round-trip exactly"

    async def test_a_line_is_still_joined_to_its_product(self, upgraded):
        async with upgraded.connect() as conn:
            row = await conn.execute(
                text(
                    "SELECT p.canonical_name FROM receipt_items i "
                    "JOIN products p ON p.id = i.product_id WHERE i.id = :id"
                ),
                {"id": IDS["mapped"]},
            )
        assert row.scalar_one() == "Pepsi 1,5 l"

    async def test_the_schema_ends_at_head(self, upgraded):
        async with upgraded.connect() as conn:
            applied = await conn.scalar(text("SELECT version_num FROM alembic_version"))
        assert applied == _revisions()[-1]


@requires_db
class TestTheNewColumnCoversWhatIsAlreadyStored:
    """A new matching rule is worth little if it only applies to receipts scanned later."""

    async def test_an_existing_alias_is_backfilled(self, upgraded_from_before_fingerprints):
        """An alias stored before the column existed must come out of the upgrade filled in."""
        from app.services.matching import fingerprint

        async with upgraded_from_before_fingerprints.connect() as conn:
            stored = await conn.scalar(
                text("SELECT fingerprint FROM product_aliases WHERE raw_name = 'PEPSI 1,5L'")
            )
        assert stored == fingerprint("PEPSI 1,5L")
        assert stored, "an empty fingerprint would match nothing, which is the failure"

    async def test_a_line_stored_last_year_now_resolves(
        self, upgraded_from_before_fingerprints
    ):
        """The whole point: a differently-spelled old line finds the product it belongs to."""
        from sqlalchemy.ext.asyncio import async_sessionmaker

        from app.services.catalog import resolve_product

        maker = async_sessionmaker(upgraded_from_before_fingerprints, expire_on_commit=False)
        async with maker() as session:
            # Another till, printing millilitres for the same 1.5 l bottle.
            found = await resolve_product(session, "PEPSI 1500ML", IDS["merchant"])
            assert found is not None, "1500 ml is 1,5 l; this should link itself"
            assert found.canonical_name == "Pepsi 1,5 l"
