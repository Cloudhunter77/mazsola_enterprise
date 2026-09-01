"""Merchants, the category tree, and the canonical product catalogue.

The catalogue is what turns a wall of receipt lines into answers: `product_aliases` maps the
shorthand a till prints ("TEJ 2,8% 1L UHT") onto a canonical product, once, so every later
purchase of that thing lands on the same row and price history becomes possible.
"""

from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, pk


class Category(Base, TimestampMixin):
    __tablename__ = "categories"

    id: Mapped[uuid.UUID] = pk()
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("categories.id", ondelete="SET NULL"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    slug: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    color: Mapped[str | None] = mapped_column(String(9), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    parent: Mapped[Category | None] = relationship(remote_side=[id], back_populates="children")
    children: Mapped[list[Category]] = relationship(back_populates="parent")


class Merchant(Base, TimestampMixin):
    __tablename__ = "merchants"

    id: Mapped[uuid.UUID] = pk()
    name: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    slug: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    tax_number: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    default_category_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("categories.id", ondelete="SET NULL"), nullable=True
    )

    aliases: Mapped[list[MerchantAlias]] = relationship(
        back_populates="merchant", cascade="all, delete-orphan"
    )


class MerchantAlias(Base, TimestampMixin):
    """Raw merchant strings as printed, e.g. 'TESCO-GLOBAL ZRT. 2049 BUDAORS'."""

    __tablename__ = "merchant_aliases"
    __table_args__ = (UniqueConstraint("raw_name", name="uq_merchant_alias_raw_name"),)

    id: Mapped[uuid.UUID] = pk()
    merchant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    raw_name: Mapped[str] = mapped_column(String(300), nullable=False)

    merchant: Mapped[Merchant] = relationship(back_populates="aliases")


class Product(Base, TimestampMixin):
    """A canonical thing you buy, independent of which shop sold it."""

    __tablename__ = "products"

    id: Mapped[uuid.UUID] = pk()
    canonical_name: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    brand: Mapped[str | None] = mapped_column(String(120), nullable=True)
    category_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("categories.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # Package size, so 1.5 l and 0.5 l cola compare on price per litre rather than per bottle.
    package_size: Mapped[float | None] = mapped_column(nullable=True)
    package_unit: Mapped[str | None] = mapped_column(String(10), nullable=True)

    category: Mapped[Category | None] = relationship()
    aliases: Mapped[list[ProductAlias]] = relationship(
        back_populates="product", cascade="all, delete-orphan"
    )


class ProductAlias(Base, TimestampMixin):
    """(merchant, raw line text) -> product. Learned when you confirm a receipt."""

    __tablename__ = "product_aliases"
    __table_args__ = (
        UniqueConstraint("merchant_id", "raw_name", name="uq_product_alias_merchant_raw"),
    )

    id: Mapped[uuid.UUID] = pk()
    product_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # NULL merchant means "applies at any shop" - useful for branded goods.
    merchant_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("merchants.id", ondelete="CASCADE"), nullable=True, index=True
    )
    raw_name: Mapped[str] = mapped_column(String(300), nullable=False, index=True)

    product: Mapped[Product] = relationship(back_populates="aliases")
