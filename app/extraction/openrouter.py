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
from decimal import Decimal
from typing import Any

import httpx
from pydantic import BaseModel, ValidationError

from app.config import Settings
from app.extraction.base import ExtractionError, ExtractionResult
from app.extraction.preprocess import prepare
from app.extraction.prompt import SYSTEM_PROMPT, USER_INSTRUCTION
from app.schemas.extraction import ExtractedReceipt

log = logging.getLogger(__name__)


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

    def _payload(self, encoded: str) -> dict[str, Any]:
        return {
            "model": self.model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/jpeg;base64,{encoded}"},
                        },
                        {"type": "text", "text": USER_INSTRUCTION},
                    ],
                },
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "hungarian_receipt",
                    "strict": True,
                    "schema": strict_schema(ExtractedReceipt),
                },
            },
        }

    async def extract(self, image_bytes: bytes, mime_type: str = "image/jpeg") -> ExtractionResult:
        jpeg, width, height = prepare(
            image_bytes,
            max_edge=self.settings.max_image_edge,
            quality=self.settings.jpeg_quality,
        )
        encoded = base64.standard_b64encode(jpeg).decode("ascii")

        started = time.monotonic()
        try:
            response = await self.client.post("/chat/completions", json=self._payload(encoded))
        except httpx.HTTPError as exc:
            raise ExtractionError(f"Could not reach OpenRouter: {exc}") from exc
        latency_ms = int((time.monotonic() - started) * 1000)

        if response.status_code != httpx.codes.OK:
            # OpenRouter's own message is the useful part - a wrong model id, no credit,
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
            content = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ExtractionError(f"Unexpected response shape from OpenRouter: {body}") from exc

        if not content or not content.strip():
            raise ExtractionError(
                "OpenRouter returned an empty message. The model may not support images."
            )

        try:
            receipt = ExtractedReceipt.model_validate_json(content)
        except ValidationError as exc:
            raise ExtractionError(
                f"The model did not return the required structure - {self.model} may not "
                f"support strict structured outputs. First 200 characters: {content[:200]!r}"
            ) from exc
        except (json.JSONDecodeError, ValueError) as exc:
            raise ExtractionError(
                f"The model returned text rather than JSON: {content[:200]!r}"
            ) from exc

        usage = body.get("usage") or {}
        cost = usage.get("cost")
        input_tokens = usage.get("prompt_tokens")
        output_tokens = usage.get("completion_tokens")

        log.info(
            "extracted receipt via openrouter model=%s image=%dx%d in=%s out=%s cost=%s "
            "latency=%dms",
            self.model, width, height, input_tokens, output_tokens, cost, latency_ms,
        )

        return ExtractionResult(
            receipt=receipt,
            extractor=self.name,
            model=self.model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            # OpenRouter reports the real charge for the request, which beats any price
            # table we could keep here.
            cost_usd=Decimal(str(cost)) if cost is not None else None,
            latency_ms=latency_ms,
            raw=receipt.model_dump(mode="json"),
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
