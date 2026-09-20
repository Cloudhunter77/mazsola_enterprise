"""The fixed category tree.

Fixed, and small, on purpose. The model is asked to pick a slug from this list rather
than invent one, because a free-text category produces `konyhai eszköz`, `konyhai
eszközök`, `konyha` and `edény` for the same drawer, and no statistic survives that. A
slug the list does not contain is not trusted - `rules` files it under `egyeb` instead.
"""

from __future__ import annotations

# slug, Hungarian name, icon
CATEGORIES: tuple[tuple[str, str, str], ...] = (
    ("butor", "Bútor", "🪑"),
    ("elektronika", "Elektronika", "🔌"),
    ("haztartasi-gep", "Háztartási gép", "🧺"),
    ("konyha", "Konyhai eszköz", "🍳"),
    ("szerszam", "Szerszám", "🔧"),
    ("kerti", "Kerti eszköz", "🌿"),
    ("sport", "Sport és szabadidő", "🚲"),
    ("ruhazat", "Ruházat", "👕"),
    ("konyv-media", "Könyv és média", "📚"),
    ("jatek", "Játék", "🧸"),
    ("dekoracio", "Dekoráció", "🖼️"),
    ("textil", "Lakástextil", "🛏️"),
    ("irodaszer", "Irodaszer", "✏️"),
    ("hangszer", "Hangszer", "🎸"),
    ("jarmu", "Jármű és tartozék", "🚗"),
    ("dokumentum", "Dokumentum", "📄"),
    ("egyeb", "Egyéb", "📦"),
)

FALLBACK_SLUG = "egyeb"

SLUGS = frozenset(slug for slug, _, _ in CATEGORIES)
NAMES: dict[str, str] = {slug: name for slug, name, _ in CATEGORIES}
