"""Turning an identification into draft items, and recording what it cost."""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from leltar.config import Settings
from leltar.extraction.base import IdentificationResult
from leltar.extraction.rules import clean_photo, midpoint, needs_review
from leltar.models import Category, IdentificationAttempt, Item, ItemStatus, Photo, PhotoStatus

log = logging.getLogger(__name__)


async def _category_ids(session: AsyncSession) -> dict[str, uuid.UUID]:
    rows = (await session.execute(select(Category.slug, Category.id))).all()
    return {slug: category_id for slug, category_id in rows}


async def persist_identification(
    session: AsyncSession,
    photo: Photo,
    result: IdentificationResult,
    settings: Settings,
) -> list[Item]:
    """Apply the rules, write the draft items, and set the photograph's status.

    Drafts from an earlier run of the same photograph are replaced. Items you already
    confirmed are not: re-identifying a photo is asking for a better guess, and throwing
    away an entry someone has already approved would be the app deleting your work.
    """
    cleaned, photo_reasons, object_reasons = clean_photo(
        result.photo, max_items=settings.max_items_per_photo
    )
    categories = await _category_ids(session)

    await session.execute(
        delete(Item).where(Item.photo_id == photo.id, Item.status == ItemStatus.DRAFT.value)
    )

    items: list[Item] = []
    for obj, reasons in zip(cleaned.objects, object_reasons, strict=True):
        item = Item(
            photo_id=photo.id,
            # The photograph knows where it was taken; the model is never asked to guess.
            place_id=photo.place_id,
            category_id=categories.get(obj.category),
            name=obj.name,
            suggested_name=obj.name,
            brand=obj.brand,
            product_model=obj.product_model,
            colour=obj.colour,
            material=obj.material,
            condition=obj.condition,
            quantity=obj.quantity,
            serial_number=obj.serial_number,
            description=obj.description,
            value_low=obj.value_low_huf,
            value_high=obj.value_high_huf,
            estimated_value=midpoint(obj.value_low_huf, obj.value_high_huf),
            currency=settings.currency,
            status=ItemStatus.DRAFT.value,
            source="photo",
            confidence=obj.confidence,
            review_reasons=reasons or None,
            alternatives=obj.alternatives or None,
        )
        session.add(item)
        items.append(item)

    photo.scene = cleaned.scene
    photo.confidence = cleaned.confidence
    photo.review_reasons = photo_reasons or None
    photo.notes = cleaned.notes
    photo.error = None
    photo.identified_at = datetime.now(UTC)
    photo.status = (
        PhotoStatus.NEEDS_REVIEW.value
        if needs_review(photo_reasons, object_reasons)
        else PhotoStatus.IDENTIFIED.value
    )

    await session.flush()
    log.info(
        "photo %s -> %d item(s), status=%s%s",
        photo.id, len(items), photo.status,
        f" ({', '.join(photo_reasons)})" if photo_reasons else "",
    )
    return items


async def record_attempt(
    session: AsyncSession,
    photo_id: uuid.UUID | None,
    *,
    engine: str,
    model: str | None,
    ok: bool,
    result: IdentificationResult | None = None,
    error: str | None = None,
    items_found: int | None = None,
) -> None:
    """One row per API call, successful or not.

    Failures are recorded too, and with their token counts where we have them: a refused
    or malformed response is still billed, and a costs page that only counts successes
    would understate the bill by exactly the amount you would most want to know about.
    """
    attempt = IdentificationAttempt(
        photo_id=photo_id,
        engine=engine,
        model=model,
        ok=ok,
        error=error,
        items_found=items_found,
    )
    if result is not None:
        attempt.input_tokens = result.input_tokens
        attempt.output_tokens = result.output_tokens
        attempt.cache_read_tokens = result.cache_read_tokens
        attempt.cache_write_tokens = result.cache_write_tokens
        attempt.cost_usd = result.cost_usd
        attempt.latency_ms = result.latency_ms
    session.add(attempt)
    await session.flush()
