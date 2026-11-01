"""Notes about what to change in the app itself, kept in the app.

Things that need fixing turn up while you are using it - a misread total, a button in the
wrong place - and that is exactly when a separate notes app is not to hand. So they are
written here, with a screenshot if one says it better than words, and ticked off once
done. Kept rather than deleted when done, so "did we ever fix that?" has an answer.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, pk


class FixNote(Base, TimestampMixin):
    __tablename__ = "fix_notes"

    id: Mapped[uuid.UUID] = pk()
    text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    image_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    image_mime: Mapped[str | None] = mapped_column(String(60), nullable=True)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    done: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    done_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
