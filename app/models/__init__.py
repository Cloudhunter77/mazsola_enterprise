"""ORM models. Importing this package registers every table on `Base.metadata`."""

from app.models.base import Base
from app.models.catalog import Category, Merchant, MerchantAlias, Product, ProductAlias
from app.models.ops import Budget, Correction, ExtractionAttempt
from app.models.receipt import (
    LineKind,
    PaymentMethod,
    Receipt,
    ReceiptImage,
    ReceiptItem,
    ReceiptStatus,
)
from app.models.recurring import Cadence, RecurringCharge, RecurringPayment

__all__ = [
    "Base",
    "Budget",
    "Cadence",
    "Category",
    "Correction",
    "ExtractionAttempt",
    "LineKind",
    "Merchant",
    "MerchantAlias",
    "PaymentMethod",
    "Product",
    "ProductAlias",
    "RecurringCharge",
    "RecurringPayment",
    "Receipt",
    "ReceiptImage",
    "ReceiptItem",
    "ReceiptStatus",
]
