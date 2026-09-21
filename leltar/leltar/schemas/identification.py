"""What the model is asked to return for one photograph.

This is the schema the engine validates against, so every field here is a promise the
model has to keep. The fields that look redundant - `markings_legible`, `serial_visible` -
are the ones that carry the most weight: they separate what was *read* in the photograph
from what was *inferred* from the shape of a thing, and only the first kind survives
`leltar.extraction.rules`.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Condition = Literal["new", "good", "used", "worn", "broken", "unknown"]


# Every field below has a default, so without this an unrelated JSON object - a model
# ignoring the schema and answering in its own shape - would validate into an empty
# result and be reported as "nothing nameable in this photograph". Forbidding unknown
# keys turns that into the engine error it actually is. Strict structured output already
# sends `additionalProperties: false`, so a compliant provider never notices.
STRICT = ConfigDict(extra="forbid")


class Box(BaseModel):
    """Where the object is in the frame, in thousandths of the image, origin top-left.

    Thousandths rather than pixels: the model never sees the original resolution - it is
    handed a downscale - so a pixel box would be in the wrong units the moment the size
    cap changed. A fraction of the frame is true at any size.

    This is what gives every item its own picture even when eight of them were
    photographed together: the box is cropped out of the original photograph, at full
    resolution, and becomes that item's thumbnail.
    """

    model_config = STRICT

    x0: int = Field(ge=0, le=1000, description="Left edge, 0-1000.")
    y0: int = Field(ge=0, le=1000, description="Top edge, 0-1000.")
    x1: int = Field(ge=0, le=1000, description="Right edge, 0-1000.")
    y1: int = Field(ge=0, le=1000, description="Bottom edge, 0-1000.")


class IdentifiedObject(BaseModel):
    model_config = STRICT

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

    box: Box | None = Field(
        default=None,
        description=(
            "A tight box around this object, in thousandths of the image. Leave it out "
            "rather than guessing: a box in the wrong place is worse than none, because "
            "it becomes the picture of this item."
        ),
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
    model_config = STRICT

    scene: str | None = Field(
        default=None,
        description="One short Hungarian phrase for what the photograph shows as a whole.",
    )
    objects: list[IdentifiedObject] = Field(default_factory=list)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    notes: str | None = Field(
        default=None, description="Anything that made this photograph hard to read."
    )
