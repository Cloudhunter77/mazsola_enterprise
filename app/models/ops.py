"""Operational tables: what each extraction cost, what you corrected, what you budgeted."""

from __future__ import annotations

import enum
import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import JSON, Date, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, money, pk


class AttemptKind(enum.StrEnum):
    """What the engine was asked to read. Three documents, three different bills."""

    RECEIPT = "receipt"
    PRICE_LABEL = "price_label"
    PRODUCT_PHOTO = "product_photo"


class ExtractionAttempt(Base, TimestampMixin):
    """One call to an extraction engine. This is the evidence behind the Costs page.

    Three kinds of document now go to the model and each costs differently: a receipt is a
    long read with a long answer, a shelf strip is a short read with several answers, a
    product photograph is short both ways. Totalling them tells you what the app costs;
    only separating them tells you *which habit* costs, which is the question worth being
    able to answer before changing anything.

    Exactly one of the three subject columns is set. They are real foreign keys rather than
    one loose id with a `kind` beside it, so deleting a receipt or a shelf photo takes its
    attempts with it and nothing is left pointing at a row that no longer exists.
    """

    __tablename__ = "extraction_attempts"

    id: Mapped[uuid.UUID] = pk()
    kind: Mapped[str] = mapped_column(
        String(16), default=AttemptKind.RECEIPT.value, nullable=False, index=True
    )
    receipt_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("receipts.id", ondelete="CASCADE"), nullable=True, index=True
    )
    price_label_photo_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("price_label_photos.id", ondelete="CASCADE"), nullable=True, index=True
    )
    shopping_item_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("shopping_items.id", ondelete="CASCADE"), nullable=True, index=True
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
