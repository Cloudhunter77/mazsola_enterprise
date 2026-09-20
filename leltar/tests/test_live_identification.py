"""The only test that measures whether this app actually works.

Everything else stubs the model out and checks the plumbing. This one sends real photographs
to the real API and looks at what comes back, which is the only way to find out whether the
prompt earns its keep.

    pytest -m live -s

It needs ANTHROPIC_API_KEY and costs a few cents. Drop photographs of your own things into
`tests/fixtures/` and they are picked up automatically - the assertions are deliberately
about the rules rather than about specific names, because what the objects *are* is
different in everybody's house.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from leltar.config import Settings
from leltar.extraction.claude import ClaudeIdentifier
from leltar.extraction.rules import clean_photo, is_generic

FIXTURES = Path(__file__).parent / "fixtures"

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        not os.environ.get("ANTHROPIC_API_KEY"),
        reason="set ANTHROPIC_API_KEY to run the live identification tests",
    ),
]


def photographs() -> list[Path]:
    return sorted(
        path
        for path in FIXTURES.iterdir()
        if path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}
    )


@pytest.fixture
def identifier() -> ClaudeIdentifier:
    return ClaudeIdentifier(Settings(anthropic_api_key=os.environ["ANTHROPIC_API_KEY"]))


@pytest.mark.parametrize("path", photographs(), ids=lambda path: path.name)
async def test_a_real_photograph_yields_usable_names(identifier, path: Path):
    result = await identifier.identify(path.read_bytes())
    cleaned, photo_reasons, object_reasons = clean_photo(result.photo, max_items=12)

    print(f"\n{path.name}: {cleaned.scene}  ({result.cost_usd} USD, {result.latency_ms} ms)")
    for obj, reasons in zip(cleaned.objects, object_reasons, strict=True):
        flags = f"   [{', '.join(reasons)}]" if reasons else ""
        print(f"  - {obj.name} ({obj.category}, {obj.confidence:.2f}){flags}")

    assert cleaned.objects, "the model found nothing nameable in this photograph"

    # The two properties that make a draft worth reviewing rather than retyping: names you
    # could search for, and categories the app actually knows about.
    named = [obj for obj in cleaned.objects if not is_generic(obj.name)]
    assert len(named) >= len(cleaned.objects) * 0.7, "too many names say nothing"
    assert "unknown_category" not in [r for reasons in object_reasons for r in reasons]


async def test_the_model_does_not_invent_a_brand_it_cannot_read(identifier):
    """The rule that matters most, checked against the engine rather than in isolation.

    An inferred brand is dropped by the rules either way; this asks whether the prompt is
    persuading the model not to guess in the first place, which is what keeps the evidence
    flag meaningful.
    """
    shelf = FIXTURES / "shelf.jpg"
    if not shelf.is_file():  # pragma: no cover - fixture ships with the repository
        pytest.skip("no shelf fixture")

    result = await identifier.identify(shelf.read_bytes())
    claimed = [obj for obj in result.photo.objects if obj.brand and not obj.markings_legible]
    assert not claimed, f"brands claimed without legible markings: {claimed}"
