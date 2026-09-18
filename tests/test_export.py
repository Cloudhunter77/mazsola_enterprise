"""Exporting the receipts you never confirmed, so a misreading can be studied.

Leaving a receipt unconfirmed is how you say "this reading is wrong". That makes the
unconfirmed pile the raw material for improving the prompt - but only if what the app read
and what it was looking at come out together. A table of numbers with no photograph beside
it says nothing about *why* the model got it wrong.
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select

from app.config import Settings
from app.models import Receipt, ReceiptItem, ReceiptStatus
from app.services.ingest import ingest_image
from app.worker import ExtractionWorker
from scripts.export_unconfirmed import collect, copy_images, render
from tests.conftest import requires_db
from tests.test_pipeline import StubExtractor

pytestmark = requires_db


async def _photographed_receipt(session, sessionmaker, tmp_path, receipt_photo) -> Receipt:
    """A receipt that went through the real pipeline, so it has a photo and a reading."""
    settings = Settings(
        data_dir=tmp_path, extractor="stub", auth_disabled=True,
        worker_enabled=False, secret_key="test",
    )
    receipt, _ = await ingest_image(session, receipt_photo, settings)
    await session.commit()
    # Keep the id as a plain value. The worker commits in its own session and this one is
    # expired below, after which reading `receipt.id` would try to reload the row from a
    # plain attribute access - the MissingGreenlet this project keeps walking into.
    receipt_id = receipt.id

    worker = ExtractionWorker(settings)
    worker._extractor = StubExtractor()
    import app.worker as worker_module

    original = worker_module.SessionLocal
    worker_module.SessionLocal = sessionmaker
    try:
        assert await worker.process_next() is True
    finally:
        worker_module.SessionLocal = original

    session.expire_all()
    return await session.get(Receipt, receipt_id)


@requires_db
class TestWhatComesOut:
    async def test_it_exports_a_receipt_you_have_not_accepted(
        self, session, sessionmaker_fixture, tmp_path, receipt_photo
    ):
        await _photographed_receipt(session, sessionmaker_fixture, tmp_path, receipt_photo)

        exports = await collect(session)
        assert len(exports) == 1
        assert exports[0].merchant_name == "Tesco"

    async def test_a_confirmed_receipt_is_left_out(
        self, session, sessionmaker_fixture, tmp_path, receipt_photo
    ):
        """Confirming it is you saying the reading was right; there is nothing to learn."""
        receipt = await _photographed_receipt(
            session, sessionmaker_fixture, tmp_path, receipt_photo
        )
        receipt.status = ReceiptStatus.CONFIRMED.value
        await session.commit()

        assert await collect(session) == []

    async def test_every_printed_line_is_in_the_document(
        self, session, sessionmaker_fixture, tmp_path, receipt_photo
    ):
        receipt = await _photographed_receipt(
            session, sessionmaker_fixture, tmp_path, receipt_photo
        )
        document = render(await collect(session))

        items = (
            await session.scalars(
                select(ReceiptItem).where(ReceiptItem.receipt_id == receipt.id)
            )
        ).all()
        assert items, "the stub extractor should have produced lines"
        for item in items:
            assert item.raw_name in document, f"{item.raw_name} is missing from the export"

    async def test_the_numbers_needed_to_spot_a_misreading_are_there(
        self, session, sessionmaker_fixture, tmp_path, receipt_photo
    ):
        await _photographed_receipt(session, sessionmaker_fixture, tmp_path, receipt_photo)
        document = render(await collect(session))

        # A thousands separator dropped by the model shows up as a wrong total, so the
        # total and the per-line amounts both have to survive the export.
        assert "3 595.00" in document, "the receipt total must be in the document"
        assert "1 098.00" in document, "a line amount must be in the document"
        assert "stub" in document, "which engine read it is part of the evidence"

    async def test_the_model_s_own_answer_is_kept(
        self, session, sessionmaker_fixture, tmp_path, receipt_photo
    ):
        """The stored rows are post-processed; the raw JSON is what the model actually said."""
        await _photographed_receipt(session, sessionmaker_fixture, tmp_path, receipt_photo)
        document = render(await collect(session))

        assert "raw model response" in document
        assert "total_printed" in document, "the transcription cross-check is the evidence"

    async def test_the_photograph_comes_out_beside_the_reading(
        self, session, sessionmaker_fixture, tmp_path, receipt_photo
    ):
        await _photographed_receipt(session, sessionmaker_fixture, tmp_path, receipt_photo)
        exports = await collect(session)

        out = tmp_path / "export"
        copied, missing = copy_images(exports, out)

        assert copied == 1 and missing == []
        stored = list((out / "images").iterdir())
        assert len(stored) == 1
        assert stored[0].name.startswith(exports[0].short_id)
        assert stored[0].read_bytes() == receipt_photo, "the original photo, not a re-encode"

    async def test_a_missing_photo_is_reported_rather_than_crashing(
        self, session, sessionmaker_fixture, tmp_path, receipt_photo
    ):
        """One deleted file must not cost you the export of everything else."""
        receipt = await _photographed_receipt(
            session, sessionmaker_fixture, tmp_path, receipt_photo
        )
        exports = await collect(session)
        exports[0].image_paths = ["/nincs/ilyen/kep.jpg"]

        copied, missing = copy_images(exports, tmp_path / "export")
        assert copied == 0
        assert missing and str(receipt.id)[:8] in missing[0]


@requires_db
class TestItReadsNothingItShouldNot:
    async def test_it_does_not_export_a_typed_in_receipt(self, session):
        """A receipt you typed has no photograph and nothing to say about the prompt."""
        from datetime import UTC, datetime

        from app.services.manual import create_manual_receipt

        receipt = await create_manual_receipt(
            session,
            merchant_name="Lidl",
            purchased_at=datetime(2026, 9, 1, tzinfo=UTC),
            items=[{"raw_name": "Bevásárlás", "gross_amount": 4200}],
        )
        # Force it out of `confirmed` so only the missing photo can exclude it.
        receipt.status = ReceiptStatus.NEEDS_REVIEW.value
        await session.commit()

        assert await collect(session) == []

    async def test_it_changes_nothing(
        self, session, sessionmaker_fixture, tmp_path, receipt_photo
    ):
        receipt = await _photographed_receipt(
            session, sessionmaker_fixture, tmp_path, receipt_photo
        )
        receipt_id = receipt.id
        before = (receipt.status, receipt.total_gross)

        await collect(session)
        session.expire_all()

        after = await session.get(Receipt, receipt_id)
        assert (after.status, after.total_gross) == before
        assert after.total_gross == Decimal("3595.00")
