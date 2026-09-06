"""Subscriptions: the rules, and the receipts they generate.

A rule is edited here; the receipts it produced are ordinary receipts and are edited there.
Deactivating a rule stops future charges and leaves everything it has already generated
alone - a cancelled subscription is still part of last year's spending.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import func, select

from app.api.deps import AuthDep, SessionDep
from app.models import RecurringCharge, RecurringPayment
from app.schemas.api import RecurringIn, RecurringOut
from app.services.catalog import resolve_merchant
from app.services.recurring import materialise_due, periods_due

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

    today = datetime.now(UTC).date()
    horizon = date(today.year + 1, today.month, 1)
    charged = set(
        (
            await session.scalars(
                select(RecurringCharge.period).where(RecurringCharge.recurring_id == payment.id)
            )
        ).all()
    )
    from app.services.recurring import charge_date

    for period in periods_due(payment, horizon):
        if period not in charged:
            return charge_date(payment, period)
    return None


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
    merchant = await resolve_merchant(session, body.merchant_name)
    payment = RecurringPayment(
        **body.model_dump(exclude={"merchant_name"}),
        merchant_name=body.merchant_name.strip()[:300],
        merchant_id=merchant.id if merchant else None,
    )
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

    for field, value in body.model_dump(exclude={"merchant_name"}).items():
        setattr(payment, field, value)
    if body.merchant_name.strip() != payment.merchant_name:
        merchant = await resolve_merchant(session, body.merchant_name)
        payment.merchant_name = body.merchant_name.strip()[:300]
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
