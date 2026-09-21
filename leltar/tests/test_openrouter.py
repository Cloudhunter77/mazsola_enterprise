"""The OpenRouter engine - the cheap-model route.

Exercised against a mock transport: the request shape and every failure mode are checked
without spending credit. Whether a given model actually honours the schema, or can place a
box on a kettle, is a question only a real call answers - `scripts/try_identify.py` is
there for that, and it is worth a few cents before trusting a model with a house.
"""

from __future__ import annotations

import io
import json

import httpx
import pytest
from PIL import Image

from leltar.config import Settings
from leltar.extraction.base import IdentificationError
from leltar.extraction.openrouter import OpenRouterIdentifier, strict_schema
from leltar.schemas.identification import IdentifiedPhoto
from tests.conftest import build_photo


@pytest.fixture
def picture() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (1600, 1200), (210, 205, 195)).save(buffer, format="JPEG")
    return buffer.getvalue()


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        data_dir=tmp_path,
        identifier="openrouter",
        openrouter_api_key="sk-or-test",
        openrouter_model="mistralai/some-vision-model",
    )


def engine_with(settings, handler) -> OpenRouterIdentifier:
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://openrouter.test/api/v1"
    )
    return OpenRouterIdentifier(settings, client=client)


def completion(content: str, finish_reason: str = "stop", **usage) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "choices": [{"message": {"content": content}, "finish_reason": finish_reason}],
            "usage": {"prompt_tokens": 1620, "completion_tokens": 740, **usage},
        },
    )


class TestSchema:
    def test_every_object_is_closed_for_strict_mode(self):
        schema = strict_schema(IdentifiedPhoto)
        assert schema["additionalProperties"] is False
        assert set(schema["required"]) == set(schema["properties"])
        for definition in schema["$defs"].values():
            if definition.get("type") == "object":
                assert definition["additionalProperties"] is False, definition

    def test_the_schema_still_describes_the_contract(self):
        schema = strict_schema(IdentifiedPhoto)
        assert "objects" in schema["properties"]
        assert "Box" in schema["$defs"]


class TestRequest:
    async def test_it_sends_one_image_the_prompt_and_a_strict_schema(self, settings, picture):
        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured.update(json.loads(request.content))
            return completion(build_photo().model_dump_json())

        await engine_with(settings, handler).identify(picture, place_path="Konyha › Polc")

        assert captured["model"] == "mistralai/some-vision-model"
        # Naming what is in a picture has one best answer; sampling would make a bad
        # reading impossible to reproduce.
        assert captured["temperature"] == 0
        assert captured["response_format"]["json_schema"]["strict"] is True

        content = captured["messages"][1]["content"]
        assert content[0]["type"] == "image_url"
        assert content[0]["image_url"]["url"].startswith("data:image/jpeg;base64,")
        assert "Konyha › Polc" in content[1]["text"]

    async def test_a_single_object_photo_asks_for_one_entry(self, settings, picture):
        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured.update(json.loads(request.content))
            return completion(build_photo().model_dump_json())

        await engine_with(settings, handler).identify(picture, single=True)

        instruction = captured["messages"][1]["content"][1]["text"]
        assert "ONE object" in instruction
        assert "Return exactly one entry" in instruction

    async def test_the_reply_is_parsed_and_costed(self, settings, picture):
        def handler(request: httpx.Request) -> httpx.Response:
            return completion(build_photo().model_dump_json(), cost=0.00042)

        result = await engine_with(settings, handler).identify(picture)

        assert len(result.photo.objects) == 3
        assert result.engine == "openrouter"
        assert result.input_tokens == 1620
        # The gateway reports what it actually charged, which beats any local price table.
        assert float(result.cost_usd) == pytest.approx(0.00042)


class TestFailures:
    async def test_a_gateway_error_is_reported_verbatim(self, settings, picture):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(402, json={"error": {"message": "Insufficient credits"}})

        with pytest.raises(IdentificationError, match="Insufficient credits"):
            await engine_with(settings, handler).identify(picture)

    async def test_an_error_inside_a_200_is_still_an_error(self, settings, picture):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"error": {"message": "No endpoints found"}})

        with pytest.raises(IdentificationError, match="No endpoints found"):
            await engine_with(settings, handler).identify(picture)

    async def test_prose_instead_of_json_says_so(self, settings, picture):
        """The one failure mode this route has that going direct to Anthropic does not."""
        def handler(request: httpx.Request) -> httpx.Response:
            return completion("Ezen a képen egy bögrét és néhány könyvet látok.")

        with pytest.raises(IdentificationError, match="text rather than JSON"):
            await engine_with(settings, handler).identify(picture)

    async def test_an_answer_cut_off_at_the_token_limit_is_diagnosed_as_that(
        self, settings, picture
    ):
        """Valid JSON that simply ends early: blaming the photograph wastes an afternoon."""
        def handler(request: httpx.Request) -> httpx.Response:
            return completion('{"objects": [{"name": "bög', finish_reason="length")

        with pytest.raises(IdentificationError, match="cut off"):
            await engine_with(settings, handler).identify(picture)

    async def test_json_of_the_wrong_shape_names_the_model(self, settings, picture):
        def handler(request: httpx.Request) -> httpx.Response:
            return completion('{"things": ["bögre"]}')

        with pytest.raises(IdentificationError, match="mistralai/some-vision-model"):
            await engine_with(settings, handler).identify(picture)

    async def test_an_empty_message_suggests_the_model_cannot_see(self, settings, picture):
        def handler(request: httpx.Request) -> httpx.Response:
            return completion("")

        with pytest.raises(IdentificationError, match="may not support images"):
            await engine_with(settings, handler).identify(picture)

    async def test_an_unreachable_gateway_is_not_a_crash(self, settings, picture):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("no route to host")

        with pytest.raises(IdentificationError, match="Could not reach OpenRouter"):
            await engine_with(settings, handler).identify(picture)


class TestConfiguration:
    def test_a_missing_key_is_refused_at_construction(self, tmp_path):
        settings = Settings(data_dir=tmp_path, identifier="openrouter", openrouter_model="x/y")
        with pytest.raises(IdentificationError, match="OPENROUTER_API_KEY"):
            OpenRouterIdentifier(settings)

    def test_a_missing_model_points_at_the_listing_script(self, tmp_path):
        """There is no default model on purpose: ids and prices change under us."""
        settings = Settings(
            data_dir=tmp_path, identifier="openrouter", openrouter_api_key="sk-or-test"
        )
        with pytest.raises(IdentificationError, match="list_models.py"):
            OpenRouterIdentifier(settings)

    def test_the_factory_builds_it(self, settings):
        from leltar.extraction.factory import build_identifier

        assert build_identifier(settings).name == "openrouter"

    def test_the_reported_model_follows_the_chosen_engine(self, settings):
        """Recording the Anthropic model while OpenRouter runs mis-attributes every cost."""
        assert settings.active_model == "mistralai/some-vision-model"
        assert Settings(identifier="claude", identifier_model="claude-sonnet-5").active_model == (
            "claude-sonnet-5"
        )
