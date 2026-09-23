"""API shapes for the shopping list."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class ShoppingItemOut(BaseModel):
    id: uuid.UUID
    product_id: uuid.UUID | None = None
    product_name: str | None = None
    raw_name: str | None = None
    # What to print for this item: the product's name, else what was read or typed, else a
    # word saying it is a photograph. Resolved server-side so every screen agrees.
    label: str
    has_photo: bool = False
    quantity: str | None = None
    note: str | None = None
    source: str
    status: str
    confidence: float | None = None
    error: str | None = None
    done: bool = False
    done_at: datetime | None = None
    created_at: datetime


class AddItemIn(BaseModel):
    product_id: uuid.UUID | None = None
    raw_name: str | None = Field(None, max_length=300)
    quantity: str | None = Field(None, max_length=60)
    note: str | None = None


class UpdateItemIn(BaseModel):
    """Every field optional: a patch says what changed."""

    product_id: uuid.UUID | None = None
    raw_name: str | None = Field(None, max_length=300)
    quantity: str | None = Field(None, max_length=60)
    note: str | None = None
    done: bool | None = None


class ShoppingSuggestion(BaseModel):
    product_id: uuid.UUID
    canonical_name: str
