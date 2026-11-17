"""Planning money ahead: periods, budget lines, their monthly amounts, and income.

Everything else in the app records what already happened. This is the other half - what you
meant to happen - and the screens under Pénz put the two side by side.

A *period* runs from one monthly meeting to the next, not by the calendar: the two of you sit
down early in the month, look back at the period just ending and plan the next one, and that
conversation is the boundary. A period is named after the month it plans ("November"), and
everything dated inside it - receipts, income - belongs to it by date. Only the start is
stored; a period ends where the next one starts, so the periods can never overlap or leave a
gap between them.

A *budget line* is one row of the plan: a name, whose it is (Közös or one person), a tag
(Fix / Változó / Célalap / Megtakarítás) and the categories it covers. Its amount is stored
only for the months where it changes - as in the spreadsheet this replaces, an amount carries
forward until you change it - in the `budgets` table that existed, unused, before any of this.
"""

from __future__ import annotations

import enum
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, money, pk


class BudgetLineKind(enum.StrEnum):
    """The tag the spreadsheet called "Csoport"."""

    FIX = "fix"                    # the same every month: rent, insurance
    VARIABLE = "valtozo"           # groceries, eating out - the ones you steer
    GOAL = "celalap"               # saving towards one thing
    SAVINGS = "megtakaritas"       # setting money aside with no particular aim


# Spending is matched to these by category. The other two are money put aside, which no
# receipt ever represents, so they are planned but have no "actual" to compare against.
SPENDING_KINDS = (BudgetLineKind.FIX.value, BudgetLineKind.VARIABLE.value)


class BudgetPeriod(Base, TimestampMixin):
    """From one monthly meeting to the next."""

    __tablename__ = "budget_periods"
    __table_args__ = (
        UniqueConstraint("month", name="uq_budget_periods_month"),
        UniqueConstraint("starts_on", name="uq_budget_periods_starts_on"),
    )

    id: Mapped[uuid.UUID] = pk()
    # The month this period plans, as its first day: a meeting on 2 November opens
    # "November". Unique: two periods planning the same month would make the plan ambiguous.
    month: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    # The day of the meeting that opened it. It ends where the next period starts.
    starts_on: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    # Set by the meeting that ends it. A closed period's plan is frozen; it can be reopened
    # to fix something, which clears this again.
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    opened_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class BudgetLine(Base, TimestampMixin):
    """One row of the plan."""

    __tablename__ = "budget_lines"

    id: Mapped[uuid.UUID] = pk()
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    # Whose line this is. NULL is Közös: the household's shared spending.
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )
    kind: Mapped[str] = mapped_column(
        String(14), default=BudgetLineKind.VARIABLE.value, nullable=False
    )
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # Archived rather than deleted once a closed period has planned with it, so the plan of
    # a month already discussed does not change after the fact.
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    categories: Mapped[list[BudgetLineCategory]] = relationship(
        back_populates="line", cascade="all, delete-orphan", lazy="selectin"
    )

    @property
    def category_ids(self) -> list[uuid.UUID]:
        return [link.category_id for link in self.categories]


class BudgetLineCategory(Base):
    """A category a line covers - and through it, every subcategory below it."""

    __tablename__ = "budget_line_categories"
    __table_args__ = (
        UniqueConstraint("line_id", "category_id", name="uq_budget_line_categories"),
    )

    id: Mapped[uuid.UUID] = pk()
    line_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("budget_lines.id", ondelete="CASCADE"), nullable=False, index=True
    )
    category_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("categories.id", ondelete="CASCADE"), nullable=False, index=True
    )

    line: Mapped[BudgetLine] = relationship(back_populates="categories")


class Budget(Base, TimestampMixin):
    """A line's planned amount from `month` on, until a later row changes it.

    The table predates budget lines: it was a monthly cap per category that nothing used.
    Its rows were moved onto lines by the migration that added them.
    """

    __tablename__ = "budgets"
    __table_args__ = (UniqueConstraint("line_id", "month", name="uq_budgets_line_month"),)

    id: Mapped[uuid.UUID] = pk()
    # Superseded by `line_id` and never written any more. Still declared because it still
    # exists - a migration here never drops a column - and a model that disagrees with the
    # database about a foreign key gets the order of a schema teardown wrong.
    category_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("categories.id", ondelete="CASCADE"), nullable=True, index=True
    )
    line_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("budget_lines.id", ondelete="CASCADE"), nullable=False, index=True
    )
    month: Mapped[date] = mapped_column(Date, nullable=False, index=True)  # first day of month
    amount: Mapped[Decimal | None] = money(nullable=False)


class IncomeEntry(Base, TimestampMixin):
    """Money that came in: a salary that arrived, a bonus, a refund.

    Income is never a receipt. It does not belong in the spending statistics, and a salary
    counted as negative spending would make every chart lie.
    """

    __tablename__ = "income_entries"
    __table_args__ = (CheckConstraint("amount > 0", name="ck_income_entries_positive"),)

    id: Mapped[uuid.UUID] = pk()
    # Whose income it is. NULL is Közös - money that belongs to the household as a whole.
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    amount: Mapped[Decimal | None] = money(nullable=False)
    received_on: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    # Set when it was the confirmation of an expected salary from Rendszeres.
    recurring_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("recurring_payments.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
