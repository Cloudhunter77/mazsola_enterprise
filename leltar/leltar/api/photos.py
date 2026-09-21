"""Uploading photographs, and what the model made of them."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import aggregate_order_by
from sqlalchemy.orm import selectinload

from leltar.api.deps import AuthDep, OptionalUUID, SessionDep, SettingsDep
from leltar.api.items import decorate_items
from leltar.models import Item, ItemStatus, Photo, PhotoMode, PhotoStatus
from leltar.schemas.api import PhotoDetail, PhotoSummary, UploadedPhoto, UploadResponse
from leltar.services.ingest import MAX_PHOTOS_PER_UPLOAD, IngestError, ingest_photo
from leltar.services.places import paths_for_all

router = APIRouter(prefix="/api/photos", tags=["photos"])


@router.post("", response_model=UploadResponse, status_code=status.HTTP_202_ACCEPTED)
async def upload_photos(
    _: AuthDep,
    session: SessionDep,
    settings: SettingsDep,
    file: list[UploadFile] = File(..., description="One or more photographs of your things."),
    place_id: OptionalUUID = None,
    mode: str = Query(
        PhotoMode.SCENE.value,
        description="scene (catalogue everything in the frame) | single (one object).",
    ),
    source: str = Query("web", description="web | shortcut"),
) -> UploadResponse:
    """Accept photographs and queue them. Returns immediately; the worker names things later.

    `place_id` is where they were taken; an empty value means it was not given. `mode` says
    whether each frame is a scene to catalogue or one object photographed on purpose.
    Each file is its own photograph with its own set of objects - repeating the field
    uploads a whole shelf in one go, not one object from several angles.
    """
    if len(file) > MAX_PHOTOS_PER_UPLOAD:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Egyszerre legfeljebb {MAX_PHOTOS_PER_UPLOAD} fénykép tölthető fel; "
                f"most {len(file)} érkezett."
            ),
        )

    results: list[UploadedPhoto] = []
    for upload in file:
        data = await upload.read()
        try:
            photo, created = await ingest_photo(
                session, data, settings, place_id=place_id, mode=mode, source=source
            )
        except IngestError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
            ) from exc
        results.append(
            UploadedPhoto(id=photo.id, status=photo.status, duplicate=not created)
        )

    await session.commit()
    queued = sum(1 for row in results if not row.duplicate)
    return UploadResponse(
        photos=results, queued=queued, duplicates=len(results) - queued
    )


@router.get("", response_model=list[PhotoSummary])
async def list_photos(
    _: AuthDep,
    session: SessionDep,
    status_filter: str | None = Query(None, alias="status"),
    place_id: OptionalUUID = None,
    limit: int = Query(50, le=200),
    offset: int = 0,
) -> list[PhotoSummary]:
    drafts = (
        select(
            Item.photo_id,
            func.count().label("total"),
            func.count().filter(Item.status == ItemStatus.DRAFT.value).label("drafts"),
            func.array_agg(aggregate_order_by(Item.name, Item.created_at)).label("names"),
        )
        .group_by(Item.photo_id)
        .subquery()
    )
    stmt = (
        select(
            Photo,
            func.coalesce(drafts.c.total, 0),
            func.coalesce(drafts.c.drafts, 0),
            drafts.c.names,
        )
        .outerjoin(drafts, drafts.c.photo_id == Photo.id)
        .order_by(Photo.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    if status_filter:
        stmt = stmt.where(Photo.status == status_filter)
    if place_id:
        stmt = stmt.where(Photo.place_id == place_id)

    rows = (await session.execute(stmt)).all()
    paths = await paths_for_all(session)

    summaries = []
    for photo, total, draft_count, names in rows:
        summary = PhotoSummary.model_validate(photo)
        summary.item_count = int(total)
        summary.draft_count = int(draft_count)
        summary.place_path = paths.get(photo.place_id) if photo.place_id else None
        # Enough to recognise the photograph in a list; the rest is a count beside them.
        summary.item_names = [name for name in (names or []) if name][:4]
        summaries.append(summary)
    return summaries


@router.get("/{photo_id}", response_model=PhotoDetail)
async def get_photo(_: AuthDep, session: SessionDep, photo_id: uuid.UUID) -> PhotoDetail:
    photo = await session.scalar(
        select(Photo).options(selectinload(Photo.items)).where(Photo.id == photo_id)
    )
    if photo is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Nincs ilyen fénykép.")

    detail = PhotoDetail.model_validate(photo)
    paths = await paths_for_all(session)
    detail.place_path = paths.get(photo.place_id) if photo.place_id else None
    detail.items = await decorate_items(session, list(photo.items))
    detail.item_count = len(detail.items)
    detail.item_names = [item.name for item in detail.items][:4]
    detail.draft_count = sum(
        1 for item in detail.items if item.status == ItemStatus.DRAFT.value
    )
    return detail


@router.get("/{photo_id}/image")
async def get_image(_: AuthDep, session: SessionDep, photo_id: uuid.UUID) -> FileResponse:
    photo = await session.get(Photo, photo_id)
    if photo is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Nincs ilyen fénykép.")
    path = Path(photo.path)
    if not path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="A fénykép fájlja hiányzik."
        )
    return FileResponse(path, media_type=photo.mime)


@router.post("/{photo_id}/reprocess", response_model=PhotoDetail)
async def reprocess(_: AuthDep, session: SessionDep, photo_id: uuid.UUID) -> PhotoDetail:
    """Ask the model again - after changing the model, or when the guesses were poor.

    The attempt counter is reset, because this is a decision you made rather than a retry
    of a failure, and a photo that already used up its attempts must still be re-readable.
    """
    photo = await session.get(Photo, photo_id)
    if photo is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Nincs ilyen fénykép.")
    photo.status = PhotoStatus.PENDING.value
    photo.attempts = 0
    photo.error = None
    await session.commit()
    return await get_photo(_, session, photo_id)


@router.post("/{photo_id}/reviewed", response_model=PhotoDetail)
async def mark_reviewed(_: AuthDep, session: SessionDep, photo_id: uuid.UUID) -> PhotoDetail:
    """You have been through this photo's suggestions; stop showing it in the queue."""
    photo = await session.get(Photo, photo_id)
    if photo is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Nincs ilyen fénykép.")
    photo.status = PhotoStatus.REVIEWED.value
    photo.reviewed_at = datetime.now(UTC)
    await session.commit()
    return await get_photo(_, session, photo_id)


@router.delete("/{photo_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_photo(_: AuthDep, session: SessionDep, photo_id: uuid.UUID) -> None:
    """Delete a photograph and its unapproved guesses.

    Items you already confirmed are kept and simply lose their photo: they are entries in
    an inventory now, and deleting a blurry picture is not a statement about whether you
    own the thing in it.
    """
    photo = await session.get(Photo, photo_id)
    if photo is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Nincs ilyen fénykép.")

    await session.execute(
        update(Item)
        .where(Item.photo_id == photo_id, Item.status != ItemStatus.DRAFT.value)
        .values(photo_id=None)
    )
    path = Path(photo.path)
    await session.delete(photo)
    await session.commit()

    # The file goes last: a failed delete leaves an orphaned file, which is recoverable,
    # while the other order leaves a row pointing at nothing, which is not.
    path.unlink(missing_ok=True)
