"""Putting a receipt line into a category without being asked.

Nothing was categorised unless you mapped the line to a product and then gave that product
a category, so in practice almost nothing was. Four rules run here, most specific first,
and each only fires where the one above it did not:

1. the product's own category - what you set, explicitly;
2. a category you already gave to a line that normalises the same way;
3. a keyword in the Hungarian product name;
4. the shop, for shops that sell only one kind of thing.

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
    "manual": 5,
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
    for item_id, raw_name, product_id, merchant_name in rows:
        category_id: uuid.UUID | None = None
        source: str | None = None

        if product_id and product_id in products:
            category_id, source = products[product_id], "product"

        if category_id is None:
            category_id = learned.get(fingerprint(raw_name))
            if category_id is not None:
                source = "learned"

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
class Assignment:
    """What one "file this name under X" changed, precisely enough to take it back."""

    item_ids: list[uuid.UUID]
    product_ids: list[uuid.UUID]
    # How many of `item_ids` were other spellings or other receipts reached through the
    # product or the learned rule, rather than the name you picked.
    spread: int


async def assign_by_name(
    session: AsyncSession, raw_name: str, category_id: uuid.UUID
) -> Assignment:
    """File every uncategorised line printed as `raw_name` under a category, and teach it.

    Three effects, all only ever filling blanks - a line or product that already has a
    category keeps it, so this can never undo a decision made elsewhere:

    * the lines with exactly this name become `manual`, the strongest source there is;
    * a product those lines belong to takes the category too, if it has none - so the
      next receipt with it arrives categorised through rule 1;
    * other blank lines of that product, or whose name normalises the same way, follow
      straight away, instead of an hour later when the timer runs.
    """
    counted = select(Receipt.id).where(Receipt.status.in_(READY_FOR_STATS))
    lines = (
        await session.execute(
            select(ReceiptItem.id, ReceiptItem.product_id)
            .where(ReceiptItem.raw_name == raw_name)
            .where(ReceiptItem.kind == LineKind.ITEM.value)
            .where(ReceiptItem.category_id.is_(None))
            .where(ReceiptItem.receipt_id.in_(counted))
        )
    ).all()
    direct = [item_id for item_id, _ in lines]
    if direct:
        await session.execute(
            update(ReceiptItem)
            .where(ReceiptItem.id.in_(direct))
            .values(category_id=category_id, category_source="manual")
        )

    product_ids = sorted({pid for _, pid in lines if pid}, key=str)
    changed_products: list[uuid.UUID] = []
    if product_ids:
        changed_products = list(
            (
                await session.scalars(
                    update(Product)
                    .where(Product.id.in_(product_ids))
                    .where(Product.category_id.is_(None))
                    .values(category_id=category_id)
                    .returning(Product.id)
                )
            ).all()
        )

    # The rest of the family: same product, or a spelling that normalises identically.
    key = fingerprint(raw_name)
    candidates = (
        await session.execute(
            select(ReceiptItem.id, ReceiptItem.raw_name, ReceiptItem.product_id)
            .where(ReceiptItem.kind == LineKind.ITEM.value)
            .where(ReceiptItem.category_id.is_(None))
            .where(ReceiptItem.receipt_id.in_(counted))
            .where(ReceiptItem.raw_name != raw_name)
        )
    ).all()
    by_product = [
        item_id for item_id, _, pid in candidates if pid and pid in changed_products
    ]
    by_name = [
        item_id
        for item_id, name, pid in candidates
        if item_id not in by_product and key and not key.startswith("|")
        and fingerprint(name) == key
    ]
    for ids, source in ((by_product, "product"), (by_name, "learned")):
        if ids:
            await session.execute(
                update(ReceiptItem)
                .where(ReceiptItem.id.in_(ids))
                .values(category_id=category_id, category_source=source)
            )

    return Assignment(
        item_ids=direct + by_product + by_name,
        product_ids=changed_products,
        spread=len(by_product) + len(by_name),
    )


async def undo_assignment(
    session: AsyncSession,
    category_id: uuid.UUID,
    item_ids: list[uuid.UUID],
    product_ids: list[uuid.UUID],
) -> int:
    """Take back exactly what `assign_by_name` did, and nothing it did not.

    Guarded on the category still being the one assigned: if something has moved a line on
    since, it is left where it now is.
    """
    result = await session.execute(
        update(ReceiptItem)
        .where(ReceiptItem.id.in_(item_ids))
        .where(ReceiptItem.category_id == category_id)
        .values(category_id=None, category_source=None)
    )
    if product_ids:
        await session.execute(
            update(Product)
            .where(Product.id.in_(product_ids))
            .where(Product.category_id == category_id)
            .values(category_id=None)
        )
    return result.rowcount or 0


async def uncategorised_names(session: AsyncSession, limit: int = 200) -> list[tuple]:
    """Every name still behind "Besorolatlan", most money first.

    Grouped by printed name because that is the unit you recognise and the unit
    `assign_by_name` acts on. Only lines that count towards spending, so the list adds up
    to the number on the dashboard.
    """
    return list(
        (
            await session.execute(
                select(
                    ReceiptItem.raw_name,
                    func.count(ReceiptItem.id),
                    func.coalesce(func.sum(ReceiptItem.gross_amount), 0),
                    func.max(Product.canonical_name),
                    func.max(Receipt.purchased_at),
                )
                .join(Receipt, Receipt.id == ReceiptItem.receipt_id)
                .outerjoin(Product, Product.id == ReceiptItem.product_id)
                .where(ReceiptItem.category_id.is_(None))
                .where(ReceiptItem.kind == LineKind.ITEM.value)
                .where(Receipt.status.in_(READY_FOR_STATS))
                .group_by(ReceiptItem.raw_name)
                .order_by(func.sum(ReceiptItem.gross_amount).desc().nulls_last())
                .limit(limit)
            )
        ).all()
    )
