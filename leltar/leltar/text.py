"""Hungarian text, folded flat for comparing and searching.

Hungarian has nine accented vowels and a keyboard where typing them on a phone is a long
press each. Nobody searching their own house for a bögre is going to type the umlaut, so
what is stored for searching, and what is typed into the box, both go through here first.

The same folding decides whether you actually changed the model's suggested name: retyping
"Bögre" as "bogre" is not a correction, and counting it as one would push the accuracy
figure in the wrong direction for no reason.
"""

from __future__ import annotations

import re
import unicodedata


def fold(text: str | None) -> str:
    """Lowercase, strip accents, drop punctuation. For matching only, never for storing."""
    if not text:
        return ""
    stripped = unicodedata.normalize("NFKD", text.lower())
    without_accents = "".join(char for char in stripped if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", " ", without_accents).strip()


def fold_tight(text: str | None) -> str:
    """As `fold`, but with the spaces gone too - for "is this the same name" questions."""
    return fold(text).replace(" ", "")


def searchable(*parts: str | None) -> str:
    """The haystack for one item: every field worth finding it by, folded into one string.

    Stored on the row rather than computed per query, because `ILIKE` over four columns
    with accents intact cannot match what a person actually types, and a folded expression
    over four columns cannot use an index.
    """
    return " ".join(folded for folded in (fold(part) for part in parts) if folded)
