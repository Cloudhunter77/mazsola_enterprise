"""Revolut pockets, the money moved into them, and the wishlist.

Money that is not for every day - savings, goals, hobbies, trips - lives in Revolut pockets,
so the app models a pocket as what it is: an account with a balance, held by one person.
Inside a pocket the money is *earmarked*: a goal (the sofa), a pocket-funded budget line
(Hobbi), the wishlist's savings. An earmark is a `BudgetLine` with `pocket_id` set, which is
what lets it be planned month by month in Terv like any other line. Money in a pocket that
no earmark claims is shown as "nincs hozzárendelve".

A balance is never stored. It is the opening balance, plus every transfer that actually
happened, minus every purchase paid from the pocket - recomputed each time, so a receipt
re-filed months later moves its forints to the right pocket. `PocketCheck` is the other
side: the balance Revolut actually showed on a day, so a difference can be noticed and
explained rather than silently drifting.

Amounts have no currency. A euro pocket is entered in euros and read as euros (D24).
"""

from __future__ import annotations

import enum
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, money, pk


class Pocket(Base, TimestampMixin):
    __tablename__ = "pockets"

    id: Mapped[uuid.UUID] = pk()
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    # Whose Revolut account the pocket is in. A Közös goal can live in either person's.
    holder_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # What it held on `opened_on`, the day the app starts keeping its books. Anything paid
    # from it before then is already inside this number.
    opening_balance: Mapped[Decimal | None] = money(nullable=False, default=Decimal("0.00"))
    opened_on: Mapped[date] = mapped_column(Date, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class TransferKind(enum.StrEnum):
    PLAN = "plan"        # the month's planned amount, from the meeting's checklist
    MANUAL = "manual"    # an extra deposit or withdrawal, by hand
    MOVE = "move"        # between two earmarks, or from unassigned money into one
    RELEASE = "release"  # a bought goal's leftover, back to the main account


class PocketTransfer(Base, TimestampMixin):
    """Money into (positive) or out of (negative) one earmark of one pocket.

    A move between earmarks is two rows sharing a `group_id`. A planned transfer exists
    from the meeting on, but counts only once `done`: until the money is actually sent in
    Revolut, the pocket does not have it.
    """

    __tablename__ = "pocket_transfers"

    id: Mapped[uuid.UUID] = pk()
    pocket_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pockets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # NULL: the pocket's unassigned money.
    line_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("budget_lines.id", ondelete="SET NULL"), nullable=True, index=True
    )
    amount: Mapped[Decimal | None] = money(nullable=False)
    on: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(10), default=TransferKind.MANUAL.value, nullable=False)
    done: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    done_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Who sends a planned transfer: each person sends their share of a Közös earmark.
    from_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    period_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("budget_periods.id", ondelete="SET NULL"), nullable=True, index=True
    )
    group_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)


class PocketCheck(Base, TimestampMixin):
    """What Revolut actually showed in a pocket on a day."""

    __tablename__ = "pocket_checks"

    id: Mapped[uuid.UUID] = pk()
    pocket_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pockets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    checked_on: Mapped[date] = mapped_column(Date, nullable=False)
    balance: Mapped[Decimal | None] = money(nullable=False)
    # Taken at this meeting: read off Revolut before that meeting's transfers were sent, so
    # it is compared with the balance without them.
    period_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("budget_periods.id", ondelete="SET NULL"), nullable=True
    )
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


PRIORITIES = {
    1: "Alacsony",
    2: "Alacsony-közepes",
    3: "Közepes",
    4: "Közép-magas",
    5: "Magas",
}


class WishlistItem(Base, TimestampMixin):
    """Something you mean to buy, not this week but some time.

    Bought when a real purchase is linked to it - a receipt line, or one typed in - which
    is also what records the actual price. Ticking it off on the shopping list does not
    count: that says it was picked up, not what it cost.
    """

    __tablename__ = "wishlist_items"

    id: Mapped[uuid.UUID] = pk()
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    estimated_price: Mapped[Decimal | None] = money()
    link: Mapped[str | None] = mapped_column(String(500), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    product_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("products.id", ondelete="SET NULL"), nullable=True
    )
    shopping_item_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("shopping_items.id", ondelete="SET NULL"), nullable=True
    )
    bought_on: Mapped[date | None] = mapped_column(Date, nullable=True)
