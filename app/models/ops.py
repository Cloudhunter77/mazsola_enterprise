"""Operational tables: what each extraction cost, what you corrected, what you budgeted."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import JSON, Date, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, money, pk


class ExtractionAttempt(Base, TimestampMixin):
    """One call to an extraction engine. This is the evidence behind the Costs page."""

    __tablename__ = "extraction_attempts"

    id: Mapped[uuid.UUID] = pk()
    receipt_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("receipts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    extractor: Mapped[str] = mapped_column(String(20), nullable=False)
    model: Mapped[str | None] = mapped_column(String(80), nullable=True)
    succeeded: Mapped[bool] = mapped_column(default=False, nullable=False)

    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cache_read_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cache_write_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Six decimal places: a single receipt costs cents, and the monthly roll-up must not
    # accumulate rounding error.
    cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 6), nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_response: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class Correction(Base, TimestampMixin):
    """Every field you fix by hand. The raw material for improving the prompt later."""

    __tablename__ = "corrections"

    id: Mapped[uuid.UUID] = pk()
    receipt_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("receipts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    item_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("receipt_items.id", ondelete="CASCADE"), nullable=True, index=True
    )
    field: Mapped[str] = mapped_column(String(60), nullable=False)
    old_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    new_value: Mapped[str | None] = mapped_column(Text, nullable=True)


class Budget(Base, TimestampMixin):
    """Monthly cap. NULL category means the whole month's spend."""

    __tablename__ = "budgets"
    __table_args__ = (UniqueConstraint("category_id", "month", name="uq_budget_category_month"),)

    id: Mapped[uuid.UUID] = pk()
    category_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("categories.id", ondelete="CASCADE"), nullable=True, index=True
    )
    month: Mapped[date] = mapped_column(Date, nullable=False, index=True)  # first day of month
    amount: Mapped[Decimal | None] = money(nullable=False)
