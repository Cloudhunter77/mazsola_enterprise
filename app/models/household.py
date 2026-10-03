"""The people who use the app, and who paid for what.

One household, several logins. Everyone sees the same receipts, lists and statistics -
splitting a bill with someone only makes sense if you can both see it - and what is
personal is who paid and who carries which share of a bill.

A share is a percentage of one receipt's total that one person carries. The person who
paid is owed every share but their own, and the balance between two people is the sum of
that over the receipts they split, less whatever they have already settled. Nothing here
is stored as a running total: a receipt corrected or re-split later simply changes the
answer next time it is computed, which a stored balance would silently get wrong.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, money, pk


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = pk()
    # Stored lowercased, so "Petra" and "petra" are one login.
    username: Mapped[str] = mapped_column(String(60), nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(String(80), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    # Admins can add and manage the other logins. Everything else is shared alike.
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Deactivated rather than deleted: receipts they paid for keep saying so.
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class ReceiptShare(Base):
    """One person's part of one receipt, as a percentage of its total."""

    __tablename__ = "receipt_shares"
    __table_args__ = (
        UniqueConstraint("receipt_id", "user_id", name="uq_receipt_shares_receipt_user"),
        CheckConstraint("percent >= 0 AND percent <= 100", name="ck_receipt_shares_percent"),
    )

    id: Mapped[uuid.UUID] = pk()
    receipt_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("receipts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    percent: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)


class Settlement(Base, TimestampMixin):
    """Money handed over to even things out - "Petra sent me 12 000 Ft"."""

    __tablename__ = "settlements"
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_settlements_positive"),
        CheckConstraint("from_user_id <> to_user_id", name="ck_settlements_two_people"),
    )

    id: Mapped[uuid.UUID] = pk()
    from_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    to_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    amount: Mapped[Decimal | None] = money(nullable=False)
    settled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
