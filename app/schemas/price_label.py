"""The extraction contract for shelf labels.

Separate from `ExtractedReceipt` because the documents are not alike. A receipt is one
transaction with many lines and a total that has to balance; a photograph of a shelf strip
is several independent labels with nothing tying them together - no total, no arithmetic
to check, and no guarantee that two labels beside each other are related at all.

That difference matters for how errors are caught. A receipt is checked by its own
arithmetic. A label has only one internal check worth anything: price, package size and
egységár have to agree, because Hungarian law makes the shop print all three.

Every field is required-but-nullable, as in the receipt contract: strict JSON-schema output
works best when the model must emit each key and say `null` rather than omit it.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ExtractedPriceLabel(BaseModel):
    """One shelf label read off a photograph."""

    line_no: int = Field(description="1-based position, left to right then top to bottom.")
    raw_name: str = Field(
        description="The product name exactly as printed on the label, abbreviations intact."
    )

    price: float | None = Field(
        description=(
            "The price you would pay today, in HUF, the large figure on the label. "
            "If the label shows a promotional price and a crossed-out one, this is the "
            "promotional price."
        )
    )
    price_printed: str | None = Field(
        description=(
            "That same price copied character for character, spaces and all, e.g. '1 299'. "
            "Copy first, convert second."
        )
    )

    unit_price: float | None = Field(
        description=(
            "The egységár - price per kilogram, litre or piece - as printed. Hungarian "
            "labels must show it, usually smaller and beside or below the price."
        )
    )
    unit: str | None = Field(
        description="The unit the egységár is per: kg, l, db. Null if none is printed."
    )

    package_size: float | None = Field(
        description="Package size as a number, e.g. 0.5 for a 0,5 l bottle or 300 for 300 g."
    )
    package_unit: str | None = Field(description="Unit of the package size: l, ml, kg, g, db.")

    is_promotion: bool = Field(
        description=(
            "True when the label advertises a temporary price: akció, akciós ár, a "
            "crossed-out original, a loyalty-card price, or a validity date."
        )
    )
    regular_price: float | None = Field(
        description="The crossed-out or 'eredeti ár' price, when one is shown. Else null."
    )
    promotion_until: str | None = Field(
        description="Last day the promotion is valid, as YYYY-MM-DD. Null if not printed."
    )

    confidence: float = Field(description="0-1 confidence that this label was read correctly.")


class ExtractedPriceLabels(BaseModel):
    """Everything readable in one photograph of a shelf."""

    merchant_name: str | None = Field(
        description=(
            "The shop, ONLY if the label itself is branded with it. Most shelf labels are "
            "not - return null rather than guessing from the look of the shelf."
        )
    )
    labels: list[ExtractedPriceLabel] = Field(
        description="Every distinct price label legible in the photograph."
    )
    notes: str | None = Field(
        description="Anything unreadable or ambiguous, in one short sentence. Else null."
    )
