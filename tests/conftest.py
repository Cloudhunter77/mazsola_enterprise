"""Shared fixtures. Builds synthetic Hungarian receipts so the rule tests need no images."""

from __future__ import annotations

import pytest

from app.schemas.extraction import ExtractedItem, ExtractedReceipt, ExtractedVatLine

# Distinguishes "caller said nothing" from "caller said None".
UNSET = object()


def item(
    line_no: int,
    raw_name: str,
    gross_amount: float,
    *,
    quantity: float | None = 1,
    unit: str | None = "db",
    unit_price: float | None = None,
    vat_code: str | None = "A",
    vat_rate: float | None = 27,
    kind: str = "item",
    confidence: float = 0.95,
    amount_printed: str | None | object = UNSET,
) -> ExtractedItem:
    return ExtractedItem(
        line_no=line_no,
        raw_name=raw_name,
        # Left unset, it mirrors the number, so a fixture that does not care about the
        # transcription cross-check is consistent rather than exempt from it. Passing None
        # explicitly is a different statement - "this line had no printed amount" - and a
        # default of None could not express both.
        amount_printed=str(gross_amount) if amount_printed is UNSET else amount_printed,
        quantity=quantity,
        unit=unit,
        unit_price=unit_price if unit_price is not None else gross_amount,
        gross_amount=gross_amount,
        vat_code=vat_code,
        vat_rate=vat_rate,
        kind=kind,
        confidence=confidence,
    )


def build_receipt(**overrides) -> ExtractedReceipt:
    """A plausible cash receipt: items, a discount, a deposit and 5 Ft rounding."""
    defaults = dict(
        merchant_name="TESCO-GLOBAL ÁRUHÁZAK ZRT.",
        merchant_address="2040 Budaörs, Kinizsi út 1-3.",
        tax_number="10307078-2-44",
        purchased_at="2026-08-14T17:22:00",
        receipt_no="NY-000123",
        nav_ap_code="AP A12345678",
        payment_method="cash",
        currency="HUF",
        total_gross=3595.0,
        total_printed="3 595",
        total_net=None,
        total_vat=None,
        rounding=-2.0,
        discount_total=200.0,
        items=[
            item(1, "COCA COLA 1,75L", 1098.0, quantity=2, unit_price=549.0),
            item(2, "BETÉTDÍJ", 100.0, quantity=2, unit_price=50.0, kind="deposit"),
            item(3, "ALMA IDARED", 247.0, quantity=0.412, unit="kg", unit_price=599.0,
                 vat_code="C", vat_rate=5),
            item(4, "TEJ 2,8% 1L UHT", 1452.0, quantity=4, unit_price=363.0,
                 vat_code="B", vat_rate=18),
            item(5, "SAJT TRAPPISTA", 900.0, vat_code="B", vat_rate=18),
            item(6, "KEDVEZMÉNY AKCIÓ", -200.0, kind="discount", vat_code=None, vat_rate=None),
            item(7, "KEREKÍTÉS", -2.0, kind="rounding", vat_code=None, vat_rate=None),
        ],
        vat_summary=[
            # Gross per rate is after the discount and before the 5 Ft rounding: 3597 in total.
            ExtractedVatLine(vat_code="A", vat_rate=27, net=785.83, vat=212.17, gross=998.0),
            ExtractedVatLine(vat_code="B", vat_rate=18, net=1993.22, vat=358.78, gross=2352.0),
            ExtractedVatLine(vat_code="C", vat_rate=5, net=235.24, vat=11.76, gross=247.0),
        ],
        confidence=0.93,
        notes=None,
    )
    defaults.update(overrides)
    return ExtractedReceipt(**defaults)


@pytest.fixture
def receipt() -> ExtractedReceipt:
    return build_receipt()


# --- database fixtures -------------------------------------------------------
# These require a real PostgreSQL: the statistics queries use date_trunc and the worker
# uses SELECT ... FOR UPDATE SKIP LOCKED, neither of which SQLite can stand in for.
import io  # noqa: E402
import os  # noqa: E402

from PIL import Image  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from app.models import Base  # noqa: E402

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
def receipt_photo() -> bytes:
    """A real (if boring) JPEG. Ingest verifies the bytes are a decodable image."""
    buffer = io.BytesIO()
    Image.new("RGB", (900, 1600), (252, 252, 250)).save(buffer, format="JPEG")
    return buffer.getvalue()


# --- HTTP client fixtures ----------------------------------------------------
# The real ASGI app wired to the test database, with the lifespan not run (migrations
# and the startup configuration guard are covered separately).
from httpx import ASGITransport, AsyncClient  # noqa: E402

from app.config import Settings, get_settings  # noqa: E402
from app.db import get_session  # noqa: E402
from app.main import create_app  # noqa: E402
from app.security import hash_password  # noqa: E402

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
        extractor="stub",
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
