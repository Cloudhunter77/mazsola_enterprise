"""Render a synthetic Hungarian till receipt as a test image.

This exists so `pytest -m live` has something to run against before you have added
photos of your own. It is a clean rendering, not a photo of thermal paper, so passing
on it is a floor rather than a guarantee - the real accuracy tuning needs real
receipts in tests/fixtures/receipts/.

    python scripts/make_test_receipt.py tests/fixtures/receipts/synthetic_tesco.jpg
"""

from __future__ import annotations

import random
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"
WIDTH, MARGIN, LINE_HEIGHT = 620, 26, 26

# The expected reading, so a live test can assert against it.
EXPECTED = {
    "merchant": "Tesco",
    "total_gross": 5235.0,   # a cash total is always a multiple of 5 Ft
    "subtotal": 5238.0,      # before the kerekítés line
    "rounding": -3.0,
    "discount_total": 1088.0,
    "goods_lines": 6,        # plus one deposit, one discount and one rounding line
    "vat_rates": {27.0, 18.0, 5.0},
}

LINES: list[tuple[str, str]] = [
    ("center", "TESCO-GLOBAL ÁRUHÁZAK ZRT."),
    ("center", "2040 Budaörs, Kinizsi út 1-3."),
    ("center", "Adószám: 10307078-2-44"),
    ("sep", ""),
    ("center", "N Y U G T A"),
    ("sep", ""),
    ("pair", "TEJ 2,8% 1L UHT|B"),
    ("pair", "  4 db x 379|1 516"),
    ("pair", "FEHÉR KENYÉR 1KG|B"),
    ("pair", "  1 db x 569|569"),
    ("pair", "ALMA IDARED|C"),
    ("pair", "  0,412 kg x 599 Ft/kg|247"),
    ("pair", "COCA COLA 1,75L|A"),
    ("pair", "  2 db x 649|1 298"),
    ("pair", "BETÉTDÍJ|A"),
    ("pair", "  2 db x 50|100"),
    ("pair", "MOSOGATÓSZER 1L|A"),
    ("pair", "  1 db x 1 099|1 099"),
    ("pair", "ŐRÖLT KÁVÉ 250G|A"),
    ("pair", "  1 db x 1 497|1 497"),
    ("pair", "KEDVEZMÉNY AKCIÓ|-1 088"),
    ("sep", ""),
    ("pair", "ÖSSZESEN:|5 238"),
    ("pair", "KEREKÍTÉS:|-3"),
    ("pair", "FIZETENDŐ:|5 235"),
    ("sep", ""),
    ("pair", "KÉSZPÉNZ:|10 000"),
    ("pair", "VISSZAJÁRÓ:|4 765"),
    ("sep", ""),
    ("left", "ÁFA ÖSSZESÍTŐ"),
    ("pair", "A 27%  alap 2 288  áfa 618|2 906"),
    ("pair", "B 18%  alap 1 767  áfa 318|2 085"),
    ("pair", "C  5%  alap   235  áfa  12|247"),
    ("sep", ""),
    ("center", "Ön ma megtakarított: 1 088 Ft"),
    ("center", "2026.08.14. 17:22"),
    ("center", "Nyugtaszám: NY-000123"),
    ("center", "AP A12345678"),
    ("center", "Köszönjük, hogy nálunk vásárolt!"),
]


def render(target: Path, noise: bool = True) -> None:
    height = MARGIN * 2 + LINE_HEIGHT * len(LINES)
    image = Image.new("RGB", (WIDTH, height), (252, 251, 247))
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype(FONT_PATH, 17)
    bold = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf", 17)

    y = MARGIN
    for kind, text in LINES:
        if kind == "sep":
            draw.line([(MARGIN, y + 12), (WIDTH - MARGIN, y + 12)], fill=(160, 158, 150), width=1)
        elif kind == "center":
            width = draw.textlength(text, font=font)
            draw.text(((WIDTH - width) / 2, y), text, font=font, fill=(28, 28, 28))
        elif kind == "left":
            draw.text((MARGIN, y), text, font=bold, fill=(28, 28, 28))
        else:
            left, _, right = text.partition("|")
            draw.text((MARGIN, y), left, font=font, fill=(28, 28, 28))
            width = draw.textlength(right, font=font)
            draw.text((WIDTH - MARGIN - width, y), right, font=font, fill=(28, 28, 28))
        y += LINE_HEIGHT

    if noise:
        # A little speckle and a slight rotation, so it is not a perfectly clean render.
        pixels = image.load()
        random.seed(3)
        for _ in range(int(WIDTH * height * 0.004)):
            x, ny = random.randrange(WIDTH), random.randrange(height)
            shade = random.randint(170, 235)
            pixels[x, ny] = (shade, shade, shade - 4)
        image = image.rotate(-0.7, expand=True, fillcolor=(252, 251, 247), resample=Image.BICUBIC)

    target.parent.mkdir(parents=True, exist_ok=True)
    image.save(target, quality=88)
    print(f"wrote {target} ({image.width}x{image.height})")


if __name__ == "__main__":
    default = "tests/fixtures/receipts/synthetic_tesco.jpg"
    destination = Path(sys.argv[1] if len(sys.argv) > 1 else default)
    render(destination)
