"""Turning subscription rules into receipts.

Spotify does not print a receipt, but it is spending, so it has to reach the same tables as
everything else. `materialise_due` walks the active rules, works out which periods have come
due and are not yet charged, and creates one typed-in receipt per period.

The whole design rests on one property: **running this twice must not charge twice.** The
worker calls it on start and every hour, a clock change or a restart can repeat a period,
and two workers could in principle overlap. So a `recurring_charges` row keyed
`(recurring_id, period)` is written in the same transaction as the receipt, and the unique
constraint - not a prior SELECT - is what actually decides. Losing that race is a no-op.
"""

from __future__ import annotations

import calendar
import logging
from datetime import UTC, date, datetime, time

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Cadence, Receipt, RecurringCharge, RecurringPayment
from app.services.manual import create_manual_receipt

log = logging.getLogger(__name__)


def charge_date(payment: RecurringPayment, period: date) -> date:
    """The day within `period` that this payment falls on.

    A payment set to the 31st still charges in February - on the 28th or 29th. Skipping the
    month instead would quietly lose a real charge from the statistics.
    """
    last = calendar.monthrange(period.year, period.month)[1]
    return period.replace(day=min(payment.day_of_month, last))


def periods_due(payment: RecurringPayment, today: date) -> list[date]:
    """Every period of this payment that has already come due, oldest first.

    A period counts once its charge date has arrived - not merely once the month has begun -
    so adding a subscription on the 3rd for a rule that bills on the 20th does not
    immediately invent this month's charge.
    """
    if not payment.active:
        return []

    start = payment.starts_on
    end = min(payment.ends_on, today) if payment.ends_on else today
    if start > end:
        return []

    out: list[date] = []
    period = start.replace(day=1)
    while period <= end:
        due = charge_date(payment, period)
        if start <= due <= end and _in_cadence(payment, period):
            out.append(period)
        period = _next_month(period)
    return out


def _in_cadence(payment: RecurringPayment, period: date) -> bool:
    if payment.cadence == Cadence.YEARLY.value:
        # A yearly payment defaults to the month it started in when none was given.
        month = payment.month_of_year or payment.starts_on.month
        return period.month == month
    return True


def _next_month(period: date) -> date:
    return date(period.year + 1, 1, 1) if period.month == 12 else date(
        period.year, period.month + 1, 1
    )


async def materialise_due(
    session: AsyncSession, *, today: date | None = None, limit_per_payment: int = 36
) -> list[Receipt]:
    """Create the receipts for every subscription period that has come due.

    Returns only the receipts actually created, so a caller can tell "nothing to do" from
    "created three". `limit_per_payment` bounds the backfill when a rule is added with a
    start date years ago - the oldest periods are taken first, and the next pass continues.
    """
    today = today or datetime.now(UTC).date()

    payments = (
        await session.scalars(
            select(RecurringPayment)
            .where(RecurringPayment.active.is_(True))
            .order_by(RecurringPayment.name)
        )
    ).all()

    created: list[Receipt] = []
    for payment in payments:
        due = periods_due(payment, today)
        if not due:
            continue

        already = set(
            (
                await session.scalars(
                    select(RecurringCharge.period).where(
                        RecurringCharge.recurring_id == payment.id
                    )
                )
            ).all()
        )
        outstanding = [period for period in due if period not in already][:limit_per_payment]

        for period in outstanding:
            receipt = await _charge(session, payment, period)
            if receipt is not None:
                created.append(receipt)

    if created:
        log.info("materialised %d recurring charge(s)", len(created))
    return created


async def _charge(
    session: AsyncSession, payment: RecurringPayment, period: date
) -> Receipt | None:
    """Create one period's receipt, or return None if it already existed.

    The receipt and the charge row go in together under a savepoint. The `already` check in
    the caller is only an optimisation; this constraint is the thing that makes a repeated
    run harmless.
    """
    when = datetime.combine(charge_date(payment, period), time(12, 0), tzinfo=UTC)
    try:
        async with session.begin_nested():
            receipt = await create_manual_receipt(
                session,
                merchant_name=payment.merchant_name,
                purchased_at=when,
                items=[{
                    "raw_name": payment.name,
                    "gross_amount": payment.amount,
                    "quantity": 1,
                    "unit": "db",
                    "unit_price": payment.amount,
                    "category_id": payment.category_id,
                }],
                total_gross=payment.amount,
                payment_method=payment.payment_method,
                currency=payment.currency,
                source="recurring",
                notes=f"Automatikus tétel: {payment.name}",
            )
            session.add(
                RecurringCharge(
                    recurring_id=payment.id, period=period, receipt_id=receipt.id
                )
            )
            await session.flush()
    except IntegrityError:
        # Another pass got there first. That is the constraint doing its job, not an error.
        log.debug("recurring charge %s/%s already existed", payment.name, period)
        return None

    log.info("charged %s for %s (%s %s)", payment.name, period, payment.amount, payment.currency)
    return receipt
