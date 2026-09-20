"""What to believe from an identification, and what to throw away.

The model's answer is never rejected wholesale - a photograph that produced eight good
entries and one invented brand is worth keeping. So every rule here either *clears* a
field it cannot trust or *flags* the entry for review, and the reasons travel with the
item so the review screen can say why it is asking.

Every rule is pure: a parsed `IdentifiedPhoto` in, a cleaned one and a list of reasons
out. No database, no API, no images - which is why they are cheap to test, and they are
the part of this app most worth testing.
"""

from __future__ import annotations

import re
import unicodedata
from decimal import Decimal

from leltar.extraction.categories import FALLBACK_SLUG, SLUGS
from leltar.schemas.identification import IdentifiedObject, IdentifiedPhoto

# A name that could be written on the box without looking inside it. These are the words a
# model reaches for when it does not know, and they are worse than useless in a search:
# "tárgy" matches everything and tells you nothing.
GENERIC_NAMES = frozenset({
    "targy", "dolog", "eszkoz", "valami", "objektum", "keszulek", "ismeretlen",
    "item", "object", "thing", "unknown", "egyeb", "cucc", "holmi",
})

# Words that carry no information on their own. They matter only when everything else in
# a name is already generic: "egy tárgy" has to fail the same test "tárgy" does.
FILLER_WORDS = frozenset({
    "egy", "az", "ez", "ezek", "ilyen", "olyan", "valamilyen", "nehany", "masik", "kb",
})

# Below this, the guess is a coin flip and goes to review rather than into the inventory.
MIN_OBJECT_CONFIDENCE = 0.55
MIN_PHOTO_CONFIDENCE = 0.45

# A range wider than this says "somewhere between a mug and a motorbike", which is not an
# estimate. Kept generous: honest uncertainty about a used appliance really is 5-10x.
MAX_VALUE_SPREAD = 40

# Nothing movable in a home is worth more than this; a larger figure is a slipped digit or
# a model pricing something it thinks is an antique.
MAX_PLAUSIBLE_VALUE_HUF = 5_000_000

MAX_QUANTITY = 99
MAX_ALTERNATIVES = 3


def _fold(text: str) -> str:
    """Lowercase, strip accents and punctuation - for comparing names, never for storing."""
    stripped = unicodedata.normalize("NFKD", text.lower())
    without_accents = "".join(char for char in stripped if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", "", without_accents)


def is_generic(name: str) -> bool:
    """Whether a name says nothing that would help you find the object again."""
    folded = _fold(name)
    if not folded:
        return True
    if folded in GENERIC_NAMES:
        return True
    # "egy tárgy", "ismeretlen eszköz": a generic head word with nothing but filler on it.
    words = [_fold(word) for word in re.split(r"\s+", name) if _fold(word)]
    meaningful = [
        word
        for word in words
        if word not in GENERIC_NAMES and word not in FILLER_WORDS and len(word) > 2
    ]
    return not meaningful


def names_match(left: str | None, right: str | None) -> bool:
    """Whether two names are the same name, ignoring case, accents and spacing.

    Used to decide whether you actually changed the model's suggestion: retyping "Bögre"
    as "bogre" is not a correction, and counting it as one would flatter nothing and
    mislead the accuracy figure in the wrong direction.
    """
    if left is None or right is None:
        return False
    return _fold(left) == _fold(right)


def midpoint(low: int | None, high: int | None) -> Decimal | None:
    """One number for the statistics, rounded to 100 Ft so it cannot look like a valuation."""
    values = [value for value in (low, high) if value is not None]
    if not values:
        return None
    middle = sum(values) / len(values)
    return Decimal(round(middle / 100) * 100)


def clean_object(raw: IdentifiedObject) -> tuple[IdentifiedObject, list[str]]:
    """Return a trustworthy copy of one identified object, plus why it may need a look."""
    reasons: list[str] = []
    obj = raw.model_copy(deep=True)

    obj.name = " ".join(obj.name.split())
    if is_generic(obj.name):
        reasons.append("generic_name")

    # The evidence flags do all the work here: a brand the model read off a label stays, a
    # brand it deduced from the silhouette does not.
    if not obj.markings_legible and (obj.brand or obj.product_model):
        obj.brand = None
        obj.product_model = None
        reasons.append("unverifiable_brand")

    if obj.serial_number and not obj.serial_visible:
        obj.serial_number = None
        reasons.append("unverifiable_serial")

    if obj.category not in SLUGS:
        obj.category = FALLBACK_SLUG
        reasons.append("unknown_category")

    low, high = obj.value_low_huf, obj.value_high_huf
    if low is not None and high is not None and low > high:
        low, high = high, low
    if low is not None and low < 0:
        low = None
    if high is not None and high < 0:
        high = None
    if low is None and high is None:
        reasons.append("no_value_estimate")
    else:
        if high is not None and high > MAX_PLAUSIBLE_VALUE_HUF:
            reasons.append("implausible_value")
        # A zero low end makes every spread infinite, so compare against at least 1 Ft.
        if low is not None and high is not None and high > max(low, 1) * MAX_VALUE_SPREAD:
            reasons.append("wide_value_range")
    obj.value_low_huf, obj.value_high_huf = low, high

    if obj.quantity < 1:
        obj.quantity = 1
    elif obj.quantity > MAX_QUANTITY:
        obj.quantity = MAX_QUANTITY
        reasons.append("implausible_quantity")

    # An alternative identical to the name is not an alternative, and the list is a UI of
    # one-tap buttons - four of them is a menu, not a shortcut.
    seen = {_fold(obj.name)}
    unique: list[str] = []
    for candidate in obj.alternatives:
        folded = _fold(candidate)
        if folded and folded not in seen:
            seen.add(folded)
            unique.append(" ".join(candidate.split()))
    obj.alternatives = unique[:MAX_ALTERNATIVES]

    if obj.confidence < MIN_OBJECT_CONFIDENCE:
        reasons.append("low_confidence_object")

    return obj, reasons


def clean_photo(
    raw: IdentifiedPhoto, max_items: int
) -> tuple[IdentifiedPhoto, list[str], list[list[str]]]:
    """Clean a whole identification.

    Returns the cleaned photo, the reasons that belong to the photograph itself, and one
    list of reasons per surviving object, in the same order.
    """
    photo_reasons: list[str] = []
    photo = raw.model_copy(deep=True)

    objects = list(photo.objects)
    if not objects:
        photo_reasons.append("no_objects")
    if len(objects) > max_items:
        # Keep the most confident ones: past the limit these are background clutter, and
        # the confident entries are the subject of the photograph.
        objects = sorted(objects, key=lambda obj: obj.confidence, reverse=True)[:max_items]
        photo_reasons.append("too_many_objects")

    cleaned: list[IdentifiedObject] = []
    per_object: list[list[str]] = []
    for obj in objects:
        clean, reasons = clean_object(obj)
        cleaned.append(clean)
        per_object.append(reasons)

    # Two rows with the same name from one photograph are the same thing counted twice -
    # the model looked at one bookshelf from two angles in the same frame. Merge them,
    # taking the larger count, rather than making the person delete duplicates by hand.
    merged: list[IdentifiedObject] = []
    merged_reasons: list[list[str]] = []
    by_name: dict[str, int] = {}
    for obj, reasons in zip(cleaned, per_object, strict=True):
        key = _fold(obj.name)
        if key in by_name:
            index = by_name[key]
            merged[index].quantity = max(merged[index].quantity, obj.quantity)
            continue
        by_name[key] = len(merged)
        merged.append(obj)
        merged_reasons.append(reasons)

    photo.objects = merged
    if photo.confidence < MIN_PHOTO_CONFIDENCE:
        photo_reasons.append("low_confidence")

    if photo.scene:
        photo.scene = " ".join(photo.scene.split())[:300]

    return photo, photo_reasons, merged_reasons


def needs_review(photo_reasons: list[str], object_reasons: list[list[str]]) -> bool:
    """Whether a person has to look at this photograph before its items are trusted.

    Any flag at all, on the photograph or on any one of its objects. The review screen is
    the normal path in this app, not an exception - approving a name is the point - so
    this decides what gets a badge, not what gets shown.
    """
    return bool(photo_reasons) or any(object_reasons)
