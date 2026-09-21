"""Every item gets a picture, and the picture is of the item.

An inventory you can only read does not answer the question an inventory is for - which of
my two drills is this row about. So these cover the whole path: a box from the model, a
crop from the original photograph, a file on disk, and a way to attach more later.
"""

from __future__ import annotations

import io

import pytest
from PIL import Image
from sqlalchemy import select

from leltar.config import Settings
from leltar.extraction.crop import PADDING, crop_box, render
from leltar.models import ItemImage, PhotoMode
from leltar.schemas.identification import Box
from leltar.services.ingest import ingest_photo
from leltar.services.persist import persist_identification
from leltar.services.seed import seed_if_empty
from tests.conftest import build_photo, obj, requires_db


# --- the geometry, with no database in sight --------------------------------
def test_a_box_becomes_padded_pixels():
    region = crop_box(Box(x0=250, y0=500, x1=500, y1=1000), width=1000, height=500)
    left, top, right, bottom = region
    # 25%-50% across a 1000px frame is 250-500, plus 6% of the box's own width either side.
    assert left == int(250 - 250 * PADDING)
    assert right == int(500 + 250 * PADDING)
    # The box runs to the bottom edge, so the padding there is clipped rather than negative.
    assert top < 250
    assert bottom == 500


def test_padding_never_escapes_the_photograph():
    region = crop_box(Box(x0=0, y0=0, x1=1000, y1=1000), width=800, height=600)
    assert region == (0, 0, 800, 600)


def test_no_box_means_no_crop():
    assert crop_box(None, 100, 100) is None


def _photo_bytes(width: int, height: int) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (180, 170, 160)).save(buffer, format="JPEG")
    return buffer.getvalue()


def test_a_crop_is_taken_from_the_original_not_the_downscale():
    """The 1280px cap exists to keep the API bill down; cropping it would waste the rest."""
    original = _photo_bytes(4000, 3000)
    jpeg, width, height = render(original, Box(x0=0, y0=0, x1=500, y1=500))

    with Image.open(io.BytesIO(jpeg)) as image:
        assert (image.width, image.height) == (width, height)
    # Half of a 4000px frame is 2000px before the thumbnail cap; a crop of the 1280px copy
    # could not have produced anything like that much detail.
    assert max(width, height) == 900


def test_without_a_box_the_picture_is_the_whole_frame():
    jpeg, width, height = render(_photo_bytes(1200, 900), None)
    assert (width, height) == (900, 675)
    assert jpeg.startswith(b"\xff\xd8")  # a real JPEG


# --- the whole path ----------------------------------------------------------

@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(data_dir=tmp_path, auth_disabled=True, worker_enabled=False)


class Stub:
    name = "stub"

    def __init__(self, photo):
        self.photo = photo

    async def identify(self, image, *, place_path=None, single=False, mime_type="image/jpeg"):
        from leltar.extraction.base import IdentificationResult

        return IdentificationResult(photo=self.photo, engine=self.name, model="stub-1")


@requires_db
async def test_every_identified_item_gets_its_own_picture(session, settings, item_photo):
    await seed_if_empty(session)
    photo, _ = await ingest_photo(session, item_photo, settings)
    result = await Stub(build_photo()).identify(item_photo)

    items = await persist_identification(session, photo, result, settings)
    await session.commit()

    images = (await session.scalars(select(ItemImage))).all()
    assert len(images) == len(items) == 3
    assert {image.kind for image in images} == {"crop"}
    assert all(image.is_primary for image in images)

    from pathlib import Path

    for image in images:
        assert Path(image.path).is_file()
        assert image.box is not None
        # And each crop is a different region, so the three items do not share one picture.
    assert len({tuple(sorted(image.box.items())) for image in images}) == 3


@requires_db
async def test_an_object_without_a_box_still_gets_a_picture(session, settings, item_photo):
    await seed_if_empty(session)
    photo, _ = await ingest_photo(session, item_photo, settings)
    result = await Stub(build_photo(objects=[obj("kézi mixer", box=None)])).identify(item_photo)

    await persist_identification(session, photo, result, settings)
    await session.commit()

    image = await session.scalar(select(ItemImage))
    assert image.kind == "photo"
    assert image.box is None


@requires_db
async def test_a_missing_photograph_costs_the_pictures_not_the_names(
    session, settings, item_photo
):
    """The names are the valuable part and are already stored when cropping runs."""
    from pathlib import Path

    await seed_if_empty(session)
    photo, _ = await ingest_photo(session, item_photo, settings)
    Path(photo.path).unlink()

    items = await persist_identification(
        session, photo, await Stub(build_photo()).identify(item_photo), settings
    )
    await session.commit()

    assert len(items) == 3
    assert (await session.scalars(select(ItemImage))).all() == []


@requires_db
async def test_a_single_object_photo_yields_one_item(session, settings, item_photo):
    """A photograph taken of one thing should not also inventory the table it sits on."""
    await seed_if_empty(session)
    photo, _ = await ingest_photo(
        session, item_photo, settings, mode=PhotoMode.SINGLE.value
    )
    result = await Stub(
        build_photo(objects=[
            obj("Makita akkus fúró", category="szerszam", confidence=0.95),
            obj("étkezőasztal", category="butor", confidence=0.4),
        ])
    ).identify(item_photo)

    items = await persist_identification(session, photo, result, settings)
    await session.commit()

    assert [item.name for item in items] == ["Makita akkus fúró"]
    assert "extra_objects_ignored" in photo.review_reasons


@requires_db
async def test_reprocessing_replaces_a_drafts_picture_too(session, settings, item_photo):
    await seed_if_empty(session)
    photo, _ = await ingest_photo(session, item_photo, settings)
    await persist_identification(
        session, photo, await Stub(build_photo()).identify(item_photo), settings
    )
    await session.commit()

    await persist_identification(
        session,
        photo,
        await Stub(build_photo(objects=[obj("fa vágódeszka", box=(10, 10, 500, 500))])).identify(
            item_photo
        ),
        settings,
    )
    await session.commit()

    images = (await session.scalars(select(ItemImage))).all()
    assert len(images) == 1


@requires_db
async def test_a_single_object_photo_keeps_no_scene(session, settings, item_photo):
    """Asked to describe a photograph of one chair, a model writes the chair - or "egyeb",
    or "as above". The review queue was using that line as the row's title, so a queue of
    single-object photographs said nothing about which was which."""
    await seed_if_empty(session)
    photo, _ = await ingest_photo(
        session, item_photo, settings, mode=PhotoMode.SINGLE.value
    )
    result = await Stub(
        build_photo(scene="as above", objects=[obj("fekete munkaszék", category="butor")])
    ).identify(item_photo)

    await persist_identification(session, photo, result, settings)
    await session.commit()

    assert photo.scene is None


@requires_db
async def test_a_scene_photo_keeps_its_description(session, settings, item_photo):
    """Where several things share a frame, the description is the one thing the names
    cannot say."""
    await seed_if_empty(session)
    photo, _ = await ingest_photo(session, item_photo, settings)
    result = await Stub(build_photo(scene="konyhai polc edényekkel")).identify(item_photo)

    await persist_identification(session, photo, result, settings)
    await session.commit()

    assert photo.scene == "konyhai polc edényekkel"
