"""Object identification with Claude vision + structured output."""

from __future__ import annotations

import base64
import logging
import time
from decimal import Decimal

import anthropic

from leltar.config import Settings
from leltar.extraction.base import IdentificationError, IdentificationResult
from leltar.extraction.preprocess import prepare
from leltar.extraction.prompt import SYSTEM_PROMPT, instruction_for
from leltar.schemas.identification import IdentifiedPhoto

log = logging.getLogger(__name__)

# USD per million tokens: (input, output). Used only to attribute cost per photograph on
# the Költség page - it does not affect what is billed. Update if list prices change.
PRICING: dict[str, tuple[float, float]] = {
    "claude-opus-5": (5.00, 25.00),
    "claude-opus-4-8": (5.00, 25.00),
    "claude-opus-4-7": (5.00, 25.00),
    "claude-opus-4-6": (5.00, 25.00),
    "claude-sonnet-5": (2.00, 10.00),
    "claude-sonnet-4-6": (3.00, 15.00),
    "claude-haiku-4-5": (1.00, 5.00),
    "claude-fable-5": (10.00, 50.00),
}
CACHE_READ_MULTIPLIER = 0.1
CACHE_WRITE_MULTIPLIER = 1.25


def compute_cost(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
) -> Decimal | None:
    """Attribute USD cost to one identification. None for a model we have no price for."""
    prices = PRICING.get(model)
    if prices is None:
        return None
    input_rate, output_rate = prices
    total = (
        input_tokens * input_rate
        + cache_read_tokens * input_rate * CACHE_READ_MULTIPLIER
        + cache_write_tokens * input_rate * CACHE_WRITE_MULTIPLIER
        + output_tokens * output_rate
    ) / 1_000_000
    return Decimal(f"{total:.6f}")


class ClaudeIdentifier:
    """Sends a downscaled photograph to Claude and gets back a validated `IdentifiedPhoto`.

    Three deliberate choices:

    * **Structured output** (`output_format=IdentifiedPhoto`) - the response is
      schema-validated by the SDK, so nothing downstream parses free text. It is also what
      makes the evidence flags (`markings_legible`, `serial_visible`) enforceable: they
      arrive as booleans next to the field they govern, not as a sentence to interpret.
    * **Prompt caching** on the system prompt - it is a stable block of about 1k tokens
      sent with every photograph. The minimum cacheable prefix is model-dependent, so this
      caches on Sonnet 5 and Opus 5 and silently will not on Haiku 4.5, where cache_read
      stays 0.
    * **effort=low** - recognising a kettle does not repay deliberation. Higher effort on
      this task buys longer descriptions, not better names.
    """

    name = "claude"

    def __init__(self, settings: Settings, client: anthropic.AsyncAnthropic | None = None):
        self.settings = settings
        self.model = settings.identifier_model
        if client is not None:
            self.client = client
        else:
            if not settings.anthropic_api_key:
                raise IdentificationError(
                    "ANTHROPIC_API_KEY is not set. Set it, or set IDENTIFIER to a local engine."
                )
            self.client = anthropic.AsyncAnthropic(
                api_key=settings.anthropic_api_key,
                timeout=180.0,
                max_retries=3,
            )

    async def identify(
        self,
        image: bytes,
        *,
        place_path: str | None = None,
        single: bool = False,
        mime_type: str = "image/jpeg",
    ) -> IdentificationResult:
        jpeg, width, height = prepare(
            image,
            max_edge=self.settings.max_image_edge,
            quality=self.settings.jpeg_quality,
        )

        # Image first, instruction last: the instruction refers to "this photograph".
        content: list[dict] = [
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/jpeg",
                    "data": base64.standard_b64encode(jpeg).decode("ascii"),
                },
            },
            {"type": "text", "text": instruction_for(place_path, single=single)},
        ]

        started = time.monotonic()
        try:
            response = await self.client.beta.messages.parse(
                model=self.model,
                max_tokens=8000,
                system=[
                    {
                        "type": "text",
                        "text": SYSTEM_PROMPT,
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
                messages=[{"role": "user", "content": content}],
                output_format=IdentifiedPhoto,
                thinking={"type": "adaptive"},
                output_config={"effort": self.settings.identifier_effort},
                # A photograph of someone's living room can trip a safety classifier in
                # ways a receipt never does - a photo of a room contains whatever is in the
                # room. A refusal would otherwise strand the upload; this reroutes it.
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            )
        except anthropic.APIStatusError as exc:
            raise IdentificationError(
                f"Anthropic API error {exc.status_code}: {exc.message}"
            ) from exc
        except anthropic.APIConnectionError as exc:
            raise IdentificationError(f"Could not reach the Anthropic API: {exc}") from exc

        latency_ms = int((time.monotonic() - started) * 1000)

        if response.stop_reason == "refusal":
            detail = getattr(response.stop_details, "explanation", None) or "no explanation given"
            raise IdentificationError(f"The model declined to process this photograph: {detail}")

        parsed = response.parsed_output
        if parsed is None:
            raise IdentificationError("The model returned no structured output for this photo.")

        usage = response.usage
        cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0
        cache_write = getattr(usage, "cache_creation_input_tokens", 0) or 0
        cost = compute_cost(
            self.model,
            usage.input_tokens or 0,
            usage.output_tokens or 0,
            cache_read,
            cache_write,
        )

        log.info(
            "identified %d object(s) image=%dx%d in=%s out=%s cache_read=%s cost=%s latency=%dms",
            len(parsed.objects), width, height, usage.input_tokens, usage.output_tokens,
            cache_read, cost, latency_ms,
        )

        return IdentificationResult(
            photo=parsed,
            engine=self.name,
            model=self.model,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cache_read_tokens=cache_read,
            cache_write_tokens=cache_write,
            cost_usd=cost,
            latency_ms=latency_ms,
            raw=parsed.model_dump(mode="json"),
        )
