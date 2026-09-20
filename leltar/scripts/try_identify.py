"""Run one photograph through the configured engine and print what it found.

No database, no containers - just the engine. This is the quickest way to find out whether
your API key, model and camera actually work together before deploying anything.

    ANTHROPIC_API_KEY=sk-ant-... python scripts/try_identify.py tests/fixtures/shelf.jpg

It costs one real API call, and prints what the rules did to the answer as well as what the
model said - so a dropped brand or a flagged value shows up here rather than being noticed
weeks later in the inventory.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from leltar.config import get_settings  # noqa: E402
from leltar.extraction.base import IdentificationError  # noqa: E402
from leltar.extraction.factory import build_identifier  # noqa: E402
from leltar.extraction.preprocess import estimate_image_tokens, prepare  # noqa: E402
from leltar.extraction.rules import clean_photo  # noqa: E402

REASON_TEXT = {
    "generic_name": "the name says nothing you could search for",
    "unverifiable_brand": "brand/model dropped: not legible in the photograph",
    "unverifiable_serial": "serial dropped: not legible in the photograph",
    "unknown_category": "category was not one of ours; filed under egyeb",
    "no_value_estimate": "no value given",
    "wide_value_range": "the value range is very wide",
    "implausible_value": "the value is implausible for a household object",
    "implausible_quantity": "the count is implausible",
    "low_confidence_object": "the model is unsure about this one",
    "low_confidence": "the model is unsure about the photograph as a whole",
    "no_objects": "nothing nameable was found",
    "too_many_objects": "more objects than the per-photo limit; the least confident were cut",
}


async def run(image_path: Path, place: str | None, show_json: bool) -> int:
    settings = get_settings()
    original = image_path.read_bytes()

    _, width, height = prepare(original, settings.max_image_edge, settings.jpeg_quality)
    print(f"photo     {image_path.name}  {len(original) // 1024} KB")
    print(f"sent as   {width}x{height}  (~{estimate_image_tokens(width, height)} image tokens)")
    print(f"engine    {settings.identifier}  ({settings.identifier_model})")

    try:
        identifier = build_identifier(settings)
    except (IdentificationError, ValueError) as exc:
        print(f"\nCould not start the engine: {exc}")
        return 2

    try:
        result = await identifier.identify(original, place_path=place)
    except IdentificationError as exc:
        print(f"\nIdentification failed: {exc}")
        return 1

    raw = result.photo
    cleaned, photo_reasons, object_reasons = clean_photo(
        raw, max_items=settings.max_items_per_photo
    )

    print(f"\nscene     {cleaned.scene or '-'}")
    print(f"cost      {result.cost_usd if result.cost_usd is not None else 'unknown'} USD "
          f"in {result.latency_ms} ms "
          f"({result.input_tokens} in / {result.output_tokens} out)")
    if photo_reasons:
        print("flags     " + ", ".join(REASON_TEXT.get(r, r) for r in photo_reasons))

    print(f"\n{len(cleaned.objects)} object(s):\n")
    for obj, reasons in zip(cleaned.objects, object_reasons, strict=True):
        count = f" ×{obj.quantity}" if obj.quantity > 1 else ""
        value = (
            f"{obj.value_low_huf or '?'}–{obj.value_high_huf or '?'} Ft"
            if (obj.value_low_huf or obj.value_high_huf)
            else "no estimate"
        )
        brand = f"  [{' '.join(filter(None, (obj.brand, obj.product_model)))}]" if obj.brand else ""
        print(f"  {obj.name}{count}{brand}")
        print(f"      {obj.category}  ·  {value}  ·  confidence {obj.confidence:.2f}")
        if obj.alternatives:
            print(f"      or: {', '.join(obj.alternatives)}")
        for reason in reasons:
            print(f"      ! {REASON_TEXT.get(reason, reason)}")
        print()

    if show_json:
        print(json.dumps(cleaned.model_dump(mode="json"), ensure_ascii=False, indent=2))

    # A photograph that produced nothing usable is a failure worth an exit code, so this
    # can be used as a check in a script.
    return 0 if cleaned.objects else 1


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", type=Path, help="A photograph of your things.")
    parser.add_argument("--place", help='Where it was taken, e.g. "Garázs › Fém polc".')
    parser.add_argument("--json", action="store_true", help="Also print the cleaned structure.")
    args = parser.parse_args()

    if not args.image.is_file():
        raise SystemExit(f"No such file: {args.image}")

    raise SystemExit(asyncio.run(run(args.image, args.place, args.json)))


if __name__ == "__main__":
    main()
