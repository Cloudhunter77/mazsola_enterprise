"""Shared fixtures. Builds identifications by hand so the rule tests need no photographs."""

from __future__ import annotations

import pytest

from leltar.schemas.identification import Box, IdentifiedObject, IdentifiedPhoto


def obj(
    name: str = "fehér porcelán bögre",
    *,
    category: str = "konyha",
    brand: str | None = None,
    product_model: str | None = None,
    markings_legible: bool = False,
    colour: str | None = "fehér",
    material: str | None = "porcelán",
    condition: str = "good",
    quantity: int = 1,
    value_low_huf: int | None = 800,
    value_high_huf: int | None = 2000,
    serial_number: str | None = None,
    serial_visible: bool = False,
    description: str | None = None,
    alternatives: list[str] | None = None,
    confidence: float = 0.9,
    box: tuple[int, int, int, int] | None = None,
) -> IdentifiedObject:
    return IdentifiedObject(
        name=name,
        category=category,
        brand=brand,
        product_model=product_model,
        markings_legible=markings_legible,
        colour=colour,
        material=material,
        condition=condition,
        quantity=quantity,
        value_low_huf=value_low_huf,
        value_high_huf=value_high_huf,
        serial_number=serial_number,
        serial_visible=serial_visible,
        description=description,
        alternatives=alternatives or [],
        confidence=confidence,
        box=Box(x0=box[0], y0=box[1], x1=box[2], y1=box[3]) if box else None,
    )


def build_photo(**overrides) -> IdentifiedPhoto:
    """A plausible shelf: three things, nothing wrong with any of them."""
    defaults = dict(
        scene="konyhai polc edényekkel",
        objects=[
            obj(box=(100, 200, 300, 450)),
            obj("fa vágódeszka", material="fa", value_low_huf=2000, value_high_huf=5000,
                box=(350, 180, 600, 430)),
            obj(
                "Bosch kézi mixer",
                category="konyha",
                brand="Bosch",
                markings_legible=True,
                value_low_huf=8000,
                value_high_huf=20000,
                box=(650, 150, 900, 470),
            ),
        ],
        confidence=0.88,
        notes=None,
    )
    defaults.update(overrides)
    return IdentifiedPhoto(**defaults)


@pytest.fixture
def photo() -> IdentifiedPhoto:
    return build_photo()


# --- database fixtures -------------------------------------------------------
# These require a real PostgreSQL: the statistics queries use date_trunc and the worker
# uses SELECT ... FOR UPDATE SKIP LOCKED, neither of which SQLite can stand in for.
import io  # noqa: E402
import os  # noqa: E402

from PIL import Image  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from leltar.models import Base  # noqa: E402

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL") or os.environ.get("DATABASE_URL")

requires_db = pytest.mark.skipif(
    not TEST_DATABASE_URL or "postgresql" not in TEST_DATABASE_URL,
    reason="set TEST_DATABASE_URL to a PostgreSQL DSN to run database tests",
)


@pytest.fixture
async def sessionmaker_fixture():
    engine = create_async_engine(TEST_DATABASE_URL, poolclass=None)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield maker
    finally:
        await engine.dispose()


@pytest.fixture
async def session(sessionmaker_fixture):
    async with sessionmaker_fixture() as s:
        yield s


@pytest.fixture
def item_photo() -> bytes:
    """A real (if boring) JPEG. Ingest verifies the bytes are a decodable image."""
    buffer = io.BytesIO()
    Image.new("RGB", (1200, 900), (210, 205, 195)).save(buffer, format="JPEG")
    return buffer.getvalue()


# --- HTTP client fixtures ----------------------------------------------------
# The real ASGI app wired to the test database, with the lifespan not run (migrations and
# the startup configuration guard are covered separately).
from httpx import ASGITransport, AsyncClient  # noqa: E402

from leltar.config import Settings, get_settings  # noqa: E402
from leltar.db import get_session  # noqa: E402
from leltar.main import create_app  # noqa: E402
from leltar.security import hash_password  # noqa: E402

TEST_SECRET = "b8f2c1d4e5a6079813f2c4d5e6a7b8c9d0e1f2a3b4c5d6e7f8091a2b3c4d5e6f"
TEST_PASSWORD = "helyes-jelszo-123"
TEST_API_KEY = "test-api-key-0123456789"


@pytest.fixture
def app_settings(tmp_path) -> Settings:
    return Settings(
        data_dir=tmp_path,
        secret_key=TEST_SECRET,
        app_password_hash=hash_password(TEST_PASSWORD),
        api_key=TEST_API_KEY,
        auth_disabled=False,
        worker_enabled=False,
        identifier="stub",
    )


@pytest.fixture
async def client(app_settings, sessionmaker_fixture):
    app = create_app()

    async def _session():
        async with sessionmaker_fixture() as session:
            yield session

    app.dependency_overrides[get_settings] = lambda: app_settings
    app.dependency_overrides[get_session] = _session

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://nas") as http:
        yield http


@pytest.fixture
async def auth_client(client):
    """A client that has already logged in, for the endpoints that need a session."""
    client.headers["X-API-Key"] = TEST_API_KEY
    return client


@pytest.fixture
async def seeded_client(auth_client, sessionmaker_fixture):
    """An authenticated client against a database that has its categories and places.

    Seeding is part of startup, and the client fixture deliberately does not run the
    lifespan, so anything that files an item under a category needs this instead.
    """
    from leltar.services.seed import seed_if_empty

    async with sessionmaker_fixture() as session:
        await seed_if_empty(session)
    return auth_client
