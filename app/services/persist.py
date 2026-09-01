"""Writing an extraction result into the database."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.extraction.base import ExtractionResult
from app.extraction.hu_rules import (
    Validation,
    classify_line,
    parse_purchased_at,
    resolve_vat,
    to_decimal,
    validate,
)
from app.models import ExtractionAttempt, LineKind, PaymentMethod, Receipt, ReceiptItem, ReceiptStatus
from app.schemas.extraction import ExtractedReceipt
from app.services.catalog import resolve_merchant, resolve_product

log = logging.getLogger(__name__)


async def record_attempt(
    session: AsyncSession,
    receipt: Receipt,
    *,
    extractor: str,
    model: str | None = None,
    result: ExtractionResult | None = None,
    error: str | None = None,
) -> ExtractionAttempt:
    """Log one engine call - succeeded or not - with its token cost."""
    attempt = ExtractionAttempt(
        receipt_id=receipt.id,
        extractor=extractor,
        model=model or (result.model if result else None),
        succeeded=result is not None and error is None,
        error=error,
    )
    if result is not None:
        attempt.input_tokens = result.input_tokens
        attempt.output_tokens = result.output_tokens
        attempt.cache_read_tokens = result.cache_read_tokens
        attempt.cache_write_tokens = result.cache_write_tokens
        attempt.cost_usd = result.cost_usd
        attempt.latency_ms = result.latency_ms
        attempt.raw_response = result.raw
    session.add(attempt)
    return attempt


async def persist_extraction(
    session: AsyncSession, receipt: Receipt, result: ExtractionResult
) -> Validation:
    """Apply an extraction to a receipt row: header, items, status.

    Replaces any previously extracted items, so re-running extraction on a receipt is safe.
    The receipt lands in `parsed` only if the Hungarian arithmetic checks pass; otherwise it
    goes to `needs_review` with the reasons attached, and never silently into your stats.
    """
    extracted: ExtractedReceipt = result.receipt
    verdict = validate(extracted)

    merchant = await resolve_merchant(session, extracted.merchant_name, extracted.tax_number)

    receipt.merchant_id = merchant.id if merchant else None
    receipt.merchant_raw_name = (extracted.merchant_name or "")[:300] or None
    receipt.tax_number = (extracted.tax_number or "")[:20] or None
    receipt.purchased_at = parse_purchased_at(extracted.purchased_at)
    receipt.total_gross = to_decimal(extracted.total_gross)
    receipt.total_net = to_decimal(extracted.total_net)
    receipt.total_vat = to_decimal(extracted.total_vat)
    receipt.rounding = to_decimal(extracted.rounding) or Decimal("0.00")
    receipt.discount_total = to_decimal(extracted.discount_total) or Decimal("0.00")
    receipt.currency = (extracted.currency or "HUF")[:3].upper()
    receipt.receipt_no = (extracted.receipt_no or "")[:60] or None
    receipt.nav_ap_code = (extracted.nav_ap_code or "")[:40] or None
    receipt.confidence = extracted.confidence
    receipt.notes = extracted.notes

    try:
        receipt.payment_method = PaymentMethod(extracted.payment_method).value
    except ValueError:
        receipt.payment_method = PaymentMethod.UNKNOWN.value

    await session.execute(delete(ReceiptItem).where(ReceiptItem.receipt_id == receipt.id))

    line_no = 0
    for raw_item in extracted.items:
        kind = classify_line(raw_item)
        if kind is None:
            # A payment, change or summary line the engine mistook for a purchase.
            log.debug("dropping non-purchase line %r", raw_item.raw_name)
            continue

        line_no += 1
        vat_code, vat_rate = resolve_vat(raw_item.vat_code, raw_item.vat_rate)
        gross = to_decimal(raw_item.gross_amount) or Decimal("0.00")
        if kind == LineKind.DISCOUNT.value:
            gross = -abs(gross)

        product = await resolve_product(
            session, raw_item.raw_name, receipt.merchant_id
        ) if kind == LineKind.ITEM.value else None

        session.add(
            ReceiptItem(
                receipt_id=receipt.id,
                line_no=line_no,
                raw_name=raw_item.raw_name[:300],
                quantity=to_decimal(raw_item.quantity),
                unit=(raw_item.unit or "")[:10] or None,
                unit_price=to_decimal(raw_item.unit_price),
                gross_amount=gross,
                vat_code=(vat_code or "")[:4] or None,
                vat_rate=vat_rate,
                kind=kind,
                confidence=raw_item.confidence,
                product_id=product.id if product else None,
                category_id=product.category_id if product else None,
            )
        )

    receipt.review_reasons = verdict.reasons or None
    receipt.status = (
        ReceiptStatus.PARSED.value if verdict.ok else ReceiptStatus.NEEDS_REVIEW.value
    )
    receipt.parsed_at = datetime.now(timezone.utc)
    receipt.error = None

    return verdict
