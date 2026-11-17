"""Money that comes and goes on a schedule: bills, subscriptions and salaries.

Spotify, the rent, the electricity bill, a salary. A bill is real spending, so it belongs in
the same statistics as everything else - which means it has to become an ordinary `Receipt`
row rather than a parallel world the dashboard would have to learn about. A salary is the
opposite: it becomes an `IncomeEntry`, never a receipt.

A `RecurringPayment` is the *rule*; a `RecurringCharge` records what happened to it in one
particular month. The charge row is what makes materialising idempotent: without it, a
restart, a clock change or two workers racing would each mint another Spotify charge and
quietly inflate the month.

Only a fixed bill books itself. A variable one (electricity) waits for you to enter what it
actually came to, and a salary waits for you to say it arrived - money that has not arrived
must not look like money you have. Either can be marked as skipped for a month it did not
happen, which is a charge row pointing at nothing.
"""

from __future__ import annotations

import enum
import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import JSON, Date, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, money, pk


class Cadence(enum.StrEnum):
    MONTHLY = "monthly"
    YEARLY = "yearly"


class Direction(enum.StrEnum):
    EXPENSE = "expense"
    INCOME = "income"


class AmountMode(enum.StrEnum):
    FIXED = "fixed"        # the same every time; a bill of this kind books itself
    VARIABLE = "variable"  # different every time; waits for the actual amount


class RecurringPayment(Base, TimestampMixin):
    """One recurring bill or income, and the rule for when it falls due."""

    __tablename__ = "recurring_payments"

    id: Mapped[uuid.UUID] = pk()

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    merchant_name: Mapped[str] = mapped_column(String(300), nullable=False)
    merchant_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("merchants.id", ondelete="SET NULL"), nullable=True
    )
    category_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("categories.id", ondelete="SET NULL"), nullable=True
    )

    amount: Mapped[Decimal] = money(nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="HUF", nullable=False)

    cadence: Mapped[str] = mapped_column(String(10), default=Cadence.MONTHLY.value, nullable=False)
    # 1-31. A month that is too short charges on its last day rather than skipping.
    day_of_month: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    # Which month of the year a yearly payment falls in; ignored when monthly.
    month_of_year: Mapped[int | None] = mapped_column(Integer, nullable=True)

    payment_method: Mapped[str] = mapped_column(String(10), default="card", nullable=False)

    # No charge is generated before this date or after `ends_on`. Cancelling a subscription
    # is setting `ends_on`, which keeps the history rather than deleting it.
    starts_on: Mapped[date] = mapped_column(Date, nullable=False)
    ends_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    active: Mapped[bool] = mapped_column(default=True, nullable=False)

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    direction: Mapped[str] = mapped_column(
        String(10), default=Direction.EXPENSE.value, nullable=False
    )
    amount_mode: Mapped[str] = mapped_column(
        String(10), default=AmountMode.FIXED.value, nullable=False
    )
    # Whose bill or income this is in the plan. NULL is Közös.
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    # Who actually pays a bill. It becomes the payer of every receipt the rule generates.
    payer_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    # How every generated receipt is split: [{"user_id": "...", "percent": "50"}, ...].
    # NULL means not split.
    default_shares: Mapped[list | None] = mapped_column(JSON, nullable=True)

    charges: Mapped[list[RecurringCharge]] = relationship(
        back_populates="payment", cascade="all, delete-orphan", order_by="RecurringCharge.period"
    )


class RecurringCharge(Base, TimestampMixin):
    """The record that one month of one rule has been dealt with.

    It points at the receipt a bill generated, or the income entry a salary was confirmed
    as - or at neither, which means the month was skipped.

    `receipt_id` is SET NULL rather than CASCADE on purpose: deleting the generated receipt
    must not make the period look unbilled, or the next pass would recreate the very row you
    just deleted. The charge row is a tombstone as much as a link.
    """

    __tablename__ = "recurring_charges"

    id: Mapped[uuid.UUID] = pk()
    recurring_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("recurring_payments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # The first day of the period this charge covers, so the key is stable regardless of
    # which day of the month the payment actually falls on.
    period: Mapped[date] = mapped_column(Date, nullable=False)
    receipt_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("receipts.id", ondelete="SET NULL"), nullable=True
    )
    income_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("income_entries.id", ondelete="SET NULL"), nullable=True
    )

    payment: Mapped[RecurringPayment] = relationship(back_populates="charges")

    __table_args__ = (UniqueConstraint("recurring_id", "period", name="uq_recurring_charge"),)
