"""The engine-agnostic identification interface.

Anything that can turn photo bytes into an `IdentifiedPhoto` is an identifier. The worker,
the API and the database know only this module - swapping Claude for a local vision model
is a new file plus one environment variable, not a refactor.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Protocol, runtime_checkable

from leltar.schemas.identification import IdentifiedPhoto


class IdentificationError(RuntimeError):
    """Raised when an engine cannot produce a result at all (network, refusal, bad output)."""


@dataclass(slots=True)
class IdentificationResult:
    """What was found in one photograph, plus what it cost to find out."""

    photo: IdentifiedPhoto
    engine: str
    model: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    cache_read_tokens: int | None = None
    cache_write_tokens: int | None = None
    cost_usd: Decimal | None = None
    latency_ms: int | None = None
    raw: dict | None = field(default=None, repr=False)


@runtime_checkable
class ObjectIdentifier(Protocol):
    """Implement this to add an engine. See `claude.py` for the reference implementation."""

    name: str

    async def identify(
        self, image: bytes, *, place_path: str | None = None, mime_type: str = "image/jpeg"
    ) -> IdentificationResult:
        """Name the movable objects in one photograph.

        `place_path` is where the person says the photo was taken ("Garázs › Fém polc");
        it is context, not something to repeat in the names. Raises `IdentificationError`
        on failure.
        """
        ...
