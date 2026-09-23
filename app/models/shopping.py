"""The shopping list.

Two things make this different from the rest of the app. Everything else records what
already happened - a receipt, a price on a shelf - and has to be exactly right because it
feeds statistics. A shopping list is about the next half hour, and its only job is to be
recognisable to you while you stand in an aisle.

So an item does not have to resolve to anything. It can be a product you track, or a name
you typed, or simply a photograph of a thing you want more of - and the photograph is a
complete item on its own, not a placeholder waiting to become one. Recognition runs
afterwards and may attach a product, but the item is useful from the moment it exists.

Quantity is free text for the same reason. "2 db", "egy nagy", "amennyi kell" are all
perfectly good instructions to yourself, and none of them is arithmetic.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, pk
from app.models.catalog import Product


class ItemSource(enum.StrEnum):
    MANUAL = "manual"    # typed in
    PRODUCT = "product"  # added with the cart button from somewhere in the app
    SCAN = "scan"        # photographed


class ScanStatus(enum.StrEnum):
    """Only meaningful for a photographed item; everything else is `ready` from the start."""

    PENDING = "pending"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


class ShoppingItem(Base, TimestampMixin):
    __tablename__ = "shopping_items"

    id: Mapped[uuid.UUID] = pk()

    # Any of these three can carry the item on its own, and an item needs at least one.
    product_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("products.id", ondelete="SET NULL"), nullable=True, index=True
    )
    raw_name: Mapped[str | None] = mapped_column(String(300), nullable=True)
    image_path: Mapped[str | None] = mapped_column(String(500), nullable=True)

    image_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    image_mime: Mapped[str | None] = mapped_column(String(60), nullable=True)

    # Free text on purpose: "2 db", "egy nagy", "amennyi kell".
    quantity: Mapped[str | None] = mapped_column(String(60), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    source: Mapped[str] = mapped_column(
        String(10), default=ItemSource.MANUAL.value, nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(12), default=ScanStatus.READY.value, nullable=False, index=True
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    confidence: Mapped[float | None] = mapped_column(nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Ticked off rather than deleted: what you bought last week is the best guess at what
    # you will want next week, and a list you can see the history of is worth more than one
    # that forgets.
    done: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    done_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    product: Mapped[Product | None] = relationship()

    @property
    def label(self) -> str:
        """What to call this item when something has to print one line about it."""
        if self.product is not None:
            return self.product.canonical_name
        if self.raw_name:
            return self.raw_name
        return "Fotó"
