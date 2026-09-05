"""Receiving a receipt photo: validate, store, deduplicate, queue."""

from __future__ import annotations

import hashlib
import io
import logging
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from PIL import Image, UnidentifiedImageError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.extraction.preprocess import sha256_of
from app.models import Receipt, ReceiptImage, ReceiptStatus

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


MAX_PARTS = 8

EXTENSIONS = {"JPEG": ".jpg", "MPO": ".jpg", "PNG": ".png", "WEBP": ".webp"}


def _storage_path(
    settings: Settings, receipt_id: uuid.UUID, extension: str, part_no: int = 0
) -> Path:
    """Bucket by year/month so a directory listing stays usable after a few thousand receipts."""
    now = datetime.now(UTC)
    directory = settings.image_dir / f"{now:%Y}" / f"{now:%m}"
    directory.mkdir(parents=True, exist_ok=True)
    # Part 0 keeps the bare `<uuid>.jpg` name every existing receipt already uses on disk.
    suffix = "" if part_no == 0 else f"-{part_no}"
    return directory / f"{receipt_id}{suffix}{extension}"


def set_digest(digests: Sequence[str]) -> str:
    """The identity of a receipt, given the hashes of its parts, in reading order.

    A single-part receipt hashes to its own image hash. That is deliberate rather than
    tidy: it is what every receipt stored before multi-part capture existed already has in
    `image_sha256`, so re-uploading one of those photos is still recognised as a duplicate.
    """
    if len(digests) == 1:
        return digests[0]
    return hashlib.sha256("".join(digests).encode("ascii")).hexdigest()


async def ingest_image(
    session: AsyncSession,
    data: bytes,
    settings: Settings,
    *,
    source: str = "web",
) -> tuple[Receipt, bool]:
    """Store one photo as a single-part receipt. Thin wrapper over `ingest_images`."""
    return await ingest_images(session, [data], settings, source=source)


async def ingest_images(
    session: AsyncSession,
    parts: Sequence[bytes],
    settings: Settings,
    *,
    source: str = "web",
) -> tuple[Receipt, bool]:
    """Store one receipt's photographs and queue it for extraction.

    `parts` is in reading order - top of the receipt first. A long receipt photographed in
    overlapping sections is one receipt, not several: the parts are sent to the model
    together and read as a single document.

    Returns `(receipt, created)`. `created` is False when these exact photos were already
    uploaded - phone shortcuts retry, and re-parsing a duplicate would double-count the
    spend as well as pay for the same extraction twice.

    The *original* photos are kept, not the downscaled copies sent to the model, so a
    future engine can re-read them at full resolution.
    """
    if not parts:
        raise IngestError("The upload was empty.")
    if len(parts) > MAX_PARTS:
        raise IngestError(f"That is {len(parts)} photos; at most {MAX_PARTS} make up one receipt.")

    total = sum(len(part) for part in parts)
    if total > MAX_UPLOAD_BYTES:
        raise IngestError(
            f"Those photos come to {total // 1024 // 1024} MB; the limit is "
            f"{MAX_UPLOAD_BYTES // 1024 // 1024} MB."
        )

    formats: list[str] = []
    digests: list[str] = []
    for index, part in enumerate(parts):
        if not part:
            raise IngestError(f"Photo {index + 1} was empty.")
        formats.append(_verify_image(part))
        digests.append(sha256_of(part))

    if len(set(digests)) != len(digests):
        raise IngestError("The same photo was uploaded twice as different parts.")

    digest = set_digest(digests)

    existing = await _find_existing(session, digest, digests)
    if existing is not None:
        log.info("duplicate upload, returning receipt %s", existing.id)
        return existing, False

    receipt_id = uuid.uuid4()
    extensions = [EXTENSIONS.get(fmt, ".jpg") for fmt in formats]
    paths = [
        _storage_path(settings, receipt_id, extension, part_no)
        for part_no, extension in enumerate(extensions)
    ]

    receipt = Receipt(
        id=receipt_id,
        # Part 0 is mirrored here so everything written before multi-part capture - the
        # review screen, the image endpoint, deletion - keeps working untouched.
        image_path=str(paths[0]),
        image_sha256=digest,
        image_bytes=total,
        image_mime=f"image/{extensions[0].lstrip('.')}",
        source=source,
        status=ReceiptStatus.PENDING.value,
    )
    receipt.images = [
        ReceiptImage(
            receipt_id=receipt_id,
            part_no=part_no,
            path=str(path),
            sha256=part_digest,
            bytes=len(part),
            mime=f"image/{extension.lstrip('.')}",
        )
        for part_no, (path, part_digest, part, extension) in enumerate(
            zip(paths, digests, parts, extensions, strict=True)
        )
    ]

    # Claim the rows before writing any file. The check above is not enough on its own: a
    # retrying phone shortcut can have two uploads of the same photo in flight at once,
    # and both will pass it. The unique indexes on the hashes are the real arbiter, and
    # losing that race is a duplicate - not the 500 (plus orphaned files) it used to be.
    try:
        async with session.begin_nested():
            session.add(receipt)
            await session.flush()
    except IntegrityError:
        existing = await _find_existing(session, digest, digests)
        if existing is None:
            raise
        log.info(
            "lost the race to store %s; using the existing receipt %s", digest[:12], existing.id
        )
        return existing, False

    # Only now put bytes on disk, so a failed insert can never leave files behind.
    for path, part in zip(paths, parts, strict=True):
        path.write_bytes(part)

    log.info(
        "queued receipt %s (%d part%s, %d KB, %s)",
        receipt.id, len(parts), "" if len(parts) == 1 else "s", total // 1024, formats[0],
    )
    return receipt, True


async def _find_existing(
    session: AsyncSession, digest: str, part_digests: Sequence[str]
) -> Receipt | None:
    """Whether we already hold these photos, as a whole receipt or as parts of one.

    The second check matters: uploading a page on its own and then again as part of a
    longer receipt would otherwise store the same photo twice and pay to read it twice.
    """
    existing = await session.scalar(select(Receipt).where(Receipt.image_sha256 == digest))
    if existing is not None:
        return existing

    receipt_id = await session.scalar(
        select(ReceiptImage.receipt_id).where(ReceiptImage.sha256.in_(list(part_digests))).limit(1)
    )
    if receipt_id is None:
        return None
    return await session.get(Receipt, receipt_id)
