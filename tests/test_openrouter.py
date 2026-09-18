"""The OpenRouter engine.

Exercised against a mock transport: the request shape and every failure mode are checked
without spending credit. Whether a given model actually honours the schema is a question
only a real call can answer - `scripts/try_extract.py` is there for that.
"""

from __future__ import annotations

import io
import json
from decimal import Decimal

import httpx
import pytest
from PIL import Image

from app.config import Settings
from app.extraction.base import ExtractionError
from app.extraction.openrouter import OpenRouterExtractor, strict_schema
from app.schemas.extraction import ExtractedReceipt
from tests.conftest import build_receipt


@pytest.fixture
def photo() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (900, 1600), (252, 252, 250)).save(buffer, format="JPEG")
    return buffer.getvalue()


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        data_dir=tmp_path,
        extractor="openrouter",
        openrouter_api_key="sk-or-test",
        openrouter_model="anthropic/claude-sonnet-4.5",
    )


def extractor_with(settings, handler) -> OpenRouterExtractor:
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://openrouter.test/api/v1"
    )
    return OpenRouterExtractor(settings, client=client)


def completion(content: str, **usage) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "choices": [{"message": {"content": content}}],
            "usage": {"prompt_tokens": 3120, "completion_tokens": 1240, **usage},
        },
    )


class TestSchema:
    def test_every_object_is_closed_for_strict_mode(self):
        schema = strict_schema(ExtractedReceipt)
        assert schema["additionalProperties"] is False
        assert set(schema["required"]) == set(schema["properties"])
        for definition in schema["$defs"].values():
            if definition.get("type") == "object":
                assert definition["additionalProperties"] is False, definition

    def test_the_schema_still_describes_the_contract(self):
        schema = strict_schema(ExtractedReceipt)
        assert "items" in schema["properties"]
        assert "total_gross" in schema["properties"]


class TestRequestShape:
    async def test_it_sends_what_openrouter_expects(self, settings, photo):
        seen: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["url"] = str(request.url)
            seen["body"] = json.loads(request.content)
            return completion(build_receipt().model_dump_json())

        await extractor_with(settings, handler).extract(photo)

        assert seen["url"].endswith("/chat/completions")
        body = seen["body"]
        assert body["model"] == "anthropic/claude-sonnet-4.5"
        assert body["response_format"]["type"] == "json_schema"
        assert body["response_format"]["json_schema"]["strict"] is True

        system, user = body["messages"]
        assert system["role"] == "system" and "NYUGTA" in system["content"]
        image, text = user["content"]
        assert image["image_url"]["url"].startswith("data:image/jpeg;base64,")
        assert text["type"] == "text"

    async def test_the_image_is_downscaled_before_it_is_sent(self, settings):
        """The cost lever has to apply here too, not just on the Anthropic path."""
        buffer = io.BytesIO()
        Image.new("RGB", (4000, 3000), (250, 250, 250)).save(buffer, format="JPEG")
        seen: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["body"] = json.loads(request.content)
            return completion(build_receipt().model_dump_json())

        await extractor_with(settings, handler).extract(buffer.getvalue())

        encoded = seen["body"]["messages"][1]["content"][0]["image_url"]["url"]
        import base64

        sent = base64.b64decode(encoded.split(",", 1)[1])
        with Image.open(io.BytesIO(sent)) as img:
            assert max(img.size) == settings.max_image_edge

    async def test_attribution_headers_when_configured(self, tmp_path, photo):
        settings = Settings(
            data_dir=tmp_path, openrouter_api_key="sk-or-test",
            openrouter_site_url="http://nas.local:8088",
        )
        extractor = OpenRouterExtractor(settings)
        assert extractor.client.headers["HTTP-Referer"] == "http://nas.local:8088"
        assert extractor.client.headers["Authorization"] == "Bearer sk-or-test"
        await extractor.aclose()


class TestResults:
    async def test_a_good_response_becomes_an_extraction(self, settings, photo):
        expected = build_receipt()
        extractor = extractor_with(
            settings, lambda r: completion(expected.model_dump_json(), cost=0.0121)
        )

        result = await extractor.extract(photo)

        assert result.extractor == "openrouter"
        assert result.model == "anthropic/claude-sonnet-4.5"
        assert result.receipt.total_gross == expected.total_gross
        assert len(result.receipt.items) == len(expected.items)
        assert result.input_tokens == 3120 and result.output_tokens == 1240
        assert result.latency_ms is not None

    async def test_the_real_charge_is_recorded_not_an_estimate(self, settings, photo):
        extractor = extractor_with(
            settings, lambda r: completion(build_receipt().model_dump_json(), cost=0.0121)
        )
        result = await extractor.extract(photo)
        assert result.cost_usd == Decimal("0.0121")

    async def test_a_missing_cost_is_not_invented(self, settings, photo):
        extractor = extractor_with(
            settings, lambda r: completion(build_receipt().model_dump_json())
        )
        assert (await extractor.extract(photo)).cost_usd is None


class TestFailures:
    async def test_a_wrong_model_id_says_so(self, settings, photo):
        def handler(request):
            return httpx.Response(
                404, json={"error": {"message": "No endpoints found for anthropic/nope."}}
            )

        with pytest.raises(ExtractionError, match="No endpoints found"):
            await extractor_with(settings, handler).extract(photo)

    async def test_no_credit_says_so(self, settings, photo):
        def handler(request):
            return httpx.Response(402, json={"error": {"message": "Insufficient credits."}})

        with pytest.raises(ExtractionError, match="Insufficient credits"):
            await extractor_with(settings, handler).extract(photo)

    async def test_an_error_inside_a_200_is_still_an_error(self, settings, photo):
        def handler(request):
            return httpx.Response(200, json={"error": {"message": "upstream timed out"}})

        with pytest.raises(ExtractionError, match="upstream timed out"):
            await extractor_with(settings, handler).extract(photo)

    async def test_a_model_that_ignores_the_schema_fails_loudly(self, settings, photo):
        """The failure this engine is most likely to hit: prose instead of the structure."""
        prose = "Sure! This receipt is from Tesco and the total was 5230 Ft."
        expected = "does not match the required structure|text rather than JSON"
        with pytest.raises(ExtractionError, match=expected):
            await extractor_with(settings, lambda r: completion(prose)).extract(photo)

    async def test_valid_json_of_the_wrong_shape_fails_loudly(self, settings, photo):
        """And names the finish reason, so a truncated answer is never mistaken for this one."""
        with pytest.raises(ExtractionError, match="does not match the required structure"):
            await extractor_with(settings, lambda r: completion('{"shop": "Tesco"}')).extract(photo)

    async def test_an_empty_message_suggests_the_cause(self, settings, photo):
        with pytest.raises(ExtractionError, match="may not support images"):
            await extractor_with(settings, lambda r: completion("")).extract(photo)

    async def test_a_network_failure_is_reported_not_swallowed(self, settings, photo):
        def handler(request):
            raise httpx.ConnectError("no route to host")

        with pytest.raises(ExtractionError, match="Could not reach OpenRouter"):
            await extractor_with(settings, handler).extract(photo)

    async def test_a_missing_key_is_caught_at_construction(self, tmp_path):
        settings = Settings(data_dir=tmp_path, extractor="openrouter", openrouter_api_key=None)
        with pytest.raises(ExtractionError, match="OPENROUTER_API_KEY"):
            OpenRouterExtractor(settings)


class TestFactory:
    def test_the_factory_builds_it(self, settings):
        from app.extraction.factory import build_extractor

        assert build_extractor(settings).name == "openrouter"

    def test_an_unknown_engine_lists_the_real_ones(self, tmp_path):
        from app.extraction.factory import build_extractor

        with pytest.raises(ValueError, match="openrouter"):
            build_extractor(Settings(data_dir=tmp_path, extractor="nonsense"))
