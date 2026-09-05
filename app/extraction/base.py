"""The engine-agnostic extraction interface.

Anything that can turn receipt image bytes into an `ExtractedReceipt` is an extractor. The
worker, the API and the database know only this module - swapping Claude for a local OCR
pipeline is a new file plus one environment variable, not a refactor.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Protocol, runtime_checkable

from app.schemas.extraction import ExtractedReceipt


class ExtractionError(RuntimeError):
    """Raised when an engine cannot produce a result at all (network, refusal, bad output)."""


@dataclass(slots=True)
class ExtractionResult:
    """A parsed receipt plus everything needed to account for what it cost to get it."""

    receipt: ExtractedReceipt
    extractor: str
    model: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    cache_read_tokens: int | None = None
    cache_write_tokens: int | None = None
    cost_usd: Decimal | None = None
    latency_ms: int | None = None
    raw: dict | None = field(default=None, repr=False)


def as_parts(images: Sequence[bytes] | bytes) -> list[bytes]:
    """Normalise an extractor's `images` argument to a list of whole images.

    A single `bytes` is accepted and wrapped. This is not politeness: `bytes` already
    satisfies `Sequence`, and iterating one yields *integers*, so passing a lone image
    where a sequence is expected would otherwise fail several layers down in the image
    decoder with a type error that says nothing about the real mistake.
    """
    if isinstance(images, bytes | bytearray):
        return [bytes(images)]
    parts = list(images)
    if not parts:
        raise ExtractionError("No image was given to extract.")
    if any(not isinstance(part, bytes | bytearray) for part in parts):
        raise ExtractionError("Every part must be the bytes of one whole image.")
    return [bytes(part) for part in parts]


@runtime_checkable
class ReceiptExtractor(Protocol):
    """Implement this to add an engine. See `claude.py` for the reference implementation."""

    name: str

    async def extract(
        self, images: Sequence[bytes] | bytes, mime_type: str = "image/jpeg"
    ) -> ExtractionResult:
        """Read one receipt from one or more photographs of it.

        `images` is in reading order, top of the receipt first. A receipt too long to
        photograph legibly in one frame arrives as several overlapping parts and must be
        read as a single document - one `ExtractedReceipt`, with any line visible in two
        parts counted once. Raises `ExtractionError` on failure.
        """
        ...
