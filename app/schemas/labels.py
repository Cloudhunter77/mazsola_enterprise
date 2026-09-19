"""API shapes for shelf labels."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class LabelUploadResponse(BaseModel):
    id: uuid.UUID
    status: str
    duplicate: bool = False


class ObservationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    line_no: int
    raw_name: str
    product_id: uuid.UUID | None = None
    product_name: str | None = None
    price: Decimal | None = None
    unit_price: Decimal | None = None
    unit: str | None = None
    package_size: float | None = None
    package_unit: str | None = None
    is_promotion: bool = False
    regular_price: Decimal | None = None
    promotion_until: date | None = None
    confidence: float | None = None


class ObservationPatch(BaseModel):
    """Every field optional: a patch says what changed, not what the row should become."""

    raw_name: str | None = Field(None, max_length=300)
    product_id: uuid.UUID | None = None
    price: Decimal | None = None
    unit_price: Decimal | None = None
    unit: str | None = Field(None, max_length=10)
    package_size: float | None = None
    package_unit: str | None = Field(None, max_length=10)
    is_promotion: bool | None = None
    regular_price: Decimal | None = None
    promotion_until: date | None = None


class LabelPhotoSummary(BaseModel):
    id: uuid.UUID
    status: str
    observed_at: datetime
    merchant_name: str | None = None
    observation_count: int = 0
    review_reasons: list[str] = Field(default_factory=list)
    error: str | None = None


class LabelPhotoDetail(BaseModel):
    id: uuid.UUID
    status: str
    observed_at: datetime
    merchant_name: str | None = None
    review_reasons: list[str] = Field(default_factory=list)
    error: str | None = None
    notes: str | None = None
    confidence: float | None = None
    observations: list[ObservationOut] = Field(default_factory=list)
