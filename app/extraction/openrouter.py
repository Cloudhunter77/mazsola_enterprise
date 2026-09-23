"""Receipt extraction through OpenRouter.

OpenRouter is a gateway that fronts many providers behind one OpenAI-shaped API. It is
here because it lets you use credit you may already hold, and try a non-Anthropic vision
model, without touching anything else in the app.

This is a separate engine rather than a base-URL switch on the Claude one. The Claude
extractor leans on Anthropic-specific features - schema-validated output through the SDK,
adaptive thinking, effort, prompt caching - and quietly pointing it at a gateway that may
support none of them would fail in confusing ways. Same prompt, same contract, different
transport: exactly what `ReceiptExtractor` exists for.
"""

from __future__ import annotations

import base64
import json
import logging
import time
from collections.abc import Callable, Sequence
from decimal import Decimal
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from app.config import Settings
from app.extraction.base import (
    ExtractionError,
    ExtractionResult,
    LabelResult,
    ProductPhotoResult,
    as_parts,
)
from app.extraction.label_prompt import LABEL_SYSTEM_PROMPT, label_instruction_for
from app.extraction.preprocess import prepare
from app.extraction.product_prompt import (
    PRODUCT_SYSTEM_PROMPT,
    product_instruction_for,
)
from app.extraction.prompt import SYSTEM_PROMPT, instruction_for
from app.schemas.extraction import ExtractedReceipt
from app.schemas.price_label import ExtractedPriceLabels
from app.schemas.product_photo import ExtractedProductPhoto

log = logging.getLogger(__name__)

# Whatever contract a document type declares; `_send` validates against it and hands it back.
_Parsed = TypeVar("_Parsed", bound=BaseModel)


def strict_schema(model: type[BaseModel]) -> dict[str, Any]:
    """A Pydantic schema tightened for strict structured output.

    Providers that enforce a schema natively require every object to close itself off:
    `additionalProperties: false`, and every property listed as required. Without that
    they fall back to best-effort JSON, which is the guarantee we are here for.
    """
    schema = model.model_json_schema()
    _tighten(schema)
    return schema


def _tighten(node: Any) -> None:
    if isinstance(node, dict):
        if node.get("type") == "object" and "properties" in node:
            node["additionalProperties"] = False
            node["required"] = list(node["properties"])
        for value in node.values():
            _tighten(value)
    elif isinstance(node, list):
        for value in node:
            _tighten(value)


# Enough for a fifty-line weekly shop with change to spare. Worth being generous: output
# tokens on this model cost fractions of a cent, and the alternative is a receipt that
# cannot be read at all.
MAX_OUTPUT_TOKENS = 16000


class OpenRouterExtractor:
    name = "openrouter"

    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None):
        self.settings = settings
        self.model = settings.openrouter_model

        if client is not None:
            self.client = client
            return

        if not settings.openrouter_api_key:
            raise ExtractionError(
                "OPENROUTER_API_KEY is not set. Set it, or choose a different EXTRACTOR."
            )

        headers = {"Authorization": f"Bearer {settings.openrouter_api_key}"}
        if settings.openrouter_site_url:
            # Optional attribution, so requests are identifiable on the OpenRouter dashboard.
            headers["HTTP-Referer"] = settings.openrouter_site_url
            headers["X-Title"] = "Receipt Tracker"

        self.client = httpx.AsyncClient(
            base_url=settings.openrouter_base_url,
            headers=headers,
            timeout=httpx.Timeout(180.0, connect=10.0),
        )

    async def aclose(self) -> None:
        await self.client.aclose()

    def _payload(
        self,
        encoded: Sequence[str],
        *,
        system: str = SYSTEM_PROMPT,
        # A callable, not a string: the instruction depends on how many images are being
        # sent, and only this method knows that number.
        instruction_for_parts: Callable[[int], str] = instruction_for,
        schema_name: str = "hungarian_receipt",
        schema_model: type[BaseModel] = ExtractedReceipt,
    ) -> dict[str, Any]:
        # Images first, instruction last: on a multi-part receipt the instruction has to be
        # read knowing how many images precede it.
        content: list[dict[str, Any]] = [
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{part}"}}
            for part in encoded
        ]
        content.append({"type": "text", "text": instruction_for_parts(len(encoded))})
        return {
            "model": self.model,
            # Copying digits off a photograph has one right answer, so sample the most
            # likely token every time. Left at a provider's default of 1.0 the same receipt
            # can read differently on a re-run, which makes a misreading impossible to
            # reproduce and therefore impossible to fix.
            "temperature": 0,
            # A weekly shop runs to fifty lines, and one line of this schema costs roughly
            # 120 tokens. A default cap cut two real receipts off mid-field, and because the
            # truncated JSON simply failed to validate it was reported as the model not
            # supporting structured output - which sent the diagnosis after the wrong thing
            # entirely.
            "max_tokens": MAX_OUTPUT_TOKENS,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": content},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": schema_name,
                    "strict": True,
                    "schema": strict_schema(schema_model),
                },
            },
        }

    async def _send(
        self,
        images: Sequence[bytes] | bytes,
        *,
        schema_model: type[_Parsed],
        what: str,
        **payload_options: Any,
    ) -> tuple[_Parsed, dict[str, Any], int, int, str]:
        """One call to the gateway, validated. Shared by every document type.

        Returns the parsed object, the usage block, the latency, how many images were sent
        and their dimensions. Everything that can go wrong with a call - a gateway error, an
        error inside a 200, an answer cut off at the token limit, an answer that does not
        match the schema - is handled here once, so a new document type cannot accidentally
        be missing a check the receipt path already learned to make.
        """
        parts = as_parts(images)
        prepared = [
            prepare(
                image,
                max_edge=self.settings.max_image_edge,
                quality=self.settings.jpeg_quality,
                min_width=self.settings.min_image_width,
            )
            for image in parts
        ]
        encoded = [base64.standard_b64encode(jpeg).decode("ascii") for jpeg, _, _ in prepared]
        dimensions = " ".join(f"{width}x{height}" for _, width, height in prepared)

        started = time.monotonic()
        try:
            response = await self.client.post(
                "/chat/completions",
                json=self._payload(encoded, schema_model=schema_model, **payload_options),
            )
        except httpx.HTTPError as exc:
            raise ExtractionError(f"Could not reach OpenRouter: {exc}") from exc
        latency_ms = int((time.monotonic() - started) * 1000)

        if response.status_code >= 400:
            # Worth surfacing verbatim: a missing key, exhausted credit, a wrong model slug
            # or a model that cannot do vision all say so explicitly.
            raise ExtractionError(
                f"OpenRouter returned {response.status_code}: {_error_detail(response)}"
            )

        body = response.json()

        # An error can also arrive inside a 200 response.
        if isinstance(body.get("error"), dict):
            message = body["error"].get("message", body["error"])
            raise ExtractionError(f"OpenRouter error: {message}")

        try:
            choice = body["choices"][0]
            content = choice["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ExtractionError(f"Unexpected response shape from OpenRouter: {body}") from exc

        if not content or not content.strip():
            raise ExtractionError(
                "OpenRouter returned an empty message. The model may not support images."
            )

        # Ask the answer why it stopped before judging what it contains. A reply cut off at
        # the token limit is valid JSON that simply ends early, and diagnosing that as a
        # malformed answer costs an afternoon looking at a photograph that was never the
        # problem.
        if choice.get("finish_reason") == "length":
            raise ExtractionError(
                f"The {what} was longer than the {MAX_OUTPUT_TOKENS} tokens allowed for one "
                f"answer, so the reading was cut off. Photograph it in more sections "
                f"(each part is read on its own) or raise the limit. The photo is fine - "
                f"{self.model} read {len(content)} characters before it ran out of room."
            )

        try:
            parsed = schema_model.model_validate_json(content)
        except ValidationError as exc:
            raise ExtractionError(
                f"{self.model} returned JSON that does not match the required structure. "
                f"Finish reason {choice.get('finish_reason')!r}. "
                f"First 200 characters: {content[:200]!r}"
            ) from exc
        except (json.JSONDecodeError, ValueError) as exc:
            raise ExtractionError(
                f"The model returned text rather than JSON: {content[:200]!r}"
            ) from exc

        return parsed, body.get("usage") or {}, latency_ms, len(parts), dimensions

    async def extract(
        self, images: Sequence[bytes] | bytes, mime_type: str = "image/jpeg"
    ) -> ExtractionResult:
        receipt, usage, latency_ms, count, dimensions = await self._send(
            images, schema_model=ExtractedReceipt, what="receipt"
        )
        cost = usage.get("cost")

        log.info(
            "extracted receipt via openrouter model=%s parts=%d images=%s in=%s out=%s "
            "cost=%s latency=%dms",
            self.model, count, dimensions, usage.get("prompt_tokens"),
            usage.get("completion_tokens"), cost, latency_ms,
        )

        return ExtractionResult(
            receipt=receipt,
            extractor=self.name,
            model=self.model,
            input_tokens=usage.get("prompt_tokens"),
            output_tokens=usage.get("completion_tokens"),
            # OpenRouter reports the real charge for the request, which beats any price
            # table we could keep here.
            cost_usd=Decimal(str(cost)) if cost is not None else None,
            latency_ms=latency_ms,
            raw=receipt.model_dump(mode="json"),
        )

    async def extract_labels(
        self, images: Sequence[bytes] | bytes, mime_type: str = "image/jpeg"
    ) -> LabelResult:
        """Read the shelf labels in one or more photographs taken during a single visit."""
        labels, usage, latency_ms, count, dimensions = await self._send(
            images,
            schema_model=ExtractedPriceLabels,
            what="shelf",
            system=LABEL_SYSTEM_PROMPT,
            instruction_for_parts=label_instruction_for,
            schema_name="hungarian_price_labels",
        )
        cost = usage.get("cost")

        log.info(
            "read %d price label(s) via openrouter model=%s photos=%d images=%s in=%s out=%s "
            "cost=%s latency=%dms",
            len(labels.labels), self.model, count, dimensions, usage.get("prompt_tokens"),
            usage.get("completion_tokens"), cost, latency_ms,
        )

        return LabelResult(
            labels=labels,
            extractor=self.name,
            model=self.model,
            input_tokens=usage.get("prompt_tokens"),
            output_tokens=usage.get("completion_tokens"),
            cost_usd=Decimal(str(cost)) if cost is not None else None,
            latency_ms=latency_ms,
            raw=labels.model_dump(mode="json"),
        )


    async def extract_product(
        self, images: Sequence[bytes] | bytes, mime_type: str = "image/jpeg"
    ) -> ProductPhotoResult:
        """Identify the product in one or more photographs of the same thing."""
        photo, usage, latency_ms, count, dimensions = await self._send(
            images,
            schema_model=ExtractedProductPhoto,
            what="photograph",
            system=PRODUCT_SYSTEM_PROMPT,
            instruction_for_parts=product_instruction_for,
            schema_name="product_photo",
        )
        cost = usage.get("cost")

        log.info(
            "identified %r via openrouter model=%s photos=%d images=%s confidence=%s "
            "in=%s out=%s cost=%s latency=%dms",
            photo.raw_name, self.model, count, dimensions, photo.confidence,
            usage.get("prompt_tokens"), usage.get("completion_tokens"), cost, latency_ms,
        )

        return ProductPhotoResult(
            photo=photo,
            extractor=self.name,
            model=self.model,
            input_tokens=usage.get("prompt_tokens"),
            output_tokens=usage.get("completion_tokens"),
            cost_usd=Decimal(str(cost)) if cost is not None else None,
            latency_ms=latency_ms,
            raw=photo.model_dump(mode="json"),
        )


def _error_detail(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return response.text[:300]
    error = body.get("error")
    if isinstance(error, dict):
        return str(error.get("message") or error)
    return str(error or body)[:300]
