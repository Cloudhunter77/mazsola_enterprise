"""Request and response bodies for budgeting: periods, the plan, Hónap and income.

An owner is a user id, or null for Közös - the household's shared money. That one convention
runs through budget lines, recurring items and income alike.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class PersonOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    display_name: str
    active: bool


# --- periods -----------------------------------------------------------------------
class PeriodOut(BaseModel):
    id: uuid.UUID
    month: date
    starts_on: date
    # Exclusive: the day the next period started. Null while this is the current period.
    ends_on: date | None
    closed_at: datetime | None
    is_current: bool


class BudgetStatus(BaseModel):
    """What the banner and the meeting screen need to know before anything else."""

    meeting_due: bool
    current: PeriodOut | None
    today: date
    # What the meeting would open if held today, unless told otherwise.
    suggested_starts_on: date
    suggested_month: date


class PeriodOpenIn(BaseModel):
    """The end of a monthly meeting. Both default: today, and the month it plans."""

    starts_on: date | None = None
    month: date | None = None


# --- budget lines -----------------------------------------------------------------
LineKindName = Literal["fix", "valtozo", "celalap", "megtakaritas"]


class LineIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    owner_id: uuid.UUID | None = None
    kind: LineKindName = "valtozo"
    category_ids: list[uuid.UUID] = Field(default_factory=list, max_length=50)
    active: bool = True
    notes: str | None = None


class LineCreate(LineIn):
    # The amount to plan from `from_month` on; `from_month` defaults to the current period's.
    amount: Decimal | None = Field(default=None, ge=0)
    from_month: date | None = None


class LineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    owner_id: uuid.UUID | None
    kind: str
    category_ids: list[uuid.UUID]
    active: bool
    sort_order: int
    notes: str | None


class LineRemoved(BaseModel):
    # False when the line was archived instead: a closed period was planned with it.
    deleted: bool


# --- the plan (Terv) -----------------------------------------------------------------
class PlanAmountIn(BaseModel):
    line_id: uuid.UUID
    month: date
    # Null removes the change in that month, so it inherits the month before again.
    amount: Decimal | None = Field(default=None, ge=0)


class PlanCell(BaseModel):
    amount: Decimal
    # Set in this very month, rather than carried forward from an earlier one.
    explicit: bool


class PlanRowOut(BaseModel):
    key: str
    type: Literal["line", "recurring", "income"]
    id: uuid.UUID
    name: str
    owner_id: uuid.UUID | None
    kind: str
    active: bool
    category_ids: list[uuid.UUID]
    yearly: bool
    cells: list[PlanCell]


class PlanMonthOut(BaseModel):
    month: date
    period_id: uuid.UUID | None
    locked: bool


class PersonTotals(BaseModel):
    user_id: uuid.UUID
    income: Decimal
    planned: Decimal
    free: Decimal


class PlanTotalsOut(BaseModel):
    income: Decimal
    planned: Decimal
    free: Decimal
    people: list[PersonTotals]


class PlanOut(BaseModel):
    months: list[PlanMonthOut]
    rows: list[PlanRowOut]
    totals: list[PlanTotalsOut]
    users: list[PersonOut]


# --- income ------------------------------------------------------------------------
class IncomeIn(BaseModel):
    user_id: uuid.UUID | None = None
    name: str = Field(min_length=1, max_length=120)
    amount: Decimal = Field(gt=0)
    received_on: date
    notes: str | None = None


class IncomeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID | None
    name: str
    amount: Decimal
    received_on: date
    recurring_id: uuid.UUID | None
    notes: str | None
    created_at: datetime


# --- recurring occurrences -----------------------------------------------------------
class OccurrenceOut(BaseModel):
    recurring_id: uuid.UUID
    name: str
    direction: str
    amount_mode: str
    owner_id: uuid.UUID | None
    month: date
    due: date
    status: Literal["expected", "due", "done", "skipped"]
    expected_amount: Decimal
    amount: Decimal | None
    booked_on: date | None
    receipt_id: uuid.UUID | None
    income_id: uuid.UUID | None


class OccurrenceConfirmIn(BaseModel):
    month: date
    amount: Decimal = Field(gt=0)
    # When it was paid or arrived. Defaults to its due day, or today if that is still ahead.
    on: date | None = None


class OccurrenceSkipIn(BaseModel):
    month: date


# --- Hónap ----------------------------------------------------------------------------
class PieceOut(BaseModel):
    receipt_id: uuid.UUID
    day: date
    merchant: str | None
    amount: Decimal
    category_id: uuid.UUID | None = None


class MonthRowOut(BaseModel):
    key: str
    type: Literal["line", "recurring", "unplanned"]
    id: uuid.UUID | None
    name: str
    owner_id: uuid.UUID | None
    kind: str
    plan: Decimal
    # Null for money set aside (Célalap, Megtakarítás without categories): no receipt shows it.
    actual: Decimal | None
    yearly: bool
    active: bool
    category_ids: list[uuid.UUID]
    receipts: list[PieceOut]


class OwnerIncome(BaseModel):
    owner_id: uuid.UUID | None
    arrived: Decimal
    # What has arrived plus what is still expected this period.
    expected: Decimal


class LateReceipt(PieceOut):
    period_month: date


class MonthIssues(BaseModel):
    """What a meeting should look at before closing the period."""

    due: list[OccurrenceOut]
    uncategorised: list[PieceOut]
    maybe_shared: list[PieceOut]
    late: list[LateReceipt]


class MonthTotals(BaseModel):
    planned_spending: Decimal
    planned_aside: Decimal
    spent: Decimal
    income_arrived: Decimal
    income_expected: Decimal
    # Expected income minus everything planned, spending and setting aside alike.
    free: Decimal


class MonthOut(BaseModel):
    period: PeriodOut
    periods: list[PeriodOut]
    users: list[PersonOut]
    rows: list[MonthRowOut]
    income: list[OwnerIncome]
    income_entries: list[IncomeOut]
    occurrences: list[OccurrenceOut]
    issues: MonthIssues
    totals: MonthTotals
    meeting_due: bool
    receipt_count: int
