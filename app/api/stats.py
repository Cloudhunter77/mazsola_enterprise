"""Read-only statistics endpoints."""

from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, HTTPException, Query

from app.api.deps import AuthDep, SessionDep
from app.schemas.api import (
    BasketComparison,
    CategoryLine,
    CategorySpend,
    InflationPoint,
    MerchantReceipt,
    MerchantSpend,
    MonthlySpend,
    ProductPriceHistory,
    SpendSummary,
)
from app.services import stats

router = APIRouter(prefix="/api/stats", tags=["stats"])


@router.get("/summary", response_model=SpendSummary)
async def spend_summary(
    _: AuthDep, session: SessionDep, start: date | None = None, end: date | None = None
) -> SpendSummary:
    return await stats.summary(session, start, end)


@router.get("/monthly", response_model=list[MonthlySpend])
async def monthly_spend(
    _: AuthDep, session: SessionDep, months: int = Query(24, le=120)
) -> list[MonthlySpend]:
    return await stats.monthly(session, months)


@router.get("/by-category", response_model=list[CategorySpend])
async def category_spend(
    _: AuthDep, session: SessionDep, start: date | None = None, end: date | None = None
) -> list[CategorySpend]:
    return await stats.by_category(session, start, end)


@router.get("/category-lines", response_model=list[CategoryLine])
async def category_lines(
    _: AuthDep,
    session: SessionDep,
    category_id: str = Query(..., description='A category id, or "none" for Besorolatlan.'),
    start: date | None = None,
    end: date | None = None,
    limit: int = Query(100, ge=1, le=500),
) -> list[CategoryLine]:
    """Where one bar of the category chart came from: its lines, largest first."""
    return await stats.category_lines(session, _uuid_or_none(category_id), start, end, limit)


@router.get("/merchant-receipts", response_model=list[MerchantReceipt])
async def merchant_receipts(
    _: AuthDep,
    session: SessionDep,
    merchant_id: str = Query(..., description='A shop id, or "none" for Ismeretlen.'),
    start: date | None = None,
    end: date | None = None,
    limit: int = Query(100, ge=1, le=500),
) -> list[MerchantReceipt]:
    """Where one bar of the shop chart came from: its receipts, largest first."""
    return await stats.merchant_receipts(session, _uuid_or_none(merchant_id), start, end, limit)


def _uuid_or_none(value: str) -> uuid.UUID | None:
    if value == "none":
        return None
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Érvénytelen azonosító.") from exc


@router.get("/by-merchant", response_model=list[MerchantSpend])
async def merchant_spend(
    _: AuthDep, session: SessionDep, start: date | None = None, end: date | None = None
) -> list[MerchantSpend]:
    return await stats.by_merchant(session, start, end)


@router.get("/price-history/{product_id}", response_model=ProductPriceHistory)
async def price_history(
    _: AuthDep, session: SessionDep, product_id: uuid.UUID
) -> ProductPriceHistory:
    history = await stats.price_history(session, product_id)
    if history is None:
        raise HTTPException(status_code=404, detail="No such product.")
    return history


@router.get("/basket-comparison", response_model=BasketComparison)
async def basket_comparison(
    _: AuthDep,
    session: SessionDep,
    min_receipts: int = Query(3, ge=1, le=50),
    window_days: int = Query(90, ge=7, le=730, description="Ignore prices older than this."),
) -> BasketComparison:
    """Which shop your usual basket is cheapest at, compared on shared products only."""
    return await stats.basket_comparison(session, min_receipts, window_days)


@router.get("/inflation", response_model=list[InflationPoint])
async def inflation(_: AuthDep, session: SessionDep) -> list[InflationPoint]:
    return await stats.inflation(session)
