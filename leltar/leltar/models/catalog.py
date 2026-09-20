"""The category tree items are filed under."""

from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from leltar.models.base import Base, TimestampMixin, pk


class Category(Base, TimestampMixin):
    __tablename__ = "categories"

    id: Mapped[uuid.UUID] = pk()
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("categories.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # The slug is what the model is asked to choose from, and what the rules validate
    # against, so it is the stable identifier - the display name may be edited freely.
    slug: Mapped[str] = mapped_column(String(60), nullable=False, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    icon: Mapped[str | None] = mapped_column(String(8), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=100, nullable=False)

    parent: Mapped[Category | None] = relationship(remote_side="Category.id")
