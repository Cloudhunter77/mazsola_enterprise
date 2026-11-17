"""Zsebek: Revolut pockets, the money moved into them, and what they paid for."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, time

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import delete, func, select

from app.api.deps import AuthDep, SessionDep
from app.models import (
    BudgetLine,
    Pocket,
    PocketTransfer,
    User,
    WishlistItem,
)
from app.schemas.budget import (
    BucketOut,
    CheckIn,
    ManualTransferIn,
    MoveIn,
    PersonOut,
    PieceOut,
    PocketCheckOut,
    PocketIn,
    PocketOut,
    PocketsOverview,
    PocketView,
    ProposedTransferOut,
    PurchaseIn,
    TransferDoneIn,
    TransferOut,
)
from app.services import budget
from app.services import pockets as pk
from app.services.manual import ManualEntryError, create_manual_receipt
from app.services.stats import LOCAL_TZ

router = APIRouter(prefix="/api/pockets", tags=["pockets"])

UNASSIGNED = "Nincs hozzárendelve"


def _bad(error: Exception) -> HTTPException:
    return HTTPException(status_code=422, detail=str(error))


def transfer_out(
    transfer: PocketTransfer, pockets: dict[uuid.UUID, Pocket], lines: dict[uuid.UUID, str]
) -> TransferOut:
    pocket = pockets.get(transfer.pocket_id)
    return TransferOut(
        id=transfer.id,
        pocket_id=transfer.pocket_id,
        pocket_name=pocket.name if pocket else "?",
        holder_id=pocket.holder_id if pocket else None,
        line_id=transfer.line_id,
        line_name=lines.get(transfer.line_id) if transfer.line_id else None,
        amount=transfer.amount,
        on=transfer.on,
        kind=transfer.kind,
        done=transfer.done,
        from_user_id=transfer.from_user_id,
        note=transfer.note,
    )


async def transfers_out(
    session: SessionDep, transfers: list[PocketTransfer]
) -> list[TransferOut]:
    pockets = {p.id: p for p in (await session.scalars(select(Pocket))).all()}
    lines = dict((await session.execute(select(BudgetLine.id, BudgetLine.name))).all())
    return [transfer_out(t, pockets, lines) for t in transfers]


def _pieces(pieces: list[budget.Piece]) -> list[PieceOut]:
    return [
        PieceOut(receipt_id=p.receipt_id, day=p.day, merchant=p.merchant, amount=p.amount)
        for p in pieces
    ]


def pocket_view_out(view: budget.PocketView) -> PocketView:
    return PocketView(
        pocket=PocketOut.model_validate(view.pocket),
        opening=view.opening,
        closing=view.closing,
        buckets=[
            BucketOut(
                line_id=b.line.id if b.line else None,
                name=b.line.name if b.line else UNASSIGNED,
                owner_id=b.line.owner_id if b.line else None,
                kind=b.line.kind if b.line else None,
                is_wishlist=b.line.is_wishlist if b.line else False,
                target_amount=b.line.target_amount if b.line else None,
                target_date=b.line.target_date if b.line else None,
                bought_on=b.line.bought_on if b.line else None,
                category_ids=b.line.category_ids if b.line else [],
                plan=b.plan,
                opening=b.opening,
                money_in=b.money_in,
                money_out=b.money_out,
                closing=b.closing,
                suggestion=b.suggestion,
                receipts=_pieces(b.pieces),
            )
            for b in view.buckets
        ],
        check=(
            PocketCheckOut(
                checked_on=view.check.checked_on,
                balance=view.check.balance,
                expected=view.expected_at_check,
                difference=view.check.balance - view.expected_at_check,
            )
            if view.check is not None and view.expected_at_check is not None else None
        ),
    )


@router.get("", response_model=list[PocketOut])
async def list_pockets(_: AuthDep, session: SessionDep) -> list[PocketOut]:
    rows = await session.scalars(select(Pocket).order_by(Pocket.sort_order, Pocket.name))
    return [PocketOut.model_validate(p) for p in rows]


@router.get("/overview", response_model=PocketsOverview)
async def overview(_: AuthDep, session: SessionDep) -> PocketsOverview:
    """Every pocket earmark by earmark, over the current period - or this calendar month
    before the first meeting - plus the transfers still waiting to be sent."""
    today = budget.today_local()
    spans = await budget.periods(session)
    if spans:
        start, month = spans[-1].start, spans[-1].period.month
    else:
        start = month = budget.first_of(today)
    led = await pk.ledger(session)
    views = await budget.pocket_views(session, led, start, None, month)
    return PocketsOverview(
        users=[PersonOut.model_validate(u) for u in await budget.household(session)],
        start=start,
        month=month,
        pockets=[pocket_view_out(v) for v in views],
        pending=await transfers_out(session, await budget.pending_transfers(session)),
    )


async def _check_holder(session: SessionDep, holder_id: uuid.UUID | None) -> None:
    if holder_id is not None and await session.get(User, holder_id) is None:
        raise HTTPException(status_code=422, detail="Nincs ilyen felhasználó.")


@router.post("", response_model=PocketOut, status_code=status.HTTP_201_CREATED)
async def create_pocket(_: AuthDep, session: SessionDep, body: PocketIn) -> PocketOut:
    """A pocket, with what it holds today: the app keeps its books from that day on."""
    await _check_holder(session, body.holder_id)
    order = await session.scalar(select(func.max(Pocket.sort_order))) or 0
    pocket = Pocket(
        name=body.name.strip(), holder_id=body.holder_id,
        opening_balance=body.opening_balance,
        opened_on=body.opened_on or budget.today_local(),
        active=body.active, notes=(body.notes or "").strip() or None, sort_order=order + 1,
    )
    session.add(pocket)
    await session.commit()
    await session.refresh(pocket)
    return PocketOut.model_validate(pocket)


@router.patch("/{pocket_id}", response_model=PocketOut)
async def update_pocket(
    _: AuthDep, session: SessionDep, pocket_id: uuid.UUID, body: PocketIn
) -> PocketOut:
    pocket = await session.get(Pocket, pocket_id)
    if pocket is None:
        raise HTTPException(status_code=404, detail="Nincs ilyen zseb.")
    await _check_holder(session, body.holder_id)
    pocket.name = body.name.strip()
    pocket.holder_id = body.holder_id
    pocket.opening_balance = body.opening_balance
    if body.opened_on is not None:
        pocket.opened_on = body.opened_on
    pocket.active = body.active
    pocket.notes = (body.notes or "").strip() or None
    await session.commit()
    await session.refresh(pocket)
    return PocketOut.model_validate(pocket)


@router.delete("/{pocket_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_pocket(_: AuthDep, session: SessionDep, pocket_id: uuid.UUID) -> None:
    """Delete a pocket nothing refers to; one with history or earmarks is only archived."""
    pocket = await session.get(Pocket, pocket_id)
    if pocket is None:
        raise HTTPException(status_code=404, detail="Nincs ilyen zseb.")
    used = (
        await session.scalar(
            select(func.count(PocketTransfer.id)).where(PocketTransfer.pocket_id == pocket.id)
        )
        or await session.scalar(
            select(func.count(BudgetLine.id)).where(BudgetLine.pocket_id == pocket.id)
        )
    )
    if used:
        pocket.active = False
    else:
        await session.delete(pocket)
    await session.commit()


@router.post("/checks", status_code=status.HTTP_204_NO_CONTENT)
async def add_check(principal: AuthDep, session: SessionDep, body: CheckIn) -> None:
    """What Revolut shows in a pocket today, to compare with what the app expects."""
    try:
        await budget.record_check(
            session, body.pocket_id, body.balance, body.on or budget.today_local(),
            principal.user_id,
        )
    except budget.BudgetError as exc:
        raise _bad(exc) from exc
    await session.commit()


@router.get("/proposed", response_model=list[ProposedTransferOut])
async def proposed(
    _: AuthDep, session: SessionDep, month: date
) -> list[ProposedTransferOut]:
    """The meeting's transfer checklist for a month: who sends what into which pocket."""
    people = [u.id for u in await budget.household(session) if u.active]
    return [
        ProposedTransferOut(
            line_id=t.line.id, line_name=t.line.name, pocket_id=t.pocket.id,
            pocket_name=t.pocket.name, holder_id=t.pocket.holder_id,
            from_user_id=t.from_user_id, amount=t.amount,
        )
        for t in await budget.proposed_transfers(session, budget.first_of(month), people)
    ]


async def _check_line_in_pocket(
    session: SessionDep, pocket_id: uuid.UUID, line_id: uuid.UUID | None
) -> None:
    if await session.get(Pocket, pocket_id) is None:
        raise HTTPException(status_code=422, detail="Nincs ilyen zseb.")
    if line_id is not None:
        line = await session.get(BudgetLine, line_id)
        if line is None or line.pocket_id != pocket_id:
            raise HTTPException(status_code=422, detail="Ez a sor nem ebben a zsebben van.")


@router.post("/transfers", status_code=status.HTTP_201_CREATED)
async def manual_transfer(
    principal: AuthDep, session: SessionDep, body: ManualTransferIn
) -> dict:
    """An extra deposit or withdrawal, made by hand outside the monthly plan."""
    await _check_line_in_pocket(session, body.pocket_id, body.line_id)
    if body.amount == 0:
        raise HTTPException(status_code=422, detail="Az összeg nem lehet nulla.")
    transfer = PocketTransfer(
        pocket_id=body.pocket_id, line_id=body.line_id, amount=body.amount,
        on=body.on or budget.today_local(), kind="manual", done=True,
        done_at=datetime.now(UTC), from_user_id=principal.user_id,
        note=(body.note or "").strip() or None,
    )
    session.add(transfer)
    await session.commit()
    return {"id": str(transfer.id)}


@router.post("/moves", status_code=status.HTTP_201_CREATED)
async def move(_: AuthDep, session: SessionDep, body: MoveIn) -> dict:
    """Move money between earmarks: unassigned money into a goal, one goal into another."""
    await _check_line_in_pocket(session, body.pocket_id, body.from_line_id)
    try:
        await budget.move_money(
            session, pocket_id=body.pocket_id, from_line=body.from_line_id,
            to_line=body.to_line_id, amount=body.amount,
            on=body.on or budget.today_local(), note=(body.note or "").strip() or None,
        )
    except budget.BudgetError as exc:
        raise _bad(exc) from exc
    await session.commit()
    return {"ok": True}


@router.patch("/transfers/{transfer_id}", status_code=status.HTTP_204_NO_CONTENT)
async def set_transfer_done(
    _: AuthDep, session: SessionDep, transfer_id: uuid.UUID, body: TransferDoneIn
) -> None:
    """Tick a planned transfer as sent (it counts from today), or untick it."""
    transfer = await session.get(PocketTransfer, transfer_id)
    if transfer is None:
        raise HTTPException(status_code=404, detail="Nincs ilyen átutalás.")
    if body.done:
        await budget.mark_transfer_done(session, transfer, budget.today_local())
    else:
        transfer.done = False
        transfer.done_at = None
    await session.commit()


@router.delete("/transfers/{transfer_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_transfer(_: AuthDep, session: SessionDep, transfer_id: uuid.UUID) -> None:
    """Take back a transfer recorded by mistake - both halves, if it was a move."""
    transfer = await session.get(PocketTransfer, transfer_id)
    if transfer is None:
        raise HTTPException(status_code=404, detail="Nincs ilyen átutalás.")
    if transfer.group_id is not None:
        await session.execute(
            delete(PocketTransfer).where(PocketTransfer.group_id == transfer.group_id)
        )
    else:
        await session.delete(transfer)
    await session.commit()


@router.post("/purchase", status_code=status.HTTP_201_CREATED)
async def purchase(principal: AuthDep, session: SessionDep, body: PurchaseIn) -> dict:
    """"Megvettük, nincs blokk": type in what a goal or wishlist item cost (D30).

    It becomes an ordinary typed-in receipt with one line, linked to the goal or the item,
    so it draws from the right pocket and shows up in the statistics like any purchase.
    """
    if (body.earmark_id is None) == (body.wishlist_item_id is None):
        raise HTTPException(status_code=422, detail="Egy célt vagy egy tételt adj meg.")
    earmark_id = body.earmark_id
    name = (body.name or "").strip()
    wish: WishlistItem | None = None
    if body.wishlist_item_id is not None:
        wish = await session.get(WishlistItem, body.wishlist_item_id)
        if wish is None:
            raise HTTPException(status_code=404, detail="Nincs ilyen tétel.")
        name = name or wish.name
        earmark_id = await wishlist_earmark(session, wish.owner_id)
    else:
        line = await session.get(BudgetLine, earmark_id)
        if line is None or line.pocket_id is None:
            raise HTTPException(status_code=422, detail="Nincs ilyen cél.")
        name = name or line.name

    on = body.on or budget.today_local()
    try:
        receipt = await create_manual_receipt(
            session,
            merchant_name=(body.merchant_name or "").strip() or name,
            purchased_at=datetime.combine(on, time(12, 0), tzinfo=LOCAL_TZ),
            items=[{"raw_name": name, "gross_amount": body.price,
                    "category_id": body.category_id}],
        )
    except ManualEntryError as exc:
        raise _bad(exc) from exc
    receipt.uploaded_by_id = receipt.paid_by_id = principal.user_id
    for item in receipt.items:
        item.earmark_id = earmark_id
        item.wishlist_item_id = wish.id if wish else None
    if wish is not None:
        wish.bought_on = on
    await session.commit()
    return {"receipt_id": str(receipt.id)}


async def wishlist_earmark(session: SessionDep, owner_id: uuid.UUID | None) -> uuid.UUID | None:
    """The owner's wishlist pot, which their wishlist purchases draw from."""
    return await session.scalar(
        select(BudgetLine.id)
        .where(BudgetLine.is_wishlist.is_(True))
        .where(BudgetLine.active.is_(True))
        .where(
            BudgetLine.owner_id == owner_id if owner_id is not None
            else BudgetLine.owner_id.is_(None)
        )
    )

