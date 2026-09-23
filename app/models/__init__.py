"""ORM models. Importing this package registers every table on `Base.metadata`."""

from app.models.base import Base
from app.models.catalog import Category, Merchant, MerchantAlias, Product, ProductAlias
from app.models.ops import Budget, Correction, ExtractionAttempt
from app.models.price import LabelStatus, PriceLabelPhoto, PriceObservation
from app.models.receipt import (
    LineKind,
    PaymentMethod,
    Receipt,
    ReceiptImage,
    ReceiptItem,
    ReceiptStatus,
)
from app.models.recurring import Cadence, RecurringCharge, RecurringPayment
from app.models.shopping import ItemSource, ScanStatus, ShoppingItem

__all__ = [
    "Base",
    "Budget",
    "Cadence",
    "Category",
    "Correction",
    "ExtractionAttempt",
    "ItemSource",
    "LabelStatus",
    "LineKind",
    "Merchant",
    "MerchantAlias",
    "PaymentMethod",
    "PriceLabelPhoto",
    "PriceObservation",
    "Product",
    "ProductAlias",
    "Receipt",
    "ReceiptImage",
    "ReceiptItem",
    "ReceiptStatus",
    "RecurringCharge",
    "RecurringPayment",
    "ScanStatus",
    "ShoppingItem",
]
