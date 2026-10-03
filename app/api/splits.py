"""Shared bills and who owes whom - the Elszámolás page."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.api.deps import AuthDep, SessionDep
from app.models import Settlement, User
from app.schemas.api import (
    SettlementIn,
    SettlementOut,
    SplitSummary,
    TransferOut,
    UserBalance,
)
from app.services.splits import balance, split_receipts

router = APIRouter(prefix="/api/split", tags=["split"])


@router.get("/summary", response_model=SplitSummary)
async def summary(_: AuthDep, session: SessionDep) -> SplitSummary:
    names = {
        user.id: user.display_name for user in (await session.scalars(select(User))).all()
    }
    result = await balance(session)
    settlements = (
        await session.scalars(
            select(Settlement).order_by(Settlement.settled_at.desc()).limit(50)
        )
    ).all()
    return SplitSummary(
        balances=[
            UserBalance(user_id=user_id, display_name=names.get(user_id, "?"), net=amount)
            for user_id, amount in sorted(result.net.items(), key=lambda kv: -kv[1])
        ],
        transfers=[
            TransferOut(
                from_user_id=t.from_user_id,
                from_name=names.get(t.from_user_id, "?"),
                to_user_id=t.to_user_id,
                to_name=names.get(t.to_user_id, "?"),
                amount=t.amount,
            )
            for t in result.transfers
        ],
        receipts=await split_receipts(session),
        settlements=[
            SettlementOut(
                id=s.id,
                from_user_id=s.from_user_id,
                from_name=names.get(s.from_user_id, "?"),
                to_user_id=s.to_user_id,
                to_name=names.get(s.to_user_id, "?"),
                amount=s.amount,
                settled_at=s.settled_at,
                note=s.note,
            )
            for s in settlements
        ],
    )


@router.post("/settlements", response_model=SettlementOut, status_code=status.HTTP_201_CREATED)
async def record_settlement(
    _: AuthDep, session: SessionDep, body: SettlementIn
) -> SettlementOut:
    """Money handed over to even things out. Recorded, not inferred: you say it happened."""
    if body.from_user_id == body.to_user_id:
        raise HTTPException(status_code=422, detail="Két különböző ember kell hozzá.")
    people = {
        user.id: user
        for user in (
            await session.scalars(
                select(User).where(User.id.in_([body.from_user_id, body.to_user_id]))
            )
        ).all()
    }
    if len(people) != 2:
        raise HTTPException(status_code=404, detail="Nincs ilyen felhasználó.")

    settlement = Settlement(
        from_user_id=body.from_user_id,
        to_user_id=body.to_user_id,
        amount=body.amount,
        note=(body.note or "").strip() or None,
    )
    session.add(settlement)
    await session.commit()
    await session.refresh(settlement)
    return SettlementOut(
        id=settlement.id,
        from_user_id=settlement.from_user_id,
        from_name=people[settlement.from_user_id].display_name,
        to_user_id=settlement.to_user_id,
        to_name=people[settlement.to_user_id].display_name,
        amount=settlement.amount,
        settled_at=settlement.settled_at,
        note=settlement.note,
    )


@router.delete("/settlements/{settlement_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_settlement(_: AuthDep, session: SessionDep, settlement_id: uuid.UUID) -> None:
    """For a settlement recorded by mistake; the balance simply goes back to what it was."""
    settlement = await session.get(Settlement, settlement_id)
    if settlement is None:
        raise HTTPException(status_code=404, detail="No such settlement.")
    await session.delete(settlement)
    await session.commit()
