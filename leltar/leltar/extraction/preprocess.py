"""Image preparation before identification.

This module is the biggest cost lever in the app: an image bills at roughly
`(width * height) / 750` tokens, so a 12 MP phone photo costs about 16k input tokens while
a 1280px downscale of the same scene costs around 1.6k.

Unlike the receipt scanner next door, there is no floor on the width here. That floor
exists to keep small printed characters legible on a tall ribbon of paper; an object is
recognised by shape, colour and proportion, and a plain longest-edge cap is the right rule
for a photograph of a room. The one thing lost at 1280px is small printed text - which is
exactly the brand and serial number the rules refuse to trust unless it is legible. So the
cap and the honesty rule agree: if it cannot be read at this size, it is not recorded.
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
    """The image token estimate; used for cost projection before a call."""
    return int((width * height) / 750)


def target_size(width: int, height: int, max_edge: int) -> tuple[int, int]:
    """Fit the longest edge to `max_edge`. Never upscales: a cap cannot invent detail."""
    scale = min(max_edge / max(width, height), 1.0)
    return max(int(width * scale), 1), max(int(height * scale), 1)


def prepare(data: bytes, max_edge: int = 1280, quality: int = 85) -> tuple[bytes, int, int]:
    """Normalise a photograph for identification.

    Applies EXIF rotation (phones store portrait shots rotated), flattens transparency onto
    white, and downscales to fit `max_edge`. Returns (jpeg_bytes, width, height).
    """
    with Image.open(io.BytesIO(data)) as img:
        # Shrink first, convert second. The other way round, a palette or transparent image
        # is expanded to 4 bytes per pixel at full size and composited onto a same-size
        # canvas before anything shrinks it - which turns a small PNG into hundreds of MB
        # of resident memory on a NAS. draft() additionally lets the JPEG decoder produce a
        # reduced-size image directly, so the common path never allocates the full bitmap.
        # EXIF rotation has not been applied yet, so ask the size question in the
        # orientation the model will actually see.
        oriented = _oriented_size(img)
        wanted = target_size(*oriented, max_edge=max_edge)
        # thumbnail() takes a bounding box and preserves aspect ratio, so passing the target
        # back in either orientation gives the same result.
        box = (max(wanted), max(wanted))
        img.draft("RGB", box)
        img.thumbnail(box, Image.Resampling.LANCZOS, reducing_gap=2.0)

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
