"""Shelf labels: what a thing costs, without having bought it.

A price on a receipt is a purchase. A price on a shelf label is an *observation* - you saw
it, you did not pay it. The two answer different questions and must never be added
together, because a label that reached the spending statistics would inflate a month by
money that never left your account, and it would balance perfectly while doing so.

Hence a separate pair of tables rather than a flag on `receipts`. Nothing in this module is
reachable from the spending queries; only price history and the basket comparison read it,
and both label where a price came from.

One photograph usually carries several labels - a shelf strip is six products in one frame -
so the photo and the readings are separate rows, exactly as a receipt and its lines are.
"""

from __future__ import annotations

import enum
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import JSON, Date, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, money, pk
from app.models.catalog import Merchant, Product


class LabelStatus(enum.StrEnum):
    PENDING = "pending"            # photographed, waiting for the worker
    PROCESSING = "processing"
    PARSED = "parsed"              # read and self-consistent
    NEEDS_REVIEW = "needs_review"  # read, but something wants a human
    FAILED = "failed"
    CONFIRMED = "confirmed"        # you checked it


class PriceLabelPhoto(Base, TimestampMixin):
    """One photograph of one or more shelf labels."""

    __tablename__ = "price_label_photos"

    id: Mapped[uuid.UUID] = pk()

    image_path: Mapped[str] = mapped_column(String(500), nullable=False)
    image_sha256: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    image_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    image_mime: Mapped[str] = mapped_column(String(60), default="image/jpeg", nullable=False)

    # Which shop you were standing in. Most shelf labels do not name it, so this usually
    # comes from the app rather than from the photograph - you say "I am in Aldi" once and
    # it holds for the whole visit.
    merchant_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("merchants.id", ondelete="SET NULL"), nullable=True, index=True
    )
    merchant_raw_name: Mapped[str | None] = mapped_column(String(300), nullable=True)
    # When you saw the price, which is what dates the observation.
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )

    status: Mapped[str] = mapped_column(
        String(20), default=LabelStatus.PENDING.value, nullable=False, index=True
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    confidence: Mapped[float | None] = mapped_column(nullable=True)
    review_reasons: Mapped[list | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    parsed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    observations: Mapped[list[PriceObservation]] = relationship(
        back_populates="photo",
        cascade="all, delete-orphan",
        order_by="PriceObservation.line_no",
    )
    merchant: Mapped[Merchant | None] = relationship()


class PriceObservation(Base, TimestampMixin):
    """One shelf label: this product, at this shop, cost this much on this day."""

    __tablename__ = "price_observations"

    id: Mapped[uuid.UUID] = pk()
    photo_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("price_label_photos.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Reading order within the photograph, so a shelf strip keeps its left-to-right sense.
    line_no: Mapped[int] = mapped_column(Integer, nullable=False)

    raw_name: Mapped[str] = mapped_column(String(300), nullable=False)
    product_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("products.id", ondelete="SET NULL"), nullable=True, index=True
    )

    # What the label asks you to pay today.
    price: Mapped[Decimal | None] = money()
    # The egységár, which Hungarian law requires on the label: Ft per kg, litre or piece.
    # This is the number worth having - comparing shops on it needs no arithmetic and no
    # assumption about package size, which is exactly what a receipt forces you to guess.
    unit_price: Mapped[Decimal | None] = money()
    unit: Mapped[str | None] = mapped_column(String(10), nullable=True)  # kg / l / db

    package_size: Mapped[float | None] = mapped_column(nullable=True)
    package_unit: Mapped[str | None] = mapped_column(String(10), nullable=True)

    # An akciós ár is a real price and a temporary one. Kept apart from the regular price so
    # a shop that happened to be running a sale does not look permanently cheap.
    is_promotion: Mapped[bool] = mapped_column(default=False, nullable=False)
    regular_price: Mapped[Decimal | None] = money()
    promotion_until: Mapped[date | None] = mapped_column(Date, nullable=True)

    confidence: Mapped[float | None] = mapped_column(nullable=True)

    photo: Mapped[PriceLabelPhoto] = relationship(back_populates="observations")
    product: Mapped[Product | None] = relationship()
