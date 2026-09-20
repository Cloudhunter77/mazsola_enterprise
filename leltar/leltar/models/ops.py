"""What each identification cost, successful or not."""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import Boolean, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from leltar.models.base import Base, TimestampMixin, pk


class IdentificationAttempt(Base, TimestampMixin):
    __tablename__ = "identification_attempts"

    id: Mapped[uuid.UUID] = pk()
    # Kept when the photo is deleted: the money was still spent, and a costs page that
    # quietly shrinks when you tidy up is worse than no costs page.
    photo_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("photos.id", ondelete="SET NULL"), nullable=True, index=True
    )
    engine: Mapped[str] = mapped_column(String(20), nullable=False)
    model: Mapped[str | None] = mapped_column(String(80), nullable=True)

    ok: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cache_read_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cache_write_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Six decimal places: one photograph costs a fraction of a cent, and rounding it to
    # two would record every identification as zero.
    cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 6), nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    items_found: Mapped[int | None] = mapped_column(Integer, nullable=True)
