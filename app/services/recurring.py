"""Turning recurring rules into receipts and income, and keeping track of each month.

Spotify does not print a receipt, but it is spending, so it has to reach the same tables as
everything else. `materialise_due` walks the active fixed bills, works out which periods
have come due and are not yet charged, and creates one typed-in receipt per period.

Everything else waits for a person. A variable bill is booked when you enter what it came
to, a salary when you say it arrived (`confirm_occurrence`), and a month that did not happen
can be skipped (`skip_occurrence`). Each of those writes the same `recurring_charges` row,
so "what is still expected this month" is simply every due date without one.

The whole design rests on one property: **running this twice must not charge twice.** The
worker calls it on start and every hour, a clock change or a restart can repeat a period,
and two workers could in principle overlap. So a `recurring_charges` row keyed
`(recurring_id, period)` is written in the same transaction as the receipt, and the unique
constraint - not a prior SELECT - is what actually decides. Losing that race is a no-op.
"""

from __future__ import annotations

import calendar
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AmountMode,
    Cadence,
    Direction,
    IncomeEntry,
    Receipt,
    RecurringCharge,
    RecurringPayment,
)
from app.services.manual import create_manual_receipt
from app.services.splits import SplitError, set_split

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

    # Only fixed bills book themselves. A variable bill's amount is not known until it
    # arrives, and income is never a receipt.
    payments = (
        await session.scalars(
            select(RecurringPayment)
            .where(RecurringPayment.active.is_(True))
            .where(RecurringPayment.direction == Direction.EXPENSE.value)
            .where(RecurringPayment.amount_mode == AmountMode.FIXED.value)
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
    try:
        async with session.begin_nested():
            receipt = await _bill(
                session, payment, charge_date(payment, period), payment.amount,
                note=f"Automatikus tétel: {payment.name}",
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


async def _bill(
    session: AsyncSession, payment: RecurringPayment, on: date, amount: Decimal, *, note: str
) -> Receipt:
    """The receipt one month of a bill becomes: its payer, its split, its category."""
    receipt = await create_manual_receipt(
        session,
        merchant_name=payment.merchant_name,
        purchased_at=datetime.combine(on, time(12, 0), tzinfo=UTC),
        items=[{
            "raw_name": payment.name,
            "gross_amount": amount,
            "quantity": 1,
            "unit": "db",
            "unit_price": amount,
            "category_id": payment.category_id,
        }],
        total_gross=amount,
        payment_method=payment.payment_method,
        currency=payment.currency,
        source="recurring",
        notes=note,
    )
    if payment.pocket_id is not None:
        # Paid from a pocket: say so on the receipt, as a person would have (D29).
        receipt.pocket_id = payment.pocket_id
        receipt.pocket_source = "manual"
    if payment.payer_id is not None or payment.default_shares:
        try:
            await set_split(session, receipt, payment.payer_id, rule_shares(payment))
        except SplitError as exc:
            # The rule was valid when saved; a person removed since then can make it not
            # be. Booking the bill unsplit is better than not booking it at all.
            log.warning("could not split %s as its rule says: %s", payment.name, exc)
    return receipt


def rule_shares(payment: RecurringPayment) -> list[tuple[uuid.UUID, Decimal]]:
    return [
        (uuid.UUID(str(share["user_id"])), Decimal(str(share["percent"])))
        for share in payment.default_shares or []
    ]


# --- one month at a time: what is expected, and what happened -----------------


class OccurrenceError(ValueError):
    """A confirmation or skip that cannot be stored; the message is for the screen."""


@dataclass(slots=True)
class Occurrence:
    """One due date of one rule, and what became of it."""

    payment: RecurringPayment
    month: date          # the first day of the month it falls in: the charge row's key
    due: date
    # expected: still ahead. due: its day has come and nothing is recorded yet.
    # done: booked or confirmed. skipped: marked as not having happened.
    status: str
    expected_amount: Decimal
    amount: Decimal | None = None
    booked_on: date | None = None
    receipt_id: uuid.UUID | None = None
    income_id: uuid.UUID | None = None


def due_dates_between(
    payment: RecurringPayment, start: date, end: date
) -> list[tuple[date, date]]:
    """(month, due date) for every occurrence of this rule due in [start, end)."""
    out: list[tuple[date, date]] = []
    month = start.replace(day=1)
    while month < end:
        due = charge_date(payment, month)
        if (
            start <= due < end
            and _in_cadence(payment, month)
            and payment.starts_on <= due
            and (payment.ends_on is None or due <= payment.ends_on)
        ):
            out.append((month, due))
        month = _next_month(month)
    return out


async def last_amounts(session: AsyncSession) -> dict[uuid.UUID, Decimal]:
    """What each rule most recently came to, for planning a variable bill or income."""
    rows = (
        await session.execute(
            select(
                RecurringCharge.recurring_id,
                RecurringCharge.period,
                Receipt.total_gross,
                IncomeEntry.amount,
            )
            .outerjoin(Receipt, Receipt.id == RecurringCharge.receipt_id)
            .outerjoin(IncomeEntry, IncomeEntry.id == RecurringCharge.income_id)
            .order_by(RecurringCharge.period)
        )
    ).all()
    latest: dict[uuid.UUID, Decimal] = {}
    for recurring_id, _, receipt_total, income_amount in rows:
        amount = receipt_total if receipt_total is not None else income_amount
        if amount is not None:
            latest[recurring_id] = Decimal(amount)
    return latest


def expected_amount(payment: RecurringPayment, last: dict[uuid.UUID, Decimal]) -> Decimal:
    """A fixed amount is what the rule says; a variable one is what it was last time."""
    if payment.amount_mode == AmountMode.VARIABLE.value and payment.id in last:
        return last[payment.id]
    return Decimal(payment.amount)


async def occurrences_between(
    session: AsyncSession, start: date, end: date, today: date
) -> list[Occurrence]:
    """Every due date in [start, end) of every rule, with what became of each, by date."""
    payments = (await session.scalars(select(RecurringPayment))).all()
    if not payments:
        return []
    last = await last_amounts(session)

    charges: dict[tuple[uuid.UUID, date], tuple] = {}
    for charge, receipt_total, receipt_at, income_amount, income_on in (
        await session.execute(
            select(
                RecurringCharge,
                Receipt.total_gross,
                Receipt.purchased_at,
                IncomeEntry.amount,
                IncomeEntry.received_on,
            )
            .outerjoin(Receipt, Receipt.id == RecurringCharge.receipt_id)
            .outerjoin(IncomeEntry, IncomeEntry.id == RecurringCharge.income_id)
            .where(RecurringCharge.period >= start.replace(day=1))
            .where(RecurringCharge.period < end)
        )
    ).all():
        charges[(charge.recurring_id, charge.period)] = (
            charge, receipt_total, receipt_at, income_amount, income_on,
        )

    out: list[Occurrence] = []
    for payment in payments:
        for month, due in due_dates_between(payment, start, end):
            found = charges.get((payment.id, month))
            occurrence = Occurrence(
                payment=payment, month=month, due=due, status="expected",
                expected_amount=expected_amount(payment, last),
            )
            if found is not None:
                charge, receipt_total, receipt_at, income_amount, income_on = found
                if charge.receipt_id is not None or charge.income_id is not None:
                    occurrence.status = "done"
                    occurrence.receipt_id = charge.receipt_id
                    occurrence.income_id = charge.income_id
                    occurrence.amount = Decimal(
                        receipt_total if receipt_total is not None else income_amount or 0
                    )
                    occurrence.booked_on = (
                        receipt_at.date() if receipt_at is not None else income_on
                    )
                else:
                    occurrence.status = "skipped"
            elif not payment.active:
                continue  # paused: nothing is expected of it any more
            elif due <= today:
                occurrence.status = "due"
            out.append(occurrence)
    out.sort(key=lambda o: (o.due, o.payment.name))
    return out


async def _charge_for(
    session: AsyncSession, payment: RecurringPayment, month: date
) -> RecurringCharge | None:
    return await session.scalar(
        select(RecurringCharge)
        .where(RecurringCharge.recurring_id == payment.id)
        .where(RecurringCharge.period == month)
    )


def _check_month(payment: RecurringPayment, month: date) -> date:
    month = month.replace(day=1)
    if not _in_cadence(payment, month):
        raise OccurrenceError("Ebben a hónapban nem esedékes.")
    return month


async def confirm_occurrence(
    session: AsyncSession,
    payment: RecurringPayment,
    month: date,
    amount: Decimal,
    on: date,
    today: date,
    user_id: uuid.UUID | None = None,
) -> RecurringCharge:
    """Record that one month's bill was paid, or one month's income arrived.

    A bill becomes a receipt, with the rule's payer and split, so it counts in spending and
    in Elszámolás like any other. Income becomes an income entry. A fixed bill can be
    confirmed too - paid early, or at a different amount this once - and the hourly pass then
    finds the month already done.
    """
    month = _check_month(payment, month)
    if amount is None or amount <= 0:
        raise OccurrenceError("Az összegnek nullánál nagyobbnak kell lennie.")
    if on > today:
        raise OccurrenceError("A dátum nem lehet a jövőben.")
    if await _charge_for(session, payment, month) is not None:
        raise OccurrenceError("Ezt a hónapot már rögzítettétek.")

    amount = Decimal(amount).quantize(Decimal("0.01"))
    try:
        async with session.begin_nested():
            if payment.direction == Direction.INCOME.value:
                entry = IncomeEntry(
                    user_id=payment.owner_id,
                    name=payment.name,
                    amount=amount,
                    received_on=on,
                    recurring_id=payment.id,
                    created_by_id=user_id,
                )
                session.add(entry)
                await session.flush()
                charge = RecurringCharge(
                    recurring_id=payment.id, period=month, income_id=entry.id
                )
            else:
                receipt = await _bill(
                    session, payment, on, amount, note=f"Rendszeres: {payment.name}"
                )
                charge = RecurringCharge(
                    recurring_id=payment.id, period=month, receipt_id=receipt.id
                )
            session.add(charge)
            await session.flush()
    except IntegrityError as exc:
        raise OccurrenceError("Ezt a hónapot már rögzítettétek.") from exc
    return charge


async def skip_occurrence(
    session: AsyncSession, payment: RecurringPayment, month: date
) -> RecurringCharge:
    """Mark a month as not having happened: no bill came, no salary arrived."""
    month = _check_month(payment, month)
    if await _charge_for(session, payment, month) is not None:
        raise OccurrenceError("Ezt a hónapot már rögzítettétek.")
    charge = RecurringCharge(recurring_id=payment.id, period=month)
    try:
        async with session.begin_nested():
            session.add(charge)
            await session.flush()
    except IntegrityError as exc:
        raise OccurrenceError("Ezt a hónapot már rögzítettétek.") from exc
    return charge


async def undo_occurrence(session: AsyncSession, payment: RecurringPayment, month: date) -> None:
    """Take back a confirmation or a skip, so the month is expected again.

    What the confirmation created goes with it. The one thing that cannot be undone here is
    a fixed bill that booked itself: the next pass would only book it again. Deleting its
    receipt is what skips it, as it always was.
    """
    charge = await _charge_for(session, payment, month.replace(day=1))
    if charge is None:
        raise OccurrenceError("Ehhez a hónaphoz nincs mit visszavonni.")
    fixed_bill = (
        payment.direction == Direction.EXPENSE.value
        and payment.amount_mode == AmountMode.FIXED.value
    )
    if fixed_bill and charge.receipt_id is not None:
        raise OccurrenceError(
            "A fix összegű tétel magától rögzül; ha ebben a hónapban nem volt, töröld a blokkját."
        )

    if charge.receipt_id is not None:
        receipt = await session.get(Receipt, charge.receipt_id)
        if receipt is not None:
            await session.delete(receipt)
    if charge.income_id is not None:
        entry = await session.get(IncomeEntry, charge.income_id)
        if entry is not None:
            await session.delete(entry)
    await session.delete(charge)
    await session.flush()
