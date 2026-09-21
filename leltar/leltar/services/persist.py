"""Turning an identification into draft items, and recording what it cost."""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from leltar.config import Settings
from leltar.extraction import crop
from leltar.extraction.base import IdentificationResult
from leltar.extraction.preprocess import sha256_of
from leltar.extraction.rules import clean_photo, needs_review
from leltar.models import (
    Category,
    IdentificationAttempt,
    Item,
    ItemImage,
    ItemStatus,
    Photo,
    PhotoMode,
    PhotoStatus,
)
from leltar.schemas.identification import Box

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

    # A photograph taken of one thing gets one entry. The instruction already asks for
    # that, and a good model obeys; a cheaper one often adds the table and the wall behind
    # it, and quietly dropping those is better than making the person reject two rows for
    # every object they photograph.
    if photo.mode == PhotoMode.SINGLE.value and len(cleaned.objects) > 1:
        best = max(range(len(cleaned.objects)), key=lambda i: cleaned.objects[i].confidence)
        cleaned.objects = [cleaned.objects[best]]
        object_reasons = [object_reasons[best]]
        photo_reasons.append("extra_objects_ignored")

    categories = await _category_ids(session)

    # Their pictures go too: `item_images` cascades on the item, and a crop belonging to a
    # draft that no longer exists is a file nothing will ever ask for again.
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
            currency=settings.currency,
            status=ItemStatus.DRAFT.value,
            source="photo",
            confidence=obj.confidence,
            review_reasons=reasons or None,
            alternatives=obj.alternatives or None,
        )
        session.add(item)
        items.append(item)

    await session.flush()
    await _make_pictures(session, photo, items, cleaned.objects, settings)

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


async def _make_pictures(
    session: AsyncSession,
    photo: Photo,
    items: list[Item],
    objects: list,
    settings: Settings,
) -> None:
    """Give every new item its own picture, cut from the photograph where possible.

    Failing to make a picture is not failing to identify: the names are the valuable part
    and they are already stored by the time this runs. So a photograph that cannot be
    re-read from disk costs the items their thumbnails and nothing else, and the error is
    logged rather than raised.
    """
    try:
        data = Path(photo.path).read_bytes()
    except OSError as exc:
        log.warning("no pictures for photo %s: %s", photo.id, exc)
        return

    taken = f"{photo.created_at:%Y/%m}" if photo.created_at else "unsorted"

    for item, obj in zip(items, objects, strict=True):
        box = obj.box
        try:
            jpeg, width, height = crop.render(data, box)
        except OSError as exc:
            log.warning("could not crop item %s: %s", item.id, exc)
            continue

        path = crop.storage_path(settings.crop_dir, item.id, taken)
        path.write_bytes(jpeg)

        session.add(
            ItemImage(
                item_id=item.id,
                kind="crop" if box is not None else "photo",
                source_photo_id=photo.id,
                box=box.model_dump() if isinstance(box, Box) else None,
                path=str(path),
                sha256=sha256_of(jpeg),
                bytes=len(jpeg),
                mime="image/jpeg",
                width=width,
                height=height,
                is_primary=True,
            )
        )

    await session.flush()


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
