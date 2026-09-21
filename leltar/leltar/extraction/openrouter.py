"""Object identification through OpenRouter.

OpenRouter is a gateway that fronts many providers behind one OpenAI-shaped API. It is
here because naming a visible object is a much easier task than transcribing a receipt,
and a model a tenth the price can do it well - which matters when cataloguing a house is
several hundred photographs.

This is a separate engine rather than a base-URL switch on the Claude one. That engine
leans on Anthropic-specific features - schema-validated output through the SDK, adaptive
thinking, effort, prompt caching - and quietly pointing it at a gateway supporting none of
them would fail in confusing ways. Same prompt, same contract, different transport:
exactly what `ObjectIdentifier` exists for.

**What changes with a cheaper model, and what does not.** The rules in `rules.py` are not
a formality here: a smaller model invents brands more readily, localises objects worse,
and is more willing to name something it cannot really see. None of that reaches the
inventory - an unreadable brand is dropped, a nonsense box is discarded, a shaky guess is
flagged - so the cost of a weaker model is more entries to correct, not a quietly wrong
inventory. That is the trade to measure on the Pontosság panel before switching for good.
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

from leltar.config import Settings
from leltar.extraction.base import IdentificationError, IdentificationResult
from leltar.extraction.preprocess import prepare
from leltar.extraction.prompt import SYSTEM_PROMPT, instruction_for
from leltar.schemas.identification import IdentifiedPhoto

log = logging.getLogger(__name__)

# A photograph of a full shelf can legitimately name a dozen objects, each with a name,
# alternatives and a box. Generous on purpose: output tokens cost fractions of a cent, and
# the alternative is an answer cut off mid-object, which is worth nothing at all.
MAX_OUTPUT_TOKENS = 8000


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


class OpenRouterIdentifier:
    name = "openrouter"

    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None):
        self.settings = settings
        self.model = settings.openrouter_model

        if client is not None:
            self.client = client
            return

        if not settings.openrouter_api_key:
            raise IdentificationError(
                "OPENROUTER_API_KEY is not set. Set it, or choose a different IDENTIFIER."
            )
        if not settings.openrouter_model:
            raise IdentificationError(
                "OPENROUTER_MODEL is not set. It has no default because model ids and "
                "prices change faster than this app does - run "
                "`python scripts/list_models.py` to see which models can do vision and "
                "strict structured outputs today, cheapest first."
            )

        headers = {"Authorization": f"Bearer {settings.openrouter_api_key}"}
        if settings.openrouter_site_url:
            # Optional attribution, so requests are identifiable on the OpenRouter dashboard.
            headers["HTTP-Referer"] = settings.openrouter_site_url
            headers["X-Title"] = "Leltár"

        self.client = httpx.AsyncClient(
            base_url=settings.openrouter_base_url,
            headers=headers,
            timeout=httpx.Timeout(180.0, connect=10.0),
        )

    async def aclose(self) -> None:
        await self.client.aclose()

    def _payload(self, encoded: str, place_path: str | None, single: bool) -> dict[str, Any]:
        content: list[dict[str, Any]] = [
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{encoded}"}},
            {"type": "text", "text": instruction_for(place_path, single=single)},
        ]
        return {
            "model": self.model,
            # Naming what is in a photograph has one best answer, so take the most likely
            # token every time. At a provider default of 1.0 the same photograph names
            # different things on a re-run, which makes a bad reading impossible to
            # reproduce and therefore impossible to fix.
            "temperature": 0,
            "max_tokens": MAX_OUTPUT_TOKENS,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": content},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "household_objects",
                    "strict": True,
                    "schema": strict_schema(IdentifiedPhoto),
                },
            },
        }

    async def identify(
        self,
        image: bytes,
        *,
        place_path: str | None = None,
        single: bool = False,
        mime_type: str = "image/jpeg",
    ) -> IdentificationResult:
        jpeg, width, height = prepare(
            image, max_edge=self.settings.max_image_edge, quality=self.settings.jpeg_quality
        )
        encoded = base64.standard_b64encode(jpeg).decode("ascii")

        started = time.monotonic()
        try:
            response = await self.client.post(
                "/chat/completions", json=self._payload(encoded, place_path, single)
            )
        except httpx.HTTPError as exc:
            raise IdentificationError(f"Could not reach OpenRouter: {exc}") from exc
        latency_ms = int((time.monotonic() - started) * 1000)

        if response.status_code >= 400:
            # Worth surfacing verbatim: a missing key, exhausted credit, a wrong model slug
            # or a model that cannot do vision all say so explicitly.
            raise IdentificationError(
                f"OpenRouter returned {response.status_code}: {_error_detail(response)}"
            )

        body = response.json()

        # An error can also arrive inside a 200 response.
        if isinstance(body.get("error"), dict):
            message = body["error"].get("message", body["error"])
            raise IdentificationError(f"OpenRouter error: {message}")

        try:
            choice = body["choices"][0]
            content = choice["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise IdentificationError(f"Unexpected response shape from OpenRouter: {body}") from exc

        if not content or not content.strip():
            raise IdentificationError(
                "OpenRouter returned an empty message. The model may not support images."
            )

        # Ask the answer why it stopped before judging what it contains. A reply cut off at
        # the token limit is valid JSON that simply ends early, and diagnosing that as a
        # malformed answer sends you looking at the photograph, which was never the problem.
        if choice.get("finish_reason") == "length":
            raise IdentificationError(
                f"The answer was longer than the {MAX_OUTPUT_TOKENS} tokens allowed, so it "
                f"was cut off. Photograph fewer things at once, or lower "
                f"MAX_ITEMS_PER_PHOTO. The photo is fine - {self.model} wrote "
                f"{len(content)} characters before it ran out of room."
            )

        # Parsed in two steps rather than with `model_validate_json`, because pydantic
        # raises ValidationError for unparseable JSON as well as for the wrong shape - so
        # a model that answered in prose would be reported as a schema mismatch, which
        # sends you looking at the schema when the problem is the model.
        try:
            payload = json.loads(content)
        except ValueError as exc:
            raise IdentificationError(
                f"The model returned text rather than JSON: {content[:200]!r}"
            ) from exc

        try:
            parsed = IdentifiedPhoto.model_validate(payload)
        except ValidationError as exc:
            raise IdentificationError(
                f"{self.model} returned JSON that does not match the required structure. "
                f"Finish reason {choice.get('finish_reason')!r}. "
                f"First 200 characters: {content[:200]!r}"
            ) from exc

        usage = body.get("usage") or {}
        cost = usage.get("cost")

        log.info(
            "identified %d object(s) via openrouter model=%s image=%dx%d in=%s out=%s "
            "cost=%s latency=%dms",
            len(parsed.objects), self.model, width, height, usage.get("prompt_tokens"),
            usage.get("completion_tokens"), cost, latency_ms,
        )

        return IdentificationResult(
            photo=parsed,
            engine=self.name,
            model=self.model,
            input_tokens=usage.get("prompt_tokens"),
            output_tokens=usage.get("completion_tokens"),
            # OpenRouter reports the real charge for the request, which beats any price
            # table this app could keep up to date.
            cost_usd=Decimal(str(cost)) if cost is not None else None,
            latency_ms=latency_ms,
            raw=parsed.model_dump(mode="json"),
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
