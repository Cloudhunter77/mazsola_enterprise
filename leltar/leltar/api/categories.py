"""The category list. Read-only: the prompt offers the model exactly these slugs, so a
category invented here would be one the model is never told about."""

from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import select

from leltar.api.deps import AuthDep, SessionDep
from leltar.models import Category
from leltar.schemas.api import CategoryOut

router = APIRouter(prefix="/api/categories", tags=["catalog"])


@router.get("", response_model=list[CategoryOut])
async def list_categories(_: AuthDep, session: SessionDep) -> list[CategoryOut]:
    rows = (
        await session.scalars(select(Category).order_by(Category.sort_order, Category.name))
    ).all()
    return [CategoryOut.model_validate(row) for row in rows]
