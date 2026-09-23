"""The shopping list: adding to it, and recognising what was photographed.

The rule that matters here is when a photograph is allowed to become a *product* rather
than staying a picture. Two things must both hold:

* the model says it **read** the packaging rather than inferred it from shape and colour;
* the name it read resolves to an existing product **exactly**, by the same normalised
  match that links a receipt line - not something similar, not something close.

Anything short of that stays a photograph on the list, which is a perfectly good list
entry: you recognise your own shopping instantly, and nothing has been attached to the
wrong price history. That asymmetry is deliberate. A photograph that could have been
matched and was not costs you nothing. A wrong match is silent, and it corrupts the price
history of two products at once.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.extraction.base import ProductPhotoResult
from app.models import ItemSource, Product, ScanStatus, ShoppingItem
from app.services.catalog import resolve_product
from app.services.ingest import EXTENSIONS, IngestError, _verify_image, sha256_of

log = logging.getLogger(__name__)

# Below this the model is telling us it recognised the object rather than read it. A name
# produced that way is fine to show - `tej`, probably - and not fine to match on.
READ_IT_CONFIDENCE = 0.75


def _storage_path(settings: Settings, item_id: uuid.UUID, extension: str) -> Path:
    directory = settings.data_dir / "shopping" / f"{datetime.now(UTC):%Y}"
    directory.mkdir(parents=True, exist_ok=True)
    return directory / f"{item_id}{extension}"


async def add_item(
    session: AsyncSession,
    *,
    product_id: uuid.UUID | None = None,
    raw_name: str | None = None,
    quantity: str | None = None,
    note: str | None = None,
    source: str = ItemSource.MANUAL.value,
) -> ShoppingItem:
    """Put something on the list. Needs a product or a name; the caller supplies one."""
    raw_name = (raw_name or "").strip()[:300] or None
    if product_id is None and not raw_name:
        raise IngestError("An item needs a product or a name.")

    # Adding what is already on the list bumps it rather than repeating it - a list with
    # `Tej` on it three times is a worse list, not a more emphatic one.
    existing = await _open_duplicate(session, product_id, raw_name)
    if existing is not None:
        if quantity:
            existing.quantity = quantity[:60]
        if note:
            existing.note = note
        log.info("already on the list: %s", existing.label)
        return existing

    item = ShoppingItem(
        product_id=product_id,
        raw_name=raw_name,
        quantity=(quantity or "").strip()[:60] or None,
        note=(note or "").strip() or None,
        source=source,
        status=ScanStatus.READY.value,
    )
    session.add(item)
    await session.flush()
    return item


async def _open_duplicate(
    session: AsyncSession, product_id: uuid.UUID | None, raw_name: str | None
) -> ShoppingItem | None:
    """An item for the same thing that is still to be bought, if there is one."""
    stmt = select(ShoppingItem).where(ShoppingItem.done.is_(False))
    if product_id is not None:
        stmt = stmt.where(ShoppingItem.product_id == product_id)
    else:
        stmt = stmt.where(ShoppingItem.product_id.is_(None))
        stmt = stmt.where(ShoppingItem.raw_name == raw_name)
    return await session.scalar(stmt.limit(1))


async def add_photo(
    session: AsyncSession, data: bytes, settings: Settings, *, quantity: str | None = None
) -> ShoppingItem:
    """Put a photograph on the list straight away, and queue it to be recognised.

    The item exists and is useful before anything has looked at the picture. Recognition is
    an improvement on it, not a precondition for it - which is why the status starts at
    `pending` rather than the item waiting somewhere invisible until a model has run.
    """
    if not data:
        raise IngestError("The upload was empty.")

    fmt = _verify_image(data)
    item_id = uuid.uuid4()
    extension = EXTENSIONS.get(fmt, ".jpg")
    path = _storage_path(settings, item_id, extension)
    path.write_bytes(data)

    item = ShoppingItem(
        id=item_id,
        image_path=str(path),
        image_bytes=len(data),
        image_mime=f"image/{extension.lstrip('.')}",
        quantity=(quantity or "").strip()[:60] or None,
        source=ItemSource.SCAN.value,
        status=ScanStatus.PENDING.value,
    )
    session.add(item)
    await session.flush()

    log.info("queued shopping photo %s (%d KB, %s, sha %s)",
             item.id, len(data) // 1024, fmt, sha256_of(data)[:12])
    return item


async def apply_recognition(
    session: AsyncSession, item: ShoppingItem, result: ProductPhotoResult
) -> ShoppingItem:
    """Record what the photograph turned out to be, and match it only if that is safe."""
    photo = result.photo
    name = (photo.raw_name or "").strip() or (photo.category_hint or "").strip()

    item.raw_name = name[:300] or None
    item.confidence = photo.confidence
    item.note = item.note or photo.notes
    item.status = ScanStatus.READY.value
    item.error = None

    # Both conditions, and in this order: the model has to claim it read the packaging, and
    # the name it read has to resolve exactly. Either alone is not enough - a confident
    # misreading and a vague name that happens to normalise onto something both end up
    # attaching a list entry to the wrong price history.
    if photo.raw_name and photo.confidence >= READ_IT_CONFIDENCE:
        product = await resolve_product(session, photo.raw_name.strip(), None)
        if product is not None:
            item.product_id = product.id
            log.info("recognised %s as %s", item.id, product.canonical_name)
            return item

    log.info(
        "%s stays a photograph (name=%r confidence=%s)", item.id, photo.raw_name, photo.confidence
    )
    return item


async def set_done(session: AsyncSession, item: ShoppingItem, done: bool) -> ShoppingItem:
    item.done = done
    item.done_at = datetime.now(UTC) if done else None
    return item


async def clear_done(session: AsyncSession) -> int:
    """Remove the ticked-off items, and the photographs that went with them."""
    items = (
        await session.scalars(select(ShoppingItem).where(ShoppingItem.done.is_(True)))
    ).all()
    for item in items:
        if item.image_path:
            Path(item.image_path).unlink(missing_ok=True)
        await session.delete(item)
    return len(items)


async def suggestions(session: AsyncSession, limit: int = 12) -> list[Product]:
    """Products worth offering, most-bought first, that are not on the list already."""
    from sqlalchemy import func

    from app.models import ReceiptItem

    on_list = select(ShoppingItem.product_id).where(ShoppingItem.done.is_(False))
    counts = (
        select(ReceiptItem.product_id, func.count().label("n"))
        .where(ReceiptItem.product_id.is_not(None))
        .where(ReceiptItem.product_id.not_in(on_list))
        .group_by(ReceiptItem.product_id)
        .order_by(func.count().desc())
        .limit(limit)
        .subquery()
    )
    return list(
        (
            await session.scalars(
                select(Product).join(counts, counts.c.product_id == Product.id)
            )
        ).all()
    )
