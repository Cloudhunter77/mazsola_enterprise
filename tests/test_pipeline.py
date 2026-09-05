"""End-to-end: a photo goes in, queryable expense rows come out.

Uses a stub extractor, so the pipeline, persistence and statistics are exercised without
spending money or depending on the network. The real engine is covered by `-m live`.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.config import Settings
from app.extraction.base import ExtractionError, ExtractionResult, as_parts
from app.models import LineKind, Merchant, Product, Receipt, ReceiptItem, ReceiptStatus
from app.schemas.extraction import ExtractedReceipt
from app.services import stats
from app.services.catalog import link_product
from app.services.ingest import IngestError, ingest_image
from app.services.seed import seed_categories
from app.worker import ExtractionWorker
from tests.conftest import build_receipt, requires_db

pytestmark = requires_db


class StubExtractor:
    """Stands in for Claude: returns a prepared receipt and records what it was asked."""

    name = "stub"

    def __init__(self, receipt: ExtractedReceipt | None = None, error: str | None = None):
        self.receipt = receipt or build_receipt()
        self.error = error
        self.calls = 0
        self.parts_seen: list[int] = []

    async def extract(self, images, mime_type: str = "image/jpeg") -> ExtractionResult:
        self.calls += 1
        self.parts_seen.append(len(as_parts(images)))
        if self.error:
            raise ExtractionError(self.error)
        return ExtractionResult(
            receipt=self.receipt,
            extractor=self.name,
            model="stub-1",
            input_tokens=3000,
            output_tokens=1200,
            cache_read_tokens=1300,
            cost_usd=Decimal("0.045000"),
            latency_ms=4200,
            raw=self.receipt.model_dump(mode="json"),
        )


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        data_dir=tmp_path,
        extractor="stub",
        auth_disabled=True,
        worker_enabled=False,
        secret_key="test",
    )


async def run_worker_once(sessionmaker, settings, extractor) -> None:
    worker = ExtractionWorker(settings)
    worker._extractor = extractor
    import app.worker as worker_module

    original = worker_module.SessionLocal
    worker_module.SessionLocal = sessionmaker
    try:
        assert await worker.process_next() is True
    finally:
        worker_module.SessionLocal = original


class TestIngest:
    async def test_stores_photo_and_queues_it(self, session, settings, receipt_photo):
        receipt, created = await ingest_image(session, receipt_photo, settings)
        await session.commit()

        assert created is True
        assert receipt.status == ReceiptStatus.PENDING.value
        assert receipt.image_bytes == len(receipt_photo)
        from pathlib import Path

        assert Path(receipt.image_path).is_file(), "the original photo must be kept"

    async def test_same_photo_twice_is_one_receipt(self, session, settings, receipt_photo):
        first, created_first = await ingest_image(session, receipt_photo, settings)
        await session.commit()
        second, created_second = await ingest_image(session, receipt_photo, settings)

        assert created_first is True and created_second is False
        assert first.id == second.id, "a retrying shortcut must not double-count spending"

    async def test_rejects_non_images(self, session, settings):
        with pytest.raises(IngestError):
            await ingest_image(session, b"this is not a photo", settings)

    async def test_rejects_empty_upload(self, session, settings):
        with pytest.raises(IngestError):
            await ingest_image(session, b"", settings)


class TestPipeline:
    async def test_photo_becomes_expense_rows(
        self, session, sessionmaker_fixture, settings, receipt_photo
    ):
        receipt, _ = await ingest_image(session, receipt_photo, settings)
        receipt_id = receipt.id
        await session.commit()

        await run_worker_once(sessionmaker_fixture, settings, StubExtractor())

        stored = await session.get(Receipt, receipt_id)
        await session.refresh(stored)
        assert stored.status == ReceiptStatus.PARSED.value
        assert stored.total_gross == Decimal("3595.00")
        assert stored.payment_method == "cash"
        assert stored.purchased_at is not None

        merchant = await session.get(Merchant, stored.merchant_id)
        assert merchant.name == "Tesco", "chain names must collapse across branches"

        items = (
            await session.scalars(
                select(ReceiptItem).where(ReceiptItem.receipt_id == receipt_id)
            )
        ).all()
        kinds = {i.raw_name: i.kind for i in items}
        assert kinds["BETÉTDÍJ"] == LineKind.DEPOSIT.value
        assert kinds["KEREKÍTÉS"] == LineKind.ROUNDING.value
        assert kinds["KEDVEZMÉNY AKCIÓ"] == LineKind.DISCOUNT.value

        discount = next(i for i in items if i.kind == LineKind.DISCOUNT.value)
        assert discount.gross_amount == Decimal("-200.00")

    async def test_change_line_never_reaches_the_database(
        self, session, sessionmaker_fixture, settings, receipt_photo
    ):
        from tests.conftest import item

        extracted = build_receipt()
        extracted.items.append(item(8, "VISSZAJÁRÓ", 1305.0))

        receipt, _ = await ingest_image(session, receipt_photo, settings)
        receipt_id = receipt.id
        await session.commit()

        await run_worker_once(sessionmaker_fixture, settings, StubExtractor(extracted))

        names = (
            await session.scalars(
                select(ReceiptItem.raw_name).where(ReceiptItem.receipt_id == receipt_id)
            )
        ).all()
        assert "VISSZAJÁRÓ" not in names

    async def test_unbalanced_receipt_goes_to_review(
        self, session, sessionmaker_fixture, settings, receipt_photo
    ):
        extracted = build_receipt(total_gross=9999.0)
        receipt, _ = await ingest_image(session, receipt_photo, settings)
        receipt_id = receipt.id
        await session.commit()

        await run_worker_once(sessionmaker_fixture, settings, StubExtractor(extracted))

        stored = await session.get(Receipt, receipt_id)
        await session.refresh(stored)
        assert stored.status == ReceiptStatus.NEEDS_REVIEW.value
        assert "items_total_mismatch" in stored.review_reasons

    async def test_extraction_cost_is_recorded(
        self, session, sessionmaker_fixture, settings, receipt_photo
    ):
        await ingest_image(session, receipt_photo, settings)
        await session.commit()
        await run_worker_once(sessionmaker_fixture, settings, StubExtractor())

        from app.models import ExtractionAttempt

        attempt = await session.scalar(select(ExtractionAttempt))
        assert attempt.succeeded is True
        assert attempt.cost_usd == Decimal("0.045000")
        assert attempt.cache_read_tokens == 1300

    async def test_failure_retries_then_gives_up(
        self, session, sessionmaker_fixture, settings, receipt_photo
    ):
        receipt, _ = await ingest_image(session, receipt_photo, settings)
        receipt_id = receipt.id
        await session.commit()

        broken = StubExtractor(error="the model is having a bad day")
        for _ in range(settings.worker_max_attempts):
            await run_worker_once(sessionmaker_fixture, settings, broken)

        stored = await session.get(Receipt, receipt_id)
        await session.refresh(stored)
        assert stored.status == ReceiptStatus.FAILED.value
        assert stored.attempts == settings.worker_max_attempts
        assert "bad day" in stored.error

    async def test_reprocessing_replaces_items_instead_of_duplicating(
        self, session, sessionmaker_fixture, settings, receipt_photo
    ):
        receipt, _ = await ingest_image(session, receipt_photo, settings)
        receipt_id = receipt.id
        await session.commit()

        await run_worker_once(sessionmaker_fixture, settings, StubExtractor())
        first_count = await session.scalar(
            select(func.count(ReceiptItem.id)).where(ReceiptItem.receipt_id == receipt_id)
        )

        stored = await session.get(Receipt, receipt_id)
        await session.refresh(stored)
        stored.status = ReceiptStatus.PENDING.value
        await session.commit()

        await run_worker_once(sessionmaker_fixture, settings, StubExtractor())
        second_count = await session.scalar(
            select(func.count(ReceiptItem.id)).where(ReceiptItem.receipt_id == receipt_id)
        )
        assert first_count == second_count


class TestResilience:
    """What happens when things are interrupted - the normal state of a home NAS."""

    async def test_a_receipt_stranded_by_a_crash_is_picked_up_again(
        self, session, sessionmaker_fixture, settings, receipt_photo
    ):
        """A container restart mid-extraction used to leave a receipt in 'processing'
        forever: the worker only ever looked at 'pending', so it was never retried."""
        from datetime import UTC, datetime, timedelta

        from sqlalchemy import update

        receipt, _ = await ingest_image(session, receipt_photo, settings)
        receipt_id = receipt.id
        receipt.status = ReceiptStatus.PROCESSING.value
        receipt.attempts = 1
        await session.commit()
        await session.execute(
            update(Receipt)
            .where(Receipt.id == receipt_id)
            .values(updated_at=datetime.now(UTC) - timedelta(hours=1))
        )
        await session.commit()

        await run_worker_once(sessionmaker_fixture, settings, StubExtractor())

        stored = await session.get(Receipt, receipt_id)
        await session.refresh(stored)
        assert stored.status == ReceiptStatus.PARSED.value

    async def test_a_recent_in_flight_receipt_is_left_alone(
        self, session, sessionmaker_fixture, settings, receipt_photo
    ):
        """The mirror image: a live extraction must never be stolen and paid for twice."""
        receipt, _ = await ingest_image(session, receipt_photo, settings)
        receipt.status = ReceiptStatus.PROCESSING.value
        await session.commit()

        worker = ExtractionWorker(settings)
        worker._extractor = StubExtractor()
        import app.worker as worker_module

        original = worker_module.SessionLocal
        worker_module.SessionLocal = sessionmaker_fixture
        try:
            assert await worker.process_next() is False
        finally:
            worker_module.SessionLocal = original

    async def test_two_simultaneous_uploads_of_one_photo(
        self, sessionmaker_fixture, settings, receipt_photo, tmp_path
    ):
        """A retrying phone shortcut can have two uploads in flight. Both used to get past
        the duplicate check; one then died on the unique index and left a stray file."""
        import asyncio

        async def upload():
            async with sessionmaker_fixture() as session:
                receipt, created = await ingest_image(session, receipt_photo, settings)
                await asyncio.sleep(0.05)
                await session.commit()
                return receipt.id, created

        results = await asyncio.gather(*(upload() for _ in range(2)))

        assert results[0][0] == results[1][0], "both callers should get the same receipt"
        assert sorted(created for _, created in results) == [False, True]

        files = list((settings.image_dir).rglob("*.jpg"))
        assert len(files) == 1, "a lost race must not leave an orphaned file behind"


class TestStatistics:
    @pytest.fixture
    async def populated(self, session, sessionmaker_fixture, settings, receipt_photo):
        await seed_categories(session)
        await ingest_image(session, receipt_photo, settings)
        await session.commit()
        await run_worker_once(sessionmaker_fixture, settings, StubExtractor())
        return session

    async def test_summary_counts_spend_and_items(self, populated):
        result = await stats.summary(populated)
        assert result.total == Decimal("3595.00")
        assert result.receipt_count == 1
        assert result.item_count == 4, "deposits, discounts and rounding are not groceries"

    async def test_monthly_and_merchant_breakdowns(self, populated):
        months = await stats.monthly(populated)
        assert len(months) == 1 and months[0].total == Decimal("3595.00")

        merchants = await stats.by_merchant(populated)
        assert merchants[0].merchant_name == "Tesco"
        assert merchants[0].average_basket == Decimal("3595.00")

    async def test_uncategorised_items_still_appear(self, populated):
        categories = await stats.by_category(populated)
        assert categories, "items with no category must not vanish from the breakdown"
        assert categories[0].category_name == "Besorolatlan"
        assert abs(sum(c.share for c in categories) - 1.0) < 1e-6

    async def test_price_history_tracks_a_product(self, populated):
        product = Product(canonical_name="Tej 2,8% 1L")
        populated.add(product)
        await populated.flush()

        item = await populated.scalar(
            select(ReceiptItem).where(ReceiptItem.raw_name == "TEJ 2,8% 1L UHT")
        )
        item.product_id = product.id
        receipt = await populated.get(Receipt, item.receipt_id)
        await link_product(populated, product.id, item.raw_name, receipt.merchant_id)
        await populated.commit()

        history = await stats.price_history(populated, product.id)
        assert history.product_name == "Tej 2,8% 1L"
        assert len(history.points) == 1
        assert history.points[0].unit_price == Decimal("363.00")
        assert history.cheapest_merchant == "Tesco"

    async def test_price_history_of_unknown_product(self, populated):
        assert await stats.price_history(populated, uuid.uuid4()) is None

    async def test_basket_comparison_needs_two_shops(self, populated):
        comparison = await stats.basket_comparison(populated)
        assert comparison.product_count == 0, "one shop cannot be compared against itself"
        assert comparison.merchants == []
