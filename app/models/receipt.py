"""Receipts and their line items."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    JSON,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, money, pk

if TYPE_CHECKING:
    from app.models.catalog import Merchant, Product


class ReceiptStatus(enum.StrEnum):
    PENDING = "pending"            # uploaded, waiting for the worker
    PROCESSING = "processing"      # extraction in flight
    PARSED = "parsed"              # extracted and self-consistent
    NEEDS_REVIEW = "needs_review"  # extracted but validation flagged something
    FAILED = "failed"              # extraction errored out past max attempts
    CONFIRMED = "confirmed"        # you checked it; counts as ground truth


class PaymentMethod(enum.StrEnum):
    CASH = "cash"
    CARD = "card"
    OTHER = "other"
    UNKNOWN = "unknown"


class LineKind(enum.StrEnum):
    """Not every printed line is a thing you bought."""

    ITEM = "item"
    DEPOSIT = "deposit"    # betétdíj - refundable bottle deposit
    DISCOUNT = "discount"  # kedvezmény / akció line reducing the total
    ROUNDING = "rounding"  # kerekítés - cash rounding to the nearest 5 Ft
    FEE = "fee"            # bag charge, service fee


class Receipt(Base, TimestampMixin):
    __tablename__ = "receipts"

    id: Mapped[uuid.UUID] = pk()

    # --- image ---------------------------------------------------------------
    # Null for a receipt that was typed in rather than photographed - a lost receipt you
    # still remember, or a subscription that never printed one. Postgres allows any number
    # of NULLs under a unique index, so those rows do not collide with each other.
    image_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    image_sha256: Mapped[str | None] = mapped_column(
        String(64), nullable=True, unique=True, index=True
    )
    image_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    image_mime: Mapped[str] = mapped_column(String(60), default="image/jpeg", nullable=False)
    # web | shortcut | folder | manual (typed in) | recurring (generated from a subscription)
    source: Mapped[str] = mapped_column(String(20), default="web", nullable=False)

    # --- extracted header ----------------------------------------------------
    merchant_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("merchants.id", ondelete="SET NULL"), nullable=True, index=True
    )
    merchant_raw_name: Mapped[str | None] = mapped_column(String(300), nullable=True)
    tax_number: Mapped[str | None] = mapped_column(String(20), nullable=True)
    purchased_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )

    total_gross: Mapped[Decimal | None] = money()
    total_net: Mapped[Decimal | None] = money()
    total_vat: Mapped[Decimal | None] = money()
    rounding: Mapped[Decimal | None] = money(default=Decimal("0.00"))
    discount_total: Mapped[Decimal | None] = money(default=Decimal("0.00"))
    currency: Mapped[str] = mapped_column(String(3), default="HUF", nullable=False)

    payment_method: Mapped[str] = mapped_column(
        String(10), default=PaymentMethod.UNKNOWN.value, nullable=False
    )
    receipt_no: Mapped[str | None] = mapped_column(String(60), nullable=True)
    nav_ap_code: Mapped[str | None] = mapped_column(String(40), nullable=True)

    # --- pipeline state ------------------------------------------------------
    status: Mapped[str] = mapped_column(
        String(20), default=ReceiptStatus.PENDING.value, nullable=False, index=True
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Why the receipt needs a human: ["items_total_mismatch", "vat_mismatch", ...]
    review_reasons: Mapped[list | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    parsed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    items: Mapped[list[ReceiptItem]] = relationship(
        back_populates="receipt",
        cascade="all, delete-orphan",
        order_by="ReceiptItem.line_no",
    )
    images: Mapped[list[ReceiptImage]] = relationship(
        back_populates="receipt",
        cascade="all, delete-orphan",
        order_by="ReceiptImage.part_no",
    )
    merchant: Mapped[Merchant | None] = relationship()  # noqa: F821


class ReceiptImage(Base, TimestampMixin):
    """One photograph. A long receipt needs several to stay legible.

    Photographing a 60 cm Lidl receipt in one frame makes the small print unreadable at any
    sane downscale, so a receipt may be captured in overlapping parts and read as a single
    document. Part 0 is also mirrored into the `receipts.image_*` columns: everything that
    predates this table - the review screen, the image endpoint, deletion - keeps working
    unchanged, and a single-photo receipt behaves exactly as it always did.
    """

    __tablename__ = "receipt_images"

    id: Mapped[uuid.UUID] = pk()
    receipt_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("receipts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Reading order, not upload order: part 0 is the top of the receipt.
    part_no: Mapped[int] = mapped_column(Integer, nullable=False)

    path: Mapped[str] = mapped_column(String(500), nullable=False)
    # Unique across every part of every receipt, so re-uploading one page of a receipt you
    # already have is caught the same way a duplicate whole receipt is.
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    mime: Mapped[str] = mapped_column(String(60), default="image/jpeg", nullable=False)

    receipt: Mapped[Receipt] = relationship(back_populates="images")

    __table_args__ = (UniqueConstraint("receipt_id", "part_no", name="uq_receipt_images_part"),)


class ReceiptItem(Base, TimestampMixin):
    __tablename__ = "receipt_items"

    id: Mapped[uuid.UUID] = pk()
    receipt_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("receipts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    line_no: Mapped[int] = mapped_column(Integer, nullable=False)

    raw_name: Mapped[str] = mapped_column(String(300), nullable=False)
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(10, 3), nullable=True)
    unit: Mapped[str | None] = mapped_column(String(10), nullable=True)  # db, kg, l, csomag
    unit_price: Mapped[Decimal | None] = money()
    gross_amount: Mapped[Decimal | None] = money()
    discount_amount: Mapped[Decimal | None] = money(default=Decimal("0.00"))

    vat_rate: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    vat_code: Mapped[str | None] = mapped_column(String(4), nullable=True)  # A / B / C / AM

    kind: Mapped[str] = mapped_column(String(12), default=LineKind.ITEM.value, nullable=False)

    product_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("products.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # Denormalised from the product so category stats stay one join shallower, and so a
    # one-off line can be categorised without inventing a product for it.
    category_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("categories.id", ondelete="SET NULL"), nullable=True, index=True
    )
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)

    receipt: Mapped[Receipt] = relationship(back_populates="items")
    product: Mapped[Product | None] = relationship()  # noqa: F821
