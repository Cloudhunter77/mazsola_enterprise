"""What extraction has actually cost.

The point of this endpoint is to make the model choice an empirical one: run Opus for a
month, look at the real per-receipt figure and the review rate, and decide whether a cheaper
model is worth it - rather than guessing from list prices.
"""

from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter
from sqlalchemy import func, select

from app.api.deps import AuthDep, SessionDep
from app.models import ExtractionAttempt
from app.schemas.api import CostByMonth, CostSummary
from app.services.stats import local_month

router = APIRouter(prefix="/api/costs", tags=["costs"])

ZERO = Decimal("0.00")


@router.get("/summary", response_model=CostSummary)
async def cost_summary(_: AuthDep, session: SessionDep) -> CostSummary:
    month_col = local_month(ExtractionAttempt.created_at).label("month")
    rows = (
        await session.execute(
            select(
                month_col,
                ExtractionAttempt.model,
                func.count(ExtractionAttempt.id),
                func.coalesce(func.sum(ExtractionAttempt.cost_usd), 0),
                func.avg(ExtractionAttempt.input_tokens),
                func.avg(ExtractionAttempt.output_tokens),
            )
            .where(ExtractionAttempt.succeeded.is_(True))
            .group_by(month_col, ExtractionAttempt.model)
            .order_by(month_col.desc())
        )
    ).all()

    by_month = [
        CostByMonth(
            month=month.date(),
            model=model,
            receipts=count,
            total_usd=Decimal(total).quantize(Decimal("0.000001")),
            avg_usd=(Decimal(total) / count).quantize(Decimal("0.000001")) if count else ZERO,
            # avg() is NULL when an engine reported no token counts at all, which is a
            # legitimate state - not every provider returns them.
            avg_input_tokens=round(avg_in) if avg_in is not None else None,
            avg_output_tokens=round(avg_out) if avg_out is not None else None,
        )
        for month, model, count, total, avg_in, avg_out in rows
    ]

    total_usd = sum((row.total_usd for row in by_month), Decimal("0"))
    receipts = sum(row.receipts for row in by_month)
    average = (total_usd / receipts) if receipts else Decimal("0")

    failures = await session.scalar(
        select(func.count(ExtractionAttempt.id)).where(ExtractionAttempt.succeeded.is_(False))
    ) or 0

    # Project from the observed rate over the months actually covered, not from list prices.
    distinct_months = len({row.month for row in by_month}) or 1
    projected = (total_usd / distinct_months) * 12

    return CostSummary(
        total_usd=total_usd.quantize(Decimal("0.000001")),
        receipts_extracted=receipts,
        average_usd=average.quantize(Decimal("0.000001")),
        projected_yearly_usd=projected.quantize(Decimal("0.01")),
        by_month=by_month,
        failures=failures,
    )
