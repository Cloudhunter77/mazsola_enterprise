"""What the model is asked to return for one photograph.

This is the schema the engine validates against, so every field here is a promise the
model has to keep. The fields that look redundant - `markings_legible`, `serial_visible` -
are the ones that carry the most weight: they separate what was *read* in the photograph
from what was *inferred* from the shape of a thing, and only the first kind survives
`leltar.extraction.rules`.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Condition = Literal["new", "good", "used", "worn", "broken", "unknown"]


class IdentifiedObject(BaseModel):
    name: str = Field(
        description=(
            "Hungarian name for this object, as you would write it on a moving box. "
            "Specific: 'fehér porcelán bögre', not 'bögre'; 'akkus fúrógép', not 'szerszám'."
        )
    )
    category: str = Field(description="One slug from the list given in the instruction.")

    brand: str | None = Field(
        default=None,
        description="Only if a logo or brand name is actually legible in the photograph.",
    )
    product_model: str | None = Field(
        default=None,
        description="Model name or number, only if legible in the photograph.",
    )
    markings_legible: bool = Field(
        default=False,
        description=(
            "True only if brand or model text is genuinely readable in this photograph. "
            "False if you are inferring the make from the shape, colour or your knowledge "
            "of similar products."
        ),
    )

    colour: str | None = Field(default=None, description="Main colour, in Hungarian.")
    material: str | None = Field(
        default=None, description="Main material in Hungarian (fa, fém, műanyag, üveg, textil)."
    )
    condition: Condition = Field(
        default="unknown",
        description="From visible wear only. 'unknown' if the photograph does not show it.",
    )
    quantity: int = Field(
        default=1,
        description=(
            "How many identical copies of this object are visible. Group identical things "
            "into one entry with a count rather than repeating them."
        ),
    )

    value_low_huf: int | None = Field(
        default=None, description="Low end of the second-hand replacement value, in HUF."
    )
    value_high_huf: int | None = Field(
        default=None, description="High end of the second-hand replacement value, in HUF."
    )

    serial_number: str | None = Field(
        default=None, description="Only if a serial or IMEI is legible in the photograph."
    )
    serial_visible: bool = Field(
        default=False, description="True only if the serial number was read from the image."
    )

    description: str | None = Field(
        default=None, description="One short Hungarian sentence, only if it adds something."
    )
    alternatives: list[str] = Field(
        default_factory=list,
        description=(
            "Up to three other plausible Hungarian names for the same object, best first. "
            "Empty when the object is unmistakable."
        ),
    )
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)


class IdentifiedPhoto(BaseModel):
    scene: str | None = Field(
        default=None,
        description="One short Hungarian phrase for what the photograph shows as a whole.",
    )
    objects: list[IdentifiedObject] = Field(default_factory=list)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    notes: str | None = Field(
        default=None, description="Anything that made this photograph hard to read."
    )
