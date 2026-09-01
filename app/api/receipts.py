"""Receipt upload, listing, review and confirmation."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, Query, Response, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.api.deps import AuthDep, SessionDep, SettingsDep
from app.models import (
    Correction,
    LineKind,
    Merchant,
    Receipt,
    ReceiptItem,
    ReceiptStatus,
)
from app.schemas.api import (
    ItemOut,
    ItemPatch,
    ReceiptDetail,
    ReceiptPatch,
    ReceiptSummary,
    UploadResponse,
)
from app.services.catalog import link_product, resolve_merchant
from app.services.ingest import IngestError, ingest_image

router = APIRouter(prefix="/api/receipts", tags=["receipts"])


def _to_summary(receipt: Receipt, merchant_name: str | None, item_count: int) -> ReceiptSummary:
    summary = ReceiptSummary.model_validate(receipt)
    summary.merchant_name = merchant_name
    summary.item_count = item_count
    return summary


@router.post("", response_model=UploadResponse, status_code=status.HTTP_202_ACCEPTED)
async def upload_receipt(
    _: AuthDep,
    session: SessionDep,
    settings: SettingsDep,
    response: Response,
    file: UploadFile = File(..., description="A photo of the receipt."),
    source: str = Query("web", description="web | shortcut | folder"),
) -> UploadResponse:
    """Accept a photo and queue it. Returns immediately; the worker extracts in the background."""
    data = await file.read()
    try:
        receipt, created = await ingest_image(session, data, settings, source=source)
    except IngestError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    await session.commit()
    if not created:
        response.status_code = status.HTTP_200_OK
    return UploadResponse(id=receipt.id, status=receipt.status, duplicate=not created)


@router.get("", response_model=list[ReceiptSummary])
async def list_receipts(
    _: AuthDep,
    session: SessionDep,
    status_filter: str | None = Query(None, alias="status"),
    merchant_id: uuid.UUID | None = None,
    limit: int = Query(50, le=200),
    offset: int = 0,
) -> list[ReceiptSummary]:
    item_counts = (
        select(ReceiptItem.receipt_id, func.count().label("n"))
        .group_by(ReceiptItem.receipt_id)
        .subquery()
    )
    stmt = (
        select(Receipt, Merchant.name, func.coalesce(item_counts.c.n, 0))
        .outerjoin(Merchant, Receipt.merchant_id == Merchant.id)
        .outerjoin(item_counts, item_counts.c.receipt_id == Receipt.id)
        .order_by(Receipt.purchased_at.desc().nullslast(), Receipt.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    if status_filter:
        stmt = stmt.where(Receipt.status == status_filter)
    if merchant_id:
        stmt = stmt.where(Receipt.merchant_id == merchant_id)

    rows = (await session.execute(stmt)).all()
    return [_to_summary(receipt, name, count) for receipt, name, count in rows]


@router.get("/{receipt_id}", response_model=ReceiptDetail)
async def get_receipt(_: AuthDep, session: SessionDep, receipt_id: uuid.UUID) -> ReceiptDetail:
    receipt = await session.scalar(
        select(Receipt).where(Receipt.id == receipt_id).options(selectinload(Receipt.items))
    )
    if receipt is None:
        raise HTTPException(status_code=404, detail="No such receipt.")

    detail = ReceiptDetail.model_validate(receipt)
    detail.item_count = len(receipt.items)
    if receipt.merchant_id:
        merchant = await session.get(Merchant, receipt.merchant_id)
        detail.merchant_name = merchant.name if merchant else None
    return detail


@router.get("/{receipt_id}/image")
async def get_receipt_image(_: AuthDep, session: SessionDep, receipt_id: uuid.UUID) -> FileResponse:
    """Serve the stored photo, so the review screen can show it beside the parsed fields."""
    receipt = await session.get(Receipt, receipt_id)
    if receipt is None:
        raise HTTPException(status_code=404, detail="No such receipt.")

    path = Path(receipt.image_path)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="The image file is missing from storage.")
    return FileResponse(path, media_type=receipt.image_mime)


@router.patch("/{receipt_id}", response_model=ReceiptDetail)
async def update_receipt(
    _: AuthDep, session: SessionDep, receipt_id: uuid.UUID, patch: ReceiptPatch
) -> ReceiptDetail:
    """Fix header fields. Every change is logged as a correction."""
    receipt = await session.scalar(
        select(Receipt).where(Receipt.id == receipt_id).options(selectinload(Receipt.items))
    )
    if receipt is None:
        raise HTTPException(status_code=404, detail="No such receipt.")

    changes = patch.model_dump(exclude_unset=True)

    if "merchant_name" in changes:
        merchant = await resolve_merchant(session, changes.pop("merchant_name"))
        if merchant is not None:
            _log_correction(session, receipt.id, "merchant_id", receipt.merchant_id, merchant.id)
            receipt.merchant_id = merchant.id

    for field, value in changes.items():
        old = getattr(receipt, field)
        if old != value:
            _log_correction(session, receipt.id, field, old, value)
            setattr(receipt, field, value)

    await session.commit()
    return await get_receipt(_, session, receipt_id)


@router.post("/{receipt_id}/confirm", response_model=ReceiptDetail)
async def confirm_receipt(
    _: AuthDep, session: SessionDep, receipt_id: uuid.UUID
) -> ReceiptDetail:
    """Mark a receipt as checked. Confirmed receipts are treated as ground truth in stats."""
    receipt = await session.get(Receipt, receipt_id)
    if receipt is None:
        raise HTTPException(status_code=404, detail="No such receipt.")

    receipt.status = ReceiptStatus.CONFIRMED.value
    receipt.confirmed_at = datetime.now(UTC)
    receipt.review_reasons = None
    await session.commit()
    return await get_receipt(_, session, receipt_id)


@router.post("/{receipt_id}/reprocess", response_model=ReceiptDetail)
async def reprocess_receipt(
    _: AuthDep, session: SessionDep, receipt_id: uuid.UUID
) -> ReceiptDetail:
    """Send a receipt back through extraction - after a prompt change or an engine switch."""
    receipt = await session.get(Receipt, receipt_id)
    if receipt is None:
        raise HTTPException(status_code=404, detail="No such receipt.")

    receipt.status = ReceiptStatus.PENDING.value
    receipt.attempts = 0
    receipt.error = None
    await session.commit()
    return await get_receipt(_, session, receipt_id)


@router.delete("/{receipt_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_receipt(
    _: AuthDep, session: SessionDep, receipt_id: uuid.UUID, keep_image: bool = False
) -> None:
    receipt = await session.get(Receipt, receipt_id)
    if receipt is None:
        raise HTTPException(status_code=404, detail="No such receipt.")

    path = Path(receipt.image_path)
    await session.delete(receipt)
    await session.commit()

    if not keep_image and path.is_file():
        path.unlink(missing_ok=True)


@router.patch("/items/{item_id}", response_model=ItemOut)
async def update_item(
    _: AuthDep, session: SessionDep, item_id: uuid.UUID, patch: ItemPatch
) -> ItemOut:
    """Fix a line item, and optionally teach the app what that line means for next time."""
    item = await session.get(ReceiptItem, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="No such item.")

    changes = patch.model_dump(exclude_unset=True)
    remember = changes.pop("remember_mapping", False)

    if "kind" in changes and changes["kind"] not in {k.value for k in LineKind}:
        raise HTTPException(status_code=400, detail=f"Unknown line kind: {changes['kind']}")

    for field, value in changes.items():
        old = getattr(item, field)
        if old != value:
            _log_correction(session, item.receipt_id, field, old, value, item_id=item.id)
            setattr(item, field, value)

    if remember and item.product_id:
        receipt = await session.get(Receipt, item.receipt_id)
        await link_product(session, item.product_id, item.raw_name, receipt.merchant_id)
        # Keep the category in step with the product it now points at.
        from app.models import Product

        product = await session.get(Product, item.product_id)
        if product is not None and product.category_id and not item.category_id:
            item.category_id = product.category_id

    await session.commit()
    await session.refresh(item)
    return ItemOut.model_validate(item)


def _log_correction(
    session: SessionDep,
    receipt_id: uuid.UUID,
    field: str,
    old: object,
    new: object,
    item_id: uuid.UUID | None = None,
) -> None:
    """Record one edit. Takes the receipt id rather than the object on purpose: reading
    `item.receipt` here would lazy-load a relationship, which raises MissingGreenlet on an
    async session and made every line-item edit fail with a 500."""
    session.add(
        Correction(
            receipt_id=receipt_id,
            item_id=item_id,
            field=field,
            old_value=None if old is None else str(old),
            new_value=None if new is None else str(new),
        )
    )
