"""Receiving a photograph: validate, store, deduplicate, queue."""

from __future__ import annotations

import io
import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path

from PIL import Image, UnidentifiedImageError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from leltar.config import Settings
from leltar.extraction.preprocess import sha256_of
from leltar.models import Photo, PhotoMode, PhotoStatus

log = logging.getLogger(__name__)

MAX_UPLOAD_BYTES = 25 * 1024 * 1024
ALLOWED_FORMATS = {"JPEG", "PNG", "HEIF", "HEIC", "WEBP", "MPO"}

# A byte limit alone does not bound memory: a solid-colour PNG is a few KB on the wire and
# hundreds of MB once decoded, which is a real problem on a NAS. The other half of this
# defence is in preprocess.prepare(), which shrinks before converting so the full
# resolution bitmap is never materialised. A 48 MP phone photo is about 8000x6000, so this
# ceiling still admits anything a real camera produces.
MAX_PIXELS = 50_000_000

# Lower PIL's own guard (default ~89 MP) to match, so any decode reached by another path
# is bounded too rather than relying on this check alone.
Image.MAX_IMAGE_PIXELS = MAX_PIXELS

# One upload, one room's worth of photographs. Past this it is a bulk import, which wants
# a different screen and a different conversation about cost.
MAX_PHOTOS_PER_UPLOAD = 20

EXTENSIONS = {"JPEG": ".jpg", "MPO": ".jpg", "PNG": ".png", "WEBP": ".webp"}


class IngestError(ValueError):
    """The upload is not something we can work with."""


def verify_image(data: bytes) -> str:
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


def _storage_path(settings: Settings, photo_id: uuid.UUID, extension: str) -> Path:
    """Bucket by year/month so a directory listing stays usable after a few thousand photos."""
    now = datetime.now(UTC)
    directory = settings.image_dir / f"{now:%Y}" / f"{now:%m}"
    directory.mkdir(parents=True, exist_ok=True)
    return directory / f"{photo_id}{extension}"


async def ingest_photo(
    session: AsyncSession,
    data: bytes,
    settings: Settings,
    *,
    place_id: uuid.UUID | None = None,
    mode: str = PhotoMode.SCENE.value,
    source: str = "web",
) -> tuple[Photo, bool]:
    """Store one photograph and queue it for identification.

    Returns `(photo, created)`. `created` is False when this exact image was already
    uploaded - phone shortcuts retry, and re-identifying a duplicate would both pay twice
    and put a second set of drafts for the same objects in the review queue.

    Unlike the receipt scanner next door, several photographs in one request are several
    independent photos, not sections of one document: each frame is its own set of objects.

    `mode` says what the picture is of - a scene to catalogue, or one object photographed
    deliberately. It is stored on the photo rather than passed to the worker later,
    because it is a fact about the act of taking it that nobody can recover afterwards.
    """
    if mode not in set(PhotoMode):
        raise IngestError(f"Ismeretlen mód: {mode}.")
    if not data:
        raise IngestError("The upload was empty.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise IngestError(
            f"That photo is {len(data) // 1024 // 1024} MB; the limit is "
            f"{MAX_UPLOAD_BYTES // 1024 // 1024} MB."
        )

    fmt = verify_image(data)
    digest = sha256_of(data)

    existing = await session.scalar(select(Photo).where(Photo.sha256 == digest))
    if existing is not None:
        log.info("duplicate upload, returning photo %s", existing.id)
        return existing, False

    photo_id = uuid.uuid4()
    extension = EXTENSIONS.get(fmt, ".jpg")
    path = _storage_path(settings, photo_id, extension)

    photo = Photo(
        id=photo_id,
        path=str(path),
        sha256=digest,
        bytes=len(data),
        mime=f"image/{extension.lstrip('.')}",
        source=source,
        place_id=place_id,
        mode=mode,
        taken_at=datetime.now(UTC),
        status=PhotoStatus.PENDING.value,
    )

    # Claim the row before writing the file. The check above is not enough on its own: a
    # retrying phone shortcut can have two uploads of the same image in flight at once and
    # both will pass it. The unique index on the hash is the real arbiter, and losing that
    # race is a duplicate - not a 500 with an orphaned file left on disk.
    try:
        async with session.begin_nested():
            session.add(photo)
            await session.flush()
    except IntegrityError:
        existing = await session.scalar(select(Photo).where(Photo.sha256 == digest))
        if existing is None:
            raise
        log.info("lost the race to store %s; using photo %s", digest[:12], existing.id)
        return existing, False

    # Only now put bytes on disk, so a failed insert can never leave files behind.
    path.write_bytes(data)

    log.info("queued photo %s (%d KB, %s)", photo.id, len(data) // 1024, fmt)
    return photo, True
