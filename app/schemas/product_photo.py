"""The extraction contract for a photograph of a product itself.

Not a receipt and not a shelf label: a picture of the thing, taken because you want more of
it. There is no arithmetic here and no price - only a name, and the honest admission that
the name might be unreadable.

That admission matters more than usual. A wrong name on a shopping list sends you to the
wrong shelf, but a wrong name that *matches an existing product* is worse: it attaches your
list item to the wrong price history. So the contract asks separately for what is printed
and for how sure the model is, and the caller only trusts a reading that resolves exactly.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ExtractedProductPhoto(BaseModel):
    """What one photograph of a product says about which product it is."""

    raw_name: str | None = Field(
        description=(
            "The product name as printed on the packaging: brand and variety, e.g. "
            "'Pilos UHT tej 2,8%' or 'Choceur tejcsokoládé'. Null if no name is legible."
        )
    )
    brand: str | None = Field(description="The brand alone, if one is printed. Else null.")
    package_size: float | None = Field(
        description="Package size as a number from the packaging, e.g. 1.5, 300. Else null."
    )
    package_unit: str | None = Field(description="Unit of that size: l, ml, kg, g, db.")
    category_hint: str | None = Field(
        description=(
            "What kind of thing this is in one or two Hungarian words - 'tej', 'mosópor', "
            "'csokoládé' - for when the brand is unreadable but the object is obvious."
        )
    )
    confidence: float = Field(
        description=(
            "0-1 that `raw_name` is what the packaging actually says. Be strict: 0.9+ only "
            "when the text is legible in the photograph, below 0.5 when you are inferring "
            "the product from its shape or colour rather than reading it."
        )
    )
    notes: str | None = Field(description="Anything unclear, in one short sentence. Else null.")
