"""Kívánságlista: things you mean to buy, not this week but some time (D31).

An item is bought when a real purchase is linked to it - a receipt line from the receipt's
page, or one typed in with "Megvettük, nincs blokk" - which also records what it actually
cost. "Listára" copies it onto the shopping list, linked, so the shop trip knows about it;
ticking it off there does not close it here, because that says it was picked up, not what
it cost.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from decimal import Decimal

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select, update

from app.api.deps import AuthDep, SessionDep
from app.api.pockets import wishlist_earmark
from app.models import (
    PRIORITIES,
    Product,
    ReceiptItem,
    ShoppingItem,
    User,
    WishlistItem,
)
from app.schemas.budget import WishlistIn, WishlistOut
from app.services.shopping import add_item

router = APIRouter(prefix="/api/wishlist", tags=["wishlist"])


async def _out(session: SessionDep, items: list[WishlistItem]) -> list[WishlistOut]:
    ids = [item.id for item in items]
    linked: dict[uuid.UUID, list[tuple[uuid.UUID, Decimal]]] = defaultdict(list)
    if ids:
        for wish_id, receipt_id, amount in (
            await session.execute(
                select(ReceiptItem.wishlist_item_id, ReceiptItem.receipt_id,
                       ReceiptItem.gross_amount)
                .where(ReceiptItem.wishlist_item_id.in_(ids))
            )
        ).all():
            linked[wish_id].append((receipt_id, Decimal(amount or 0)))
    shopping = {
        s.id: s for s in (
            await session.scalars(
                select(ShoppingItem).where(
                    ShoppingItem.id.in_([i.shopping_item_id for i in items if i.shopping_item_id])
                )
            )
        ).all()
    }
    products = {
        p.id: p.canonical_name for p in (
            await session.scalars(
                select(Product).where(Product.id.in_([i.product_id for i in items if i.product_id]))
            )
        ).all()
    }
    earmarks: dict[uuid.UUID | None, uuid.UUID | None] = {}
    out: list[WishlistOut] = []
    for item in items:
        if item.owner_id not in earmarks:
            earmarks[item.owner_id] = await wishlist_earmark(session, item.owner_id)
        on_list = item.shopping_item_id in shopping and not shopping[item.shopping_item_id].done
        lines = linked.get(item.id, [])
        out.append(WishlistOut(
            id=item.id, owner_id=item.owner_id, name=item.name, priority=item.priority,
            priority_label=PRIORITIES.get(item.priority, "?"),
            estimated_price=item.estimated_price, link=item.link, note=item.note,
            product_id=item.product_id, product_name=products.get(item.product_id),
            on_list=on_list, bought_on=item.bought_on,
            actual_price=sum((a for _, a in lines), Decimal("0")) if lines else None,
            receipt_ids=list(dict.fromkeys(r for r, _ in lines)),
            earmark_id=earmarks[item.owner_id],
        ))
    return out


def _order(item: WishlistItem):
    # Open before bought; then the most wanted first; then the cheaper first.
    return (
        item.bought_on is not None,
        -item.priority,
        item.estimated_price if item.estimated_price is not None else Decimal("1e12"),
        item.name,
    )


@router.get("", response_model=list[WishlistOut])
async def list_wishlist(_: AuthDep, session: SessionDep) -> list[WishlistOut]:
    items = sorted((await session.scalars(select(WishlistItem))).all(), key=_order)
    return await _out(session, items)


async def _check(session: SessionDep, body: WishlistIn) -> None:
    if body.owner_id is not None and await session.get(User, body.owner_id) is None:
        raise HTTPException(status_code=422, detail="Nincs ilyen felhasználó.")
    if body.product_id is not None and await session.get(Product, body.product_id) is None:
        raise HTTPException(status_code=422, detail="Nincs ilyen termék.")


def _apply(item: WishlistItem, body: WishlistIn) -> None:
    item.owner_id = body.owner_id
    item.name = body.name.strip()
    item.priority = body.priority
    item.estimated_price = body.estimated_price
    item.link = (body.link or "").strip() or None
    item.note = (body.note or "").strip() or None
    item.product_id = body.product_id


@router.post("", response_model=WishlistOut, status_code=status.HTTP_201_CREATED)
async def add_wish(_: AuthDep, session: SessionDep, body: WishlistIn) -> WishlistOut:
    await _check(session, body)
    item = WishlistItem()
    _apply(item, body)
    session.add(item)
    await session.commit()
    await session.refresh(item)
    return (await _out(session, [item]))[0]


async def _get(session: SessionDep, wish_id: uuid.UUID) -> WishlistItem:
    item = await session.get(WishlistItem, wish_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Nincs ilyen tétel.")
    return item


@router.patch("/{wish_id}", response_model=WishlistOut)
async def update_wish(
    _: AuthDep, session: SessionDep, wish_id: uuid.UUID, body: WishlistIn
) -> WishlistOut:
    item = await _get(session, wish_id)
    await _check(session, body)
    _apply(item, body)
    await session.commit()
    await session.refresh(item)
    return (await _out(session, [item]))[0]


@router.delete("/{wish_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_wish(_: AuthDep, session: SessionDep, wish_id: uuid.UUID) -> None:
    """Remove an item. A purchase linked to it stays a purchase, just no longer linked."""
    item = await _get(session, wish_id)
    await session.delete(item)
    await session.commit()


@router.post("/{wish_id}/to-list", response_model=WishlistOut)
async def to_shopping_list(_: AuthDep, session: SessionDep, wish_id: uuid.UUID) -> WishlistOut:
    """Copy it onto the shopping list, linked, so it can be bought on the next trip."""
    item = await _get(session, wish_id)
    entry = await add_item(
        session,
        product_id=item.product_id,
        raw_name=None if item.product_id else item.name,
        note="Kívánságlistáról",
    )
    await session.flush()
    item.shopping_item_id = entry.id
    await session.commit()
    return (await _out(session, [item]))[0]


@router.post("/{wish_id}/reopen", response_model=WishlistOut)
async def reopen(_: AuthDep, session: SessionDep, wish_id: uuid.UUID) -> WishlistOut:
    """Not bought after all: unlink the purchase, which goes back to ordinary spending."""
    item = await _get(session, wish_id)
    await session.execute(
        update(ReceiptItem)
        .where(ReceiptItem.wishlist_item_id == item.id)
        .values(wishlist_item_id=None, earmark_id=None)
    )
    item.bought_on = None
    await session.commit()
    return (await _out(session, [item]))[0]
