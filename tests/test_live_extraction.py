"""Live extraction against the real API. Opt in with `pytest -m live`.

These tests cost money - roughly a few cents per image - and need ANTHROPIC_API_KEY.
They are the ones that say whether extraction is actually any good; everything else in
the suite only proves the plumbing works.

    pytest -m live -s

Drop photos of your own receipts into tests/fixtures/receipts/ and they are picked up
automatically. The accuracy assertions apply only to the synthetic fixture, whose exact
contents are known; your photos get a report and the arithmetic check.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from app.config import Settings
from app.extraction.claude import ClaudeExtractor
from app.extraction.hu_rules import classify_line, to_decimal, validate

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.make_test_receipt import EXPECTED  # noqa: E402

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "receipts"
SYNTHETIC = FIXTURE_DIR / "synthetic_tesco.jpg"

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        not os.environ.get("ANTHROPIC_API_KEY"),
        reason="live extraction needs ANTHROPIC_API_KEY",
    ),
]


def settings() -> Settings:
    return Settings(
        anthropic_api_key=os.environ["ANTHROPIC_API_KEY"],
        extractor_model=os.environ.get("EXTRACTOR_MODEL", "claude-opus-5"),
    )


def report(name: str, result, verdict) -> None:
    receipt = result.receipt
    print(f"\n--- {name} ---")
    print(f"model      {result.model}")
    print(f"tokens     in={result.input_tokens} out={result.output_tokens} "
          f"cache_read={result.cache_read_tokens}")
    print(f"cost       ${result.cost_usd}   latency {result.latency_ms} ms")
    print(f"merchant   {receipt.merchant_name}")
    print(f"date       {receipt.purchased_at}")
    print(f"total      {receipt.total_gross}  rounding {receipt.rounding}")
    print(f"confidence {receipt.confidence}")
    print(f"lines      {len(receipt.items)}")
    for item in receipt.items:
        print(f"    {item.kind:9} {item.raw_name[:34]:36} {item.gross_amount:>9} "
              f"{item.vat_code or '':>3}")
    print(f"verdict    {'OK' if verdict.ok else ', '.join(verdict.reasons)}")
    if receipt.notes:
        print(f"notes      {receipt.notes}")


@pytest.mark.skipif(not SYNTHETIC.is_file(), reason="run scripts/make_test_receipt.py first")
async def test_reads_the_synthetic_receipt_correctly():
    """The one fixture whose correct answer is known exactly."""
    result = await ClaudeExtractor(settings()).extract(SYNTHETIC.read_bytes())
    receipt = result.receipt
    verdict = validate(receipt)
    report(SYNTHETIC.name, result, verdict)

    assert receipt.merchant_name and "TESCO" in receipt.merchant_name.upper()
    assert receipt.purchased_at and receipt.purchased_at.startswith("2026-08-14")
    assert to_decimal(receipt.total_gross) == to_decimal(EXPECTED["total_gross"])
    assert to_decimal(receipt.rounding) == to_decimal(EXPECTED["rounding"])

    kinds = [classify_line(item) for item in receipt.items]
    goods = [item for item, kind in zip(receipt.items, kinds, strict=True) if kind == "item"]
    assert len(goods) == EXPECTED["goods_lines"], (
        f"expected {EXPECTED['goods_lines']} goods, got {[g.raw_name for g in goods]}"
    )

    names = " ".join(item.raw_name.upper() for item in receipt.items)
    assert "VISSZAJÁRÓ" not in names, "change handed back must not become a line"
    assert "KÉSZPÉNZ" not in names, "the amount tendered must not become a line"
    assert "MEGTAKARÍT" not in names, "the savings summary must not become a line"

    assert any(kind == "deposit" for kind in kinds), "BETÉTDÍJ must be recognised as a deposit"
    assert any(kind == "discount" for kind in kinds), "KEDVEZMÉNY must be recognised as a discount"

    rates = {float(r) for r in (to_decimal(i.vat_rate) for i in goods) if r is not None}
    expected_rates = EXPECTED["vat_rates"]
    assert expected_rates <= rates, f"expected ÁFA rates {expected_rates}, saw {rates}"

    assert verdict.ok, f"the receipt should balance, but: {verdict.reasons}"


@pytest.mark.parametrize(
    "image",
    [p for p in sorted(FIXTURE_DIR.glob("*")) if p.suffix.lower() in {".jpg", ".jpeg", ".png"}
     and p.name != "synthetic_tesco.jpg"] or [pytest.param(None, marks=pytest.mark.skip(
         reason="add your own receipt photos to tests/fixtures/receipts/"))],
)
async def test_reads_real_photos(image: Path):
    """Runs over whatever photos you have added; asserts only what must hold for any receipt."""
    result = await ClaudeExtractor(settings()).extract(image.read_bytes())
    verdict = validate(result.receipt)
    report(image.name, result, verdict)

    assert result.receipt.items, "no lines were read at all"
    assert to_decimal(result.receipt.total_gross), "no total was read"
    # Not asserting `verdict.ok`: a genuinely crumpled receipt may legitimately need
    # review. The report above is what you read to judge whether the model is good enough.
