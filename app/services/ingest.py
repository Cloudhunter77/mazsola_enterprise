"""Receiving a receipt photo: validate, store, deduplicate, queue."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
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


class IngestError(ValueError):
    """The upload is not something we can work with."""


def _verify_image(data: bytes) -> str:
    """Confirm the bytes really are an image and return its format."""
    try:
        with Image.open(__import__("io").BytesIO(data)) as img:
            fmt = (img.format or "").upper()
            img.verify()
    except (UnidentifiedImageError, OSError) as exc:
        raise IngestError("That file is not a readable image.") from exc

    if fmt not in ALLOWED_FORMATS:
        raise IngestError(f"Unsupported image format: {fmt or 'unknown'}.")
    return fmt


def _storage_path(settings: Settings, receipt_id: uuid.UUID, extension: str) -> Path:
    """Bucket by year/month so a directory listing stays usable after a few thousand receipts."""
    now = datetime.now(timezone.utc)
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
