"""Making one picture per item out of one photograph.

An inventory you can only read is not much use for the thing an inventory is for -
recognising which of your two drills the entry means. So every item gets a picture, and
where the model located the object in the frame, that picture is the object rather than
the shelf it stood on.

Crops come from the **original** photograph, not the downscale sent to the model: the
downscale exists to keep the API bill small, and cropping a tenth of it would give a
thumbnail barely bigger than an icon.
"""

from __future__ import annotations

import io
import logging
import uuid
from pathlib import Path

from PIL import Image, ImageOps

from leltar.schemas.identification import Box

log = logging.getLogger(__name__)

# The longest edge of a stored item picture. Big enough to fill a phone screen on the item
# page, small enough that a house full of things is tens of megabytes rather than
# gigabytes - and it is derived data either way, rebuildable from the photograph.
THUMBNAIL_EDGE = 900

# A tight box against the object's own edges looks like a mistake once it is a thumbnail;
# this much of the box's size is added on each side, then clipped to the photograph.
PADDING = 0.06

JPEG_QUALITY = 85


def crop_box(box: Box | None, width: int, height: int) -> tuple[int, int, int, int] | None:
    """Turn a box in thousandths into padded pixel coordinates for this photograph."""
    if box is None:
        return None

    x0 = box.x0 / 1000 * width
    x1 = box.x1 / 1000 * width
    y0 = box.y0 / 1000 * height
    y1 = box.y1 / 1000 * height

    pad_x = (x1 - x0) * PADDING
    pad_y = (y1 - y0) * PADDING

    left = max(0, int(x0 - pad_x))
    top = max(0, int(y0 - pad_y))
    right = min(width, int(x1 + pad_x))
    bottom = min(height, int(y1 + pad_y))

    if right - left < 2 or bottom - top < 2:
        return None
    return left, top, right, bottom


def render(data: bytes, box: Box | None) -> tuple[bytes, int, int]:
    """One item's picture: the boxed region if there is one, else the whole photograph.

    Returns (jpeg_bytes, width, height). Raises OSError if the photograph cannot be read,
    which the caller treats as "this item has no picture" rather than as a failure of the
    identification - the names are the valuable part and they are already in hand.
    """
    with Image.open(io.BytesIO(data)) as img:
        # Phones store portrait shots rotated, and the model was shown the rotated version,
        # so a box is in *those* coordinates. Straightening first is what makes the crop
        # land on the object rather than ninety degrees away from it.
        img = ImageOps.exif_transpose(img)

        if img.mode != "RGB":
            img = img.convert("RGB")

        region = crop_box(box, img.width, img.height)
        if region is not None:
            img = img.crop(region)

        img.thumbnail((THUMBNAIL_EDGE, THUMBNAIL_EDGE), Image.Resampling.LANCZOS)

        out = io.BytesIO()
        img.save(out, format="JPEG", quality=JPEG_QUALITY, optimize=True)
        return out.getvalue(), img.width, img.height


def storage_path(root: Path, item_id: uuid.UUID, taken: str) -> Path:
    """Bucketed by the photograph's year and month, like the originals beside them."""
    directory = root / taken
    directory.mkdir(parents=True, exist_ok=True)
    return directory / f"{item_id}.jpg"
