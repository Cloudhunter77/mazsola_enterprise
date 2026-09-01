"""Statistics maths.

These are the numbers you would act on, so the arithmetic gets checked directly rather
than inferred from the endpoints returning 200.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from app.models import LineKind, Product, Receipt, ReceiptItem, ReceiptStatus
from app.services import stats
from app.services.catalog import resolve_merchant
from tests.conftest import requires_db

pytestmark = requires_db

BUDAPEST = ZoneInfo("Europe/Budapest")


async def add_receipt(session, *, merchant, when, lines, status=ReceiptStatus.CONFIRMED.value):
    """`lines` is a list of (product, unit_price, quantity)."""
    total = sum(Decimal(str(price)) * Decimal(str(qty)) for _, price, qty in lines)
    receipt = Receipt(
        id=uuid.uuid4(),
        image_path="(test)",
        image_sha256=uuid.uuid4().hex,
        merchant_id=merchant.id if merchant else None,
        purchased_at=when,
        total_gross=total,
        status=status,
    )
    session.add(receipt)
    await session.flush()

    for index, (product, price, qty) in enumerate(lines, start=1):
        session.add(
            ReceiptItem(
                receipt_id=receipt.id,
                line_no=index,
                raw_name=product.canonical_name if product else "EGYÉB",
                product_id=product.id if product else None,
                quantity=Decimal(str(qty)),
                unit="db",
                unit_price=Decimal(str(price)),
                gross_amount=Decimal(str(price)) * Decimal(str(qty)),
                kind=LineKind.ITEM.value,
            )
        )
    await session.commit()
    return receipt


@pytest.fixture
async def products(session) -> dict[str, Product]:
    made = {}
    for name in ("Tej", "Kenyér", "Kávé"):
        product = Product(canonical_name=name)
        session.add(product)
        made[name] = product
    await session.flush()
    return made


class TestMonthBucketing:
    """Timestamps are stored in UTC but months must be counted in local time."""

    async def test_a_purchase_just_after_midnight_counts_in_the_new_month(
        self, session, products
    ):
        # 00:30 on 1 September in Budapest is 22:30 on 31 August UTC.
        await add_receipt(
            session, merchant=None,
            when=datetime(2026, 9, 1, 0, 30, tzinfo=BUDAPEST),
            lines=[(products["Tej"], 400, 1)],
        )
        months = await stats.monthly(session)
        assert [row.month.month for row in months] == [9], "bucketed into the previous month"

    async def test_a_late_evening_purchase_stays_in_its_own_month(self, session, products):
        await add_receipt(
            session, merchant=None,
            when=datetime(2026, 8, 31, 23, 45, tzinfo=BUDAPEST),
            lines=[(products["Tej"], 400, 1)],
        )
        months = await stats.monthly(session)
        assert [row.month.month for row in months] == [8]

    async def test_both_land_in_the_right_months(self, session, products):
        for when in (
            datetime(2026, 8, 31, 23, 45, tzinfo=BUDAPEST),
            datetime(2026, 9, 1, 0, 30, tzinfo=BUDAPEST),
        ):
            await add_receipt(session, merchant=None, when=when,
                              lines=[(products["Tej"], 400, 1)])

        months = await stats.monthly(session)
        assert [(row.month.month, row.receipt_count) for row in months] == [(8, 1), (9, 1)]


class TestSummaryAndBreakdowns:
    async def test_totals_and_average_basket(self, session, products):
        now = datetime.now(UTC)
        await add_receipt(session, merchant=None, when=now,
                          lines=[(products["Tej"], 400, 2)])            # 800
        await add_receipt(session, merchant=None, when=now,
                          lines=[(products["Kenyér"], 600, 1)])         # 600

        summary = await stats.summary(session)
        assert summary.total == Decimal("1400.00")
        assert summary.receipt_count == 2
        assert summary.average_basket == Decimal("700.00")

    async def test_only_counted_statuses_contribute(self, session, products):
        now = datetime.now(UTC)
        await add_receipt(session, merchant=None, when=now,
                          lines=[(products["Tej"], 400, 1)],
                          status=ReceiptStatus.PENDING.value)
        assert (await stats.summary(session)).total == Decimal("0.00")

    async def test_needs_review_is_counted_but_reported(self, session, products):
        # Excluding it would understate spending whenever the review queue grows.
        await add_receipt(session, merchant=None, when=datetime.now(UTC),
                          lines=[(products["Tej"], 400, 1)],
                          status=ReceiptStatus.NEEDS_REVIEW.value)
        summary = await stats.summary(session)
        assert summary.total == Decimal("400.00")
        assert summary.pending_review == 1

    async def test_merchant_breakdown(self, session, products):
        tesco = await resolve_merchant(session, "TESCO-GLOBAL ZRT.")
        lidl = await resolve_merchant(session, "LIDL MAGYARORSZÁG BT.")
        await session.flush()
        now = datetime.now(UTC)

        await add_receipt(session, merchant=tesco, when=now, lines=[(products["Tej"], 400, 3)])
        await add_receipt(session, merchant=lidl, when=now, lines=[(products["Tej"], 350, 1)])

        by_merchant = await stats.by_merchant(session)
        assert [(m.merchant_name, m.total) for m in by_merchant] == [
            ("Tesco", Decimal("1200.00")),
            ("Lidl", Decimal("350.00")),
        ]

    async def test_category_shares_sum_to_one(self, session, products):
        now = datetime.now(UTC)
        await add_receipt(session, merchant=None, when=now,
                          lines=[(products["Tej"], 400, 1), (products["Kávé"], 1600, 1)])
        categories = await stats.by_category(session)
        assert abs(sum(c.share for c in categories) - 1.0) < 1e-9


class TestPriceHistory:
    async def test_prices_are_returned_in_order_with_the_change(self, session, products):
        tesco = await resolve_merchant(session, "TESCO-GLOBAL ZRT.")
        await session.flush()
        base = datetime.now(UTC) - timedelta(days=60)

        for offset, price in ((0, 400), (30, 440), (55, 480)):
            await add_receipt(session, merchant=tesco, when=base + timedelta(days=offset),
                              lines=[(products["Tej"], price, 1)])

        history = await stats.price_history(session, products["Tej"].id)
        assert [p.unit_price for p in history.points] == [
            Decimal("400.00"), Decimal("440.00"), Decimal("480.00")
        ]
        assert history.latest_price == Decimal("480.00")
        assert history.change_pct == pytest.approx(20.0)
        assert history.cheapest_merchant == "Tesco"

    async def test_unit_price_falls_back_to_line_total_over_quantity(self, session, products):
        receipt = await add_receipt(session, merchant=None, when=datetime.now(UTC),
                                    lines=[(products["Tej"], 400, 3)])
        item = (await session.scalars(
            __import__("sqlalchemy").select(ReceiptItem).where(
                ReceiptItem.receipt_id == receipt.id)
        )).one()
        item.unit_price = None          # some receipts only print the line total
        await session.commit()

        history = await stats.price_history(session, products["Tej"].id)
        assert history.points[0].unit_price == Decimal("400.00")


class TestBasketComparison:
    async def test_the_cheaper_shop_wins_on_shared_products(self, session, products):
        tesco = await resolve_merchant(session, "TESCO-GLOBAL ZRT.")
        lidl = await resolve_merchant(session, "LIDL MAGYARORSZÁG BT.")
        await session.flush()
        now = datetime.now(UTC)

        for days in range(3):
            when = now - timedelta(days=days)
            await add_receipt(session, merchant=tesco, when=when,
                              lines=[(products["Tej"], 400, 1), (products["Kenyér"], 600, 1)])
            await add_receipt(session, merchant=lidl, when=when,
                              lines=[(products["Tej"], 350, 1), (products["Kenyér"], 550, 1)])

        comparison = await stats.basket_comparison(session)
        assert comparison.product_count == 2
        assert comparison.merchants[0].merchant_name == "Lidl"
        assert comparison.merchants[0].basket_total == Decimal("900.00")
        assert comparison.potential_saving == Decimal("100.00")

    async def test_stale_prices_are_excluded(self, session, products):
        """A shop you stopped visiting must not win on year-old prices."""
        tesco = await resolve_merchant(session, "TESCO-GLOBAL ZRT.")
        lidl = await resolve_merchant(session, "LIDL MAGYARORSZÁG BT.")
        await session.flush()
        now = datetime.now(UTC)

        for days in range(3):
            # Lidl was very cheap - a year ago.
            await add_receipt(session, merchant=lidl, when=now - timedelta(days=400 + days),
                              lines=[(products["Tej"], 200, 1)])
            await add_receipt(session, merchant=tesco, when=now - timedelta(days=days),
                              lines=[(products["Tej"], 400, 1)])

        comparison = await stats.basket_comparison(session, window_days=90)
        assert comparison.window_days == 90
        names = [m.merchant_name for m in comparison.merchants]
        assert "Lidl" not in names, "prices from over a year ago should not be compared"

    async def test_a_single_shop_cannot_be_compared(self, session, products):
        tesco = await resolve_merchant(session, "TESCO-GLOBAL ZRT.")
        await session.flush()
        for days in range(3):
            await add_receipt(session, merchant=tesco,
                              when=datetime.now(UTC) - timedelta(days=days),
                              lines=[(products["Tej"], 400, 1)])

        assert (await stats.basket_comparison(session)).product_count == 0


class TestInflationIndex:
    async def test_a_steady_rise_is_reported(self, session, products):
        base = datetime.now(UTC) - timedelta(days=120)
        for month, price in enumerate((400, 420, 440, 460)):
            await add_receipt(session, merchant=None, when=base + timedelta(days=31 * month),
                              lines=[(products["Tej"], price, 1),
                                     (products["Kenyér"], price + 200, 1),
                                     (products["Kávé"], price * 3, 1)])

        points = await stats.inflation(session)
        assert len(points) == 4
        assert points[0].index == 100.0, "the first month is the base"
        assert points[-1].index > points[0].index
        assert all(
            later.index >= earlier.index
            for earlier, later in zip(points, points[1:], strict=False)
        )

    async def test_a_product_not_bought_this_month_holds_its_price(self, session, products):
        """Without carrying prices forward the basket changes every month and the line
        jumps for reasons that have nothing to do with prices."""
        base = datetime.now(UTC) - timedelta(days=90)

        # Month 1: both products. Month 2: only one of them. Month 3: both again.
        await add_receipt(session, merchant=None, when=base,
                          lines=[(products["Tej"], 400, 1), (products["Kenyér"], 600, 1),
                                 (products["Kávé"], 1500, 1)])
        await add_receipt(session, merchant=None, when=base + timedelta(days=31),
                          lines=[(products["Tej"], 400, 1)])
        await add_receipt(session, merchant=None, when=base + timedelta(days=62),
                          lines=[(products["Tej"], 400, 1), (products["Kenyér"], 600, 1),
                                 (products["Kávé"], 1500, 1)])

        points = await stats.inflation(session)
        # Nothing changed price, so the index must stay flat rather than wobble.
        assert [p.index for p in points] == [100.0, 100.0, 100.0]
        assert [p.product_count for p in points] == [3, 3, 3]

    async def test_opposite_moves_cancel_out(self, session, products):
        """A geometric mean is the right average for price relatives: a doubling and a
        halving cancel, where an arithmetic mean would report a 25% rise."""
        base = datetime.now(UTC) - timedelta(days=60)
        await add_receipt(session, merchant=None, when=base,
                          lines=[(products["Tej"], 400, 1), (products["Kenyér"], 400, 1),
                                 (products["Kávé"], 400, 1)])
        await add_receipt(session, merchant=None, when=base + timedelta(days=31),
                          lines=[(products["Tej"], 800, 1), (products["Kenyér"], 200, 1),
                                 (products["Kávé"], 400, 1)])

        points = await stats.inflation(session)
        assert points[-1].index == pytest.approx(100.0, abs=0.01)

    async def test_newly_mapped_products_do_not_reset_the_index(self, session, products):
        """Mapping a batch of new products in one month must not drag the index back to
        100 and report a fall that never happened."""
        base = datetime.now(UTC) - timedelta(days=120)

        # Three months of a genuine, steady rise across the original basket.
        for month, price in enumerate((400, 500, 600)):
            await add_receipt(session, merchant=None, when=base + timedelta(days=31 * month),
                              lines=[(products["Tej"], price, 1),
                                     (products["Kenyér"], price, 1),
                                     (products["Kávé"], price, 1)])

        risen = (await stats.inflation(session))[-1].index
        assert risen > 140, "the setup should show a clear rise"

        # Now a pile of newly mapped products appears, at whatever they happen to cost.
        newcomers = []
        for index in range(20):
            product = Product(canonical_name=f"Új termék {index}")
            session.add(product)
            newcomers.append(product)
        await session.flush()

        await add_receipt(
            session, merchant=None, when=base + timedelta(days=31 * 3),
            lines=[(products["Tej"], 600, 1), (products["Kenyér"], 600, 1),
                   (products["Kávé"], 600, 1)] + [(p, 1000, 1) for p in newcomers],
        )

        after = (await stats.inflation(session))[-1].index
        assert after == pytest.approx(risen, abs=0.5), (
            f"the index fell from {risen} to {after} purely because new products appeared"
        )

    async def test_too_few_products_is_not_reported(self, session, products):
        await add_receipt(session, merchant=None, when=datetime.now(UTC),
                          lines=[(products["Tej"], 400, 1)])
        assert await stats.inflation(session) == []
