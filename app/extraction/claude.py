"""Receipt extraction with Claude vision + structured output."""

from __future__ import annotations

import base64
import logging
import time
from collections.abc import Sequence
from decimal import Decimal

import anthropic

from app.config import Settings
from app.extraction.base import ExtractionError, ExtractionResult, as_parts
from app.extraction.preprocess import prepare
from app.extraction.prompt import SYSTEM_PROMPT, instruction_for
from app.schemas.extraction import ExtractedReceipt

log = logging.getLogger(__name__)

# USD per million tokens: (input, output). Used only to attribute cost per receipt on the
# Costs page - it does not affect what is billed. Update if Anthropic changes list prices.
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
    """Attribute USD cost to one extraction. Returns None for a model we have no price for."""
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


class ClaudeExtractor:
    """Sends a downscaled receipt photo to Claude and gets back a validated `ExtractedReceipt`.

    Three deliberate choices:

    * **Structured output** (`output_format=ExtractedReceipt`) - the response is schema-validated
      by the SDK, so nothing downstream ever parses free text or repairs broken JSON.
    * **Prompt caching** on the system prompt - it is ~1.3k stable tokens sent with every
      receipt. Note the minimum cacheable prefix is model-dependent: this caches on Opus 5
      (512-token minimum) but silently will not on Haiku 4.5 (4096), where cache_read stays 0.
    * **effort=medium** - transcription does not repay deep reasoning; high effort costs more
      for no measurable accuracy gain on this task.
    """

    name = "claude"

    def __init__(self, settings: Settings, client: anthropic.AsyncAnthropic | None = None):
        self.settings = settings
        self.model = settings.extractor_model
        if client is not None:
            self.client = client
        else:
            if not settings.anthropic_api_key:
                raise ExtractionError(
                    "ANTHROPIC_API_KEY is not set. Set it, or set EXTRACTOR to a local engine."
                )
            self.client = anthropic.AsyncAnthropic(
                api_key=settings.anthropic_api_key,
                timeout=180.0,
                max_retries=3,
            )

    async def extract(
        self, images: Sequence[bytes] | bytes, mime_type: str = "image/jpeg"
    ) -> ExtractionResult:
        parts = as_parts(images)
        prepared = [
            prepare(
                image,
                max_edge=self.settings.max_image_edge,
                quality=self.settings.jpeg_quality,
            )
            for image in parts
        ]
        # Images first, instruction last: the instruction refers to "these images", and on
        # a multi-part receipt it has to be read knowing how many there are.
        content: list[dict] = [
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/jpeg",
                    "data": base64.standard_b64encode(jpeg).decode("ascii"),
                },
            }
            for jpeg, _, _ in prepared
        ]
        content.append({"type": "text", "text": instruction_for(len(parts))})
        dimensions = " ".join(f"{width}x{height}" for _, width, height in prepared)

        started = time.monotonic()
        try:
            response = await self.client.beta.messages.parse(
                model=self.model,
                max_tokens=16000,
                system=[
                    {
                        "type": "text",
                        "text": SYSTEM_PROMPT,
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
                messages=[{"role": "user", "content": content}],
                output_format=ExtractedReceipt,
                thinking={"type": "adaptive"},
                output_config={"effort": self.settings.extractor_effort},
                # Safety classifiers essentially never fire on a grocery receipt, but a refusal
                # would otherwise strand the upload; this reroutes it instead of failing.
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            )
        except anthropic.APIStatusError as exc:
            raise ExtractionError(f"Anthropic API error {exc.status_code}: {exc.message}") from exc
        except anthropic.APIConnectionError as exc:
            raise ExtractionError(f"Could not reach the Anthropic API: {exc}") from exc

        latency_ms = int((time.monotonic() - started) * 1000)

        if response.stop_reason == "refusal":
            detail = getattr(response.stop_details, "explanation", None) or "no explanation given"
            raise ExtractionError(f"The model declined to process this image: {detail}")

        parsed = response.parsed_output
        if parsed is None:
            raise ExtractionError("The model returned no structured output for this image.")

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
            "extracted receipt parts=%d images=%s in=%s out=%s cache_read=%s cost=%s latency=%dms",
            len(parts), dimensions, usage.input_tokens, usage.output_tokens,
            cache_read, cost, latency_ms,
        )

        return ExtractionResult(
            receipt=parsed,
            extractor=self.name,
            model=self.model,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cache_read_tokens=cache_read,
            cache_write_tokens=cache_write,
            cost_usd=cost,
            latency_ms=latency_ms,
            raw=parsed.model_dump(mode="json"),
        )
