"""Categories, merchants, products and budgets."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, select

from app.api.deps import AuthDep, SessionDep
from app.models import Budget, Category, Merchant, Product, ReceiptItem
from app.schemas.api import (
    BudgetIn,
    BudgetOut,
    CategoryOut,
    MerchantOut,
    ProductCreate,
    ProductOut,
)
from app.services.catalog import link_product

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
