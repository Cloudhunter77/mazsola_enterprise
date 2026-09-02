"""Run one receipt through the configured extraction engine and print what came back.

No database, no containers - just the engine. This is the quickest way to find out
whether your API key, model and image actually work together before deploying anything.

    EXTRACTOR=openrouter OPENROUTER_API_KEY=sk-or-... \
        python scripts/try_extract.py tests/fixtures/receipts/synthetic_tesco.jpg

It costs one real API call. The exit status is 0 only if the receipt both parsed and
balanced, so it can be used as a check in a script.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import get_settings  # noqa: E402
from app.extraction.base import ExtractionError  # noqa: E402
from app.extraction.factory import build_extractor  # noqa: E402
from app.extraction.hu_rules import classify_line, validate  # noqa: E402
from app.extraction.preprocess import estimate_image_tokens, prepare  # noqa: E402


async def run(image_path: Path, show_json: bool) -> int:
    settings = get_settings()
    original = image_path.read_bytes()
    _, width, height = prepare(original, settings.max_image_edge, settings.jpeg_quality)

    print(f"image     {image_path.name}  {len(original) // 1024} KB")
    print(f"sent as   {width}x{height}  (~{estimate_image_tokens(width, height)} image tokens)")
    print(f"engine    {settings.extractor}")

    try:
        extractor = build_extractor(settings)
    except (ExtractionError, ValueError) as exc:
        print(f"\nCould not start the engine: {exc}")
        return 2

    try:
        result = await extractor.extract(original)
    except ExtractionError as exc:
        print(f"\nExtraction failed: {exc}")
        return 1
    finally:
        closer = getattr(extractor, "aclose", None)
        if closer is not None:
            await closer()

    receipt = result.receipt
    verdict = validate(receipt)

    print(f"model     {result.model}")
    print(f"tokens    in={result.input_tokens} out={result.output_tokens}")
    charge = f"${result.cost_usd}" if result.cost_usd is not None else "not reported"
    print(f"cost      {charge}")
    print(f"latency   {result.latency_ms} ms\n")

    print(f"shop      {receipt.merchant_name}")
    print(f"date      {receipt.purchased_at}")
    print(f"total     {receipt.total_gross}  (rounding {receipt.rounding})")
    print(f"confidence {receipt.confidence}\n")

    for item in receipt.items:
        kind = classify_line(item)
        label = "dropped" if kind is None else kind
        code = item.vat_code or ""
        print(f"  {label:9} {item.raw_name[:36]:38} {item.gross_amount:>10}  {code:>3}")

    print()
    if verdict.ok:
        print("The arithmetic balances - this receipt would be stored as parsed.")
    else:
        print(f"Would go to review: {', '.join(verdict.reasons)}")
        print(f"  items + rounding = {verdict.computed_total}, receipt says {verdict.stated_total}")

    if receipt.notes:
        print(f"\nThe model noted: {receipt.notes}")

    if show_json:
        print("\n" + receipt.model_dump_json(indent=2))

    return 0 if verdict.ok else 1


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", type=Path, help="a photo of a receipt")
    parser.add_argument("--json", action="store_true", help="also print the full structure")
    args = parser.parse_args()

    if not args.image.is_file():
        raise SystemExit(f"No such file: {args.image}")

    raise SystemExit(asyncio.run(run(args.image, args.json)))


if __name__ == "__main__":
    main()
