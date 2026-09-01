"""Statistics queries behind the dashboard.

Data volumes here are small - a household produces a few thousand line items a year - so
these deliberately favour a simple query plus clear Python over heroic SQL. Correctness and
being able to read the logic later matter more than milliseconds.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Category, LineKind, Merchant, Product, Receipt, ReceiptItem, ReceiptStatus
from app.schemas.api import (
    BasketComparison,
    CategorySpend,
    InflationPoint,
    MerchantBasketPrice,
    MerchantSpend,
    MonthlySpend,
    PricePoint,
    ProductPriceHistory,
    SpendSummary,
)

ZERO = Decimal("0.00")

# Receipts that count towards spending. `needs_review` is included on purpose: excluding it
# would make the dashboard quietly understate your spending whenever the review queue grows.
# The summary reports how many are unreviewed so the number can be read with that in mind.
COUNTED_STATUSES = (
    ReceiptStatus.PARSED.value,
    ReceiptStatus.NEEDS_REVIEW.value,
    ReceiptStatus.CONFIRMED.value,
)

UNCATEGORISED = "Besorolatlan"


def _in_range(stmt: Select, start: date | None, end: date | None) -> Select:
    stmt = stmt.where(Receipt.status.in_(COUNTED_STATUSES))
    if start:
        stmt = stmt.where(Receipt.purchased_at >= datetime(start.year, start.month, start.day,
                                                           tzinfo=UTC))
    if end:
        stmt = stmt.where(Receipt.purchased_at < datetime(end.year, end.month, end.day,
                                                          tzinfo=UTC))
    return stmt


def _q(value: Decimal | int | float | None) -> Decimal:
    return (Decimal(value) if value is not None else ZERO).quantize(Decimal("0.01"))


async def summary(
    session: AsyncSession, start: date | None = None, end: date | None = None
) -> SpendSummary:
    stmt = _in_range(
        select(
            func.coalesce(func.sum(Receipt.total_gross), 0),
            func.count(Receipt.id),
            func.min(Receipt.purchased_at),
            func.max(Receipt.purchased_at),
        ),
        start,
        end,
    )
    total, count, first, last = (await session.execute(stmt)).one()

    item_stmt = _in_range(
        select(func.count(ReceiptItem.id)).join(Receipt, ReceiptItem.receipt_id == Receipt.id),
        start,
        end,
    ).where(ReceiptItem.kind == LineKind.ITEM.value)
    item_count = await session.scalar(item_stmt) or 0

    pending = await session.scalar(
        select(func.count(Receipt.id)).where(Receipt.status == ReceiptStatus.NEEDS_REVIEW.value)
    ) or 0

    return SpendSummary(
        total=_q(total),
        receipt_count=count or 0,
        item_count=item_count,
        average_basket=_q(Decimal(total) / count) if count else ZERO,
        first_purchase=first,
        last_purchase=last,
        pending_review=pending,
    )


async def monthly(session: AsyncSession, months: int = 24) -> list[MonthlySpend]:
    month_col = func.date_trunc("month", Receipt.purchased_at).label("month")
    stmt = (
        _in_range(
            select(month_col, func.sum(Receipt.total_gross), func.count(Receipt.id)), None, None
        )
        .where(Receipt.purchased_at.is_not(None))
        .group_by(month_col)
        .order_by(month_col.desc())
        .limit(months)
    )
    rows = (await session.execute(stmt)).all()
    return [
        MonthlySpend(month=m.date(), total=_q(total), receipt_count=count)
        for m, total, count in reversed(rows)
    ]


async def by_category(
    session: AsyncSession, start: date | None = None, end: date | None = None
) -> list[CategorySpend]:
    stmt = (
        _in_range(
            select(
                ReceiptItem.category_id,
                func.coalesce(Category.name, UNCATEGORISED),
                func.sum(ReceiptItem.gross_amount),
                func.count(ReceiptItem.id),
            )
            .join(Receipt, ReceiptItem.receipt_id == Receipt.id)
            .outerjoin(Category, ReceiptItem.category_id == Category.id),
            start,
            end,
        )
        .where(ReceiptItem.kind == LineKind.ITEM.value)
        .group_by(ReceiptItem.category_id, Category.name)
    )
    rows = (await session.execute(stmt)).all()
    grand_total = sum((Decimal(r[2] or 0) for r in rows), ZERO)

    result = [
        CategorySpend(
            category_id=cat_id,
            category_name=name,
            total=_q(total),
            share=float(Decimal(total or 0) / grand_total) if grand_total else 0.0,
            item_count=count,
        )
        for cat_id, name, total, count in rows
    ]
    return sorted(result, key=lambda c: c.total, reverse=True)


async def by_merchant(
    session: AsyncSession, start: date | None = None, end: date | None = None, limit: int = 15
) -> list[MerchantSpend]:
    stmt = (
        _in_range(
            select(
                Receipt.merchant_id,
                func.coalesce(Merchant.name, "Ismeretlen"),
                func.sum(Receipt.total_gross),
                func.count(Receipt.id),
            ).outerjoin(Merchant, Receipt.merchant_id == Merchant.id),
            start,
            end,
        )
        .group_by(Receipt.merchant_id, Merchant.name)
        .order_by(func.sum(Receipt.total_gross).desc())
        .limit(limit)
    )
    rows = (await session.execute(stmt)).all()
    return [
        MerchantSpend(
            merchant_id=mid,
            merchant_name=name,
            total=_q(total),
            receipt_count=count,
            average_basket=_q(Decimal(total or 0) / count) if count else ZERO,
        )
        for mid, name, total, count in rows
    ]


def _effective_unit_price(item_price, gross, quantity) -> Decimal | None:
    """Unit price as printed, falling back to line total / quantity."""
    if item_price:
        return Decimal(item_price)
    if gross and quantity and Decimal(quantity) != 0:
        return (Decimal(gross) / Decimal(quantity)).quantize(Decimal("0.01"))
    return None


async def price_history(
    session: AsyncSession, product_id: uuid.UUID
) -> ProductPriceHistory | None:
    """Every recorded purchase of one product, so you can see what it now costs where."""
    product = await session.get(Product, product_id)
    if product is None:
        return None

    stmt = (
        _in_range(
            select(
                Receipt.purchased_at,
                Receipt.merchant_id,
                func.coalesce(Merchant.name, "Ismeretlen"),
                ReceiptItem.unit_price,
                ReceiptItem.gross_amount,
                ReceiptItem.quantity,
                ReceiptItem.unit,
                Receipt.id,
            )
            .join(Receipt, ReceiptItem.receipt_id == Receipt.id)
            .outerjoin(Merchant, Receipt.merchant_id == Merchant.id),
            None,
            None,
        )
        .where(ReceiptItem.product_id == product_id)
        .where(Receipt.purchased_at.is_not(None))
        .order_by(Receipt.purchased_at)
    )
    rows = (await session.execute(stmt)).all()

    points: list[PricePoint] = []
    for purchased_at, merchant_id, merchant_name, unit_price, gross, qty, unit, receipt_id in rows:
        price = _effective_unit_price(unit_price, gross, qty)
        if price is None or price <= 0:
            continue
        points.append(
            PricePoint(
                purchased_at=purchased_at,
                merchant_id=merchant_id,
                merchant_name=merchant_name,
                unit_price=price,
                quantity=Decimal(qty) if qty is not None else None,
                unit=unit,
                receipt_id=receipt_id,
            )
        )

    cheapest = min(points, key=lambda p: p.unit_price).merchant_name if points else None
    change_pct = None
    if len(points) >= 2 and points[0].unit_price > 0:
        change_pct = float(
            (points[-1].unit_price - points[0].unit_price) / points[0].unit_price * 100
        )

    return ProductPriceHistory(
        product_id=product.id,
        product_name=product.canonical_name,
        points=points,
        cheapest_merchant=cheapest,
        latest_price=points[-1].unit_price if points else None,
        change_pct=change_pct,
    )


async def basket_comparison(session: AsyncSession, min_receipts: int = 3) -> BasketComparison:
    """What your regular basket would cost at each shop.

    Only compares on products that *every* considered shop has sold you - otherwise a shop
    that happens to stock fewer of your regulars would look cheap purely by absence.
    """
    stmt = (
        _in_range(
            select(
                ReceiptItem.product_id,
                Receipt.merchant_id,
                func.coalesce(Merchant.name, "Ismeretlen"),
                Receipt.purchased_at,
                ReceiptItem.unit_price,
                ReceiptItem.gross_amount,
                ReceiptItem.quantity,
            )
            .join(Receipt, ReceiptItem.receipt_id == Receipt.id)
            .outerjoin(Merchant, Receipt.merchant_id == Merchant.id),
            None,
            None,
        )
        .where(ReceiptItem.product_id.is_not(None))
        .where(Receipt.merchant_id.is_not(None))
        .where(ReceiptItem.kind == LineKind.ITEM.value)
        .order_by(Receipt.purchased_at)
    )
    rows = (await session.execute(stmt)).all()

    # Latest price per (merchant, product); rows arrive oldest-first so later rows win.
    latest: dict[tuple[uuid.UUID, uuid.UUID], Decimal] = {}
    merchant_names: dict[uuid.UUID, str] = {}
    receipts_per_merchant: dict[uuid.UUID, set] = defaultdict(set)

    for product_id, merchant_id, merchant_name, purchased_at, unit_price, gross, qty in rows:
        price = _effective_unit_price(unit_price, gross, qty)
        if price is None or price <= 0:
            continue
        latest[(merchant_id, product_id)] = price
        merchant_names[merchant_id] = merchant_name
        receipts_per_merchant[merchant_id].add(purchased_at)

    # Shops you actually use, not the one-off petrol station.
    merchants = [m for m in merchant_names if len(receipts_per_merchant[m]) >= min_receipts]
    if len(merchants) < 2:
        return BasketComparison(product_count=0, merchants=[], potential_saving=ZERO)

    products_per_merchant = [
        {product_id for (mid, product_id) in latest if mid == merchant} for merchant in merchants
    ]
    shared = set.intersection(*products_per_merchant)
    if not shared:
        return BasketComparison(product_count=0, merchants=[], potential_saving=ZERO)

    totals = [
        MerchantBasketPrice(
            merchant_id=merchant,
            merchant_name=merchant_names[merchant],
            covered_products=len(shared),
            basket_total=_q(sum((latest[(merchant, p)] for p in shared), ZERO)),
        )
        for merchant in merchants
    ]
    totals.sort(key=lambda m: m.basket_total)
    saving = totals[-1].basket_total - totals[0].basket_total

    return BasketComparison(
        product_count=len(shared), merchants=totals, potential_saving=_q(saving)
    )


async def inflation(session: AsyncSession) -> list[InflationPoint]:
    """A personal price index: what your own regular products cost relative to their first price.

    Each product contributes the ratio of its price that month to its first recorded price;
    the index is the mean of those ratios, so it tracks *your* basket rather than the CPI.
    """
    stmt = (
        _in_range(
            select(
                ReceiptItem.product_id,
                Receipt.purchased_at,
                ReceiptItem.unit_price,
                ReceiptItem.gross_amount,
                ReceiptItem.quantity,
            ).join(Receipt, ReceiptItem.receipt_id == Receipt.id),
            None,
            None,
        )
        .where(ReceiptItem.product_id.is_not(None))
        .where(Receipt.purchased_at.is_not(None))
        .where(ReceiptItem.kind == LineKind.ITEM.value)
        .order_by(Receipt.purchased_at)
    )
    rows = (await session.execute(stmt)).all()

    baseline: dict[uuid.UUID, Decimal] = {}
    monthly_prices: dict[date, dict[uuid.UUID, list[Decimal]]] = defaultdict(
        lambda: defaultdict(list)
    )

    for product_id, purchased_at, unit_price, gross, qty in rows:
        price = _effective_unit_price(unit_price, gross, qty)
        if price is None or price <= 0:
            continue
        baseline.setdefault(product_id, price)
        month = date(purchased_at.year, purchased_at.month, 1)
        monthly_prices[month][product_id].append(price)

    points: list[InflationPoint] = []
    for month in sorted(monthly_prices):
        ratios = [
            float(sum(prices, ZERO) / len(prices) / baseline[product_id])
            for product_id, prices in monthly_prices[month].items()
            if baseline.get(product_id)
        ]
        if ratios:
            points.append(
                InflationPoint(
                    month=month,
                    index=round(sum(ratios) / len(ratios) * 100, 2),
                    product_count=len(ratios),
                )
            )
    return points
