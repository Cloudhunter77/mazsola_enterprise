"""Categories, merchants, products and budgets."""

from __future__ import annotations

import uuid
from decimal import Decimal

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, select, update

from app.api.deps import AuthDep, SessionDep
from app.models import (
    Budget,
    Category,
    LineKind,
    Merchant,
    Product,
    ProductAlias,
    Receipt,
    ReceiptItem,
)
from app.schemas.api import (
    ApplySuggestionIn,
    BudgetIn,
    BudgetOut,
    CategoryOut,
    MerchantOut,
    ProductCreate,
    ProductOut,
    SuggestionOut,
    SuggestionsOut,
)
from app.services.autolink import READY_FOR_STATS, autolink_stored
from app.services.catalog import link_product
from app.services.matching import cluster, fingerprint, parse_name

router = APIRouter(prefix="/api", tags=["catalog"])


@router.get("/categories", response_model=list[CategoryOut])
async def list_categories(_: AuthDep, session: SessionDep) -> list[CategoryOut]:
    rows = await session.scalars(select(Category).order_by(Category.sort_order, Category.name))
    return [CategoryOut.model_validate(c) for c in rows]


@router.get("/merchants", response_model=list[MerchantOut])
async def list_merchants(_: AuthDep, session: SessionDep) -> list[MerchantOut]:
    rows = await session.scalars(select(Merchant).order_by(Merchant.name))
    return [MerchantOut.model_validate(m) for m in rows]


@router.get("/products", response_model=list[ProductOut])
async def list_products(
    _: AuthDep,
    session: SessionDep,
    q: str | None = Query(None, description="Case-insensitive name search."),
    limit: int = Query(100, le=500),
) -> list[ProductOut]:
    stmt = select(Product).order_by(Product.canonical_name).limit(limit)
    if q:
        stmt = stmt.where(Product.canonical_name.ilike(f"%{q}%"))
    rows = await session.scalars(stmt)
    return [ProductOut.model_validate(p) for p in rows]


@router.get("/products/tracked", response_model=list[ProductOut])
async def tracked_products(_: AuthDep, session: SessionDep) -> list[ProductOut]:
    """Products bought more than once - the ones whose price history is worth looking at."""
    counts = (
        select(ReceiptItem.product_id, func.count().label("n"))
        .where(ReceiptItem.product_id.is_not(None))
        .group_by(ReceiptItem.product_id)
        .having(func.count() > 1)
        .subquery()
    )
    rows = await session.scalars(
        select(Product).join(counts, counts.c.product_id == Product.id).order_by(counts.c.n.desc())
    )
    return [ProductOut.model_validate(p) for p in rows]


@router.post("/products", response_model=ProductOut, status_code=201)
async def create_product(
    _: AuthDep,
    session: SessionDep,
    body: ProductCreate,
    from_raw_name: str | None = Query(
        None, description="Receipt line text to map onto the new product straight away."
    ),
    merchant_id: uuid.UUID | None = Query(None),
) -> ProductOut:
    """Create a canonical product, optionally learning the receipt line that led to it."""
    existing = await session.scalar(
        select(Product).where(Product.canonical_name == body.canonical_name)
    )
    if existing is not None:
        product = existing
    else:
        product = Product(**body.model_dump())
        session.add(product)
        await session.flush()

    if from_raw_name:
        await link_product(session, product.id, from_raw_name, merchant_id)

    await session.commit()
    await session.refresh(product)
    return ProductOut.model_validate(product)


@router.get("/budgets", response_model=list[BudgetOut])
async def list_budgets(_: AuthDep, session: SessionDep) -> list[BudgetOut]:
    rows = await session.scalars(select(Budget).order_by(Budget.month.desc()))
    return [BudgetOut.model_validate(b) for b in rows]


@router.put("/budgets", response_model=BudgetOut)
async def upsert_budget(_: AuthDep, session: SessionDep, body: BudgetIn) -> BudgetOut:
    month = body.month.replace(day=1)
    stmt = select(Budget).where(Budget.month == month)
    stmt = stmt.where(
        Budget.category_id == body.category_id
        if body.category_id
        else Budget.category_id.is_(None)
    )
    budget = await session.scalar(stmt)

    if budget is None:
        budget = Budget(category_id=body.category_id, month=month, amount=body.amount)
        session.add(budget)
    else:
        budget.amount = body.amount

    await session.commit()
    await session.refresh(budget)
    return BudgetOut.model_validate(budget)


@router.delete("/budgets/{budget_id}", status_code=204)
async def delete_budget(_: AuthDep, session: SessionDep, budget_id: uuid.UUID) -> None:
    budget = await session.get(Budget, budget_id)
    if budget is None:
        raise HTTPException(status_code=404, detail="No such budget.")
    await session.delete(budget)
    await session.commit()

@router.get("/suggestions", response_model=SuggestionsOut)
async def product_suggestions(
    _: AuthDep, session: SessionDep, limit: int = Query(40, le=200)
) -> SuggestionsOut:
    """Group the receipt lines that are not yet mapped to a product.

    Everything here is derived on the fly rather than stored: the grouping rules can change
    without a migration, and a suggestion nobody acted on is not worth a row.
    """
    rows = (
        await session.execute(
            select(
                ReceiptItem.raw_name,
                func.count(ReceiptItem.id),
                func.coalesce(func.sum(ReceiptItem.gross_amount), 0),
            )
            .join(Receipt, Receipt.id == ReceiptItem.receipt_id)
            .where(ReceiptItem.product_id.is_(None))
            .where(ReceiptItem.kind == LineKind.ITEM.value)
            .where(Receipt.status.in_(READY_FOR_STATS))
            .group_by(ReceiptItem.raw_name)
        )
    ).all()

    counts = {name: count for name, count, _ in rows}
    spend = {name: Decimal(total) for name, _, total in rows}
    if not counts:
        return SuggestionsOut(unmapped_lines=0, groups=[])

    # Which existing product, if any, each normalised name already belongs to - so a group
    # can join a price history instead of starting a second one beside it.
    known: dict[str, uuid.UUID] = {}
    for alias in (await session.scalars(select(ProductAlias))).all():
        if alias.fingerprint:
            known.setdefault(alias.fingerprint, alias.product_id)
    names = {
        product.id: product.canonical_name
        for product in (await session.scalars(select(Product))).all()
    }

    groups: list[SuggestionOut] = []
    for group in cluster(counts)[:limit]:
        product_id = next(
            (known[fp] for fp in (fingerprint(m) for m in group.members) if fp in known), None
        )
        groups.append(
            SuggestionOut(
                suggested_name=group.suggested_name,
                members=group.members,
                occurrences=group.occurrences,
                score=round(group.score, 3),
                band=group.band,
                total_spent=sum((spend[m] for m in group.members), Decimal("0.00")),
                product_id=product_id,
                product_name=names.get(product_id) if product_id else None,
            )
        )

    return SuggestionsOut(unmapped_lines=sum(counts.values()), groups=groups)


@router.post("/suggestions/apply", response_model=ProductOut, status_code=201)
async def apply_suggestion(
    _: AuthDep, session: SessionDep, body: ApplySuggestionIn
) -> ProductOut:
    """Confirm a group: create or reuse the product, alias every name, and backfill.

    Backfilling matters more than it sounds. Without it, confirming a product would only
    affect receipts you scan *afterwards*, and the price history you wanted it for - the
    months already in the database - would stay empty.
    """
    product: Product | None = None
    if body.product_id:
        product = await session.get(Product, body.product_id)
    if product is None:
        product = await session.scalar(
            select(Product).where(Product.canonical_name == body.canonical_name)
        )
    if product is None:
        parts = parse_name(body.canonical_name)
        product = Product(
            canonical_name=body.canonical_name[:200],
            category_id=body.category_id,
            package_size=float(parts.size) if parts.size else None,
            package_unit=parts.unit,
        )
        session.add(product)
        await session.flush()
    elif body.category_id and not product.category_id:
        product.category_id = body.category_id

    for raw_name in dict.fromkeys(body.raw_names):
        await link_product(session, product.id, raw_name, body.merchant_id)

    # Apply to what is already stored, not just to what arrives next.
    await session.execute(
        update(ReceiptItem)
        .where(ReceiptItem.raw_name.in_(list(body.raw_names)))
        .where(ReceiptItem.product_id.is_(None))
        .values(
            product_id=product.id,
            # Never replace a category you set on the line yourself with the product's
            # empty default - confirming a name must not undo a categorisation.
            category_id=func.coalesce(ReceiptItem.category_id, product.category_id),
        )
    )

    await session.commit()
    await session.refresh(product)
    return ProductOut.model_validate(product)


@router.post("/suggestions/autolink")
async def autolink(_: AuthDep, session: SessionDep) -> dict:
    """Link every stored line that letter-for-letter matches a product you already have.

    The same pass the worker runs hourly, on demand - because the moment you want it is
    right after mapping a product, not an hour later. Only exact normalised matches, so
    there is nothing here to review afterwards.
    """
    linked = await autolink_stored(session)
    await session.commit()
    return {"linked": linked}
