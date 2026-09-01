"""Declarative base and shared column helpers."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Numeric, Uuid, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """All ORM models inherit from this."""


def pk() -> Mapped[uuid.UUID]:
    return mapped_column(Uuid, primary_key=True, default=uuid.uuid4)


def money(nullable: bool = True, default: Decimal | None = None) -> Mapped[Decimal | None]:
    """Money is Numeric(12, 2) everywhere. Never float: HUF totals must round-trip exactly."""
    return mapped_column(Numeric(12, 2), nullable=nullable, default=default)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
