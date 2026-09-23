"""What extraction has actually cost, split by what was being read.

The point of this endpoint is to make the model choice an empirical one: run a model for a
month, look at the real per-call figure and the review rate, and decide whether a cheaper
one is worth it - rather than guessing from list prices.

Split by kind because three different documents now go to the model and they do not cost
alike. A receipt is a long read with a long answer; a shelf strip is a short read with
several answers at once; a product photograph is short both ways. A single total tells you
what the app costs. Only the split tells you which *habit* costs - and that is the question
you need answered before changing anything, because photographing forty shelf labels on a
Saturday and scanning forty receipts are not the same decision.
"""

from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthDep, SessionDep
from app.models import ExtractionAttempt
from app.schemas.api import CostByKind, CostByMonth, CostSummary
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
                ExtractionAttempt.kind,
                ExtractionAttempt.model,
                func.count(ExtractionAttempt.id),
                func.coalesce(func.sum(ExtractionAttempt.cost_usd), 0),
                func.avg(ExtractionAttempt.input_tokens),
                func.avg(ExtractionAttempt.output_tokens),
            )
            .where(ExtractionAttempt.succeeded.is_(True))
            .group_by(month_col, ExtractionAttempt.kind, ExtractionAttempt.model)
            .order_by(month_col.desc())
        )
    ).all()

    by_month = [
        CostByMonth(
            month=month.date(),
            kind=kind,
            model=model,
            calls=count,
            total_usd=Decimal(total).quantize(Decimal("0.000001")),
            avg_usd=(Decimal(total) / count).quantize(Decimal("0.000001")) if count else ZERO,
            # avg() is NULL when an engine reported no token counts at all, which is a
            # legitimate state - not every provider returns them.
            avg_input_tokens=round(avg_in) if avg_in is not None else None,
            avg_output_tokens=round(avg_out) if avg_out is not None else None,
        )
        for month, kind, model, count, total, avg_in, avg_out in rows
    ]

    by_kind = await _by_kind(session)

    total_usd = sum((row.total_usd for row in by_month), Decimal("0"))
    calls = sum(row.calls for row in by_month)
    average = (total_usd / calls) if calls else Decimal("0")

    failures = await session.scalar(
        select(func.count(ExtractionAttempt.id)).where(ExtractionAttempt.succeeded.is_(False))
    ) or 0

    # Project from the observed rate over the months actually covered, not from list prices.
    distinct_months = len({row.month for row in by_month}) or 1
    projected = (total_usd / distinct_months) * 12

    return CostSummary(
        total_usd=total_usd.quantize(Decimal("0.000001")),
        calls=calls,
        average_usd=average.quantize(Decimal("0.000001")),
        projected_yearly_usd=projected.quantize(Decimal("0.01")),
        by_kind=by_kind,
        by_month=by_month,
        failures=failures,
    )


async def _by_kind(session: AsyncSession) -> list[CostByKind]:
    """Each document type's whole bill, dearest first.

    Failures are counted alongside, because a kind that fails often is costing you twice:
    once for the call that did not work, and again for whatever you do about it.
    """
    rows = (
        await session.execute(
            select(
                ExtractionAttempt.kind,
                func.count(ExtractionAttempt.id),
                func.coalesce(func.sum(ExtractionAttempt.cost_usd), 0),
                func.avg(ExtractionAttempt.input_tokens),
                func.avg(ExtractionAttempt.output_tokens),
            )
            .where(ExtractionAttempt.succeeded.is_(True))
            .group_by(ExtractionAttempt.kind)
        )
    ).all()

    failures = dict(
        (
            await session.execute(
                select(ExtractionAttempt.kind, func.count(ExtractionAttempt.id))
                .where(ExtractionAttempt.succeeded.is_(False))
                .group_by(ExtractionAttempt.kind)
            )
        ).all()
    )

    summaries = [
        CostByKind(
            kind=kind,
            calls=count,
            total_usd=Decimal(total).quantize(Decimal("0.000001")),
            avg_usd=(Decimal(total) / count).quantize(Decimal("0.000001")) if count else ZERO,
            avg_input_tokens=round(avg_in) if avg_in is not None else None,
            avg_output_tokens=round(avg_out) if avg_out is not None else None,
            failures=failures.get(kind, 0),
        )
        for kind, count, total, avg_in, avg_out in rows
    ]

    # A kind that only ever failed has no successful row above, and is exactly the kind you
    # want to see on this page.
    for kind, count in failures.items():
        if not any(summary.kind == kind for summary in summaries):
            summaries.append(
                CostByKind(kind=kind, calls=0, total_usd=ZERO, avg_usd=ZERO, failures=count)
            )

    summaries.sort(key=lambda summary: summary.total_usd, reverse=True)
    return summaries
