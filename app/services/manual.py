"""Receipts typed in by hand.

Two sources feed this: a receipt you lost but still remember, and a subscription that never
printed one. Both produce an ordinary `Receipt` row so that every statistic - monthly spend,
category breakdown, price history, basket comparison - counts them without knowing they were
not photographed.

A typed receipt is `confirmed`, not `parsed`. The review queue exists to catch a model
misreading a photograph; there is nothing to second-guess when you entered the numbers
yourself, and leaving them pending would put your own typing in a queue for your approval.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import LineKind, Receipt, ReceiptItem, ReceiptStatus
from app.services.catalog import resolve_merchant, resolve_product

log = logging.getLogger(__name__)

MAX_MANUAL_ITEMS = 100


class ManualEntryError(ValueError):
    """The entry does not describe a receipt we can store."""


def _money(value: Decimal | float | int) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"))


async def create_manual_receipt(
    session: AsyncSession,
    *,
    merchant_name: str,
    purchased_at: datetime,
    items: list[dict],
    total_gross: Decimal | float | int | None = None,
    payment_method: str = "card",
    currency: str = "HUF",
    notes: str | None = None,
    source: str = "manual",
) -> Receipt:
    """Store a receipt entered by hand, and return it.

    `items` are dicts of `raw_name`, `gross_amount`, and optionally `quantity`, `unit`,
    `unit_price`, `vat_rate`, `kind`, `category_id`. When `total_gross` is omitted it is the
    sum of the lines - the common case, where you remember what you bought rather than what
    the till printed.
    """
    merchant_name = (merchant_name or "").strip()
    if not merchant_name:
        raise ManualEntryError("A shop name is required.")
    if not items:
        raise ManualEntryError("Add at least one line.")
    if len(items) > MAX_MANUAL_ITEMS:
        raise ManualEntryError(f"That is {len(items)} lines; at most {MAX_MANUAL_ITEMS}.")

    if purchased_at.tzinfo is None:
        purchased_at = purchased_at.replace(tzinfo=UTC)
    if purchased_at > datetime.now(UTC).replace(hour=23, minute=59):
        raise ManualEntryError("That date is in the future.")

    lines: list[ReceiptItem] = []
    computed = Decimal("0.00")
    for index, raw in enumerate(items, start=1):
        name = str(raw.get("raw_name") or "").strip()
        if not name:
            raise ManualEntryError(f"Line {index} has no description.")

        amount = _money(raw.get("gross_amount") or 0)
        kind = str(raw.get("kind") or LineKind.ITEM.value)
        if kind not in {k.value for k in LineKind}:
            raise ManualEntryError(f"Line {index} has an unknown kind: {kind}.")
        # A discount reduces the total whichever sign was typed; being lenient here means a
        # hand entry does not silently double the spend because of a missing minus.
        if kind == LineKind.DISCOUNT.value:
            amount = -abs(amount)

        quantity = raw.get("quantity")
        unit_price = raw.get("unit_price")
        lines.append(
            ReceiptItem(
                line_no=index,
                raw_name=name[:300],
                quantity=_money(quantity) if quantity is not None else Decimal("1.00"),
                unit=(str(raw.get("unit")) if raw.get("unit") else "db")[:10],
                unit_price=_money(unit_price) if unit_price is not None else amount,
                gross_amount=amount,
                vat_rate=raw.get("vat_rate"),
                kind=kind,
                confidence=1.0,
                category_id=raw.get("category_id"),
            )
        )
        computed += amount

    total = _money(total_gross) if total_gross is not None else computed
    if total <= 0:
        raise ManualEntryError("The total must be more than zero.")

    merchant = await resolve_merchant(session, merchant_name)

    receipt = Receipt(
        id=uuid.uuid4(),
        image_path=None,
        image_sha256=None,
        source=source,
        merchant_id=merchant.id if merchant else None,
        merchant_raw_name=merchant_name[:300],
        purchased_at=purchased_at,
        total_gross=total,
        rounding=Decimal("0.00"),
        discount_total=sum(
            (-line.gross_amount for line in lines if line.kind == LineKind.DISCOUNT.value),
            Decimal("0.00"),
        ),
        currency=(currency or "HUF")[:3].upper(),
        payment_method=payment_method,
        # Typed in, so it is ground truth: it skips the review queue by design.
        status=ReceiptStatus.CONFIRMED.value,
        confidence=1.0,
        notes=notes,
        parsed_at=datetime.now(UTC),
        confirmed_at=datetime.now(UTC),
    )
    receipt.items = lines
    session.add(receipt)
    await session.flush()

    # Same lookup as a photographed receipt, so a typed "TEJ 2,8% 1L UHT" joins the product
    # it was already mapped to and extends that price history rather than starting a second
    # one. Unmapped lines stay unmapped here too - products are created deliberately in the
    # review screen, never guessed.
    for line in lines:
        if line.kind != LineKind.ITEM.value:
            continue
        product = await resolve_product(session, line.raw_name, receipt.merchant_id)
        if product is not None:
            line.product_id = product.id
            line.category_id = line.category_id or product.category_id

    log.info(
        "stored manual receipt %s (%s, %s, %d lines)",
        receipt.id, merchant_name, total, len(lines),
    )
    return receipt
