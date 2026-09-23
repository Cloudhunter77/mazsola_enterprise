"""The shopping list.

Nothing here can write to `receipts`: a list of what you intend to buy must not be able to
become a record of what you did.
"""

from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.deps import AuthDep, SessionDep, SettingsDep
from app.models import ItemSource, Product, ShoppingItem
from app.schemas.shopping import (
    AddItemIn,
    ShoppingItemOut,
    ShoppingSuggestion,
    UpdateItemIn,
)
from app.services.ingest import IngestError
from app.services.shopping import (
    add_item,
    add_photo,
    clear_done,
    set_done,
    suggestions,
)

router = APIRouter(prefix="/api/shopping", tags=["shopping list"])


def _out(item: ShoppingItem) -> ShoppingItemOut:
    return ShoppingItemOut(
        id=item.id,
        product_id=item.product_id,
        product_name=item.product.canonical_name if item.product else None,
        raw_name=item.raw_name,
        label=item.label,
        has_photo=bool(item.image_path),
        quantity=item.quantity,
        note=item.note,
        source=item.source,
        status=item.status,
        confidence=item.confidence,
        error=item.error,
        done=item.done,
        done_at=item.done_at,
        created_at=item.created_at,
    )


@router.get("", response_model=list[ShoppingItemOut])
async def list_items(
    _: AuthDep,
    session: SessionDep,
    include_done: bool = Query(True, description="Keep ticked-off items in the answer."),
) -> list[ShoppingItemOut]:
    """The list: still to buy first, oldest first within that, then what is ticked off."""
    stmt = (
        select(ShoppingItem)
        .options(selectinload(ShoppingItem.product))
        .order_by(ShoppingItem.done, ShoppingItem.created_at)
    )
    if not include_done:
        stmt = stmt.where(ShoppingItem.done.is_(False))
    return [_out(item) for item in (await session.scalars(stmt)).all()]


@router.post("", response_model=ShoppingItemOut, status_code=status.HTTP_201_CREATED)
async def add(_: AuthDep, session: SessionDep, body: AddItemIn) -> ShoppingItemOut:
    """Add a product or a typed name. Adding what is already on the list bumps it instead."""
    if body.product_id is not None:
        product = await session.get(Product, body.product_id)
        if product is None:
            raise HTTPException(status_code=404, detail="No such product.")

    try:
        item = await add_item(
            session,
            product_id=body.product_id,
            raw_name=body.raw_name,
            quantity=body.quantity,
            note=body.note,
            source=ItemSource.PRODUCT.value if body.product_id else ItemSource.MANUAL.value,
        )
    except IngestError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    await session.commit()
    await session.refresh(item, ["product"])
    return _out(item)


@router.post("/scan", response_model=ShoppingItemOut, status_code=status.HTTP_202_ACCEPTED)
async def scan(
    _: AuthDep,
    session: SessionDep,
    settings: SettingsDep,
    file: UploadFile = File(..., description="A photo of the product you want more of."),
    quantity: str | None = Query(None),
) -> ShoppingItemOut:
    """Photograph a product onto the list.

    The item is on the list before anything has looked at the picture. Recognition happens
    in the background and may attach a product to it; if it cannot, the photograph stays,
    which is a complete list entry on its own.
    """
    try:
        item = await add_photo(session, await file.read(), settings, quantity=quantity)
    except IngestError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    await session.commit()
    await session.refresh(item, ["product"])
    return _out(item)


@router.get("/suggestions", response_model=list[ShoppingSuggestion])
async def what_you_usually_buy(_: AuthDep, session: SessionDep) -> list[ShoppingSuggestion]:
    """Your most-bought products that are not on the list, for one-tap adding."""
    return [
        ShoppingSuggestion(product_id=product.id, canonical_name=product.canonical_name)
        for product in await suggestions(session)
    ]


@router.get("/{item_id}/image")
async def get_item_image(_: AuthDep, session: SessionDep, item_id: uuid.UUID) -> FileResponse:
    item = await session.get(ShoppingItem, item_id)
    if item is None or not item.image_path:
        raise HTTPException(status_code=404, detail="No photo for that item.")
    path = Path(item.image_path)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="The photo file is missing.")
    return FileResponse(path, media_type=item.image_mime or "image/jpeg")


@router.patch("/{item_id}", response_model=ShoppingItemOut)
async def update(
    _: AuthDep, session: SessionDep, item_id: uuid.UUID, body: UpdateItemIn
) -> ShoppingItemOut:
    item = await session.get(ShoppingItem, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="No such item.")

    patch = body.model_dump(exclude_unset=True)
    if "done" in patch:
        await set_done(session, item, bool(patch.pop("done")))
    for field, value in patch.items():
        setattr(item, field, value)

    await session.commit()
    await session.refresh(item, ["product"])
    return _out(item)


@router.post("/clear-done")
async def remove_ticked_off(_: AuthDep, session: SessionDep) -> dict:
    removed = await clear_done(session)
    await session.commit()
    return {"removed": removed}


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_item(_: AuthDep, session: SessionDep, item_id: uuid.UUID) -> None:
    item = await session.get(ShoppingItem, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="No such item.")
    path = Path(item.image_path) if item.image_path else None
    await session.delete(item)
    await session.commit()
    if path:
        path.unlink(missing_ok=True)
