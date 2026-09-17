"""Resolving raw receipt text onto stable catalogue rows.

A till prints "TESCO-GLOBAL ÁRUHÁZAK ZRT. 2040 BUDAÖRS" on one receipt and
"TESCO EXPRESS BUDAPEST" on the next. Left alone, those become two merchants and your
"spend by shop" chart is nonsense. Same problem one level down: "TEJ 2,8% 1L UHT" has to
land on the same product row every time or price history never accumulates.
"""

from __future__ import annotations

import logging
import re
import unicodedata
import uuid

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Merchant, MerchantAlias, Product, ProductAlias

# Known Hungarian chains, matched against the folded raw name. Collapsing every branch of a
# chain onto one merchant is what makes "where do I spend the most" answerable.
log = logging.getLogger(__name__)

CHAIN_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\btesco\b", "Tesco"),
    (r"\blidl\b", "Lidl"),
    (r"\baldi\b", "Aldi"),
    (r"\bspar\b|\binterspar\b", "Spar"),
    (r"\bpenny\b", "Penny Market"),
    (r"\bauchan\b", "Auchan"),
    (r"\bcba\b", "CBA"),
    (r"\bcoop\b", "Coop"),
    (r"\bprima\b", "Prima"),
    (r"\breal\b", "Reál"),
    (r"\bdm\b|drogerie markt", "dm"),
    (r"\brossmann\b", "Rossmann"),
    (r"\bmuller\b", "Müller"),
    (r"\bmediamarkt\b|media markt", "MediaMarkt"),
    (r"\bdecathlon\b", "Decathlon"),
    (r"\bikea\b", "IKEA"),
    (r"\bpepco\b", "Pepco"),
    (r"\bjysk\b", "JYSK"),
    (r"\bobi\b", "OBI"),
    (r"\bpraktiker\b", "Praktiker"),
    (r"\bmol\b", "MOL"),
    (r"\bomv\b", "OMV"),
    (r"\bshell\b", "Shell"),
    (r"\bmcdonald", "McDonald's"),
    (r"\bkfc\b", "KFC"),
    (r"\bbkk\b|\bbkv\b", "BKK"),
)


def fold(text: str) -> str:
    """Lowercase, strip accents, collapse whitespace."""
    decomposed = unicodedata.normalize("NFKD", text.lower())
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", stripped).strip()


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", fold(text)).strip("-")
    return slug or "ismeretlen"


def canonical_merchant_name(raw_name: str) -> str:
    """Map a printed merchant string to a chain name, or tidy it up if we don't know it."""
    folded = fold(raw_name)
    for pattern, name in CHAIN_PATTERNS:
        if re.search(pattern, folded):
            return name

    # Unknown merchant: drop the company-form suffix and the address tail, then title-case.
    cleaned = re.sub(
        r"\b(zrt|kft|bt|nyrt|ev|e\.?v|kkt|rt)\b\.?", "", raw_name, flags=re.IGNORECASE
    )
    cleaned = re.sub(r"\b\d{4}\b.*$", "", cleaned)  # postcode onwards is the address
    cleaned = re.sub(r"[.,;:]+\s*$", "", cleaned).strip()
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    if not cleaned:
        return raw_name.strip() or "Ismeretlen bolt"
    return cleaned.title() if cleaned.isupper() else cleaned


async def resolve_merchant(
    session: AsyncSession, raw_name: str | None, tax_number: str | None = None
) -> Merchant | None:
    """Find or create the merchant for a printed name, remembering the alias for next time."""
    if not raw_name or not raw_name.strip():
        return None

    raw_name = raw_name.strip()[:300]

    alias = await session.scalar(select(MerchantAlias).where(MerchantAlias.raw_name == raw_name))
    if alias is not None:
        return await session.get(Merchant, alias.merchant_id)

    if tax_number:
        by_tax = await session.scalar(select(Merchant).where(Merchant.tax_number == tax_number))
        if by_tax is not None:
            session.add(MerchantAlias(merchant_id=by_tax.id, raw_name=raw_name))
            return by_tax

    # Keep within the column widths; a garbled OCR read should not break ingestion.
    name = canonical_merchant_name(raw_name)[:200]
    slug = slugify(name)[:200]

    merchant = await session.scalar(select(Merchant).where(Merchant.slug == slug))
    if merchant is None:
        merchant = Merchant(name=name, slug=slug, tax_number=tax_number)
        session.add(merchant)
        await session.flush()
    elif tax_number and not merchant.tax_number:
        merchant.tax_number = tax_number

    session.add(MerchantAlias(merchant_id=merchant.id, raw_name=raw_name))
    return merchant


async def resolve_product(
    session: AsyncSession, raw_name: str, merchant_id: uuid.UUID | None
) -> Product | None:
    """Look up a learned alias for this line. Shop-specific mappings win over global ones.

    Returns None when the line has never been mapped - products are created deliberately in
    the review screen, not guessed from receipt shorthand.
    """
    raw_name = raw_name.strip()[:300]
    if not raw_name:
        return None

    # `merchant_id IN (:id, NULL)` looks like it would also match the global aliases, but
    # SQL never matches NULL through IN, so written that way a global alias was invisible
    # whenever a merchant was known - which is every real receipt.
    scope = (
        or_(ProductAlias.merchant_id == merchant_id, ProductAlias.merchant_id.is_(None))
        if merchant_id
        else ProductAlias.merchant_id.is_(None)
    )
    stmt = (
        select(ProductAlias)
        .where(ProductAlias.raw_name == raw_name)
        .where(scope)
        # False sorts before True, so the shop-specific alias comes first.
        .order_by(ProductAlias.merchant_id.is_(None))
    )
    alias = await session.scalar(stmt)
    if alias is not None:
        return await session.get(Product, alias.product_id)

    # No alias for this exact spelling. Before giving up, try the normalised form: another
    # till printing `Pepsi Cola 1.5 l` for something already mapped as `PEPSI 1,5L` is the
    # same product, and linking it here is what stops one drink becoming five price
    # histories. Only an exact normalised match is taken automatically - anything less
    # certain is left for the suggestions screen, because a wrong link is silent and
    # corrupts a price history for months before anyone notices.
    return await _resolve_by_fingerprint(session, raw_name, merchant_id)


async def _resolve_by_fingerprint(
    session: AsyncSession, raw_name: str, merchant_id: uuid.UUID | None
) -> Product | None:
    """Find a product whose learned spelling normalises to the same thing, and learn this one."""
    from app.services.matching import fingerprint

    key = fingerprint(raw_name)[:320]
    if not key or key.startswith("|"):
        # Nothing but a size, or nothing at all: too little to match on.
        return None

    matches = (
        await session.scalars(
            select(ProductAlias)
            .where(ProductAlias.fingerprint == key)
            .order_by(ProductAlias.merchant_id.is_(None))
        )
    ).all()
    if not matches:
        return None

    # Two products sharing a normalised name means the normalisation is not specific enough
    # for this pair. Guessing between them is exactly the silent corruption to avoid.
    if len({match.product_id for match in matches}) > 1:
        log.info("fingerprint %r is ambiguous across %d products", key, len(matches))
        return None

    product = await session.get(Product, matches[0].product_id)
    if product is not None:
        await link_product(session, product.id, raw_name, merchant_id)
    return product


async def link_product(
    session: AsyncSession,
    product_id: uuid.UUID,
    raw_name: str,
    merchant_id: uuid.UUID | None,
) -> ProductAlias:
    """Teach the app that this receipt line means this product. Idempotent."""
    raw_name = raw_name.strip()[:300]
    existing = await session.scalar(
        select(ProductAlias)
        .where(ProductAlias.raw_name == raw_name)
        .where(
            ProductAlias.merchant_id == merchant_id
            if merchant_id
            else ProductAlias.merchant_id.is_(None)
        )
    )
    if existing is not None:
        from app.services.matching import fingerprint

        existing.product_id = product_id
        existing.fingerprint = fingerprint(raw_name)[:320]
        return existing

    from app.services.matching import fingerprint

    alias = ProductAlias(
        product_id=product_id,
        raw_name=raw_name,
        merchant_id=merchant_id,
        fingerprint=fingerprint(raw_name)[:320],
    )
    session.add(alias)
    return alias
