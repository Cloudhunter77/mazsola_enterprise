"""Draw a synthetic 'shelf' image, so the documented smoke test has something to run on.

    python scripts/make_test_photo.py tests/fixtures/shelf.jpg

It is a drawing, not a photograph: shapes on a shelf, with one object carrying a legible
brand label and one carrying nothing. That is enough to exercise the whole path - the
engine, the evidence rules, the cost accounting - without shipping a picture of somebody's
actual living room in a public container image.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw

WIDTH, HEIGHT = 1200, 800
WALL = (232, 228, 219)
SHELF = (168, 134, 96)


def draw(path: Path) -> None:
    image = Image.new("RGB", (WIDTH, HEIGHT), WALL)
    canvas = ImageDraw.Draw(image)

    # Two shelf boards.
    for y in (430, 700):
        canvas.rectangle([80, y, WIDTH - 80, y + 26], fill=SHELF)

    # A mug, on the upper shelf.
    canvas.rounded_rectangle([180, 320, 300, 430], radius=12, fill=(250, 250, 248),
                             outline=(190, 188, 182), width=3)
    canvas.arc([290, 340, 350, 400], start=270, end=90, fill=(190, 188, 182), width=8)

    # A stack of books.
    for index, colour in enumerate([(120, 60, 60), (60, 90, 130), (80, 110, 70)]):
        top = 430 - (index + 1) * 34
        canvas.rectangle([420, top, 660, top + 30], fill=colour, outline=(40, 40, 40))

    # A box with a legible label - the one object whose "brand" may be trusted.
    canvas.rectangle([760, 300, 1050, 430], fill=(196, 178, 150), outline=(140, 120, 96), width=4)
    canvas.rectangle([800, 340, 1010, 392], fill=(252, 252, 250))
    canvas.text((820, 356), "SZERSZAM", fill=(30, 30, 30))

    # A potted plant on the lower shelf, and a lamp beside it.
    canvas.polygon([(200, 700), (300, 700), (285, 610), (215, 610)], fill=(150, 90, 70))
    canvas.ellipse([190, 520, 310, 620], fill=(70, 120, 70))
    canvas.polygon([(560, 700), (700, 700), (630, 590)], fill=(90, 90, 96))
    canvas.ellipse([580, 520, 680, 600], fill=(240, 226, 180))

    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, format="JPEG", quality=88)
    print(f"wrote {path} ({path.stat().st_size // 1024} KB)")


def main() -> None:
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("tests/fixtures/shelf.jpg")
    draw(target)


if __name__ == "__main__":
    main()
