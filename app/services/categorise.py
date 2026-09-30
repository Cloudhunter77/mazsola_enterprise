"""Putting a receipt line into a category without being asked.

Nothing was categorised unless you mapped the line to a product and then gave that product
a category, so in practice almost nothing was. Five rules run here, most specific first,
and each only fires where the one above it did not:

1. the product's own category - what you set, explicitly;
2. a category you already gave to a line that normalises the same way;
3. a shop you told to always mean one category;
4. a keyword in the Hungarian product name;
5. a known single-purpose chain (a pharmacy, a petrol station).

Every assignment records *which* rule made it, in `category_source`. That is the part that
makes automation safe here rather than merely convenient. A mis-categorised line is the
quiet kind of wrong - your Élelmiszer total is off and no screen looks broken - so a
stronger rule may overwrite a weaker one later, a better keyword table can be re-run over
exactly what the old one touched, and nothing may ever overwrite `manual`.
"""

from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Category, LineKind, Merchant, Product, Receipt, ReceiptItem
from app.services.autolink import READY_FOR_STATS
from app.services.catalog import fold
from app.services.matching import fingerprint

log = logging.getLogger(__name__)

# How a line got its category. Ordered weakest to strongest; a rule may only overwrite one
# that sits below it, and `manual` sits above everything.
SOURCE_STRENGTH: dict[str, int] = {
    "merchant": 1,
    "keyword": 2,
    "learned": 3,
    "product": 4,
    # A whole receipt filed at once. Stronger than any guess, because you chose it; weaker
    # than a line you set yourself, because it was one choice for many lines.
    "receipt": 5,
    "manual": 6,
}

# Shops that sell one kind of thing. A supermarket is deliberately absent: Tesco sells food,
# bin bags and socks, so a grocery default there would be wrong in a way that looks
# plausible - which is worse than leaving the line uncategorised and visible.
MERCHANT_CATEGORIES: dict[str, str] = {
    "Rossmann": "Drogéria",
    "dm": "Drogéria",
    "Müller": "Drogéria",
    "MOL": "Üzemanyag",
    "OMV": "Üzemanyag",
    "Shell": "Üzemanyag",
    "JYSK": "Lakás és otthon",
    "IKEA": "Lakás és otthon",
    "OBI": "Barkács",
    "Praktiker": "Barkács",
    "Pepco": "Ruházat",
    "C&A": "Ruházat",
    "Decathlon": "Sport",
    "MediaMarkt": "Elektronika",
    "McDonald's": "Vendéglátás",
    "KFC": "Vendéglátás",
    "BKK": "Tömegközlekedés",
}

# A pharmacy is not one chain but a whole class of shop, so it is matched on the name.
MERCHANT_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"gyogyszertar|patika|pharma", "Gyógyszer és vitamin"),
    (r"benzinkut|toltoallomas", "Üzemanyag"),
    (r"pekseg|bakery", "Pékáru"),
    (r"kavezo|cafe|coffee|bisztro|etterem|bufe|fornetti", "Vendéglátás"),
    (r"allatelede|allatpatika|petshop", "Állateledel"),
)

# Hungarian shopping vocabulary, matched against the folded product name. Order matters:
# the first hit wins, so anything specific must come before the word it contains. `tejfol`
# and `tejcsok` both contain `tej`, and neither is milk.
KEYWORD_CATEGORIES: tuple[tuple[str, str], ...] = (
    # --- specific before general -------------------------------------------------
    ("tejcsok|tejcs\\.|tejcs\\b", "Édesség és snack"),
    ("tejfol", "Tejtermék"),
    ("tejszin", "Tejtermék"),
    ("tejdesszert", "Édesség és snack"),
    ("kokusztej|zabtej|mandulatej|rizstej|szojatej", "Tejtermék"),
    ("savanyu kaposzta|savanyusag", "Konzerv és készétel"),
    ("gyumolcsjoghurt|joghurt", "Tejtermék"),
    # --- dairy ---------------------------------------------------------------------
    ("\\btej\\b|uht tej|lm uht|tej 2,8|tej 1,5", "Tejtermék"),
    ("sajt|trappista|mozzarella|cheddar|camembert|parmezan", "Tejtermék"),
    ("\\bvaj\\b|margarin|\\brama\\b|delma", "Tejtermék"),
    ("turo|kefir|aludttej", "Tejtermék"),
    # --- bakery --------------------------------------------------------------------
    ("kenyer|cipo|bagett|kifli|zsemle|buci|kalacs|pekaru|bagel|toast", "Pékáru"),
    ("croissant|briós|brios|pogacsa|reteg", "Pékáru"),
    # --- meat and fish --------------------------------------------------------------
    ("csirke|sertes|marha|pulyka|\\bhus\\b|husl|darlt hus|darlthus", "Hús és hal"),
    ("szalami|sonka|kolbasz|virsli|parizsi|szalonna|bacon", "Hús és hal"),
    ("\\bhal\\b|lazac|tonhal|halaszle|pisztrang|hekk", "Hús és hal"),
    # --- fruit and vegetables --------------------------------------------------------
    ("alma|korte|banan|szolo|narancs|citrom|eper|malna|afonya|barack|szilva",
     "Zöldség és gyümölcs"),
    ("burgonya|krumpli|hagyma|paradicsom|paprika|uborka|salata|sargarepa", "Zöldség és gyümölcs"),
    ("kaposzta|karfiol|brokkoli|cukkini|padlizsan|gomba|zoldseg|leveszoldseg",
     "Zöldség és gyümölcs"),
    ("babkonzerv|vorosbab|csicseri|lencse", "Alapvető élelmiszer"),
    # --- store cupboard ---------------------------------------------------------------
    ("liszt|cukor|\\bso\\b|\\bbors|fuszer|olaj|ecet|\\briz|teszta|spagetti|makaroni",
     "Alapvető élelmiszer"),
    ("pesto|ketchup|majonez|mustar|szosz|passata|guacamole", "Konzerv és készétel"),
    ("konzerv|\\bleves\\b|instant leves|tyukhusleves|zoldseglev", "Konzerv és készétel"),
    # --- sweets and snacks --------------------------------------------------------------
    ("csoki|csokolade|keksz|ostya|nápolyi|napolyi|bonbon|desszert", "Édesség és snack"),
    ("chips|ropi|nasi|snack|pattogat|mogyoro|\\bdio\\b|mandula", "Édesség és snack"),
    ("fagyi|jegkrem|pottyos|turo rudi", "Édesség és snack"),
    # --- frozen -------------------------------------------------------------------------
    ("fagyaszt|fagy\\.|melegszendvics|\\bpizza\\b", "Fagyasztott"),
    # --- drinks -------------------------------------------------------------------------
    ("asvanyviz|szensavmentes|szensavas viz", "Ásványvíz"),
    ("kave|kávé|nescafe|jacobs|tchibo|espresso|latte|cappuccino", "Kávé és tea"),
    ("\\btea\\b|teekanne|fuzetea|herbatea", "Kávé és tea"),
    ("\\bsor\\b|\\bbor\\b|pezsgo|vodka|whisky|palinka|unicum|\\brum\\b|likor",
     "Alkohol"),
    # Hungarian beer brands, which carry no word saying they are beer.
    ("soproni|borsodi|dreher|arany aszok|kobanyai|heineken|staropramen", "Alkohol"),
    ("cola|pepsi|fanta|sprite|udito|szorp|juice|gyumolcsle|narancsle|limonade", "Üdítő"),
    # --- household -----------------------------------------------------------------------
    ("mosogat|mosopor|mososzer|oblito|tisztito|hypo|fertotlenit", "Tisztítószer"),
    ("szalveta|papirtorlo|wc papir|toalettpapir|zsebkendo", "Papíráru"),
    ("szemetes|szemeteszsak|zacsko|alufolia|folpack|\\bzsak\\b", "Konyhai eszköz"),
    ("\\bizzo|\\belem\\b|akkumulator", "Izzó és elem"),
    # --- drugstore -------------------------------------------------------------------------
    ("sampon|tusfurdo|szappan|dezodor|borotva|fogkrem|fogkefe", "Testápolás"),
    ("\\bkrem\\b|arckrem|testapolo|naptej|kezkrem", "Testápolás"),
    ("pelenka|bebi|\\bbaba\\b", "Baba"),
    ("vitamin|tabletta|filmtabl|kapszula|szirup|tapasz|gyogyszer", "Gyógyszer és vitamin"),
    # --- pets ----------------------------------------------------------------------------
    ("kutya|macska|allateledel|whiskas|pedigree|felix", "Állateledel"),
    # --- transport and other ----------------------------------------------------------------
    ("benzin|gazolaj|dizel|uzemanyag|95-os", "Üzemanyag"),
    ("parkol", "Parkolás"),
    ("\\bbkk\\b|berlet|\\bjegy\\b|\\bmetro\\b", "Tömegközlekedés"),
    ("betetdij|visszavaltasi dij", "Betétdíj"),
    ("szallitasi dij|kiszallitas|csomagolasi dij", "Szolgáltatás"),
)

_COMPILED: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (re.compile(pattern), name) for pattern, name in KEYWORD_CATEGORIES
)
_MERCHANT_COMPILED: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (re.compile(pattern), name) for pattern, name in MERCHANT_PATTERNS
)


def category_for_name(raw_name: str) -> str | None:
    """The category a Hungarian product name suggests, or None when nothing matches."""
    folded = fold(raw_name)
    for pattern, category in _COMPILED:
        if pattern.search(folded):
            return category
    return None


def category_for_merchant(merchant_name: str) -> str | None:
    """The category a single-purpose shop implies. None for anywhere that sells everything."""
    if merchant_name in MERCHANT_CATEGORIES:
        return MERCHANT_CATEGORIES[merchant_name]
    folded = fold(merchant_name)
    for pattern, category in _MERCHANT_COMPILED:
        if pattern.search(folded):
            return category
    return None


async def _category_ids(session: AsyncSession) -> dict[str, uuid.UUID]:
    return {
        name: category_id
        for name, category_id in (
            await session.execute(select(Category.name, Category.id))
        ).all()
    }


async def _learned_categories(session: AsyncSession) -> dict[str, uuid.UUID]:
    """What you have categorised by hand, keyed by normalised name.

    This is rule 2, and for a long time it was only described in this file's docstring and
    never run - so a category set on one line stayed on that one line, and the next receipt
    with the same milk on it arrived uncategorised again. Keyed by fingerprint rather than
    raw name so `UHT TEJ 1L` learns from `uht tej 1 l`.

    A name you have filed under two different categories is left out: the rule cannot know
    which you meant, and guessing is the quiet kind of wrong.
    """
    rows = (
        await session.execute(
            select(ReceiptItem.raw_name, ReceiptItem.category_id)
            .where(ReceiptItem.category_source == "manual")
            .where(ReceiptItem.category_id.is_not(None))
            .group_by(ReceiptItem.raw_name, ReceiptItem.category_id)
        )
    ).all()

    seen: dict[str, set[uuid.UUID]] = {}
    for raw_name, category_id in rows:
        key = fingerprint(raw_name)
        if key and not key.startswith("|"):
            seen.setdefault(key, set()).add(category_id)
    return {key: next(iter(found)) for key, found in seen.items() if len(found) == 1}


async def categorise_stored(session: AsyncSession, limit: int = 2000) -> dict[str, int]:
    """Give a category to stored lines that have none. Returns a count per rule that fired.

    Only fills blanks. A line already carrying a category keeps it, whatever set it - which
    is what makes this safe to run on a timer and safe to run again after the keyword table
    grows.
    """
    rows = (
        await session.execute(
            select(
                ReceiptItem.id,
                ReceiptItem.raw_name,
                ReceiptItem.product_id,
                Merchant.name,
                Receipt.merchant_id,
            )
            .join(Receipt, Receipt.id == ReceiptItem.receipt_id)
            .outerjoin(Merchant, Receipt.merchant_id == Merchant.id)
            .where(ReceiptItem.category_id.is_(None))
            .where(ReceiptItem.kind == LineKind.ITEM.value)
            .where(Receipt.status.in_(READY_FOR_STATS))
            .limit(limit)
        )
    ).all()
    if not rows:
        return {}

    ids = await _category_ids(session)
    learned = await _learned_categories(session)
    shop_defaults = {
        merchant_id: category_id
        for merchant_id, category_id in (
            await session.execute(
                select(Merchant.id, Merchant.default_category_id)
                .where(Merchant.default_category_id.is_not(None))
            )
        ).all()
    }
    # What each product is already categorised as, so a line can inherit it.
    products = {
        product_id: category_id
        for product_id, category_id in (
            await session.execute(
                select(Product.id, Product.category_id).where(Product.category_id.is_not(None))
            )
        ).all()
    }

    applied: dict[str, int] = {}
    for item_id, raw_name, product_id, merchant_name, merchant_id in rows:
        category_id: uuid.UUID | None = None
        source: str | None = None

        if product_id and product_id in products:
            category_id, source = products[product_id], "product"

        if category_id is None:
            category_id = learned.get(fingerprint(raw_name))
            if category_id is not None:
                source = "learned"

        if category_id is None and merchant_id in shop_defaults:
            # Yours, so it goes before the keywords: in a café you filed as Vendéglátás, a
            # "tejeskávé" is not a dairy purchase.
            category_id, source = shop_defaults[merchant_id], "merchant"

        if category_id is None:
            name = category_for_name(raw_name)
            if name and name in ids:
                category_id, source = ids[name], "keyword"

        if category_id is None and merchant_name:
            name = category_for_merchant(merchant_name)
            if name and name in ids:
                category_id, source = ids[name], "merchant"

        if category_id is None:
            continue

        await session.execute(
            update(ReceiptItem)
            .where(ReceiptItem.id == item_id)
            .where(ReceiptItem.category_id.is_(None))
            .values(category_id=category_id, category_source=source)
        )
        applied[source] = applied.get(source, 0) + 1

    if applied:
        log.info("categorised %s", ", ".join(f"{n} by {rule}" for rule, n in applied.items()))
    return applied


@dataclass(slots=True)
class Filing:
    """What filing one receipt changed, precisely enough to take it back."""

    item_ids: list[uuid.UUID]
    # Set when the shop was told to always mean this category: which shop, and what it
    # meant before, so undo can put that back rather than guess.
    merchant_id: uuid.UUID | None = None
    previous_default: uuid.UUID | None = None
    # Lines on *other* receipts from the same shop that the new default filed at once.
    spread: int = 0


async def file_receipt(
    session: AsyncSession,
    receipt_id: uuid.UUID,
    category_id: uuid.UUID,
    remember_shop: bool = False,
) -> Filing:
    """File every uncategorised line on one receipt under one category.

    Only blanks are filled: on a mixed supermarket receipt where the keywords already
    filed the milk and the washing-up liquid, those keep their categories and only the
    rest follows your choice.

    The lines are marked `receipt`, not `manual`. Filing a whole receipt is one coarse
    decision about many lines, and the learning rule must not read it as a statement about
    each name - otherwise one supermarket receipt filed as Élelmiszer would teach every
    future receipt that the washing-up liquid on it was food.

    With `remember_shop`, the shop itself is told to always mean this category: its other
    receipts' blank lines follow now, and future ones on the hourly pass.
    """
    item_ids = list(
        (
            await session.scalars(
                update(ReceiptItem)
                .where(ReceiptItem.receipt_id == receipt_id)
                .where(ReceiptItem.kind == LineKind.ITEM.value)
                .where(ReceiptItem.category_id.is_(None))
                .values(category_id=category_id, category_source="receipt")
                .returning(ReceiptItem.id)
            )
        ).all()
    )
    filing = Filing(item_ids=item_ids)

    if not remember_shop:
        return filing

    merchant_id = await session.scalar(select(Receipt.merchant_id).where(Receipt.id == receipt_id))
    merchant = await session.get(Merchant, merchant_id) if merchant_id else None
    if merchant is None:
        return filing

    filing.merchant_id = merchant.id
    filing.previous_default = merchant.default_category_id
    merchant.default_category_id = category_id

    others = select(Receipt.id).where(Receipt.merchant_id == merchant.id).where(
        Receipt.status.in_(READY_FOR_STATS)
    )
    spread = list(
        (
            await session.scalars(
                update(ReceiptItem)
                .where(ReceiptItem.receipt_id.in_(others))
                .where(ReceiptItem.kind == LineKind.ITEM.value)
                .where(ReceiptItem.category_id.is_(None))
                .values(category_id=category_id, category_source="merchant")
                .returning(ReceiptItem.id)
            )
        ).all()
    )
    filing.item_ids += spread
    filing.spread = len(spread)
    return filing


async def undo_filing(
    session: AsyncSession,
    category_id: uuid.UUID,
    item_ids: list[uuid.UUID],
    merchant_id: uuid.UUID | None = None,
    previous_default: uuid.UUID | None = None,
) -> int:
    """Take back exactly what `file_receipt` did, and nothing it did not.

    Guarded on each line still holding the category it was given: anything moved on since
    stays where it now is. The shop gets back what it meant before, not simply nothing.
    """
    result = await session.execute(
        update(ReceiptItem)
        .where(ReceiptItem.id.in_(item_ids))
        .where(ReceiptItem.category_id == category_id)
        .where(ReceiptItem.category_source.in_(("receipt", "merchant")))
        .values(category_id=None, category_source=None)
    )
    if merchant_id:
        await session.execute(
            update(Merchant)
            .where(Merchant.id == merchant_id)
            .where(Merchant.default_category_id == category_id)
            .values(default_category_id=previous_default)
        )
    return result.rowcount or 0


async def receipts_to_file(session: AsyncSession, limit: int = 100) -> list[dict]:
    """Receipts with at least one uncategorised line, most uncategorised money first.

    Only receipts that count towards spending, so the list adds up to the Besorolatlan
    figure on the dashboard. Each carries a few of its uncategorised names, because a shop
    and a date alone rarely say whether a receipt was one kind of thing or a mixed shop.
    """
    blank = (
        select(
            ReceiptItem.receipt_id,
            func.count(ReceiptItem.id).label("lines"),
            func.coalesce(func.sum(ReceiptItem.gross_amount), 0).label("amount"),
        )
        .where(ReceiptItem.kind == LineKind.ITEM.value)
        .where(ReceiptItem.category_id.is_(None))
        .group_by(ReceiptItem.receipt_id)
        .subquery()
    )
    item_lines = (
        select(ReceiptItem.receipt_id, func.count(ReceiptItem.id).label("item_count"))
        .where(ReceiptItem.kind == LineKind.ITEM.value)
        .group_by(ReceiptItem.receipt_id)
        .subquery()
    )
    rows = (
        await session.execute(
            select(
                Receipt.id,
                Receipt.purchased_at,
                Receipt.total_gross,
                Receipt.merchant_id,
                func.coalesce(Merchant.name, Receipt.merchant_raw_name),
                Merchant.default_category_id,
                blank.c.lines,
                blank.c.amount,
                item_lines.c.item_count,
            )
            .join(blank, blank.c.receipt_id == Receipt.id)
            .join(item_lines, item_lines.c.receipt_id == Receipt.id)
            .outerjoin(Merchant, Merchant.id == Receipt.merchant_id)
            .where(Receipt.status.in_(READY_FOR_STATS))
            .order_by(blank.c.amount.desc(), Receipt.purchased_at.desc())
            .limit(limit)
        )
    ).all()
    if not rows:
        return []

    names: dict[uuid.UUID, list[str]] = {}
    for receipt_id, raw_name in (
        await session.execute(
            select(ReceiptItem.receipt_id, ReceiptItem.raw_name)
            .where(ReceiptItem.receipt_id.in_([row[0] for row in rows]))
            .where(ReceiptItem.kind == LineKind.ITEM.value)
            .where(ReceiptItem.category_id.is_(None))
            .order_by(ReceiptItem.receipt_id, ReceiptItem.gross_amount.desc())
        )
    ).all():
        names.setdefault(receipt_id, []).append(raw_name)

    return [
        {
            "receipt_id": receipt_id,
            "purchased_at": purchased_at,
            "total_gross": total,
            "merchant_id": merchant_id,
            "merchant_name": merchant_name,
            "shop_default_id": shop_default,
            "uncategorised_lines": lines,
            "uncategorised_amount": amount,
            "item_lines": items,
            "names": names.get(receipt_id, [])[:5],
        }
        for (
            receipt_id, purchased_at, total, merchant_id, merchant_name, shop_default,
            lines, amount, items,
        ) in rows
    ]
