"""ORM models. Importing this package registers every table on `Base.metadata`."""

from app.models.base import Base
from app.models.catalog import Category, Merchant, MerchantAlias, Product, ProductAlias
from app.models.ops import Budget, Correction, ExtractionAttempt
from app.models.receipt import LineKind, PaymentMethod, Receipt, ReceiptItem, ReceiptStatus

__all__ = [
    "Base",
    "Budget",
    "Category",
    "Correction",
    "ExtractionAttempt",
    "LineKind",
    "Merchant",
    "MerchantAlias",
    "PaymentMethod",
    "Product",
    "ProductAlias",
    "Receipt",
    "ReceiptItem",
    "ReceiptStatus",
]
