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


class TransferPlanIn(BaseModel):
    """One line of the meeting's transfer checklist, as it was left when closing."""

    line_id: uuid.UUID
    from_user_id: uuid.UUID | None = None
    amount: Decimal = Field(ge=0)
    # Ticked: sent already. Unticked: stays in Hónap's to-do list until it is (D28).
    done: bool = True


class CheckIn(BaseModel):
    """What Revolut shows in a pocket right now."""

    pocket_id: uuid.UUID
    balance: Decimal
    on: date | None = None


class PeriodOpenIn(BaseModel):
    """The end of a monthly meeting. Both default: today, and the month it plans."""

    starts_on: date | None = None
    month: date | None = None
    transfers: list[TransferPlanIn] = Field(default_factory=list, max_length=200)
    checks: list[CheckIn] = Field(default_factory=list, max_length=50)


# --- budget lines -----------------------------------------------------------------
LineKindName = Literal["fix", "valtozo", "celalap", "megtakaritas"]


class LineIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    owner_id: uuid.UUID | None = None
    kind: LineKindName = "valtozo"
    category_ids: list[uuid.UUID] = Field(default_factory=list, max_length=50)
    active: bool = True
    notes: str | None = None
    # In a Revolut pocket: its amount is a transfer, and what is left carries over (D25).
    pocket_id: uuid.UUID | None = None
    # A goal (D26).
    target_amount: Decimal | None = Field(default=None, gt=0)
    target_date: date | None = None
    is_wishlist: bool = False


class LineCreate(LineIn):
    # The amount to plan from `from_month` on; `from_month` defaults to the current period's.
    # Left out for a goal with a target and a date, it starts at the suggestion.
    amount: Decimal | None = Field(default=None, ge=0)
    from_month: date | None = None
    # Already in the pocket for this: moved out of the pocket's unassigned money today.
    saved_amount: Decimal | None = Field(default=None, gt=0)


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
    pocket_id: uuid.UUID | None = None
    target_amount: Decimal | None = None
    target_date: date | None = None
    is_wishlist: bool = False
    bought_on: date | None = None


class GoalBoughtIn(BaseModel):
    """The goal's thing was bought. What is left goes to another earmark, back to the main
    account, or - with neither - stays in the pocket unassigned."""

    move_to_line_id: uuid.UUID | None = None
    release: bool = False


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
    pocket_id: uuid.UUID | None = None
    target_amount: Decimal | None = None
    target_date: date | None = None
    # What a goal needs per month from the first month shown, to reach its target in time.
    suggestion: Decimal | None = None


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


class TransferOut(BaseModel):
    id: uuid.UUID
    pocket_id: uuid.UUID
    pocket_name: str
    holder_id: uuid.UUID | None
    line_id: uuid.UUID | None
    line_name: str | None
    amount: Decimal
    on: date
    kind: str
    done: bool
    from_user_id: uuid.UUID | None
    note: str | None


class MonthIssues(BaseModel):
    """What a meeting should look at before closing the period."""

    due: list[OccurrenceOut]
    uncategorised: list[PieceOut]
    maybe_shared: list[PieceOut]
    late: list[LateReceipt]
    # Spending in a pocket line's categories paid from the main account.
    maybe_pocket: list[PieceOut] = Field(default_factory=list)
    # Transfers the meeting planned that nobody ticked as sent yet.
    transfers: list[TransferOut] = Field(default_factory=list)


# --- pockets -----------------------------------------------------------------------------
class PocketIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    holder_id: uuid.UUID | None = None
    opening_balance: Decimal = Decimal("0")
    opened_on: date | None = None
    active: bool = True
    notes: str | None = None


class PocketOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    holder_id: uuid.UUID | None
    opening_balance: Decimal
    opened_on: date
    active: bool
    notes: str | None


class BucketOut(BaseModel):
    """One earmark of a pocket - or, with no line, the money no earmark claims."""

    line_id: uuid.UUID | None
    name: str
    owner_id: uuid.UUID | None
    kind: str | None
    is_wishlist: bool = False
    target_amount: Decimal | None = None
    target_date: date | None = None
    bought_on: date | None = None
    category_ids: list[uuid.UUID] = Field(default_factory=list)
    plan: Decimal
    opening: Decimal
    money_in: Decimal
    money_out: Decimal
    closing: Decimal
    suggestion: Decimal | None = None
    receipts: list[PieceOut] = Field(default_factory=list)


class PocketCheckOut(BaseModel):
    checked_on: date
    balance: Decimal
    expected: Decimal
    difference: Decimal


class PocketView(BaseModel):
    pocket: PocketOut
    opening: Decimal
    closing: Decimal
    buckets: list[BucketOut]
    check: PocketCheckOut | None = None


class PocketsOverview(BaseModel):
    users: list[PersonOut]
    start: date
    month: date
    pockets: list[PocketView]
    pending: list[TransferOut]


class ProposedTransferOut(BaseModel):
    line_id: uuid.UUID
    line_name: str
    pocket_id: uuid.UUID
    pocket_name: str
    holder_id: uuid.UUID | None
    from_user_id: uuid.UUID | None
    amount: Decimal


class ManualTransferIn(BaseModel):
    """An extra deposit (positive) or withdrawal (negative), by hand."""

    pocket_id: uuid.UUID
    line_id: uuid.UUID | None = None
    amount: Decimal
    on: date | None = None
    note: str | None = None


class MoveIn(BaseModel):
    pocket_id: uuid.UUID
    from_line_id: uuid.UUID | None = None
    to_line_id: uuid.UUID | None = None
    amount: Decimal = Field(gt=0)
    on: date | None = None
    note: str | None = None


class TransferDoneIn(BaseModel):
    done: bool = True


class PurchaseIn(BaseModel):
    """"Megvettük, nincs blokk": a goal or wishlist purchase typed in (D30)."""

    earmark_id: uuid.UUID | None = None
    wishlist_item_id: uuid.UUID | None = None
    name: str | None = Field(default=None, max_length=200)
    price: Decimal = Field(gt=0)
    on: date | None = None
    merchant_name: str | None = Field(default=None, max_length=300)
    category_id: uuid.UUID | None = None


# --- wishlist ------------------------------------------------------------------------------
class WishlistIn(BaseModel):
    owner_id: uuid.UUID | None = None
    name: str = Field(min_length=1, max_length=200)
    priority: int = Field(default=3, ge=1, le=5)
    estimated_price: Decimal | None = Field(default=None, ge=0)
    link: str | None = Field(default=None, max_length=500)
    note: str | None = None
    product_id: uuid.UUID | None = None


class WishlistOut(BaseModel):
    id: uuid.UUID
    owner_id: uuid.UUID | None
    name: str
    priority: int
    priority_label: str
    estimated_price: Decimal | None
    link: str | None
    note: str | None
    product_id: uuid.UUID | None
    product_name: str | None = None
    # On the shopping list and not yet ticked off there.
    on_list: bool = False
    bought_on: date | None
    actual_price: Decimal | None = None
    receipt_ids: list[uuid.UUID] = Field(default_factory=list)
    # The owner's wishlist pot, which a purchase of this draws from; null if none.
    earmark_id: uuid.UUID | None = None


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
    pockets: list[PocketView] = Field(default_factory=list)
    totals: MonthTotals
    meeting_due: bool
    receipt_count: int
