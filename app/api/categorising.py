"""Clearing out "Besorolatlan", a receipt at a time.

The automatic rules file what they recognise and leave the rest blank on purpose - a wrong
category is the quiet kind of wrong. The receipt is the unit that blank is dealt with in,
because it is the unit you remember: a restaurant bill, a pharmacy visit, a hardware-store
run is one kind of spending however many lines it prints. A mixed supermarket shop is the
exception, and for that the receipt's own screen still files line by line.
"""

from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, HTTPException, Query

from app.api.deps import AuthDep, SessionDep
from app.models import Category, Receipt
from app.schemas.api import FileReceiptIn, FileReceiptOut, ReceiptToFile, UndoFilingIn
from app.services.categorise import file_receipt, receipts_to_file, undo_filing

router = APIRouter(prefix="/api/categorise", tags=["categorise"])


@router.get("/receipts", response_model=list[ReceiptToFile])
async def list_receipts(
    _: AuthDep, session: SessionDep, limit: int = Query(100, ge=1, le=500)
) -> list[ReceiptToFile]:
    return [
        ReceiptToFile(
            **{
                **row,
                "uncategorised_amount": Decimal(row["uncategorised_amount"]).quantize(
                    Decimal("0.01")
                ),
            }
        )
        for row in await receipts_to_file(session, limit)
    ]


@router.post("/receipt", response_model=FileReceiptOut)
async def file_one(_: AuthDep, session: SessionDep, body: FileReceiptIn) -> FileReceiptOut:
    if await session.get(Category, body.category_id) is None:
        raise HTTPException(status_code=404, detail="No such category.")
    if await session.get(Receipt, body.receipt_id) is None:
        raise HTTPException(status_code=404, detail="No such receipt.")
    filing = await file_receipt(
        session,
        body.receipt_id,
        body.category_id,
        remember_shop=body.remember_shop,
        replace_guesses=body.replace_guesses,
    )
    await session.commit()
    return FileReceiptOut(
        category_id=body.category_id,
        item_ids=filing.item_ids,
        lines=len(filing.item_ids) - filing.spread,
        spread=filing.spread,
        merchant_id=filing.merchant_id,
        previous_default=filing.previous_default,
    )


@router.post("/undo")
async def undo(_: AuthDep, session: SessionDep, body: UndoFilingIn) -> dict:
    reverted = await undo_filing(
        session, body.category_id, body.item_ids, body.merchant_id, body.previous_default
    )
    await session.commit()
    return {"reverted": reverted}
