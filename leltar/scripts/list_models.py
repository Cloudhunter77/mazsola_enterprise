"""Shortlist the OpenRouter models this app can actually use, cheapest first.

    python scripts/list_models.py
    python scripts/list_models.py --contains mistral
    python scripts/list_models.py --in 1800 --out 900 --photos 400

Two things make a model usable here, and both are checked rather than assumed:

  * it must accept images, or it cannot name anything at all;
  * it must support strict structured outputs, or `openrouter.py` cannot trust the JSON it
    gets back - that is the one failure mode this route has that going direct to Anthropic
    does not.

Everything else is price. The ranking is by the estimated cost of *one photograph* at the
token counts you pass in, so it reflects this workload rather than a headline per-million
figure - a model with cheap input and expensive output can easily lose one that looks
dearer on the tin.

This exists instead of a recommended model in the README, because model ids and prices
change every few weeks and a list written into a file is wrong by the time anyone reads
it. This asks OpenRouter what is true today.

Get your real token counts from Rendszer -> Felismerési költség, or from the app log line
reading `identified N object(s) via openrouter ... in=… out=…`, and pass them with
--in/--out. The defaults are a starting guess for one downscaled photograph.

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

# A downscaled photograph at MAX_IMAGE_EDGE=1280 (~1.6k image tokens) plus the system
# prompt; output is a handful of named objects. Both are guesses until you measure.
DEFAULT_INPUT_TOKENS = 1800
DEFAULT_OUTPUT_TOKENS = 900

# Enough of one to trust the JSON. OpenRouter reports both spellings depending on the
# provider, and either is sufficient for the strict json_schema request we send.
STRUCTURED = {"structured_outputs", "response_format"}


def fetch(url: str) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"User-Agent": "leltar/list-models"})
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
                        help=f"input tokens per photo (default {DEFAULT_INPUT_TOKENS})")
    parser.add_argument("--out", dest="output_tokens", type=int, default=DEFAULT_OUTPUT_TOKENS,
                        help=f"output tokens per photo (default {DEFAULT_OUTPUT_TOKENS})")
    parser.add_argument("--photos", type=int, default=500,
                        help="how many photographs cataloguing the house will take")
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

        per_photo = args.input_tokens * prompt_price + args.output_tokens * completion_price
        # Some providers bill each image on top of its tokens - which matters more here
        # than for text work, since every single call carries one.
        per_image = price(pricing, "image")
        if per_image:
            per_photo += per_image
        # And a few charge a flat fee per request.
        per_request = price(pricing, "request")
        if per_request:
            per_photo += per_request

        if per_photo == 0 and not args.free:
            continue

        rows.append({
            "id": model_id,
            "per_receipt": per_photo,
            "yearly": per_photo * args.photos,
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
    print(f"Ranked by cost of one photograph at {args.input_tokens} in / "
          f"{args.output_tokens} out.")
    print(f"Whole-house column assumes {args.photos} photographs.\n")

    header = (
        f"{'model id':<52} {'per photo':>12} {'the house':>10} "
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
        "\n\nA cheap model whose names you rewrite is not cheap - the typing is the cost"
        "\nthis app exists to remove. Try a candidate on a real photograph first:"
        "\n  docker run --rm -e IDENTIFIER=openrouter -e OPENROUTER_API_KEY \\"
        "\n    -e OPENROUTER_MODEL=<id> ghcr.io/cloudhunter77/leltar:latest \\"
        "\n    python scripts/try_identify.py tests/fixtures/shelf.jpg"
        "\n\nWatch three things in the output: are the names specific enough to search for,"
        "\ndoes it claim brands it cannot read (the app drops those, but a model that keeps"
        "\nguessing will lose you the field), and do the boxes land on the right objects."
        "\nThen run a week of real photographs and read Pontosság: the share of names you"
        "\nkept unchanged is the number that decides whether a cheaper model is cheaper.",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
