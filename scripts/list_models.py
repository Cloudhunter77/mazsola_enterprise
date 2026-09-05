"""Shortlist the OpenRouter models this app can actually use, cheapest first.

    python scripts/list_models.py
    python scripts/list_models.py --in 4200 --out 1400 --per-week 20

Two things make a model usable here, and both are checked rather than assumed:

  * it must accept images, or it cannot read a receipt at all;
  * it must support strict structured outputs, or `openrouter.py` cannot trust the JSON
    it gets back - that is the one failure mode this route has that going direct to
    Anthropic does not.

Everything else is price. The ranking is by the estimated cost of *one receipt* at the
token counts you pass in, so it reflects this workload rather than a headline per-million
figure - a model with cheap input and expensive output can easily lose to one that looks
dearer on the tin.

Get your real token counts from the Costs page (Felismerési költség) or from the app log
line that reads `extracted receipt via openrouter ... in=… out=…`, and pass them with
--in/--out. The defaults are only a starting guess.

No API key is needed: the model catalogue is public.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from typing import Any

MODELS_URL = "https://openrouter.ai/api/v1/models"

# A downscaled receipt at MAX_IMAGE_EDGE=1600 plus the ~1.3k-token Hungarian system
# prompt; output is one JSON receipt. Both are guesses until you measure your own.
DEFAULT_INPUT_TOKENS = 3000
DEFAULT_OUTPUT_TOKENS = 1200

# Enough of one to trust the JSON. OpenRouter reports both spellings depending on the
# provider, and either is sufficient for the strict json_schema request we send.
STRUCTURED = {"structured_outputs", "response_format"}


def fetch(url: str) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"User-Agent": "receipt-tracker/list-models"})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        raise SystemExit(f"OpenRouter returned {exc.code}: {exc.reason}") from exc
    except urllib.error.URLError as exc:
        raise SystemExit(
            f"Could not reach {url}: {exc.reason}\n"
            "If this NAS is behind a proxy or a restrictive firewall, run this from a "
            "machine that can reach openrouter.ai."
        ) from exc


def price(pricing: dict[str, Any], key: str) -> float | None:
    """OpenRouter quotes prices per token, as strings. Missing or empty means unknown."""
    raw = pricing.get(key)
    if raw in (None, "", "-1"):
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def usable(model: dict[str, Any]) -> bool:
    architecture = model.get("architecture") or {}
    modalities = architecture.get("input_modalities") or []
    if "image" not in modalities:
        # Older catalogue entries only carry the combined string.
        if "image" not in str(architecture.get("modality") or ""):
            return False
    return bool(STRUCTURED & set(model.get("supported_parameters") or []))


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--in", dest="input_tokens", type=int, default=DEFAULT_INPUT_TOKENS,
                        help=f"input tokens per receipt (default {DEFAULT_INPUT_TOKENS})")
    parser.add_argument("--out", dest="output_tokens", type=int, default=DEFAULT_OUTPUT_TOKENS,
                        help=f"output tokens per receipt (default {DEFAULT_OUTPUT_TOKENS})")
    parser.add_argument("--per-week", type=int, default=20,
                        help="receipts per week, for the yearly figure")
    parser.add_argument("--top", type=int, default=25, help="how many to show")
    parser.add_argument("--free", action="store_true",
                        help="include $0 models (often rate-limited)")
    parser.add_argument("--contains", default="", help="only ids containing this substring")
    args = parser.parse_args()

    catalogue = fetch(MODELS_URL).get("data") or []
    if not catalogue:
        raise SystemExit("OpenRouter returned an empty model list.")

    rows = []
    for model in catalogue:
        if not usable(model):
            continue
        model_id = model.get("id", "")
        if args.contains and args.contains not in model_id:
            continue

        pricing = model.get("pricing") or {}
        prompt_price = price(pricing, "prompt")
        completion_price = price(pricing, "completion")
        if prompt_price is None or completion_price is None:
            continue

        per_receipt = args.input_tokens * prompt_price + args.output_tokens * completion_price
        # Some providers bill each image on top of its tokens.
        per_image = price(pricing, "image")
        if per_image:
            per_receipt += per_image
        # And a few charge a flat fee per request.
        per_request = price(pricing, "request")
        if per_request:
            per_receipt += per_request

        if per_receipt == 0 and not args.free:
            continue

        rows.append({
            "id": model_id,
            "per_receipt": per_receipt,
            "yearly": per_receipt * args.per_week * 52,
            "in_m": prompt_price * 1_000_000,
            "out_m": completion_price * 1_000_000,
            "context": model.get("context_length") or 0,
            "extra": "img+req" if (per_image and per_request) else
                     "img" if per_image else "req" if per_request else "",
        })

    if not rows:
        raise SystemExit("No model matched. Try --free, or relax --contains.")

    rows.sort(key=lambda row: row["per_receipt"])
    shown = rows[: args.top]

    print(f"\n{len(rows)} models accept images and support structured outputs.")
    print(f"Ranked by cost of one receipt at {args.input_tokens} in / {args.output_tokens} out.")
    print(f"Yearly column assumes {args.per_week} receipts a week.\n")

    header = (
        f"{'model id':<52} {'per receipt':>12} {'per year':>10} "
        f"{'$/Mtok in':>10} {'out':>9} {'context':>9}"
    )
    print(header)
    print("-" * len(header))
    for row in shown:
        flag = f" [{row['extra']}]" if row["extra"] else ""
        print(
            f"{row['id']:<52} ${row['per_receipt']:>10.5f} ${row['yearly']:>8.2f} "
            f"{row['in_m']:>10.2f} {row['out_m']:>9.2f} {row['context']:>9,}{flag}"
        )

    print(
        "\n[img] / [req] mean the provider also bills per image or per request, "
        "already included above."
        "\n\nA cheap model that misreads receipts is not cheap. Try a candidate on a real"
        "\nphoto before switching:"
        "\n  docker run --rm -e EXTRACTOR=openrouter -e OPENROUTER_API_KEY \\"
        "\n    -e OPENROUTER_MODEL=<id> ghcr.io/cloudhunter77/receipt-tracker:latest \\"
        "\n    python scripts/try_extract.py tests/fixtures/receipts/synthetic_tesco.jpg"
        "\n\nThe expected answer for that fixture: total 5230 Ft, rounding -2, six goods lines.",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
