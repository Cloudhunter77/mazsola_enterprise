"""Receipts captured as several photographs.

A receipt longer than a phone frame can hold legibly is photographed in overlapping
sections. The rule that makes this worth testing rather than obvious: the sections are one
receipt, not several - one row, one extraction call, one arithmetic check - and the
photographs are individually addressable afterwards so a reviewer can check a line against
the section it came from.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from PIL import Image
from sqlalchemy import select

from app.extraction.base import ExtractionError, as_parts
from app.extraction.prompt import MULTIPART_INSTRUCTION, USER_INSTRUCTION, instruction_for
from app.models import Receipt, ReceiptImage
from app.services.ingest import MAX_PARTS, IngestError, ingest_images, set_digest
from tests.conftest import requires_db


def photo(shade: int, size: tuple[int, int] = (900, 1600)) -> bytes:
    """A distinct JPEG per shade, so two parts are never accidentally the same bytes."""
    buffer = io.BytesIO()
    Image.new("RGB", size, (shade, shade, shade)).save(buffer, format="JPEG")
    return buffer.getvalue()


async def upload(client, photos: list[bytes]):
    return await client.post(
        "/api/receipts",
        files=[("file", (f"part{i}.jpg", data, "image/jpeg")) for i, data in enumerate(photos)],
    )


class TestTheContract:
    """`as_parts` exists because `bytes` is itself a Sequence, and iterating one gives ints."""

    def test_a_single_image_is_accepted_whole_not_iterated(self):
        data = photo(200)
        assert as_parts(data) == [data], "a lone image must not be split into its bytes"

    def test_a_list_passes_through_in_order(self):
        first, second = photo(200), photo(100)
        assert as_parts([first, second]) == [first, second]

    def test_nothing_to_read_is_an_extraction_error(self):
        with pytest.raises(ExtractionError):
            as_parts([])

    def test_a_list_of_something_other_than_images_is_refused(self):
        with pytest.raises(ExtractionError, match="whole image"):
            as_parts(["/path/to/photo.jpg"])


class TestThePrompt:
    def test_one_photo_gets_the_plain_instruction(self):
        assert instruction_for(1) == USER_INSTRUCTION

    def test_several_photos_get_the_overlap_warning(self):
        text = instruction_for(3)
        assert text != USER_INSTRUCTION
        assert "3" in text
        # The single most likely failure of a multi-part read is a line transcribed from
        # both the section it ends and the section it begins.
        assert "ONE line" in text
        assert MULTIPART_INSTRUCTION.format(count=3) == text


class TestIdentity:
    def test_one_part_hashes_to_its_own_image(self):
        """Receipts stored before multi-part capture keep working as duplicates."""
        assert set_digest(["abc123"]) == "abc123"

    def test_more_parts_hash_to_something_of_their_own(self):
        combined = set_digest(["aaa", "bbb"])
        assert combined not in ("aaa", "bbb")
        assert len(combined) == 64

    def test_order_is_part_of_the_identity(self):
        """Top-then-bottom is a different receipt from bottom-then-top, and reads differently."""
        assert set_digest(["aaa", "bbb"]) != set_digest(["bbb", "aaa"])


@requires_db
class TestIngest:
    async def test_the_parts_become_one_receipt_in_reading_order(self, session, app_settings):
        parts = [photo(250), photo(200), photo(150)]
        receipt, created = await ingest_images(session, parts, app_settings)
        await session.commit()

        assert created
        assert [image.part_no for image in receipt.images] == [0, 1, 2]
        assert len({image.path for image in receipt.images}) == 3, "each part its own file"
        for image in receipt.images:
            assert Path(image.path).is_file()

        # Part 0 is mirrored onto the receipt so everything written before multi-part
        # capture - the review screen, the image endpoint, deletion - still works.
        assert receipt.image_path == receipt.images[0].path
        assert receipt.image_bytes == sum(len(part) for part in parts)

    async def test_only_one_receipt_row_exists_for_the_whole_thing(self, session, app_settings):
        await ingest_images(session, [photo(250), photo(200)], app_settings)
        await session.commit()

        assert len((await session.scalars(select(Receipt))).all()) == 1

    async def test_re_uploading_the_same_set_is_a_duplicate(self, session, app_settings):
        parts = [photo(250), photo(200)]
        first, created_first = await ingest_images(session, parts, app_settings)
        await session.commit()
        second, created_second = await ingest_images(session, parts, app_settings)

        assert created_first and not created_second
        assert first.id == second.id

    async def test_a_photo_already_filed_under_another_receipt_is_a_duplicate(
        self, session, app_settings
    ):
        """Uploading a page alone and then again inside a longer receipt must not pay twice."""
        page = photo(250)
        alone, _ = await ingest_images(session, [page], app_settings)
        await session.commit()

        again, created = await ingest_images(session, [page, photo(200)], app_settings)
        assert not created
        assert again.id == alone.id

    async def test_the_same_photo_twice_in_one_upload_is_refused(self, session, app_settings):
        page = photo(250)
        with pytest.raises(IngestError, match="twice"):
            await ingest_images(session, [page, page], app_settings)

    async def test_too_many_parts_is_refused(self, session, app_settings):
        parts = [photo(100 + index) for index in range(MAX_PARTS + 1)]
        with pytest.raises(IngestError, match="at most"):
            await ingest_images(session, parts, app_settings)

    async def test_one_unreadable_part_rejects_the_whole_upload(self, session, app_settings):
        with pytest.raises(IngestError):
            await ingest_images(session, [photo(250), b"not an image"], app_settings)

    async def test_a_rejected_upload_leaves_no_files_behind(self, session, app_settings):
        with pytest.raises(IngestError):
            await ingest_images(session, [photo(250), b"not an image"], app_settings)
        written = [p for p in app_settings.image_dir.rglob("*") if p.is_file()]
        assert written == [], "a refused upload must not put half a receipt on disk"


@requires_db
class TestTheApi:
    async def test_uploading_several_photos_returns_one_receipt(self, auth_client):
        response = await upload(auth_client, [photo(250), photo(200), photo(150)])
        assert response.status_code == 202

        detail = (await auth_client.get(f"/api/receipts/{response.json()['id']}")).json()
        assert detail["pages"] == 3

    async def test_a_single_photo_is_still_one_page(self, auth_client, receipt_photo):
        response = await auth_client.post(
            "/api/receipts", files={"file": ("blokk.jpg", receipt_photo, "image/jpeg")}
        )
        assert response.status_code == 202
        detail = (await auth_client.get(f"/api/receipts/{response.json()['id']}")).json()
        assert detail["pages"] == 1

    async def test_each_part_is_served_separately(self, auth_client):
        parts = [photo(250), photo(200)]
        receipt_id = (await upload(auth_client, parts)).json()["id"]

        for index, original in enumerate(parts):
            served = await auth_client.get(f"/api/receipts/{receipt_id}/image?part={index}")
            assert served.status_code == 200
            assert served.content == original, f"part {index} served the wrong photo"

    async def test_the_default_part_is_the_top_of_the_receipt(self, auth_client):
        parts = [photo(250), photo(200)]
        receipt_id = (await upload(auth_client, parts)).json()["id"]

        assert (await auth_client.get(f"/api/receipts/{receipt_id}/image")).content == parts[0]

    async def test_asking_for_a_page_that_does_not_exist_is_a_404(self, auth_client):
        receipt_id = (await upload(auth_client, [photo(250)])).json()["id"]
        missing = await auth_client.get(f"/api/receipts/{receipt_id}/image?part=7")
        assert missing.status_code == 404

    async def test_deleting_removes_every_part_from_disk(self, auth_client, session):
        receipt_id = (await upload(auth_client, [photo(250), photo(200)])).json()["id"]
        paths = [
            Path(image.path)
            for image in (
                await session.scalars(
                    select(ReceiptImage).order_by(ReceiptImage.part_no)
                )
            ).all()
        ]
        assert len(paths) == 2 and all(path.is_file() for path in paths)

        assert (await auth_client.delete(f"/api/receipts/{receipt_id}")).status_code == 204
        assert not any(path.is_file() for path in paths), "a later page was left orphaned"


@requires_db
class TestTheWorker:
    """The point of the whole feature: several photographs, but one read of one receipt."""

    async def test_every_part_reaches_the_engine_in_one_call(
        self, session, sessionmaker_fixture, app_settings
    ):
        from tests.test_pipeline import StubExtractor, run_worker_once

        parts = [photo(250), photo(200), photo(150)]
        receipt, _ = await ingest_images(session, parts, app_settings)
        await session.commit()

        extractor = StubExtractor()
        await run_worker_once(sessionmaker_fixture, app_settings, extractor)

        assert extractor.calls == 1, "three photos must not become three extractions"
        assert extractor.parts_seen == [3]

        await session.refresh(receipt)
        assert receipt.status in {"parsed", "needs_review"}

    async def test_a_missing_later_part_fails_rather_than_reading_half_a_receipt(
        self, session, sessionmaker_fixture, app_settings
    ):
        from tests.test_pipeline import StubExtractor, run_worker_once

        receipt, _ = await ingest_images(session, [photo(250), photo(200)], app_settings)
        await session.commit()
        Path(receipt.images[1].path).unlink()

        extractor = StubExtractor()
        await run_worker_once(sessionmaker_fixture, app_settings, extractor)

        await session.refresh(receipt)
        assert extractor.calls == 0, "reading the top of a receipt as if it were all of it"
        assert receipt.status == "failed"
