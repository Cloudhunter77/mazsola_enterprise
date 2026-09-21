"""Request and response bodies for the HTTP API.

Separate from the ORM models on purpose: what the database stores and what the app hands
to a browser are allowed to differ, and a response model is also the list of fields a
client may rely on.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from leltar.schemas.identification import Condition


class SessionInfo(BaseModel):
    authenticated: bool
    subject: str | None = None


class LoginRequest(BaseModel):
    password: str


# --- upload ------------------------------------------------------------------
class UploadedPhoto(BaseModel):
    id: uuid.UUID
    status: str
    duplicate: bool


class UploadResponse(BaseModel):
    photos: list[UploadedPhoto]
    queued: int
    duplicates: int


# --- places ------------------------------------------------------------------
class PlaceIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    kind: str = "room"
    parent_id: uuid.UUID | None = None
    sort_order: int = 100
    notes: str | None = None


class PlacePatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    kind: str | None = None
    # A `PATCH` that omits `parent_id` must not move the place to the root, so "no change"
    # and "move to the top level" cannot both be None here. `unset` is the sentinel for
    # the first, and the router reads `model_fields_set` to tell them apart.
    parent_id: uuid.UUID | None = None
    sort_order: int | None = None
    notes: str | None = None


class PlaceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    parent_id: uuid.UUID | None
    name: str
    kind: str
    sort_order: int
    notes: str | None
    path: str = ""
    item_count: int = 0


class ItemImageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    item_id: uuid.UUID
    kind: str
    source_photo_id: uuid.UUID | None
    box: dict | None
    width: int | None
    height: int | None
    is_primary: bool
    created_at: datetime


class CategoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    slug: str
    name: str
    icon: str | None
    sort_order: int


# --- items -------------------------------------------------------------------
class ItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    photo_id: uuid.UUID | None
    place_id: uuid.UUID | None
    category_id: uuid.UUID | None
    name: str
    suggested_name: str | None
    brand: str | None
    product_model: str | None
    colour: str | None
    material: str | None
    condition: str
    quantity: int
    serial_number: str | None
    description: str | None
    value: Decimal | None
    currency: str
    acquired_on: date | None
    status: str
    source: str
    edited: bool
    confidence: float | None
    review_reasons: list[str] | None
    alternatives: list[str] | None
    notes: str | None
    confirmed_at: datetime | None
    created_at: datetime

    # Filled in by the router: a client showing a list of items should not have to fetch
    # the place tree and the category list to render a single row.
    place_path: str | None = None
    category_name: str | None = None
    # How many pictures this item has. A list renders `/api/items/{id}/image` only when
    # this is non-zero, so a missing picture is a layout decision rather than a broken
    # image icon on every row.
    image_count: int = 0


class ItemPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    place_id: uuid.UUID | None = None
    category_id: uuid.UUID | None = None
    brand: str | None = None
    product_model: str | None = None
    colour: str | None = None
    material: str | None = None
    condition: Condition | None = None
    quantity: int | None = Field(default=None, ge=1, le=999)
    serial_number: str | None = None
    description: str | None = None
    value: Decimal | None = None
    acquired_on: date | None = None
    notes: str | None = None
    status: str | None = None


class ItemIn(BaseModel):
    """Something typed in rather than photographed."""

    name: str = Field(min_length=1, max_length=200)
    place_id: uuid.UUID | None = None
    category_id: uuid.UUID | None = None
    brand: str | None = None
    product_model: str | None = None
    colour: str | None = None
    material: str | None = None
    condition: Condition = "unknown"
    quantity: int = Field(default=1, ge=1, le=999)
    serial_number: str | None = None
    description: str | None = None
    value: Decimal | None = None
    acquired_on: date | None = None
    notes: str | None = None


# --- photos ------------------------------------------------------------------
class PhotoSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    status: str
    source: str
    mode: str
    place_id: uuid.UUID | None
    taken_at: datetime | None
    scene: str | None
    confidence: float | None
    review_reasons: list[str] | None
    error: str | None
    attempts: int
    created_at: datetime

    place_path: str | None = None
    item_count: int = 0
    draft_count: int = 0


class PhotoDetail(PhotoSummary):
    notes: str | None = None
    items: list[ItemOut] = Field(default_factory=list)


# --- statistics --------------------------------------------------------------
class StatsSummary(BaseModel):
    items: int
    copies: int
    places_used: int
    categories_used: int
    with_picture: int
    drafts: int
    photos: int
    photos_pending: int
    photos_needing_review: int
    photos_failed: int
    last_added: datetime | None


class PlaceStat(BaseModel):
    place_id: uuid.UUID | None
    place_path: str
    items: int
    copies: int
    share: float


class CategoryStat(BaseModel):
    category_id: uuid.UUID | None
    category_name: str
    icon: str | None
    items: int
    copies: int
    share: float


class AccuracyStat(BaseModel):
    confirmed_from_photos: int
    kept_as_suggested: int
    edited: int
    keep_rate: float | None
    mean_confidence: float | None


class CostMonth(BaseModel):
    month: datetime
    model: str | None
    calls: int
    total_usd: Decimal
    items_found: int


class CostSummary(BaseModel):
    total_usd: Decimal
    calls: int
    failures: int
    items_found: int
    confirmed_items: int
    usd_per_photo: Decimal
    usd_per_confirmed_item: Decimal | None
    mean_latency_ms: int | None
    by_month: list[CostMonth]
