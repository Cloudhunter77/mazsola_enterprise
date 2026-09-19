"""Shelf labels: storing a price you saw rather than one you paid.

The whole point of this module is the thing it refuses to do. A shelf label is evidence
about a price; it is not a transaction. Nothing here touches `receipts`, and nothing in the
spending statistics can reach a `PriceObservation`. Keeping that separation structural
rather than a flag is deliberate: a boolean on `receipts` would be one forgotten `WHERE`
away from adding money you never spent to a month's total, and - as every misread this
project has chased demonstrates - it would balance perfectly while doing it.

What a label is good for is the opposite of what a receipt is good for. A receipt tells you
what you actually paid, once, for the things you happened to buy. A label tells you what
anything on the shelf costs today, whether you bought it or not, and it prints the egységár
so the comparison needs no arithmetic at all.
"""

from __future__ import annotations

import io
import logging
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from PIL import Image
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.extraction.base import LabelResult
from app.extraction.hu_rules import BUDAPEST, strip_category_code, to_decimal
from app.models import LabelStatus, PriceLabelPhoto, PriceObservation
from app.services.catalog import resolve_merchant, resolve_product
from app.services.ingest import (
    EXTENSIONS,
    IngestError,
    _verify_image,
    sha256_of,
)

log = logging.getLogger(__name__)

# One frame holds a shelf strip; beyond this it is a photograph of an aisle and nothing in
# it will be legible anyway.
MAX_LABELS_PER_PHOTO = 40

# A price that is almost certainly a misread digit rather than a thing on a shelf.
IMPLAUSIBLE_PRICE = Decimal("1000000")

# Price, package size and egységár are all printed, so they can check each other. Generous,
# because shops round the egységár and a 330 g pack is sometimes labelled per 100 g.
UNIT_PRICE_TOLERANCE = Decimal("0.15")

# Everything except the observations you have looked at and accepted.
UNCONFIRMED = (
    LabelStatus.PARSED.value,
    LabelStatus.NEEDS_REVIEW.value,
)


# EXIF tag 36867, DateTimeOriginal: when the shutter actually fired.
EXIF_TAKEN_AT = 36867


def taken_at(data: bytes) -> datetime | None:
    """When the photograph was taken, according to the camera that took it.

    This matters as soon as you can upload from the gallery. An observation dated by when
    it was *uploaded* would put a shelf you photographed last week at today's date, and a
    batch of old photos would land as one flat snapshot of today - which is precisely the
    kind of wrong that looks completely ordinary on a chart.

    EXIF timestamps carry no timezone, so it is read as local time and converted. Returns
    None when the photo has no EXIF at all (a screenshot, a download, a stripped export),
    and the caller falls back to now.
    """
    try:
        with Image.open(io.BytesIO(data)) as img:
            raw = (img.getexif() or {}).get(EXIF_TAKEN_AT)
    except Exception:  # noqa: BLE001 - a photo without readable EXIF is ordinary, not an error
        return None

    if not raw or not isinstance(raw, str):
        return None
    try:
        # `2026:09:19 14:32:05` is the EXIF spelling.
        naive = datetime.strptime(raw.strip(), "%Y:%m:%d %H:%M:%S")
    except ValueError:
        return None

    stamped = naive.replace(tzinfo=BUDAPEST).astimezone(UTC)
    # A camera with a flat battery can report 1970, and a clock set wrong can report next
    # year. Neither is a date to file a price under.
    now = datetime.now(UTC)
    if stamped > now + timedelta(days=1) or stamped.year < 2000:
        log.info("ignoring implausible EXIF date %r", raw)
        return None
    return stamped


def _storage_path(settings: Settings, photo_id: uuid.UUID, extension: str) -> Path:
    """Alongside the receipts, bucketed by month, but in their own tree."""
    now = datetime.now(UTC)
    directory = settings.data_dir / "labels" / f"{now:%Y}" / f"{now:%m}"
    directory.mkdir(parents=True, exist_ok=True)
    return directory / f"{photo_id}{extension}"


async def ingest_label_photo(
    session: AsyncSession,
    data: bytes,
    settings: Settings,
    *,
    merchant_name: str | None = None,
    observed_at: datetime | None = None,
) -> tuple[PriceLabelPhoto, bool]:
    """Store one photograph of a shelf and queue it for reading.

    `merchant_name` is the shop you are standing in. Most shelf labels do not name it, so
    the app asks once at the start of a visit and passes the same answer for every photo -
    which is far more reliable than asking a model to infer a shop from the flooring.

    Returns `(photo, created)`. `created` is False when this exact photograph is already
    stored, so a double-tap in a shop aisle does not read - and pay for - the same shelf
    twice.
    """
    if not data:
        raise IngestError("The upload was empty.")

    fmt = _verify_image(data)
    digest = sha256_of(data)

    existing = await session.scalar(
        select(PriceLabelPhoto).where(PriceLabelPhoto.image_sha256 == digest)
    )
    if existing is not None:
        log.info("duplicate shelf photo, returning %s", existing.id)
        return existing, False

    merchant = await resolve_merchant(session, merchant_name) if merchant_name else None

    photo_id = uuid.uuid4()
    extension = EXTENSIONS.get(fmt, ".jpg")
    path = _storage_path(settings, photo_id, extension)
    path.write_bytes(data)

    photo = PriceLabelPhoto(
        id=photo_id,
        image_path=str(path),
        image_sha256=digest,
        image_bytes=len(data),
        image_mime=f"image/{extension.lstrip('.')}",
        merchant_id=merchant.id if merchant else None,
        merchant_raw_name=(merchant_name or "").strip()[:300] or None,
        # What the caller said, else what the camera recorded, else now. A gallery upload
        # is dated by the photograph; a fresh capture has no EXIF worth preferring over
        # the clock, and they agree anyway.
        observed_at=observed_at or taken_at(data) or datetime.now(UTC),
        status=LabelStatus.PENDING.value,
    )
    session.add(photo)
    await session.flush()

    log.info(
        "queued shelf photo %s (%s, %d KB, %s)",
        photo.id, merchant.name if merchant else "shop unknown", len(data) // 1024, fmt,
    )
    return photo, True


def _check(
    price: Decimal | None, unit_price: Decimal | None, size: float | None, unit: str | None
) -> bool:
    """Do the price, the package size and the egységár tell the same story?

    A label has no total to balance, so this is the only internal check available - and it
    is the one that catches the mistake that matters, which is reading the egységár as the
    price. `598 Ft` for a 0,5 l bottle with `1 196 Ft/l` beneath it is consistent; `1 196`
    in the price field is not.
    """
    if price is None or unit_price is None or not size or not unit:
        return True  # nothing to check against; not the same as disagreeing

    base = Decimal(str(size))
    if unit in {"l", "kg"} and base > 0:
        expected = price / base
    else:
        return True

    if expected <= 0 or unit_price <= 0:
        return True
    ratio = abs(expected - unit_price) / unit_price
    return ratio <= UNIT_PRICE_TOLERANCE


async def persist_labels(
    session: AsyncSession, photo: PriceLabelPhoto, result: LabelResult
) -> list[str]:
    """Write the labels read from one photograph. Returns the review reasons, if any.

    Replaces anything read from this photo before, so re-reading it is safe.
    """
    extracted = result.labels
    reasons: list[str] = []

    # The shop the app said it was in wins over the shop a model thought it saw: the app is
    # stating a fact, the model is inferring one from branding that may not be there.
    if photo.merchant_id is None and extracted.merchant_name:
        merchant = await resolve_merchant(session, extracted.merchant_name)
        if merchant is not None:
            photo.merchant_id = merchant.id
            photo.merchant_raw_name = extracted.merchant_name[:300]

    # Deleted by query rather than by walking `photo.observations`: the relationship is
    # lazy, so touching it here is a database round trip from sync code and fails with
    # MissingGreenlet. `persist_extraction` has always done it this way for receipt lines;
    # this deviated from the pattern that already worked.
    await session.execute(
        delete(PriceObservation).where(PriceObservation.photo_id == photo.id)
    )

    if not extracted.labels:
        reasons.append("no_labels_found")

    if len(extracted.labels) > MAX_LABELS_PER_PHOTO:
        reasons.append("implausible_label_count")

    kept = 0
    confidences: list[float] = []
    for index, label in enumerate(extracted.labels[:MAX_LABELS_PER_PHOTO], start=1):
        raw_name = strip_category_code(label.raw_name.strip())
        price = to_decimal(label.price)
        unit_price = to_decimal(label.unit_price)

        if not raw_name:
            continue
        if price is None and unit_price is None:
            # Nothing to record. A label whose price could not be read is not an
            # observation, it is a photograph of a label.
            reasons.append("label_without_price")
            continue
        if price is not None and (price <= 0 or price > IMPLAUSIBLE_PRICE):
            reasons.append("implausible_price")
            continue
        if not _check(price, unit_price, label.package_size, (label.unit or "").lower() or None):
            reasons.append("unit_price_mismatch")

        product = await resolve_product(session, raw_name, photo.merchant_id)

        session.add(
            PriceObservation(
                photo_id=photo.id,
                line_no=index,
                raw_name=raw_name[:300],
                product_id=product.id if product else None,
                price=price,
                unit_price=unit_price,
                unit=(label.unit or "")[:10].lower() or None,
                package_size=label.package_size,
                package_unit=(label.package_unit or "")[:10].lower() or None,
                is_promotion=bool(label.is_promotion),
                regular_price=to_decimal(label.regular_price),
                promotion_until=_as_date(label.promotion_until),
                confidence=label.confidence,
            )
        )
        kept += 1
        confidences.append(label.confidence)

    if photo.merchant_id is None:
        # Without a shop a price cannot be compared with anything, which is the only reason
        # to have recorded it.
        reasons.append("shop_unknown")

    if confidences and min(confidences) < 0.5:
        reasons.append("low_confidence_label")

    photo.confidence = min(confidences) if confidences else None
    photo.notes = extracted.notes
    photo.review_reasons = reasons or None
    photo.status = LabelStatus.PARSED.value if not reasons else LabelStatus.NEEDS_REVIEW.value
    photo.parsed_at = datetime.now(UTC)
    photo.error = None

    log.info("read %d label(s) from photo %s%s", kept, photo.id,
             f" ({', '.join(reasons)})" if reasons else "")
    return reasons


def _as_date(raw: str | None):
    if not raw:
        return None
    try:
        return datetime.strptime(raw[:10], "%Y-%m-%d").date()
    except ValueError:
        return None
