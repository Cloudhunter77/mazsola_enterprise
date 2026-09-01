"""Receiving a receipt photo: validate, store, deduplicate, queue."""

from __future__ import annotations

import io
import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path

from PIL import Image, UnidentifiedImageError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.extraction.preprocess import sha256_of
from app.models import Receipt, ReceiptStatus

log = logging.getLogger(__name__)

MAX_UPLOAD_BYTES = 25 * 1024 * 1024
ALLOWED_FORMATS = {"JPEG", "PNG", "HEIF", "HEIC", "WEBP", "MPO"}

# A byte limit alone does not bound memory: a solid-colour PNG is a few KB on the wire
# and hundreds of MB once decoded, which is a real problem on a NAS. The other half of
# this defence is in preprocess.prepare(), which shrinks before converting so the full
# resolution bitmap is never materialised. A 48 MP phone photo is about 8000x6000, so
# this ceiling still admits anything a real camera produces.
MAX_PIXELS = 50_000_000

# Lower PIL's own guard (default ~89 MP) to match, so any decode reached by another path
# is bounded too rather than relying on this check alone.
Image.MAX_IMAGE_PIXELS = MAX_PIXELS


class IngestError(ValueError):
    """The upload is not something we can work with."""


def _verify_image(data: bytes) -> str:
    """Confirm the bytes really are an image of a sane size, and return its format."""
    try:
        with Image.open(io.BytesIO(data)) as img:
            fmt = (img.format or "").upper()
            width, height = img.size
            img.verify()
    except Image.DecompressionBombError as exc:
        # Not an OSError, so it would otherwise escape as a 500 rather than a clean 400.
        raise IngestError("That image is far too large to process.") from exc
    except (UnidentifiedImageError, OSError) as exc:
        raise IngestError("That file is not a readable image.") from exc

    if width * height > MAX_PIXELS:
        raise IngestError(
            f"That image is {width}×{height} ({width * height // 1_000_000} megapixels); "
            f"the limit is {MAX_PIXELS // 1_000_000}."
        )

    if fmt not in ALLOWED_FORMATS:
        raise IngestError(f"Unsupported image format: {fmt or 'unknown'}.")
    return fmt


def _storage_path(settings: Settings, receipt_id: uuid.UUID, extension: str) -> Path:
    """Bucket by year/month so a directory listing stays usable after a few thousand receipts."""
    now = datetime.now(UTC)
    directory = settings.image_dir / f"{now:%Y}" / f"{now:%m}"
    directory.mkdir(parents=True, exist_ok=True)
    return directory / f"{receipt_id}{extension}"


async def ingest_image(
    session: AsyncSession,
    data: bytes,
    settings: Settings,
    *,
    source: str = "web",
) -> tuple[Receipt, bool]:
    """Store an uploaded photo and queue it for extraction.

    Returns `(receipt, created)`. `created` is False when this exact image was already
    uploaded - phone shortcuts retry, and re-parsing a duplicate would double-count the
    spend as well as pay for the same extraction twice.

    The *original* photo is kept, not the downscaled copy sent to the model, so a future
    engine can re-read it at full resolution.
    """
    if not data:
        raise IngestError("The upload was empty.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise IngestError(
            f"Image is {len(data) // 1024 // 1024} MB; the limit is "
            f"{MAX_UPLOAD_BYTES // 1024 // 1024} MB."
        )

    fmt = _verify_image(data)
    digest = sha256_of(data)

    existing = await session.scalar(select(Receipt).where(Receipt.image_sha256 == digest))
    if existing is not None:
        log.info("duplicate upload, returning receipt %s", existing.id)
        return existing, False

    receipt_id = uuid.uuid4()
    extension = {"JPEG": ".jpg", "MPO": ".jpg", "PNG": ".png", "WEBP": ".webp"}.get(fmt, ".jpg")
    path = _storage_path(settings, receipt_id, extension)
    path.write_bytes(data)

    receipt = Receipt(
        id=receipt_id,
        image_path=str(path),
        image_sha256=digest,
        image_bytes=len(data),
        image_mime=f"image/{extension.lstrip('.')}",
        source=source,
        status=ReceiptStatus.PENDING.value,
    )
    session.add(receipt)
    await session.flush()
    log.info("queued receipt %s (%d KB, %s)", receipt.id, len(data) // 1024, fmt)
    return receipt, True
