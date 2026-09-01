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


def sha256_of(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def estimate_image_tokens(width: int, height: int) -> int:
    """Claude's image token estimate; used for cost projection before a call."""
    return int((width * height) / 750)


def prepare(data: bytes, max_edge: int = 1600, quality: int = 85) -> tuple[bytes, int, int]:
    """Normalise a receipt photo for extraction.

    Applies EXIF rotation (phones store portrait shots rotated), flattens transparency onto
    white, and downscales the longest edge to `max_edge`. Returns (jpeg_bytes, width, height).

    Colour is deliberately kept: chain logos and the red/highlighted discount lines on some
    receipts help the model tell an item from a promotion.
    """
    with Image.open(io.BytesIO(data)) as img:
        img = ImageOps.exif_transpose(img)

        if img.mode in ("RGBA", "LA", "P"):
            img = img.convert("RGBA")
            background = Image.new("RGB", img.size, (255, 255, 255))
            background.paste(img, mask=img.split()[-1])
            img = background
        elif img.mode != "RGB":
            img = img.convert("RGB")

        longest = max(img.size)
        if longest > max_edge:
            scale = max_edge / longest
            new_size = (max(1, round(img.width * scale)), max(1, round(img.height * scale)))
            img = img.resize(new_size, Image.Resampling.LANCZOS)

        out = io.BytesIO()
        img.save(out, format="JPEG", quality=quality, optimize=True)
        return out.getvalue(), img.width, img.height
