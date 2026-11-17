"""Income: salaries confirmed from Rendszeres, and anything added by hand.

A salary is normally confirmed on the Rendszeres page or in Hónap, which writes an entry here
linked to its rule. A bonus, a refund or a gift of money is added directly. Deleting an entry
that confirmed a salary takes the confirmation with it, so that month's salary is expected
again rather than silently marked as skipped.
"""

from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import delete, select

from app.api.deps import AuthDep, SessionDep
from app.models import IncomeEntry, RecurringCharge, User
from app.schemas.budget import IncomeIn, IncomeOut
from app.services.budget import today_local

router = APIRouter(prefix="/api/income", tags=["income"])


async def _check(session: SessionDep, body: IncomeIn) -> None:
    if body.user_id is not None and await session.get(User, body.user_id) is None:
        raise HTTPException(status_code=422, detail="Nincs ilyen felhasználó.")
    if body.received_on > today_local():
        raise HTTPException(status_code=422, detail="A dátum nem lehet a jövőben.")


@router.get("", response_model=list[IncomeOut])
async def list_income(
    _: AuthDep, session: SessionDep, start: date | None = None, end: date | None = None
) -> list[IncomeOut]:
    """Income entries, newest first; `end` is exclusive."""
    stmt = select(IncomeEntry).order_by(IncomeEntry.received_on.desc(), IncomeEntry.created_at)
    if start is not None:
        stmt = stmt.where(IncomeEntry.received_on >= start)
    if end is not None:
        stmt = stmt.where(IncomeEntry.received_on < end)
    return [IncomeOut.model_validate(entry) for entry in (await session.scalars(stmt)).all()]


@router.post("", response_model=IncomeOut, status_code=status.HTTP_201_CREATED)
async def add_income(principal: AuthDep, session: SessionDep, body: IncomeIn) -> IncomeOut:
    await _check(session, body)
    entry = IncomeEntry(
        user_id=body.user_id,
        name=body.name.strip(),
        amount=body.amount,
        received_on=body.received_on,
        notes=(body.notes or "").strip() or None,
        created_by_id=principal.user_id,
    )
    session.add(entry)
    await session.commit()
    await session.refresh(entry)
    return IncomeOut.model_validate(entry)


@router.patch("/{income_id}", response_model=IncomeOut)
async def update_income(
    _: AuthDep, session: SessionDep, income_id: uuid.UUID, body: IncomeIn
) -> IncomeOut:
    entry = await session.get(IncomeEntry, income_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Nincs ilyen bevétel.")
    await _check(session, body)
    entry.user_id = body.user_id
    entry.name = body.name.strip()
    entry.amount = body.amount
    entry.received_on = body.received_on
    entry.notes = (body.notes or "").strip() or None
    await session.commit()
    await session.refresh(entry)
    return IncomeOut.model_validate(entry)


@router.delete("/{income_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_income(_: AuthDep, session: SessionDep, income_id: uuid.UUID) -> None:
    entry = await session.get(IncomeEntry, income_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Nincs ilyen bevétel.")
    # Explicitly, before the entry: the foreign key would only null the link, leaving a
    # charge row that points at nothing - which is how a skipped month is recorded.
    await session.execute(delete(RecurringCharge).where(RecurringCharge.income_id == entry.id))
    await session.delete(entry)
    await session.commit()
