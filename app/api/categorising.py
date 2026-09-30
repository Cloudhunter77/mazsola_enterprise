"""Clearing out "Besorolatlan": filing the names nothing could categorise on its own.

The automatic rules categorise what they recognise and leave the rest blank on purpose - a
wrong category is the quiet kind of wrong. That blank has to go somewhere a person can act
on it, and one line at a time inside each receipt was not that place: the same milk on
twenty receipts meant twenty trips. Here each name appears once, and filing it files every
line printed that way, teaches the product, and reaches the other spellings of it.
"""

from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, HTTPException, Query

from app.api.deps import AuthDep, SessionDep
from app.models import Category
from app.schemas.api import (
    AssignCategoryIn,
    AssignCategoryOut,
    UncategorisedName,
    UndoCategoryIn,
)
from app.services.categorise import assign_by_name, uncategorised_names, undo_assignment

router = APIRouter(prefix="/api/categorise", tags=["categorise"])


@router.get("/uncategorised", response_model=list[UncategorisedName])
async def list_uncategorised(
    _: AuthDep, session: SessionDep, limit: int = Query(200, ge=1, le=1000)
) -> list[UncategorisedName]:
    return [
        UncategorisedName(
            raw_name=raw_name,
            lines=count,
            total=Decimal(total).quantize(Decimal("0.01")),
            product_name=product_name,
            last_bought=last_bought,
        )
        for raw_name, count, total, product_name, last_bought in await uncategorised_names(
            session, limit
        )
    ]


@router.post("/assign", response_model=AssignCategoryOut)
async def assign(_: AuthDep, session: SessionDep, body: AssignCategoryIn) -> AssignCategoryOut:
    if await session.get(Category, body.category_id) is None:
        raise HTTPException(status_code=404, detail="No such category.")
    done = await assign_by_name(session, body.raw_name, body.category_id)
    await session.commit()
    return AssignCategoryOut(
        category_id=body.category_id,
        item_ids=done.item_ids,
        product_ids=done.product_ids,
        lines=len(done.item_ids),
        spread=done.spread,
    )


@router.post("/undo")
async def undo(_: AuthDep, session: SessionDep, body: UndoCategoryIn) -> dict:
    reverted = await undo_assignment(
        session, body.category_id, body.item_ids, body.product_ids
    )
    await session.commit()
    return {"reverted": reverted}
