"""Image preparation before extraction.

This module is the biggest cost lever in the app. Claude bills an image at roughly
`(width * height) / 750` tokens, so a 12 MP phone photo would cost about 16k input tokens
while a 1600px-tall downscale of the same receipt costs around 3k and reads just as well -
till receipts are high-contrast text on white, not fine detail.
"""

from __future__ import annotations

import hashlib
import io

from PIL import Image, ImageOps


def _oriented_size(img: Image.Image) -> tuple[int, int]:
    """The (width, height) the image will have once EXIF rotation is applied."""
    # 5-8 are the transposing orientations; the rest keep the axes as stored.
    orientation = (img.getexif() or {}).get(0x0112, 1)
    return (img.height, img.width) if orientation in {5, 6, 7, 8} else (img.width, img.height)


def sha256_of(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def estimate_image_tokens(width: int, height: int) -> int:
    """Claude's image token estimate; used for cost projection before a call."""
    return int((width * height) / 750)


def target_size(width: int, height: int, max_edge: int, min_width: int) -> tuple[int, int]:
    """The size to downscale to: fit `max_edge`, but never starve the width below `min_width`.

    Capping the *longest* edge is the wrong rule for a till receipt. A receipt is a tall
    ribbon - a real one measured 1200x3757, and fitting that to a 1600px long edge leaves
    511px of width for about 40 characters a line. Legibility lives in the width; the height
    only carries more rows of the same text.

    So the long edge is a ceiling and the width is a floor, and the floor wins. Upscaling is
    never done - a floor cannot invent detail the photograph does not have.
    """
    scale = min(max_edge / max(width, height), 1.0)
    if width * scale < min_width:
        scale = min(min_width / width, 1.0)
    return max(int(width * scale), 1), max(int(height * scale), 1)


def prepare(
    data: bytes, max_edge: int = 1600, quality: int = 85, min_width: int = 800
) -> tuple[bytes, int, int]:
    """Normalise a receipt photo for extraction.

    Applies EXIF rotation (phones store portrait shots rotated), flattens transparency onto
    white, and downscales to fit `max_edge` without letting the width fall below `min_width`.
    Returns (jpeg_bytes, width, height).

    Colour is deliberately kept: chain logos and the red/highlighted discount lines on some
    receipts help the model tell an item from a promotion.
    """
    with Image.open(io.BytesIO(data)) as img:
        # Shrink first, convert second. Doing it the other way round means a palette or
        # transparent image is expanded to 4 bytes per pixel at full size and composited
        # onto a same-size canvas before anything shrinks it - which turned a 7 KB PNG
        # into 769 MB of resident memory. draft() additionally lets the JPEG decoder
        # produce a reduced-size image directly, so the common path never allocates the
        # full-resolution bitmap at all.
        # EXIF rotation has not been applied yet, so a portrait photo stored rotated still
        # reports its sides the other way round. Ask the size question in the orientation the
        # model will actually see, or a receipt would be measured across its length.
        oriented = _oriented_size(img)
        wanted = target_size(*oriented, max_edge=max_edge, min_width=min_width)
        # thumbnail() takes a bounding box and preserves aspect ratio, so passing the target
        # back in either orientation gives the same result.
        box = (max(wanted), max(wanted))
        img.draft("RGB", box)
        img.thumbnail(box, Image.Resampling.LANCZOS, reducing_gap=2.0)

        # Phones store portrait shots rotated; apply that to the now-small image.
        img = ImageOps.exif_transpose(img)

        if img.mode in ("RGBA", "LA", "P"):
            img = img.convert("RGBA")
            background = Image.new("RGB", img.size, (255, 255, 255))
            background.paste(img, mask=img.split()[-1])
            img = background
        elif img.mode != "RGB":
            img = img.convert("RGB")

        out = io.BytesIO()
        img.save(out, format="JPEG", quality=quality, optimize=True)
        return out.getvalue(), img.width, img.height
