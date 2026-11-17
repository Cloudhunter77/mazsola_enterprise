"""Pénz: periods and the monthly meeting, the plan, budget lines, and Hónap."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import func, select

from app.api.deps import AuthDep, SessionDep
from app.models import BudgetLine, BudgetLineKind, Direction
from app.models.budget import SPENDING_KINDS
from app.schemas.budget import (
    BudgetStatus,
    IncomeOut,
    LateReceipt,
    LineCreate,
    LineIn,
    LineOut,
    LineRemoved,
    MonthIssues,
    MonthOut,
    MonthRowOut,
    MonthTotals,
    OccurrenceOut,
    OwnerIncome,
    PeriodOpenIn,
    PeriodOut,
    PersonOut,
    PersonTotals,
    PieceOut,
    PlanAmountIn,
    PlanCell,
    PlanMonthOut,
    PlanOut,
    PlanRowOut,
    PlanTotalsOut,
)
from app.services import budget
from app.services.recurring import Occurrence

router = APIRouter(prefix="/api/budget", tags=["budget"])

ZERO = Decimal("0.00")


def _bad(error: Exception) -> HTTPException:
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error))


def period_out(span: budget.PeriodSpan) -> PeriodOut:
    return PeriodOut(
        id=span.period.id,
        month=span.period.month,
        starts_on=span.start,
        ends_on=span.end,
        closed_at=span.period.closed_at,
        is_current=span.is_current,
    )


def occurrence_out(occurrence: Occurrence) -> OccurrenceOut:
    payment = occurrence.payment
    return OccurrenceOut(
        recurring_id=payment.id,
        name=payment.name,
        direction=payment.direction,
        amount_mode=payment.amount_mode,
        owner_id=payment.owner_id,
        month=occurrence.month,
        due=occurrence.due,
        status=occurrence.status,
        expected_amount=occurrence.expected_amount,
        amount=occurrence.amount,
        booked_on=occurrence.booked_on,
        receipt_id=occurrence.receipt_id,
        income_id=occurrence.income_id,
    )


def _piece(piece: budget.Piece) -> PieceOut:
    return PieceOut(
        receipt_id=piece.receipt_id,
        day=piece.day,
        merchant=piece.merchant,
        amount=piece.amount,
        category_id=piece.category_id,
    )


# --- periods and the banner ----------------------------------------------------------


@router.get("/status", response_model=BudgetStatus)
async def budget_status(_: AuthDep, session: SessionDep) -> BudgetStatus:
    """Is a monthly meeting due? Asked by the banner on Rögzítés and Pénz."""
    spans = await budget.periods(session)
    today = budget.today_local()
    latest = spans[-1].period if spans else None
    return BudgetStatus(
        meeting_due=budget.meeting_due(spans, today),
        current=period_out(spans[-1]) if spans else None,
        today=today,
        suggested_starts_on=today,
        suggested_month=budget.suggested_month(today, latest),
    )


@router.get("/periods", response_model=list[PeriodOut])
async def list_periods(_: AuthDep, session: SessionDep) -> list[PeriodOut]:
    return [period_out(span) for span in reversed(await budget.periods(session))]


@router.post("/periods", response_model=PeriodOut, status_code=status.HTTP_201_CREATED)
async def open_period(principal: AuthDep, session: SessionDep, body: PeriodOpenIn) -> PeriodOut:
    """Close the running period and start the next one - the last step of the meeting."""
    today = budget.today_local()
    try:
        period = await budget.open_period(
            session,
            starts_on=body.starts_on or today,
            month=body.month,
            user_id=principal.user_id,
            today=today,
        )
    except budget.BudgetError as exc:
        raise _bad(exc) from exc
    await session.commit()
    span = budget.span_of(await budget.periods(session), period.id)
    return period_out(span)


async def _period_span(session: SessionDep, period_id: uuid.UUID) -> budget.PeriodSpan:
    span = budget.span_of(await budget.periods(session), period_id)
    if span is None:
        raise HTTPException(status_code=404, detail="Nincs ilyen időszak.")
    return span


@router.post("/periods/{period_id}/reopen", response_model=PeriodOut)
async def reopen_period(_: AuthDep, session: SessionDep, period_id: uuid.UUID) -> PeriodOut:
    """Unfreeze a closed period's plan to fix something in it."""
    span = await _period_span(session, period_id)
    await budget.reopen_period(session, span.period)
    await session.commit()
    return period_out(span)


@router.post("/periods/{period_id}/close", response_model=PeriodOut)
async def close_period(
    principal: AuthDep, session: SessionDep, period_id: uuid.UUID
) -> PeriodOut:
    """Freeze a reopened period again. The current one is closed by the next meeting."""
    span = await _period_span(session, period_id)
    if span.is_current:
        raise HTTPException(
            status_code=409,
            detail="A folyamatban lévő időszakot a havi megbeszélés zárja le.",
        )
    await budget.close_period(session, span.period, principal.user_id)
    await session.commit()
    return period_out(span)


# --- Hónap -------------------------------------------------------------------------


@router.get("/month", response_model=MonthOut)
async def month(
    _: AuthDep, session: SessionDep, period_id: uuid.UUID | None = None
) -> MonthOut:
    """One period at a glance: income, every line's plan and actual, and what is open."""
    spans = await budget.periods(session)
    span = budget.span_of(spans, period_id)
    if span is None:
        raise HTTPException(
            status_code=404,
            detail="Még nincs időszak." if not spans else "Nincs ilyen időszak.",
        )
    today = budget.today_local()
    view = await budget.month_view(session, span, today)

    income: dict[uuid.UUID | None, OwnerIncome] = {}

    def bucket(owner: uuid.UUID | None) -> OwnerIncome:
        return income.setdefault(
            owner, OwnerIncome(owner_id=owner, arrived=ZERO, expected=ZERO)
        )

    for entry in view.income_entries:
        bucket(entry.user_id).arrived += entry.amount
        bucket(entry.user_id).expected += entry.amount
    for occurrence in view.occurrences:
        if (
            occurrence.payment.direction == Direction.INCOME.value
            and occurrence.status in ("expected", "due")
        ):
            bucket(occurrence.payment.owner_id).expected += occurrence.expected_amount

    planned_spending = sum(
        (r.plan for r in view.rows if r.type == "recurring" or r.kind in SPENDING_KINDS),
        ZERO,
    )
    planned_aside = sum(
        (r.plan for r in view.rows if r.type == "line" and r.kind not in SPENDING_KINDS),
        ZERO,
    )
    spent = sum((r.actual for r in view.rows if r.actual is not None), ZERO)
    income_arrived = sum((i.arrived for i in income.values()), ZERO)
    income_expected = sum((i.expected for i in income.values()), ZERO)

    return MonthOut(
        period=period_out(span),
        periods=[period_out(s) for s in reversed(spans)],
        users=[PersonOut.model_validate(u) for u in await budget.household(session)],
        rows=[
            MonthRowOut(
                key=row.key, type=row.type, id=row.id, name=row.name, owner_id=row.owner_id,
                kind=row.kind, plan=row.plan, actual=row.actual, yearly=row.yearly,
                active=row.active, category_ids=row.category_ids,
                receipts=[_piece(p) for p in sorted(row.pieces, key=lambda p: p.day)],
            )
            for row in view.rows
        ],
        income=list(income.values()),
        income_entries=[IncomeOut.model_validate(e) for e in view.income_entries],
        occurrences=[occurrence_out(o) for o in view.occurrences],
        issues=MonthIssues(
            due=[occurrence_out(o) for o in view.occurrences if o.status == "due"],
            uncategorised=[_piece(p) for p in view.spending.uncategorised.values()],
            maybe_shared=[_piece(p) for p in view.spending.maybe_shared.values()],
            late=[
                LateReceipt(
                    receipt_id=receipt.id,
                    day=receipt.purchased_at.astimezone(budget.LOCAL_TZ).date(),
                    merchant=receipt.merchant_raw_name,
                    amount=receipt.total_gross or ZERO,
                    period_month=period.month,
                )
                for receipt, period in view.late
            ],
        ),
        totals=MonthTotals(
            planned_spending=planned_spending,
            planned_aside=planned_aside,
            spent=spent,
            income_arrived=income_arrived,
            income_expected=income_expected,
            free=income_expected - planned_spending - planned_aside,
        ),
        meeting_due=budget.meeting_due(spans, today),
        receipt_count=view.spending.receipt_count,
    )


# --- Terv ---------------------------------------------------------------------------


@router.get("/plan", response_model=PlanOut)
async def plan(
    _: AuthDep,
    session: SessionDep,
    start: date | None = None,
    months: int = Query(6, ge=1, le=12),
) -> PlanOut:
    """The plan for the coming months: every line, recurring item and income, per month.

    Starts at the current period's month unless told otherwise, so the first column is
    always the month you are in the middle of.
    """
    if start is None:
        spans = await budget.periods(session)
        start = spans[-1].period.month if spans else budget.first_of(budget.today_local())
    users = await budget.household(session)
    people = [u.id for u in users if u.active]
    grid = await budget.plan_grid(session, start, months)
    totals = budget.plan_totals(grid, people)
    return PlanOut(
        months=[PlanMonthOut(month=m.month, period_id=m.period_id, locked=m.locked)
                for m in grid.months],
        rows=[
            PlanRowOut(
                key=row.key, type=row.type, id=row.id, name=row.name, owner_id=row.owner_id,
                kind=row.kind, active=row.active, category_ids=row.category_ids,
                yearly=row.yearly,
                cells=[PlanCell(amount=a, explicit=e) for a, e in row.amounts],
            )
            for row in grid.rows
        ],
        totals=[
            PlanTotalsOut(
                income=house.income,
                planned=house.planned,
                free=house.free,
                people=[
                    PersonTotals(user_id=person, income=t.income, planned=t.planned, free=t.free)
                    for person, t in each.items()
                ],
            )
            for house, each in totals
        ],
        users=[PersonOut.model_validate(u) for u in users],
    )


@router.put("/plan", status_code=status.HTTP_204_NO_CONTENT)
async def set_plan_amount(_: AuthDep, session: SessionDep, body: PlanAmountIn) -> None:
    """Set a line's amount from a month on; it carries forward until changed again."""
    line = await session.get(BudgetLine, body.line_id)
    if line is None:
        raise HTTPException(status_code=404, detail="Nincs ilyen sor.")
    try:
        await budget.set_amount(session, line, body.month, body.amount)
    except budget.BudgetError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await session.commit()


# --- budget lines --------------------------------------------------------------------


def line_out(line: BudgetLine) -> LineOut:
    return LineOut(
        id=line.id, name=line.name, owner_id=line.owner_id, kind=line.kind,
        category_ids=line.category_ids, active=line.active, sort_order=line.sort_order,
        notes=line.notes,
    )


@router.get("/lines", response_model=list[LineOut])
async def list_lines(_: AuthDep, session: SessionDep) -> list[LineOut]:
    return [line_out(line) for line in await budget.all_lines(session)]


@router.post("/lines", response_model=LineOut, status_code=status.HTTP_201_CREATED)
async def create_line(_: AuthDep, session: SessionDep, body: LineCreate) -> LineOut:
    try:
        await budget.check_line(
            session, line_id=None, owner_id=body.owner_id, kind=body.kind,
            category_ids=body.category_ids,
        )
    except budget.BudgetError as exc:
        raise _bad(exc) from exc

    order = await session.scalar(select(func.max(BudgetLine.sort_order))) or 0
    line = BudgetLine(
        name=body.name.strip(), owner_id=body.owner_id, kind=body.kind,
        notes=(body.notes or "").strip() or None, sort_order=order + 1, active=True,
    )
    session.add(line)
    await session.flush()
    await budget.set_line_categories(session, line, body.category_ids)

    if body.amount is not None:
        from_month = body.from_month
        if from_month is None:
            spans = await budget.periods(session)
            from_month = (
                spans[-1].period.month if spans else budget.first_of(budget.today_local())
            )
        try:
            await budget.set_amount(session, line, from_month, body.amount)
        except budget.BudgetError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    await session.commit()
    await session.refresh(line)
    return line_out(line)


@router.patch("/lines/{line_id}", response_model=LineOut)
async def update_line(
    _: AuthDep, session: SessionDep, line_id: uuid.UUID, body: LineIn
) -> LineOut:
    line = await session.get(BudgetLine, line_id)
    if line is None:
        raise HTTPException(status_code=404, detail="Nincs ilyen sor.")
    if body.active:
        try:
            await budget.check_line(
                session, line_id=line.id, owner_id=body.owner_id, kind=body.kind,
                category_ids=body.category_ids,
            )
        except budget.BudgetError as exc:
            raise _bad(exc) from exc
    elif body.kind not in {k.value for k in BudgetLineKind}:
        raise HTTPException(status_code=422, detail="Ismeretlen csoport.")

    line.name = body.name.strip()
    line.owner_id = body.owner_id
    line.kind = body.kind
    line.active = body.active
    line.notes = (body.notes or "").strip() or None
    await budget.set_line_categories(session, line, body.category_ids)
    await session.commit()
    await session.refresh(line)
    return line_out(line)


@router.delete("/lines/{line_id}", response_model=LineRemoved)
async def remove_line(_: AuthDep, session: SessionDep, line_id: uuid.UUID) -> LineRemoved:
    """Delete a line - or archive it, if a month already discussed was planned with it."""
    line = await session.get(BudgetLine, line_id)
    if line is None:
        raise HTTPException(status_code=404, detail="Nincs ilyen sor.")
    deleted = await budget.remove_line(session, line)
    await session.commit()
    return LineRemoved(deleted=deleted)

