"""Export the receipts you have not confirmed, so the misreads can be studied.

A receipt left unconfirmed is a receipt whose reading you did not accept. That makes the
unconfirmed pile the most valuable data in the database for improving the prompt: every row
in it is a case where the model and the paper disagree, and the paper is still on file.

What comes out is two halves that only mean something together:

* `unconfirmed.md` - what the app *read*: header, every line in printed order, the review
  reasons, and the model's own raw JSON. Plain text, so it can be pasted into a chat whole.
* `images/` - what the app was *looking at*. The photographs, named after the same short id
  the Markdown uses, so a line and the paper it came from can be put side by side.

Run it inside the app container, which already has the database URL and the image directory:

    docker exec receipt-tracker-app-1 python scripts/export_unconfirmed.py

By default it writes into `/data/export`, which is a bind mount, so the files appear on the
NAS without copying anything out of the container.

Nothing here writes to the database.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import sys
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from app.models import (  # noqa: E402
    ExtractionAttempt,
    Merchant,
    Receipt,
    ReceiptImage,
    ReceiptItem,
    ReceiptStatus,
)

# Everything except the receipts you looked at and accepted. `failed` is included on
# purpose: a receipt that never parsed at all is as much a lesson as one that parsed wrong.
UNCONFIRMED = (
    ReceiptStatus.PARSED.value,
    ReceiptStatus.NEEDS_REVIEW.value,
    ReceiptStatus.FAILED.value,
    ReceiptStatus.PENDING.value,
    ReceiptStatus.PROCESSING.value,
)


@dataclass(slots=True)
class Export:
    receipt: Receipt
    merchant_name: str | None
    items: list[ReceiptItem]
    attempt: ExtractionAttempt | None
    image_paths: list[str] = field(default_factory=list)

    @property
    def short_id(self) -> str:
        """Enough of the uuid to be unique here, short enough to be quotable in a chat."""
        return str(self.receipt.id)[:8]


async def collect(session: AsyncSession, limit: int = 100) -> list[Export]:
    """Gather every unconfirmed receipt with its lines, images and last extraction attempt."""
    receipts = (
        await session.scalars(
            select(Receipt)
            .where(Receipt.status.in_(UNCONFIRMED))
            # A typed-in receipt has nothing to teach a vision prompt.
            .where(Receipt.image_path.is_not(None))
            .order_by(Receipt.purchased_at.desc().nullslast(), Receipt.created_at.desc())
            .limit(limit)
        )
    ).all()

    exports: list[Export] = []
    for receipt in receipts:
        items = (
            await session.scalars(
                select(ReceiptItem)
                .where(ReceiptItem.receipt_id == receipt.id)
                .order_by(ReceiptItem.line_no)
            )
        ).all()
        # The last attempt is the reading currently on screen; earlier ones are history.
        attempt = await session.scalar(
            select(ExtractionAttempt)
            .where(ExtractionAttempt.receipt_id == receipt.id)
            .order_by(ExtractionAttempt.created_at.desc())
            .limit(1)
        )
        parts = (
            await session.scalars(
                select(ReceiptImage)
                .where(ReceiptImage.receipt_id == receipt.id)
                .order_by(ReceiptImage.part_no)
            )
        ).all()
        merchant = (
            await session.get(Merchant, receipt.merchant_id) if receipt.merchant_id else None
        )

        exports.append(
            Export(
                receipt=receipt,
                merchant_name=merchant.name if merchant else None,
                items=list(items),
                attempt=attempt,
                # Older receipts predate the parts table and only have the single column.
                image_paths=[p.path for p in parts] or [receipt.image_path or ""],
            )
        )
    return exports


def _money(value: Decimal | None) -> str:
    return "–" if value is None else f"{value:,.2f}".replace(",", " ")


def render(exports: list[Export]) -> str:
    """One Markdown document describing every unconfirmed reading."""
    lines: list[str] = [
        "# Nem megerősített blokkok / Unconfirmed receipts",
        "",
        f"{len(exports)} receipt(s) whose reading was never accepted. For each one the "
        "photograph is in `images/` under the same short id.",
        "",
    ]

    for export in exports:
        receipt = export.receipt
        lines += [
            "---",
            "",
            f"## {export.short_id} — {export.merchant_name or receipt.merchant_raw_name or '?'}",
            "",
            f"- **status**: `{receipt.status}`",
            f"- **photographed**: {', '.join(Path(p).name for p in export.image_paths if p)}",
            f"- **purchased_at**: {receipt.purchased_at}",
            f"- **merchant_raw_name**: {receipt.merchant_raw_name!r}",
            f"- **total_gross**: {_money(receipt.total_gross)}"
            f" · **total_vat**: {_money(receipt.total_vat)}"
            f" · **rounding**: {_money(receipt.rounding)}"
            f" · **discount_total**: {_money(receipt.discount_total)}",
            f"- **payment_method**: {receipt.payment_method}"
            f" · **confidence**: {receipt.confidence}",
        ]
        if receipt.review_reasons:
            lines.append(f"- **review_reasons**: {', '.join(receipt.review_reasons)}")
        if receipt.error:
            lines.append(f"- **error**: `{receipt.error}`")
        if export.attempt is not None:
            attempt = export.attempt
            lines.append(
                f"- **engine**: {attempt.extractor} / {attempt.model}"
                f" · tokens in/out {attempt.input_tokens}/{attempt.output_tokens}"
                f" · ${attempt.cost_usd}"
            )

        lines += [
            "",
            "| # | raw_name | kind | qty | unit | unit_price | gross | vat |",
            "|---|----------|------|-----|------|-----------|-------|-----|",
        ]
        for item in export.items:
            lines.append(
                f"| {item.line_no} | {item.raw_name} | {item.kind} | {item.quantity} "
                f"| {item.unit or ''} | {_money(item.unit_price)} | {_money(item.gross_amount)} "
                f"| {item.vat_code or ''} {item.vat_rate or ''} |"
            )

        if export.attempt is not None and export.attempt.raw_response:
            lines += [
                "",
                "<details><summary>raw model response</summary>",
                "",
                "```json",
                json.dumps(export.attempt.raw_response, ensure_ascii=False, indent=2),
                "```",
                "",
                "</details>",
            ]
        lines.append("")

    return "\n".join(lines)


def copy_images(exports: list[Export], out_dir: Path) -> tuple[int, list[str]]:
    """Put each photograph next to the reading it produced. Returns (copied, missing)."""
    images = out_dir / "images"
    images.mkdir(parents=True, exist_ok=True)

    copied, missing = 0, []
    for export in exports:
        for index, raw in enumerate(export.image_paths):
            source = Path(raw) if raw else None
            if source is None or not source.exists():
                missing.append(f"{export.short_id}: {raw or '(no path)'}")
                continue
            suffix = "" if index == 0 else f"-{index}"
            shutil.copy2(source, images / f"{export.short_id}{suffix}{source.suffix}")
            copied += 1
    return copied, missing


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("/data/export"))
    parser.add_argument("--limit", type=int, default=100)
    args = parser.parse_args()

    from app.db import SessionLocal

    async with SessionLocal() as session:
        exports = await collect(session, limit=args.limit)

    if not exports:
        print("Nothing unconfirmed - every receipt has been accepted.")
        return 0

    args.out.mkdir(parents=True, exist_ok=True)
    document = args.out / "unconfirmed.md"
    document.write_text(render(exports), encoding="utf-8")
    copied, missing = copy_images(exports, args.out)

    print(f"{len(exports)} receipt(s) -> {document}")
    print(f"{copied} image(s) -> {args.out / 'images'}")
    for gap in missing:
        print(f"  missing image {gap}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
