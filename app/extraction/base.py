"""The engine-agnostic extraction interface.

Anything that can turn receipt image bytes into an `ExtractedReceipt` is an extractor. The
worker, the API and the database know only this module - swapping Claude for a local OCR
pipeline is a new file plus one environment variable, not a refactor.
"""

from __future__ import annotations

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


@runtime_checkable
class ReceiptExtractor(Protocol):
    """Implement this to add an engine. See `claude.py` for the reference implementation."""

    name: str

    async def extract(self, image_bytes: bytes, mime_type: str = "image/jpeg") -> ExtractionResult:
        """Read a receipt photo. Raises `ExtractionError` on failure."""
        ...
