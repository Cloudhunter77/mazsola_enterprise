"""The inventory itself: approving guesses, editing them, and typing in what was missed."""

from __future__ import annotations

import csv
import io
import uuid
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse, PlainTextResponse
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from leltar.api.deps import AuthDep, OptionalUUID, SessionDep, SettingsDep
from leltar.extraction import crop
from leltar.extraction.preprocess import sha256_of
from leltar.extraction.rules import midpoint, names_match
from leltar.models import Category, Item, ItemImage, ItemStatus, Photo, PhotoStatus
from leltar.schemas.api import ItemImageOut, ItemIn, ItemOut, ItemPatch
from leltar.services.ingest import IngestError, verify_image
from leltar.services.places import paths_for_all

router = APIRouter(prefix="/api/items", tags=["items"])


async def decorate_items(session: AsyncSession, items: list[Item]) -> list[ItemOut]:
    """Attach the place path, category name and picture count every list view needs."""
    if not items:
        return []

    paths = await paths_for_all(session)
    category_names = dict(
        (await session.execute(select(Category.id, Category.name))).all()
    )
    # One query for the whole page rather than one per row: a list of 300 items would
    # otherwise be 300 round trips to find out whether to draw a thumbnail.
    counts = dict(
        (
            await session.execute(
                select(ItemImage.item_id, func.count(ItemImage.id))
                .where(ItemImage.item_id.in_([item.id for item in items]))
                .group_by(ItemImage.item_id)
            )
        ).all()
    )

    out: list[ItemOut] = []
    for item in items:
        row = ItemOut.model_validate(item)
        row.place_path = paths.get(item.place_id) if item.place_id else None
        row.category_name = category_names.get(item.category_id) if item.category_id else None
        row.image_count = int(counts.get(item.id, 0))
        out.append(row)
    return out


def _recompute_value(item: Item) -> None:
    """Keep the midpoint consistent with an edited range.

    Only when the range moved: an explicit `estimated_value` in the same request is a
    deliberate override and must survive, which is the difference between "I corrected the
    range" and "I know what this is worth".
    """
    item.estimated_value = midpoint(
        int(item.value_low) if item.value_low is not None else None,
        int(item.value_high) if item.value_high is not None else None,
    )


@router.get("", response_model=list[ItemOut])
async def list_items(
    _: AuthDep,
    session: SessionDep,
    status_filter: str | None = Query(None, alias="status"),
    place_id: OptionalUUID = None,
    category_id: OptionalUUID = None,
    q: str | None = Query(None, description="Substring of the name, brand or description."),
    limit: int = Query(100, le=500),
    offset: int = 0,
) -> list[ItemOut]:
    stmt = select(Item).order_by(Item.created_at.desc()).limit(limit).offset(offset)
    if status_filter:
        stmt = stmt.where(Item.status == status_filter)
    if place_id:
        stmt = stmt.where(Item.place_id == place_id)
    if category_id:
        stmt = stmt.where(Item.category_id == category_id)
    if q:
        pattern = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(
                Item.name.ilike(pattern),
                Item.brand.ilike(pattern),
                Item.description.ilike(pattern),
                Item.serial_number.ilike(pattern),
            )
        )
    items = list((await session.scalars(stmt)).all())
    return await decorate_items(session, items)


@router.post("", response_model=ItemOut, status_code=status.HTTP_201_CREATED)
async def create_item(_: AuthDep, session: SessionDep, body: ItemIn) -> ItemOut:
    """Type in something you did not photograph.

    It is stored `confirmed` rather than as a draft: you named it, so there is no guess for
    the review queue to second-guess.
    """
    item = Item(
        **body.model_dump(exclude={"value_low", "value_high"}),
        value_low=body.value_low,
        value_high=body.value_high,
        status=ItemStatus.CONFIRMED.value,
        source="manual",
        confirmed_at=datetime.now(UTC),
    )
    _recompute_value(item)
    session.add(item)
    await session.commit()
    return (await decorate_items(session, [item]))[0]


@router.get("/export.csv", response_class=PlainTextResponse)
async def export_csv(_: AuthDep, session: SessionDep) -> PlainTextResponse:
    """The confirmed inventory as a spreadsheet - the form an insurer or a mover wants.

    Drafts are left out: this file is meant to be evidence of what you own, and a guess
    nobody has looked at is not that.
    """
    items = list(
        (
            await session.scalars(
                select(Item)
                .where(Item.status == ItemStatus.CONFIRMED.value)
                .order_by(Item.name)
            )
        ).all()
    )
    rows = await decorate_items(session, items)

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow([
        "nev", "darab", "hely", "kategoria", "marka", "tipus", "allapot",
        "ertek_min", "ertek_max", "becsult_ertek", "penznem", "sorozatszam",
        "beszerzes", "megjegyzes",
    ])
    for row in rows:
        writer.writerow([
            row.name, row.quantity, row.place_path or "", row.category_name or "",
            row.brand or "", row.product_model or "", row.condition,
            row.value_low or "", row.value_high or "", row.estimated_value or "",
            row.currency, row.serial_number or "",
            row.acquired_on.isoformat() if row.acquired_on else "",
            (row.notes or "").replace("\n", " "),
        ])

    return PlainTextResponse(
        # A BOM so Excel opens it as UTF-8 rather than mangling every Hungarian accent,
        # which is the one thing guaranteed to make a CSV export look broken.
        "﻿" + buffer.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="leltar.csv"'},
    )


# --- pictures ----------------------------------------------------------------
# These sit above `/{item_id}` on purpose: FastAPI matches in declaration order, and
# `/images/{image_id}` under a bare `/{item_id}` route would be read as an item called
# "images".
@router.post(
    "/images/{image_id}/primary", response_model=ItemImageOut, tags=["item-images"]
)
async def set_primary_image(
    _: AuthDep, session: SessionDep, image_id: uuid.UUID
) -> ItemImageOut:
    """Choose which picture represents the item in a list."""
    image = await session.get(ItemImage, image_id)
    if image is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Nincs ilyen kép.")

    await _clear_primary(session, image.item_id)
    image.is_primary = True
    await session.commit()
    return ItemImageOut.model_validate(image)


@router.delete(
    "/images/{image_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["item-images"]
)
async def delete_image(_: AuthDep, session: SessionDep, image_id: uuid.UUID) -> None:
    image = await session.get(ItemImage, image_id)
    if image is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Nincs ilyen kép.")

    item_id, was_primary, path = image.item_id, image.is_primary, Path(image.path)
    await session.delete(image)
    await session.flush()

    # Something has to represent the item, or its row loses its picture while pictures
    # remain. The oldest survivor is the least surprising choice.
    if was_primary:
        successor = await session.scalar(
            select(ItemImage)
            .where(ItemImage.item_id == item_id)
            .order_by(ItemImage.created_at)
            .limit(1)
        )
        if successor is not None:
            successor.is_primary = True

    await session.commit()
    path.unlink(missing_ok=True)


@router.get("/{item_id}/images", response_model=list[ItemImageOut], tags=["item-images"])
async def list_images(
    _: AuthDep, session: SessionDep, item_id: uuid.UUID
) -> list[ItemImageOut]:
    rows = (
        await session.scalars(
            select(ItemImage)
            .where(ItemImage.item_id == item_id)
            .order_by(ItemImage.is_primary.desc(), ItemImage.created_at)
        )
    ).all()
    return [ItemImageOut.model_validate(row) for row in rows]


@router.get("/{item_id}/image", tags=["item-images"])
async def get_image(_: AuthDep, session: SessionDep, item_id: uuid.UUID) -> FileResponse:
    """The item's picture: the chosen one, or the oldest if none was chosen."""
    image = await session.scalar(
        select(ItemImage)
        .where(ItemImage.item_id == item_id)
        .order_by(ItemImage.is_primary.desc(), ItemImage.created_at)
        .limit(1)
    )
    if image is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Ehhez a tárgyhoz nincs kép."
        )
    path = Path(image.path)
    if not path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="A kép fájlja hiányzik.")
    return FileResponse(path, media_type=image.mime)


@router.post(
    "/{item_id}/images",
    response_model=ItemImageOut,
    status_code=status.HTTP_201_CREATED,
    tags=["item-images"],
)
async def add_image(
    _: AuthDep,
    session: SessionDep,
    settings: SettingsDep,
    item_id: uuid.UUID,
    file: UploadFile = File(..., description="A photograph of this item."),
    primary: bool = Query(True, description="Make it the picture shown in lists."),
) -> ItemImageOut:
    """Attach a photograph to an item you already have.

    This is the second pass an inventory actually needs: the serial plate, the damage, the
    thing out of its case. It goes straight on the item and is never sent to the model -
    nothing here is being identified, only recorded.
    """
    item = await session.get(Item, item_id)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Nincs ilyen tárgy.")

    data = await file.read()
    try:
        verify_image(data)
    except IngestError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    # Stored at the same size as a crop, and as a JPEG whatever arrived: these are
    # pictures for recognising a thing on a phone screen, not archival originals.
    try:
        jpeg, width, height = crop.render(data, None)
    except OSError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="A képet nem sikerült feldolgozni."
        ) from exc

    taken = f"{datetime.now(UTC):%Y/%m}"
    path = crop.storage_path(settings.crop_dir, uuid.uuid4(), taken)
    path.write_bytes(jpeg)

    if primary:
        await _clear_primary(session, item_id)

    image = ItemImage(
        item_id=item_id,
        kind="upload",
        path=str(path),
        sha256=sha256_of(jpeg),
        bytes=len(jpeg),
        mime="image/jpeg",
        width=width,
        height=height,
        is_primary=primary,
    )
    session.add(image)
    await session.commit()
    return ItemImageOut.model_validate(image)


async def _clear_primary(session: AsyncSession, item_id: uuid.UUID) -> None:
    """Demote the current primary, and flush before a new one is set.

    The flush is not optional: a partial unique index forbids two primaries per item, and
    without it both the UPDATE and the INSERT reach the database in the same statement
    batch and the constraint fires.
    """
    current = await session.scalars(
        select(ItemImage).where(ItemImage.item_id == item_id, ItemImage.is_primary.is_(True))
    )
    for image in current:
        image.is_primary = False
    await session.flush()


@router.get("/{item_id}", response_model=ItemOut)
async def get_item(_: AuthDep, session: SessionDep, item_id: uuid.UUID) -> ItemOut:
    item = await session.get(Item, item_id)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Nincs ilyen tárgy.")
    return (await decorate_items(session, [item]))[0]


@router.patch("/{item_id}", response_model=ItemOut)
async def patch_item(
    _: AuthDep, session: SessionDep, item_id: uuid.UUID, body: ItemPatch
) -> ItemOut:
    item = await session.get(Item, item_id)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Nincs ilyen tárgy.")

    changes = body.model_dump(exclude_unset=True)
    if "status" in changes and changes["status"] not in set(ItemStatus):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Ismeretlen állapot: {changes['status']}.",
        )

    for field, value in changes.items():
        setattr(item, field, value)

    if "name" in changes:
        # The accuracy figure depends on this one line: a name you retyped identically is
        # not an edit, and only a real change counts against the suggestion.
        item.edited = item.suggested_name is not None and not names_match(
            item.name, item.suggested_name
        )
    if ("value_low" in changes or "value_high" in changes) and "estimated_value" not in changes:
        _recompute_value(item)
    if changes.get("status") == ItemStatus.CONFIRMED.value and item.confirmed_at is None:
        item.confirmed_at = datetime.now(UTC)

    await session.commit()
    return (await decorate_items(session, [item]))[0]


async def _confirm(session: AsyncSession, item: Item) -> None:
    item.status = ItemStatus.CONFIRMED.value
    item.confirmed_at = datetime.now(UTC)


@router.post("/{item_id}/confirm", response_model=ItemOut)
async def confirm_item(_: AuthDep, session: SessionDep, item_id: uuid.UUID) -> ItemOut:
    item = await session.get(Item, item_id)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Nincs ilyen tárgy.")
    await _confirm(session, item)
    await session.commit()
    return (await decorate_items(session, [item]))[0]


@router.post("/{item_id}/reject", response_model=ItemOut)
async def reject_item(_: AuthDep, session: SessionDep, item_id: uuid.UUID) -> ItemOut:
    """Not a thing worth listing. Kept rather than deleted, so it stays out of the queue."""
    item = await session.get(Item, item_id)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Nincs ilyen tárgy.")
    item.status = ItemStatus.REJECTED.value
    await session.commit()
    return (await decorate_items(session, [item]))[0]


@router.post("/confirm-photo/{photo_id}", response_model=list[ItemOut])
async def confirm_photo_items(
    _: AuthDep, session: SessionDep, photo_id: uuid.UUID
) -> list[ItemOut]:
    """Approve every remaining draft from one photograph, and close its review.

    This is the fast path the whole app is for: a shelf photographed once, eight names
    read, one button. Editing an individual entry first is still possible - a confirmed
    item is not touched here.
    """
    photo = await session.get(Photo, photo_id)
    if photo is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Nincs ilyen fénykép.")

    drafts = list(
        (
            await session.scalars(
                select(Item).where(
                    Item.photo_id == photo_id, Item.status == ItemStatus.DRAFT.value
                )
            )
        ).all()
    )
    for item in drafts:
        await _confirm(session, item)

    photo.status = PhotoStatus.REVIEWED.value
    photo.reviewed_at = datetime.now(UTC)
    await session.commit()
    return await decorate_items(session, drafts)


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_item(_: AuthDep, session: SessionDep, item_id: uuid.UUID) -> None:
    item = await session.get(Item, item_id)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Nincs ilyen tárgy.")
    await session.delete(item)
    await session.commit()
