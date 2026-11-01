"""Javítani való: notes about what to change in the app, with an optional screenshot."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import select

from app.api.deps import AuthDep, SessionDep, SettingsDep
from app.config import Settings
from app.models import FixNote, User
from app.schemas.api import FixNoteOut, FixNotePatch
from app.services.ingest import (
    EXTENSIONS,
    MAX_UPLOAD_BYTES,
    IngestError,
    _verify_image,
)

router = APIRouter(prefix="/api/fixes", tags=["fixes"])

MAX_TEXT = 5000


def _storage_path(settings: Settings, note_id: uuid.UUID, extension: str) -> Path:
    directory = settings.data_dir / "fixes" / f"{datetime.now(UTC):%Y}"
    directory.mkdir(parents=True, exist_ok=True)
    return directory / f"{note_id}{extension}"


async def _out(session, note: FixNote) -> FixNoteOut:
    author = await session.get(User, note.created_by_id) if note.created_by_id else None
    return FixNoteOut(
        id=note.id,
        text=note.text,
        has_image=bool(note.image_path),
        created_by=author.display_name if author else None,
        created_at=note.created_at,
        done=note.done,
        done_at=note.done_at,
    )


@router.get("", response_model=list[FixNoteOut])
async def list_notes(_: AuthDep, session: SessionDep) -> list[FixNoteOut]:
    """Open ones first, newest first within each - what still needs doing is on top."""
    notes = (
        await session.scalars(
            select(FixNote).order_by(FixNote.done, FixNote.created_at.desc())
        )
    ).all()
    return [await _out(session, note) for note in notes]


@router.post("", response_model=FixNoteOut, status_code=status.HTTP_201_CREATED)
async def create_note(
    principal: AuthDep,
    session: SessionDep,
    settings: SettingsDep,
    text: str = Form(""),
    image: UploadFile | None = File(None),
) -> FixNoteOut:
    text = text.strip()
    if len(text) > MAX_TEXT:
        raise HTTPException(status_code=422, detail=f"Legfeljebb {MAX_TEXT} karakter.")
    data = await image.read() if image is not None else b""
    if not text and not data:
        raise HTTPException(status_code=422, detail="Írj valamit, vagy csatolj egy képet.")

    note = FixNote(id=uuid.uuid4(), text=text, created_by_id=principal.user_id)
    if data:
        if len(data) > MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="A kép túl nagy.")
        try:
            fmt = _verify_image(data)
        except IngestError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        extension = EXTENSIONS.get(fmt, f".{fmt.lower()}")
        path = _storage_path(settings, note.id, extension)
        path.write_bytes(data)
        note.image_path = str(path)
        note.image_mime = f"image/{extension.lstrip('.').replace('jpg', 'jpeg')}"

    session.add(note)
    await session.commit()
    await session.refresh(note)
    return await _out(session, note)


@router.patch("/{note_id}", response_model=FixNoteOut)
async def update_note(
    _: AuthDep, session: SessionDep, note_id: uuid.UUID, body: FixNotePatch
) -> FixNoteOut:
    note = await session.get(FixNote, note_id)
    if note is None:
        raise HTTPException(status_code=404, detail="No such note.")
    if body.text is not None:
        note.text = body.text.strip()[:MAX_TEXT]
    if body.done is not None and body.done != note.done:
        note.done = body.done
        note.done_at = datetime.now(UTC) if body.done else None
    await session.commit()
    await session.refresh(note)
    return await _out(session, note)


@router.delete("/{note_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_note(_: AuthDep, session: SessionDep, note_id: uuid.UUID) -> None:
    note = await session.get(FixNote, note_id)
    if note is None:
        raise HTTPException(status_code=404, detail="No such note.")
    image = Path(note.image_path) if note.image_path else None
    await session.delete(note)
    await session.commit()
    # After the commit, so a failed delete never leaves a note pointing at a missing file.
    if image is not None:
        image.unlink(missing_ok=True)


@router.get("/{note_id}/image")
async def note_image(_: AuthDep, session: SessionDep, note_id: uuid.UUID) -> FileResponse:
    note = await session.get(FixNote, note_id)
    if note is None or not note.image_path:
        raise HTTPException(status_code=404, detail="No image for that note.")
    path = Path(note.image_path)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="The image file is missing.")
    return FileResponse(path, media_type=note.image_mime or "image/jpeg")
