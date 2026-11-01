"""Javítani való: notes about what to change in the app, with an optional screenshot."""

from __future__ import annotations

import io
from pathlib import Path

from PIL import Image
from sqlalchemy import select

from app.models import FixNote
from tests.conftest import requires_db

pytestmark = requires_db


def png() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (390, 844), (30, 30, 30)).save(buffer, format="PNG")
    return buffer.getvalue()


async def add(client, text: str = "", image: bytes | None = None):
    files = {"image": ("kepernyo.png", image, "image/png")} if image is not None else None
    return await client.post("/api/fixes", data={"text": text}, files=files)


class TestWritingANote:
    async def test_text_alone_is_enough(self, auth_client):
        response = await add(auth_client, "A Lista fülön a pipa túl kicsi")
        assert response.status_code == 201
        body = response.json()
        assert body["text"] == "A Lista fülön a pipa túl kicsi"
        assert body["has_image"] is False and body["done"] is False
        assert body["created_by"] == "admin"

    async def test_a_screenshot_alone_is_enough(self, auth_client):
        response = await add(auth_client, image=png())
        assert response.status_code == 201
        note = response.json()
        assert note["has_image"] is True
        image = await auth_client.get(f"/api/fixes/{note['id']}/image")
        assert image.status_code == 200 and image.headers["content-type"] == "image/png"
        assert image.content == png()

    async def test_nothing_at_all_is_refused(self, auth_client):
        assert (await add(auth_client, "   ")).status_code == 422

    async def test_a_file_that_is_not_an_image_is_refused(self, auth_client):
        response = await add(auth_client, "nézd", image=b"#!/bin/sh\nrm -rf /\n")
        assert response.status_code == 400

    async def test_it_needs_a_login(self, client):
        assert (await client.get("/api/fixes")).status_code == 401
        assert (await add(client, "x")).status_code == 401


class TestTrackingThem:
    async def test_open_notes_come_first(self, auth_client):
        first = (await add(auth_client, "első")).json()
        await add(auth_client, "második")
        await auth_client.patch(f"/api/fixes/{first['id']}", json={"done": True})

        notes = (await auth_client.get("/api/fixes")).json()
        assert [n["text"] for n in notes] == ["második", "első"]
        assert notes[1]["done"] is True and notes[1]["done_at"] is not None

    async def test_reopening_clears_the_done_date(self, auth_client):
        note = (await add(auth_client, "x")).json()
        await auth_client.patch(f"/api/fixes/{note['id']}", json={"done": True})
        reopened = (
            await auth_client.patch(f"/api/fixes/{note['id']}", json={"done": False})
        ).json()
        assert reopened["done"] is False and reopened["done_at"] is None

    async def test_deleting_a_note_removes_its_image(self, auth_client, session):
        note = (await add(auth_client, "x", image=png())).json()
        path = Path(await session.scalar(select(FixNote.image_path)))
        assert path.is_file()

        assert (await auth_client.delete(f"/api/fixes/{note['id']}")).status_code == 204
        assert not path.exists()
        assert (await auth_client.get("/api/fixes")).json() == []
