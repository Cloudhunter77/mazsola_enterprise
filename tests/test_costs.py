"""What the reading cost, split by what was being read.

The bug this file exists to prevent is not a wrong sum. It is a *missing* one: for a while
only receipts recorded an attempt, so photographing forty shelf labels on a Saturday cost
real money and moved the Costs page by nothing at all. A page that under-reports is worse
than no page, because it is believed.

So the tests below are mostly about presence - that a label call and a product-photo call
each leave a row, that the row carries which document it was, and that the totals include
them - rather than about arithmetic.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.extraction.base import ExtractionResult, LabelResult, ProductPhotoResult
from app.models import (
    AttemptKind,
    ExtractionAttempt,
    PriceLabelPhoto,
    Receipt,
    ReceiptStatus,
    ShoppingItem,
)
from app.schemas.price_label import ExtractedPriceLabels
from app.schemas.product_photo import ExtractedProductPhoto
from app.services.persist import record_attempt
from tests.conftest import build_receipt, requires_db

pytestmark = requires_db


def cost(value: str) -> Decimal:
    return Decimal(value)


async def a_receipt(session) -> Receipt:
    receipt = Receipt(
        image_path="x.jpg",
        image_sha256=uuid.uuid4().hex,
        status=ReceiptStatus.PARSED.value,
        source="upload",
    )
    session.add(receipt)
    await session.flush()
    return receipt


async def a_label_photo(session) -> PriceLabelPhoto:
    photo = PriceLabelPhoto(
        image_path="label.jpg",
        image_sha256=uuid.uuid4().hex,
        observed_at=datetime.now(UTC),
    )
    session.add(photo)
    await session.flush()
    return photo


async def a_shopping_item(session) -> ShoppingItem:
    item = ShoppingItem(raw_name="valami a polcról", source="scan")
    session.add(item)
    await session.flush()
    return item


def receipt_result(**kw) -> ExtractionResult:
    return ExtractionResult(
        receipt=build_receipt(), extractor="stub", model="cheap-model",
        input_tokens=3000, output_tokens=900, cost_usd=cost("0.000500"), **kw
    )


def label_result(**kw) -> LabelResult:
    return LabelResult(
        labels=ExtractedPriceLabels(merchant_name=None, labels=[], notes=None),
        extractor="stub", model="cheap-model",
        input_tokens=1200, output_tokens=300, cost_usd=cost("0.000200"), **kw
    )


def photo_result(**kw) -> ProductPhotoResult:
    return ProductPhotoResult(
        photo=ExtractedProductPhoto(
            raw_name="Pepsi Cola 1,5 l", brand="Pepsi", package_size=1.5,
            package_unit="l", category_hint="üdítő", notes=None, confidence=0.9,
        ),
        extractor="stub", model="cheap-model",
        input_tokens=900, output_tokens=60, cost_usd=cost("0.000100"), **kw
    )


class TestEveryCallIsRecorded:
    """The property that was broken: two of the three document types recorded nothing."""

    async def test_a_receipt_call_is_recorded_against_the_receipt(self, session):
        receipt = await a_receipt(session)
        await record_attempt(session, receipt, extractor="stub", result=receipt_result())
        await session.commit()

        attempt = await session.scalar(select(ExtractionAttempt))
        assert attempt.kind == AttemptKind.RECEIPT.value
        assert attempt.receipt_id == receipt.id
        assert attempt.price_label_photo_id is None

    async def test_a_shelf_label_call_is_recorded(self, session):
        photo = await a_label_photo(session)
        await record_attempt(
            session, extractor="stub", result=label_result(),
            kind=AttemptKind.PRICE_LABEL.value, price_label_photo_id=photo.id,
        )
        await session.commit()

        attempt = await session.scalar(select(ExtractionAttempt))
        assert attempt.kind == AttemptKind.PRICE_LABEL.value
        assert attempt.price_label_photo_id == photo.id
        # The column it used to require, and the reason label calls recorded nothing.
        assert attempt.receipt_id is None
        assert attempt.cost_usd == cost("0.000200")

    async def test_a_product_photo_call_is_recorded(self, session):
        item = await a_shopping_item(session)
        await record_attempt(
            session, extractor="stub", result=photo_result(),
            kind=AttemptKind.PRODUCT_PHOTO.value, shopping_item_id=item.id,
        )
        await session.commit()

        attempt = await session.scalar(select(ExtractionAttempt))
        assert attempt.kind == AttemptKind.PRODUCT_PHOTO.value
        assert attempt.shopping_item_id == item.id
        assert attempt.receipt_id is None

    async def test_a_failed_call_is_recorded_with_its_kind(self, session):
        photo = await a_label_photo(session)
        await record_attempt(
            session, extractor="stub", error="a gateway said no",
            kind=AttemptKind.PRICE_LABEL.value, price_label_photo_id=photo.id,
        )
        await session.commit()

        attempt = await session.scalar(select(ExtractionAttempt))
        assert attempt.succeeded is False
        assert attempt.kind == AttemptKind.PRICE_LABEL.value

    async def test_deleting_the_photo_does_not_keep_a_dangling_attempt(self, session):
        """The attempt hangs off the photo, so removing a bad photo takes its row with it."""
        photo = await a_label_photo(session)
        await record_attempt(
            session, extractor="stub", result=label_result(),
            kind=AttemptKind.PRICE_LABEL.value, price_label_photo_id=photo.id,
        )
        await session.commit()

        await session.delete(photo)
        await session.commit()
        assert await session.scalar(select(ExtractionAttempt)) is None


class TestTheSplit:
    @pytest.fixture
    async def three_kinds(self, session):
        """One of each, at deliberately different prices."""
        receipt = await a_receipt(session)
        photo = await a_label_photo(session)
        item = await a_shopping_item(session)
        await record_attempt(session, receipt, extractor="stub", result=receipt_result())
        await record_attempt(
            session, extractor="stub", result=label_result(),
            kind=AttemptKind.PRICE_LABEL.value, price_label_photo_id=photo.id,
        )
        await record_attempt(
            session, extractor="stub", result=photo_result(),
            kind=AttemptKind.PRODUCT_PHOTO.value, shopping_item_id=item.id,
        )
        await session.commit()

    async def test_each_kind_gets_its_own_line(self, auth_client, three_kinds):
        body = (await auth_client.get("/api/costs/summary")).json()
        by_kind = {row["kind"]: row for row in body["by_kind"]}

        assert set(by_kind) == {"receipt", "price_label", "product_photo"}
        assert Decimal(by_kind["receipt"]["total_usd"]) == cost("0.000500")
        assert Decimal(by_kind["price_label"]["total_usd"]) == cost("0.000200")
        assert Decimal(by_kind["product_photo"]["total_usd"]) == cost("0.000100")

    async def test_the_dearest_habit_is_listed_first(self, auth_client, three_kinds):
        """The page exists to answer "what should I change", so the answer goes at the top."""
        body = (await auth_client.get("/api/costs/summary")).json()
        assert [row["kind"] for row in body["by_kind"]] == [
            "receipt", "price_label", "product_photo"
        ]

    async def test_the_total_counts_all_three(self, auth_client, three_kinds):
        """This is the number that was wrong: it used to be the receipt bill alone."""
        body = (await auth_client.get("/api/costs/summary")).json()
        assert body["calls"] == 3
        assert Decimal(body["total_usd"]) == cost("0.000800")

    async def test_the_monthly_table_is_split_by_kind_too(self, auth_client, three_kinds):
        body = (await auth_client.get("/api/costs/summary")).json()
        rows = body["by_month"]
        assert len(rows) == 3
        assert {row["kind"] for row in rows} == {"receipt", "price_label", "product_photo"}
        assert all(row["calls"] == 1 for row in rows)
        # One month observed, so the projection is that month's bill twelve times over.
        assert Decimal(body["projected_yearly_usd"]) == cost("0.0096").quantize(cost("0.01"))

    async def test_tokens_are_reported_per_kind(self, auth_client, three_kinds):
        """A receipt is a long read; a product photograph is a short one. Worth seeing."""
        body = (await auth_client.get("/api/costs/summary")).json()
        by_kind = {row["kind"]: row for row in body["by_kind"]}
        assert by_kind["receipt"]["avg_input_tokens"] == 3000
        assert by_kind["product_photo"]["avg_input_tokens"] == 900

    async def test_failures_are_counted_against_the_kind_that_failed(self, auth_client, session):
        photo = await a_label_photo(session)
        await record_attempt(
            session, extractor="stub", error="no",
            kind=AttemptKind.PRICE_LABEL.value, price_label_photo_id=photo.id,
        )
        await session.commit()

        body = (await auth_client.get("/api/costs/summary")).json()
        # A kind that only ever failed still has to appear - it is the one you want to see.
        assert [row["kind"] for row in body["by_kind"]] == ["price_label"]
        assert body["by_kind"][0]["failures"] == 1
        assert body["by_kind"][0]["calls"] == 0
        assert body["failures"] == 1

    async def test_no_calls_at_all_is_an_empty_split_not_an_error(self, auth_client):
        body = (await auth_client.get("/api/costs/summary")).json()
        assert body["calls"] == 0
        assert body["by_kind"] == []
