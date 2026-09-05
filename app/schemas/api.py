"""Request and response bodies for the HTTP API."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --- auth --------------------------------------------------------------------
class LoginRequest(BaseModel):
    password: str


class SessionInfo(BaseModel):
    authenticated: bool
    subject: str | None = None


# --- receipts ----------------------------------------------------------------
class UploadResponse(BaseModel):
    id: uuid.UUID
    status: str
    duplicate: bool = Field(description="True when this exact photo was already uploaded.")


class ItemOut(ORMModel):
    id: uuid.UUID
    line_no: int
    raw_name: str
    quantity: Decimal | None
    unit: str | None
    unit_price: Decimal | None
    gross_amount: Decimal | None
    discount_amount: Decimal | None
    vat_rate: Decimal | None
    vat_code: str | None
    kind: str
    product_id: uuid.UUID | None
    category_id: uuid.UUID | None
    confidence: float | None


class ReceiptSummary(ORMModel):
    id: uuid.UUID
    status: str
    source: str
    purchased_at: datetime | None
    merchant_id: uuid.UUID | None
    merchant_name: str | None = None
    total_gross: Decimal | None
    currency: str
    review_reasons: list[str] | None
    confidence: float | None
    item_count: int = 0
    created_at: datetime


class ReceiptDetail(ReceiptSummary):
    merchant_raw_name: str | None
    tax_number: str | None
    total_net: Decimal | None
    total_vat: Decimal | None
    rounding: Decimal | None
    discount_total: Decimal | None
    payment_method: str
    receipt_no: str | None
    nav_ap_code: str | None
    notes: str | None
    error: str | None
    attempts: int
    parsed_at: datetime | None
    confirmed_at: datetime | None
    items: list[ItemOut] = []
    # How many photographs make up this receipt. 1 for everything captured in one frame,
    # which is nearly all of them; the review screen only shows a page switcher above that.
    pages: int = 1


class ReceiptPatch(BaseModel):
    """Every field is optional; only what you send is changed."""

    purchased_at: datetime | None = None
    merchant_name: str | None = None
    total_gross: Decimal | None = None
    payment_method: str | None = None
    rounding: Decimal | None = None
    discount_total: Decimal | None = None
    notes: str | None = None


class ItemPatch(BaseModel):
    raw_name: str | None = None
    quantity: Decimal | None = None
    unit: str | None = None
    unit_price: Decimal | None = None
    gross_amount: Decimal | None = None
    vat_rate: Decimal | None = None
    kind: str | None = None
    category_id: uuid.UUID | None = None
    product_id: uuid.UUID | None = None
    # When set with product_id, remember this mapping for every future receipt.
    remember_mapping: bool = False


# --- catalogue ---------------------------------------------------------------
class CategoryOut(ORMModel):
    id: uuid.UUID
    parent_id: uuid.UUID | None
    name: str
    slug: str
    color: str | None
    sort_order: int


class MerchantOut(ORMModel):
    id: uuid.UUID
    name: str
    slug: str
    tax_number: str | None


class ProductOut(ORMModel):
    id: uuid.UUID
    canonical_name: str
    brand: str | None
    category_id: uuid.UUID | None
    package_size: float | None
    package_unit: str | None


class ProductCreate(BaseModel):
    canonical_name: str
    brand: str | None = None
    category_id: uuid.UUID | None = None
    package_size: float | None = None
    package_unit: str | None = None


class BudgetIn(BaseModel):
    category_id: uuid.UUID | None = None
    month: date
    amount: Decimal


class BudgetOut(ORMModel):
    id: uuid.UUID
    category_id: uuid.UUID | None
    month: date
    amount: Decimal | None


# --- statistics --------------------------------------------------------------
class SpendSummary(BaseModel):
    total: Decimal
    receipt_count: int
    item_count: int
    average_basket: Decimal
    first_purchase: datetime | None
    last_purchase: datetime | None
    pending_review: int


class MonthlySpend(BaseModel):
    month: date
    total: Decimal
    receipt_count: int


class CategorySpend(BaseModel):
    category_id: uuid.UUID | None
    category_name: str
    total: Decimal
    share: float
    item_count: int


class MerchantSpend(BaseModel):
    merchant_id: uuid.UUID | None
    merchant_name: str
    total: Decimal
    receipt_count: int
    average_basket: Decimal


class PricePoint(BaseModel):
    purchased_at: datetime
    merchant_id: uuid.UUID | None
    merchant_name: str
    unit_price: Decimal
    quantity: Decimal | None
    unit: str | None
    receipt_id: uuid.UUID


class ProductPriceHistory(BaseModel):
    product_id: uuid.UUID
    product_name: str
    points: list[PricePoint]
    cheapest_merchant: str | None
    latest_price: Decimal | None
    change_pct: float | None = Field(
        default=None, description="Percent change from the first to the most recent purchase."
    )


class MerchantBasketPrice(BaseModel):
    merchant_id: uuid.UUID
    merchant_name: str
    covered_products: int
    basket_total: Decimal


class BasketComparison(BaseModel):
    """What your regular basket costs at each shop that sells all of it."""

    product_count: int
    merchants: list[MerchantBasketPrice]
    potential_saving: Decimal
    window_days: int = Field(
        default=90, description="Only prices seen this recently were compared."
    )


class InflationPoint(BaseModel):
    month: date
    index: float
    product_count: int


# --- costs -------------------------------------------------------------------
class CostByMonth(BaseModel):
    month: date
    model: str | None
    receipts: int
    total_usd: Decimal
    avg_usd: Decimal
    # The token counts are here so a surprising bill can be diagnosed rather than just
    # observed. A per-receipt cost far above the model's list price is almost always an
    # input-token count far above expectation - usually the image - and the only way to
    # tell that apart from simply having picked a dear model is to see both numbers.
    avg_input_tokens: int | None = None
    avg_output_tokens: int | None = None


class CostSummary(BaseModel):
    total_usd: Decimal
    receipts_extracted: int
    average_usd: Decimal
    projected_yearly_usd: Decimal
    by_month: list[CostByMonth]
    failures: int
