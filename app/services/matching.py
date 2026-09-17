"""Deciding when two printed line names are the same product.

Tills abbreviate differently in every chain: `PEPSI 1,5L`, `Pepsi Cola 1.5 l`, `PEPSI COLA
1500ML`. All three are one product and one price history; left unmapped they are three, and
the cheapest-shop comparison has nothing to compare.

The matching here is deliberately **rule-based rather than a model call**: it is free,
instant, the same answer every time, and - the part that matters for a screen that asks you
to confirm - the score can be explained by pointing at the tokens. A model pass over the
leftovers is a reasonable future addition; starting there would have made every grouping
unexplainable and cost money per receipt.

Two rules do most of the work:

* **Size is part of identity.** Pepsi 1.5 l and Pepsi 0.5 l are different products, because
  500 Ft for each is not the same price and merging them makes unit-price history
  meaningless. Sizes are normalised first (1500 ml *is* 1.5 l) and then compared, so the
  rule catches genuine matches rather than just identical spellings.
* **Only an exact normalised match is automatic.** Everything else is a suggestion for a
  person, because a wrong link corrupts price history quietly and is not noticed for months.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from difflib import SequenceMatcher

from app.services.catalog import fold

# Everything is reduced to a base unit so 1500 ml and 1,5 l land on the same value.
UNIT_TO_BASE: dict[str, tuple[str, Decimal]] = {
    "l": ("l", Decimal(1)), "liter": ("l", Decimal(1)), "litre": ("l", Decimal(1)),
    "dl": ("l", Decimal("0.1")), "cl": ("l", Decimal("0.01")),
    "ml": ("l", Decimal("0.001")),
    "kg": ("kg", Decimal(1)), "dkg": ("kg", Decimal("0.01")), "g": ("kg", Decimal("0.001")),
    "gr": ("kg", Decimal("0.001")),
    "db": ("db", Decimal(1)), "pár": ("db", Decimal(1)), "par": ("db", Decimal(1)),
}

# `1,5 l`, `1.5L`, `150ml`, `500 g`, `2x1,5l` - the trailing group is the one that counts.
SIZE_PATTERN = re.compile(
    r"(?<![a-z0-9])(\d+(?:[.,]\d+)?)\s*(" + "|".join(sorted(UNIT_TO_BASE, key=len, reverse=True))
    + r")(?![a-z])",
    re.IGNORECASE,
)

# Shelf noise that says nothing about which product this is.
NOISE_TOKENS = frozenset({
    "akcio", "akcios", "uj", "new", "bio", "eredeti", "original", "csom", "csomag",
    "kiszereles", "termek", "ft", "x", "db",
})

# An identical normalised name. Anything below this is a suggestion, never automatic.
EXACT = Decimal("1")
# Above this a pair is worth showing as a likely match; below, it is a guess.
LIKELY = 0.72


@dataclass(frozen=True, slots=True)
class NameParts:
    """A printed line name, reduced to the things that decide identity."""

    tokens: tuple[str, ...]
    size: Decimal | None
    unit: str | None

    @property
    def fingerprint(self) -> str:
        """The key two names share when they are letter-for-letter the same product."""
        size = f"{self.size.normalize()}{self.unit}" if self.size and self.unit else ""
        return f"{' '.join(self.tokens)}|{size}"


def parse_name(raw: str) -> NameParts:
    """Split a printed name into comparable tokens plus a normalised package size."""
    folded = fold(raw)

    size: Decimal | None = None
    unit: str | None = None
    for match in SIZE_PATTERN.finditer(folded):
        try:
            value = Decimal(match.group(1).replace(",", "."))
        except InvalidOperation:
            continue
        base_unit, factor = UNIT_TO_BASE[match.group(2).lower()]
        # `db` is a count, not a size: two of something is not a different product.
        if base_unit == "db":
            continue
        size, unit = (value * factor).normalize(), base_unit

    # Remove the size text so it cannot also count as a word, then keep what identifies it.
    without_size = SIZE_PATTERN.sub(" ", folded)
    words = re.findall(r"[a-z0-9%]+", without_size)
    tokens = tuple(sorted({w for w in words if w not in NOISE_TOKENS and len(w) > 1}))

    return NameParts(tokens=tokens, size=size, unit=unit)


def fingerprint(raw: str) -> str:
    return parse_name(raw).fingerprint


def similarity(left: NameParts, right: NameParts) -> float:
    """0 to 1. Exactly 1 only when the two normalise identically."""
    # Different sizes are different products - the one rule that is not a matter of degree.
    if left.size and right.size and (left.size != right.size or left.unit != right.unit):
        return 0.0
    if not left.tokens or not right.tokens:
        return 0.0
    if left.fingerprint == right.fingerprint:
        return 1.0

    shared = set(left.tokens) & set(right.tokens)
    union = set(left.tokens) | set(right.tokens)
    jaccard = len(shared) / len(union)
    # Token overlap alone is blind to abbreviation: `coca c.zero` and `coca cola zero` share
    # only one token but read as the same thing. Character similarity catches those.
    ratio = SequenceMatcher(None, " ".join(left.tokens), " ".join(right.tokens)).ratio()
    # And Jaccard punishes one till simply printing less: `PEPSI` against `PEPSI COLA` is
    # 0.5 overlap but one name contained in the other, which is the commonest real case.
    containment = len(shared) / min(len(left.tokens), len(right.tokens))

    score = max(0.5 * jaccard + 0.5 * ratio, 0.75 * containment)

    if left.size and right.size:
        # Reaching here means the sizes agree - the check above returned already if not.
        # Two names for a thing sold in exactly 1.5 l is real evidence, not a coincidence.
        score += 0.12
    elif bool(left.size) != bool(right.size):
        # One side naming a size the other omits is weak evidence against, not proof.
        score *= 0.85

    # Never let a near-match reach the score that means "identical".
    return min(score, 0.99)


def band(score: float) -> str:
    """green links itself, yellow asks, red is only a starting point."""
    if score >= 1.0:
        return "green"
    return "yellow" if score >= LIKELY else "red"


@dataclass(slots=True)
class Cluster:
    """A group of printed names that look like one product."""

    suggested_name: str
    members: list[str]
    occurrences: int
    score: float

    @property
    def band(self) -> str:
        return band(self.score)


def cluster(names: Counter[str] | dict[str, int]) -> list[Cluster]:
    """Group printed names into likely products, most-seen first.

    `names` maps a printed name to how often it has been bought. Frequency decides which
    spelling represents the group: the one you see most is the one you will recognise.
    """
    counts = Counter(names)
    ordered = [name for name, _ in counts.most_common()]
    parsed = {name: parse_name(name) for name in ordered}

    clusters: list[Cluster] = []
    scores: list[float] = []
    heads: list[NameParts] = []

    for name in ordered:
        parts = parsed[name]
        best_index, best_score = -1, 0.0
        for index, head in enumerate(heads):
            score = similarity(parts, head)
            if score > best_score:
                best_index, best_score = index, score

        if best_index >= 0 and best_score >= LIKELY:
            clusters[best_index].members.append(name)
            clusters[best_index].occurrences += counts[name]
            # A cluster is only as certain as its weakest member.
            scores[best_index] = min(scores[best_index], best_score)
            clusters[best_index].score = scores[best_index]
            continue

        clusters.append(
            Cluster(suggested_name=name, members=[name], occurrences=counts[name], score=1.0)
        )
        scores.append(1.0)
        heads.append(parts)

    # Worth-your-attention order: the ones you buy most, then the most certain.
    clusters.sort(key=lambda c: (-c.occurrences, -c.score))
    return clusters
