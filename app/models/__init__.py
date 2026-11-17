"""ORM models. Importing this package registers every table on `Base.metadata`."""

from app.models.base import Base
from app.models.budget import (
    Budget,
    BudgetLine,
    BudgetLineCategory,
    BudgetLineKind,
    BudgetPeriod,
    IncomeEntry,
)
from app.models.catalog import Category, Merchant, MerchantAlias, Product, ProductAlias
from app.models.feedback import FixNote
from app.models.household import ReceiptShare, Settlement, User
from app.models.ops import AttemptKind, Correction, ExtractionAttempt
from app.models.pockets import (
    PRIORITIES,
    Pocket,
    PocketCheck,
    PocketTransfer,
    TransferKind,
    WishlistItem,
)
from app.models.price import LabelStatus, PriceLabelPhoto, PriceObservation
from app.models.receipt import (
    LineKind,
    PaymentMethod,
    Receipt,
    ReceiptImage,
    ReceiptItem,
    ReceiptStatus,
)
from app.models.recurring import (
    AmountMode,
    Cadence,
    Direction,
    RecurringCharge,
    RecurringPayment,
)
from app.models.shopping import ItemSource, ScanStatus, ShoppingItem

__all__ = [
    "AmountMode",
    "AttemptKind",
    "Base",
    "Budget",
    "BudgetLine",
    "BudgetLineCategory",
    "BudgetLineKind",
    "BudgetPeriod",
    "Cadence",
    "Category",
    "Correction",
    "Direction",
    "ExtractionAttempt",
    "FixNote",
    "IncomeEntry",
    "ItemSource",
    "LabelStatus",
    "LineKind",
    "Merchant",
    "MerchantAlias",
    "PRIORITIES",
    "PaymentMethod",
    "Pocket",
    "PocketCheck",
    "PocketTransfer",
    "PriceLabelPhoto",
    "PriceObservation",
    "Product",
    "ProductAlias",
    "Receipt",
    "ReceiptImage",
    "ReceiptItem",
    "ReceiptShare",
    "ReceiptStatus",
    "RecurringCharge",
    "RecurringPayment",
    "ScanStatus",
    "Settlement",
    "ShoppingItem",
    "TransferKind",
    "WishlistItem",
    "User",
]
