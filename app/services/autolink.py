"""Linking receipt lines that were stored before the product existed.

Recognising `PEPSI 1500ML` as the `Pepsi 1,5 l` you already mapped happens on the way in,
in `resolve_product`. That only ever helps the *next* receipt. The lines already in the
database were stored when no such alias existed, and nothing would ever go back and look at
them again - so a year of shopping stays unmapped while every new receipt lands correctly,
and the price history you built the app for starts from today rather than from your data.

This pass closes that gap. It is deliberately the most conservative one available: only an
exact normalised match, the same rule that links itself during ingest, and the same
ambiguity guard. Anything less certain stays on the suggestions screen for you to confirm,
because a wrong link is silent - it merges two products' price histories and nothing on any
screen looks broken.

Nothing here deletes or overwrites: it fills in `product_id` where it is NULL and leaves
every line that already has one alone.
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import LineKind, Receipt, ReceiptItem, ReceiptStatus
from app.services.catalog import resolve_product

log = logging.getLogger(__name__)

# A line only counts once its receipt has a reading worth trusting.
READY_FOR_STATS = (
    ReceiptStatus.PARSED.value,
    ReceiptStatus.NEEDS_REVIEW.value,
    ReceiptStatus.CONFIRMED.value,
)

# One pass is bounded so the hourly tick cannot turn into a long transaction on a big
# database. Whatever is left is picked up an hour later, or by the button.
MAX_NAMES_PER_PASS = 400


async def autolink_stored(session: AsyncSession, limit: int = MAX_NAMES_PER_PASS) -> int:
    """Map unmapped stored lines onto products they letter-for-letter match.

    Returns how many line rows were linked. Idempotent: a second run finds nothing, because
    the lines it linked no longer have a NULL `product_id`.
    """
    pairs = (
        await session.execute(
            select(ReceiptItem.raw_name, Receipt.merchant_id, func.count(ReceiptItem.id))
            .join(Receipt, Receipt.id == ReceiptItem.receipt_id)
            .where(ReceiptItem.product_id.is_(None))
            .where(ReceiptItem.kind == LineKind.ITEM.value)
            .where(Receipt.status.in_(READY_FOR_STATS))
            .group_by(ReceiptItem.raw_name, Receipt.merchant_id)
            # The spellings you buy most are the ones worth the budget of a bounded pass.
            .order_by(func.count(ReceiptItem.id).desc())
            .limit(limit)
        )
    ).all()

    linked = 0
    for raw_name, merchant_id, _ in pairs:
        # The same call ingest makes, so a line can never be linked here by a rule that
        # would not have linked it on arrival.
        product = await resolve_product(session, raw_name, merchant_id)
        if product is None:
            continue
        linked += await _apply(session, raw_name, merchant_id, product.id, product.category_id)

    if linked:
        log.info("auto-linked %d stored receipt lines", linked)
    return linked


async def _apply(
    session: AsyncSession,
    raw_name: str,
    merchant_id: uuid.UUID | None,
    product_id: uuid.UUID,
    category_id: uuid.UUID | None,
) -> int:
    """Fill in the product on every stored line with this spelling at this shop."""
    receipts = select(Receipt.id).where(Receipt.status.in_(READY_FOR_STATS))
    receipts = receipts.where(
        Receipt.merchant_id == merchant_id if merchant_id else Receipt.merchant_id.is_(None)
    )
    result = await session.execute(
        update(ReceiptItem)
        .where(ReceiptItem.raw_name == raw_name)
        .where(ReceiptItem.product_id.is_(None))
        .where(ReceiptItem.kind == LineKind.ITEM.value)
        .where(ReceiptItem.receipt_id.in_(receipts))
        .values(
            product_id=product_id,
            # A category you set on the line by hand outranks the product's default, so
            # coalesce rather than assign: this pass must not undo a decision you made.
            category_id=func.coalesce(ReceiptItem.category_id, category_id),
        )
    )
    return result.rowcount or 0
