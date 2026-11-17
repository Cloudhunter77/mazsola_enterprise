"""Rendszeres: recurring bills and income, and what became of each month.

A rule is edited here; the receipts it produced are ordinary receipts and are edited there.
Deactivating a rule stops future charges and leaves everything it has already generated
alone - a cancelled subscription is still part of last year's spending.

Each month of a rule is an *occurrence*: expected, due, done or skipped. A fixed bill becomes
done by itself; a variable bill or a salary is confirmed here with what it actually came to.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import func, select

from app.api.budget import occurrence_out
from app.api.deps import AuthDep, SessionDep
from app.models import (
    AmountMode,
    Category,
    Direction,
    RecurringCharge,
    RecurringPayment,
    User,
)
from app.schemas.api import RecurringIn, RecurringOut
from app.schemas.budget import OccurrenceConfirmIn, OccurrenceOut, OccurrenceSkipIn
from app.services import budget
from app.services.catalog import resolve_merchant
from app.services.recurring import (
    OccurrenceError,
    charge_date,
    confirm_occurrence,
    materialise_due,
    occurrences_between,
    periods_due,
    skip_occurrence,
    undo_occurrence,
)

router = APIRouter(prefix="/api/recurring", tags=["recurring"])


async def _to_out(session: SessionDep, payment: RecurringPayment) -> RecurringOut:
    out = RecurringOut.model_validate(payment)
    out.charge_count = await session.scalar(
        select(func.count(RecurringCharge.id)).where(RecurringCharge.recurring_id == payment.id)
    ) or 0
    out.next_charge = await _next_charge(session, payment)
    return out


async def _next_charge(session: SessionDep, payment: RecurringPayment) -> date | None:
    """When this rule will next produce a receipt, or None if it never will again.

    Derived by asking for the periods due a year out and taking the first that has no charge
    row yet - so it stays honest about a backlog rather than always showing next month.
    """
    if not payment.active:
        return None

    today = budget.today_local()
    horizon = date(today.year + 1, today.month, 1)
    charged = set(
        (
            await session.scalars(
                select(RecurringCharge.period).where(RecurringCharge.recurring_id == payment.id)
            )
        ).all()
    )

    # A fixed bill catches up on its own, so its oldest unbilled month really is the next
    # thing that will happen. A salary or a variable bill only happens when someone confirms
    # it; a month nobody confirmed months ago is not "next" - the next due date is.
    books_itself = (
        payment.direction == Direction.EXPENSE.value
        and payment.amount_mode == AmountMode.FIXED.value
    )
    for period in periods_due(payment, horizon):
        due = charge_date(payment, period)
        if period not in charged and (books_itself or due >= today):
            return due
    return None


async def _validated(session: SessionDep, body: RecurringIn) -> dict:
    """The rule's columns, checked: people that exist, and a split that adds up.

    The split is checked here, when the rule is saved, rather than each time it generates a
    receipt - an error found by the hourly pass at 3 a.m. has nobody to read it.
    """
    people = {user.id for user in (await session.scalars(select(User))).all()}
    for person in (body.owner_id, body.payer_id):
        if person is not None and person not in people:
            raise HTTPException(status_code=422, detail="Nincs ilyen felhasználó.")
    if body.category_id is not None and await session.get(Category, body.category_id) is None:
        raise HTTPException(status_code=422, detail="Nincs ilyen kategória.")

    values = body.model_dump(exclude={"merchant_name", "default_shares"})
    income = body.direction == Direction.INCOME.value
    shares = [] if income else [s for s in body.default_shares or [] if s.percent > 0]
    if shares:
        if body.payer_id is None:
            raise HTTPException(status_code=422, detail="Megosztáshoz tudni kell, ki fizeti.")
        if any(share.user_id not in people for share in shares):
            raise HTTPException(status_code=422, detail="Nincs ilyen felhasználó.")
        if sum((share.percent for share in shares), Decimal(0)) != 100:
            raise HTTPException(
                status_code=422, detail="A részeknek együtt 100%-ot kell kiadniuk."
            )
    values["default_shares"] = (
        [{"user_id": str(share.user_id), "percent": str(share.percent)} for share in shares]
        or None
    )
    if income:
        # Income is nobody's bill: no payer, no split, no spending category.
        values.update(payer_id=None, category_id=None)
    values["merchant_name"] = ((body.merchant_name or "").strip() or body.name.strip())[:300]
    return values


@router.get("", response_model=list[RecurringOut])
async def list_recurring(_: AuthDep, session: SessionDep) -> list[RecurringOut]:
    payments = (
        await session.scalars(
            select(RecurringPayment).order_by(
                RecurringPayment.active.desc(), RecurringPayment.name
            )
        )
    ).all()
    return [await _to_out(session, payment) for payment in payments]


@router.post("", response_model=RecurringOut, status_code=status.HTTP_201_CREATED)
async def create_recurring(_: AuthDep, session: SessionDep, body: RecurringIn) -> RecurringOut:
    """Add a subscription, and immediately generate anything already due.

    Charging on create is deliberate: a rule added with a start date in the past is a
    statement about spending that already happened, and leaving it invisible until the
    worker's next hourly pass would look like the entry had not saved.
    """
    values = await _validated(session, body)
    merchant = await resolve_merchant(session, values["merchant_name"])
    payment = RecurringPayment(**values, merchant_id=merchant.id if merchant else None)
    session.add(payment)
    await session.flush()
    await materialise_due(session)
    await session.commit()
    return await _to_out(session, payment)


@router.patch("/{recurring_id}", response_model=RecurringOut)
async def update_recurring(
    _: AuthDep, session: SessionDep, recurring_id: uuid.UUID, body: RecurringIn
) -> RecurringOut:
    payment = await session.get(RecurringPayment, recurring_id)
    if payment is None:
        raise HTTPException(status_code=404, detail="No such recurring payment.")

    values = await _validated(session, body)
    merchant_name = values.pop("merchant_name")
    for field, value in values.items():
        setattr(payment, field, value)
    if merchant_name != payment.merchant_name:
        merchant = await resolve_merchant(session, merchant_name)
        payment.merchant_name = merchant_name
        payment.merchant_id = merchant.id if merchant else None

    await materialise_due(session)
    await session.commit()
    return await _to_out(session, payment)


@router.delete("/{recurring_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_recurring(_: AuthDep, session: SessionDep, recurring_id: uuid.UUID) -> None:
    """Remove the rule. Receipts it already generated stay - they are real spending.

    To stop future charges while keeping the rule visible, set `active` to false instead.
    """
    payment = await session.get(RecurringPayment, recurring_id)
    if payment is None:
        raise HTTPException(status_code=404, detail="No such recurring payment.")
    await session.delete(payment)
    await session.commit()


@router.post("/run", response_model=list[RecurringOut])
async def run_now(_: AuthDep, session: SessionDep) -> list[RecurringOut]:
    """Generate anything due right now, without waiting for the worker's hourly pass."""
    await materialise_due(session)
    await session.commit()
    return await list_recurring(_, session)


# --- one month at a time ------------------------------------------------------------


@router.get("/occurrences", response_model=list[OccurrenceOut])
async def list_occurrences(
    _: AuthDep, session: SessionDep, period_id: uuid.UUID | None = None
) -> list[OccurrenceOut]:
    """Every due date in a period, with what became of it. Defaults to the current period;
    before the first meeting, to the current calendar month."""
    today = budget.today_local()
    spans = await budget.periods(session)
    span = budget.span_of(spans, period_id)
    if span is None and period_id is not None:
        raise HTTPException(status_code=404, detail="Nincs ilyen időszak.")
    if span is None:
        start = budget.first_of(today)
        end = budget.add_months(start, 1)
    else:
        start, end = span.start, span.expectation_end(today)
    return [occurrence_out(o) for o in await occurrences_between(session, start, end, today)]


async def _payment(session: SessionDep, recurring_id: uuid.UUID) -> RecurringPayment:
    payment = await session.get(RecurringPayment, recurring_id)
    if payment is None:
        raise HTTPException(status_code=404, detail="No such recurring payment.")
    return payment


@router.post("/{recurring_id}/occurrences", status_code=status.HTTP_204_NO_CONTENT)
async def confirm(
    principal: AuthDep, session: SessionDep, recurring_id: uuid.UUID, body: OccurrenceConfirmIn
) -> None:
    """"Kifizetve" or "Megérkezett": one month of a bill or income, at its actual amount."""
    payment = await _payment(session, recurring_id)
    today = budget.today_local()
    on = body.on or min(charge_date(payment, body.month.replace(day=1)), today)
    try:
        await confirm_occurrence(
            session, payment, body.month, body.amount, on, today, principal.user_id
        )
    except OccurrenceError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    await session.commit()


@router.post("/{recurring_id}/occurrences/skip", status_code=status.HTTP_204_NO_CONTENT)
async def skip(
    _: AuthDep, session: SessionDep, recurring_id: uuid.UUID, body: OccurrenceSkipIn
) -> None:
    """This month it did not happen: no bill came, no salary arrived."""
    payment = await _payment(session, recurring_id)
    try:
        await skip_occurrence(session, payment, body.month)
    except OccurrenceError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    await session.commit()


@router.delete("/{recurring_id}/occurrences/{month}", status_code=status.HTTP_204_NO_CONTENT)
async def undo(_: AuthDep, session: SessionDep, recurring_id: uuid.UUID, month: date) -> None:
    """Take back a confirmation or a skip; the month is expected again."""
    payment = await _payment(session, recurring_id)
    try:
        await undo_occurrence(session, payment, month)
    except OccurrenceError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    await session.commit()
