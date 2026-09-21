"""Ingest, the worker, and what ends up in the database - with the model stubbed out."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from leltar.config import Settings
from leltar.extraction.base import IdentificationError, IdentificationResult
from leltar.models import IdentificationAttempt, Item, ItemStatus, Photo, PhotoStatus
from leltar.services.ingest import IngestError, ingest_photo
from leltar.services.persist import persist_identification
from leltar.services.seed import seed_if_empty
from tests.conftest import build_photo, obj, requires_db

pytestmark = requires_db


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(data_dir=tmp_path, auth_disabled=True, worker_enabled=False)


class StubIdentifier:
    """Stands in for Claude. Returns whatever it was constructed with, or raises."""

    name = "stub"

    def __init__(self, photo=None, error: str | None = None):
        self.photo = photo or build_photo()
        self.error = error
        self.calls = 0
        self.place_paths: list[str | None] = []
        self.singles: list[bool] = []

    async def identify(self, image, *, place_path=None, single=False, mime_type="image/jpeg"):
        self.calls += 1
        self.place_paths.append(place_path)
        self.singles.append(single)
        if self.error:
            raise IdentificationError(self.error)
        return IdentificationResult(
            photo=self.photo,
            engine=self.name,
            model="stub-1",
            input_tokens=1500,
            output_tokens=400,
            cost_usd=None,
            latency_ms=42,
        )


# --- ingest ------------------------------------------------------------------
async def test_an_upload_is_stored_and_queued(session, settings, item_photo):
    photo, created = await ingest_photo(session, item_photo, settings)
    await session.commit()

    assert created is True
    assert photo.status == PhotoStatus.PENDING.value
    assert (settings.image_dir).exists()
    from pathlib import Path

    assert Path(photo.path).is_file()


async def test_the_same_photo_twice_is_one_photo(session, settings, item_photo):
    """A phone shortcut retries; paying to read the same picture twice is the failure."""
    first, created_first = await ingest_photo(session, item_photo, settings)
    await session.commit()
    second, created_second = await ingest_photo(session, item_photo, settings)
    await session.commit()

    assert created_first is True
    assert created_second is False
    assert first.id == second.id
    assert await session.scalar(select(Photo.id).where(Photo.id != first.id)) is None


async def test_a_file_that_is_not_an_image_is_refused(session, settings):
    with pytest.raises(IngestError):
        await ingest_photo(session, b"this is not a JPEG", settings)


async def test_an_empty_upload_is_refused(session, settings):
    with pytest.raises(IngestError):
        await ingest_photo(session, b"", settings)


# --- persistence -------------------------------------------------------------
async def test_identification_becomes_draft_items(session, settings, item_photo):
    await seed_if_empty(session)
    photo, _ = await ingest_photo(session, item_photo, settings)
    result = await StubIdentifier().identify(item_photo)

    items = await persist_identification(session, photo, result, settings)
    await session.commit()

    assert len(items) == 3
    assert {item.status for item in items} == {ItemStatus.DRAFT.value}
    assert photo.status == PhotoStatus.IDENTIFIED.value
    # Every item keeps the name it was given, so an edit is measurable later.
    assert all(item.suggested_name == item.name for item in items)
    # The category slug was resolved against the seeded tree rather than stored as text.
    assert all(item.category_id is not None for item in items)


async def test_items_inherit_the_place_the_photo_was_taken_in(session, settings, item_photo):
    await seed_if_empty(session)
    from leltar.models import Place

    place = await session.scalar(select(Place).limit(1))
    photo, _ = await ingest_photo(session, item_photo, settings, place_id=place.id)
    result = await StubIdentifier().identify(item_photo)

    items = await persist_identification(session, photo, result, settings)
    assert {item.place_id for item in items} == {place.id}


async def test_a_flagged_object_sends_the_photo_to_review(session, settings, item_photo):
    await seed_if_empty(session)
    photo, _ = await ingest_photo(session, item_photo, settings)
    result = await StubIdentifier(
        photo=build_photo(objects=[obj("laptop", brand="Dell", markings_legible=False)])
    ).identify(item_photo)

    items = await persist_identification(session, photo, result, settings)
    await session.commit()

    assert photo.status == PhotoStatus.NEEDS_REVIEW.value
    assert items[0].brand is None
    assert "unverifiable_brand" in items[0].review_reasons


async def test_reprocessing_replaces_drafts_but_keeps_what_you_confirmed(
    session, settings, item_photo
):
    await seed_if_empty(session)
    photo, _ = await ingest_photo(session, item_photo, settings)
    first = await persist_identification(
        session, photo, await StubIdentifier().identify(item_photo), settings
    )
    keeper = first[0]
    keeper.status = ItemStatus.CONFIRMED.value
    keeper.name = "az én bögrém"
    await session.commit()

    await persist_identification(
        session,
        photo,
        await StubIdentifier(photo=build_photo(objects=[obj("fa vágódeszka")])).identify(
            item_photo
        ),
        settings,
    )
    await session.commit()

    names = set(
        (await session.scalars(select(Item.name).where(Item.photo_id == photo.id))).all()
    )
    assert names == {"az én bögrém", "fa vágódeszka"}


async def test_the_item_limit_is_enforced_from_settings(session, settings, item_photo):
    await seed_if_empty(session)
    narrow = settings.model_copy(update={"max_items_per_photo": 2})
    photo, _ = await ingest_photo(session, item_photo, settings)

    items = await persist_identification(
        session, photo, await StubIdentifier().identify(item_photo), narrow
    )
    assert len(items) == 2
    assert "too_many_objects" in photo.review_reasons


# --- the worker --------------------------------------------------------------
async def test_the_worker_identifies_a_queued_photo(
    sessionmaker_fixture, settings, item_photo, monkeypatch
):
    from leltar import worker as worker_module
    from leltar.worker import IdentificationWorker

    monkeypatch.setattr(worker_module, "SessionLocal", sessionmaker_fixture)

    async with sessionmaker_fixture() as session:
        await seed_if_empty(session)
        photo, _ = await ingest_photo(session, item_photo, settings)
        await session.commit()
        photo_id = photo.id

    worker = IdentificationWorker(settings)
    stub = StubIdentifier()
    worker._identifier = stub

    assert await worker.process_next() is True
    assert await worker.process_next() is False  # queue is empty now
    assert stub.calls == 1

    async with sessionmaker_fixture() as session:
        stored = await session.get(Photo, photo_id)
        assert stored.status == PhotoStatus.IDENTIFIED.value
        items = (await session.scalars(select(Item).where(Item.photo_id == photo_id))).all()
        assert len(items) == 3
        attempt = await session.scalar(select(IdentificationAttempt))
        assert attempt.ok is True
        assert attempt.items_found == 3
        assert attempt.input_tokens == 1500


async def test_a_failure_is_retried_then_given_up_on(
    sessionmaker_fixture, settings, item_photo, monkeypatch
):
    from leltar import worker as worker_module
    from leltar.worker import IdentificationWorker

    monkeypatch.setattr(worker_module, "SessionLocal", sessionmaker_fixture)

    async with sessionmaker_fixture() as session:
        photo, _ = await ingest_photo(session, item_photo, settings)
        await session.commit()
        photo_id = photo.id

    worker = IdentificationWorker(settings)
    worker._identifier = StubIdentifier(error="a modell nem válaszolt")

    for _ in range(settings.worker_max_attempts):
        assert await worker.process_next() is True

    async with sessionmaker_fixture() as session:
        stored = await session.get(Photo, photo_id)
        assert stored.status == PhotoStatus.FAILED.value
        assert stored.attempts == settings.worker_max_attempts
        assert "nem válaszolt" in stored.error
        # Every attempt is recorded, failures included: they are billed too.
        failures = (
            await session.scalars(
                select(IdentificationAttempt).where(IdentificationAttempt.ok.is_(False))
            )
        ).all()
        assert len(failures) == settings.worker_max_attempts

    # And it stays given up on rather than looping forever.
    assert await worker.process_next() is False


async def test_the_worker_tells_the_model_where_the_photo_was_taken(
    sessionmaker_fixture, settings, item_photo, monkeypatch
):
    from leltar import worker as worker_module
    from leltar.models import Place
    from leltar.worker import IdentificationWorker

    monkeypatch.setattr(worker_module, "SessionLocal", sessionmaker_fixture)

    async with sessionmaker_fixture() as session:
        garage = Place(name="Garázs")
        session.add(garage)
        await session.flush()
        shelf = Place(name="Fém polc", parent_id=garage.id)
        session.add(shelf)
        await session.flush()
        await ingest_photo(session, item_photo, settings, place_id=shelf.id)
        await session.commit()

    worker = IdentificationWorker(settings)
    stub = StubIdentifier()
    worker._identifier = stub
    await worker.process_next()

    assert stub.place_paths == ["Garázs › Fém polc"]


async def test_the_worker_tells_the_model_when_one_object_was_photographed(
    sessionmaker_fixture, settings, item_photo, monkeypatch
):
    """The mode is a fact about taking the picture, so it is stored on it, not re-guessed."""
    from leltar import worker as worker_module
    from leltar.models import PhotoMode
    from leltar.worker import IdentificationWorker

    monkeypatch.setattr(worker_module, "SessionLocal", sessionmaker_fixture)

    async with sessionmaker_fixture() as session:
        await seed_if_empty(session)
        await ingest_photo(session, item_photo, settings, mode=PhotoMode.SINGLE.value)
        await session.commit()

    worker = IdentificationWorker(settings)
    stub = StubIdentifier()
    worker._identifier = stub
    await worker.process_next()

    assert stub.singles == [True]


async def test_two_readers_never_take_the_same_photograph(
    sessionmaker_fixture, settings, item_photo, monkeypatch
):
    """The two-person flow: one person photographing, several loops reading.

    `FOR UPDATE SKIP LOCKED` is what makes this safe, and this is the test that says so -
    a photograph read twice is paid for twice and produces two sets of drafts for the same
    objects, which is exactly the mess the person reviewing does not need.
    """
    import asyncio
    import io

    from PIL import Image

    from leltar import worker as worker_module
    from leltar.worker import IdentificationWorker

    monkeypatch.setattr(worker_module, "SessionLocal", sessionmaker_fixture)

    def jpeg(colour):
        buffer = io.BytesIO()
        Image.new("RGB", (900, 600), colour).save(buffer, format="JPEG")
        return buffer.getvalue()

    async with sessionmaker_fixture() as session:
        await seed_if_empty(session)
        for colour in [(10, 20, 30), (200, 100, 50), (40, 160, 90), (90, 90, 90)]:
            await ingest_photo(session, jpeg(colour), settings)
        await session.commit()

    # Four loops against four photographs, started together.
    workers = []
    for _ in range(4):
        worker = IdentificationWorker(settings)
        worker._identifier = StubIdentifier()
        workers.append(worker)

    results = await asyncio.gather(*(worker.process_next() for worker in workers))
    assert all(results)

    async with sessionmaker_fixture() as session:
        photos = (await session.scalars(select(Photo))).all()
        assert len(photos) == 4
        # Each was claimed exactly once: a second claim would show as a second attempt.
        assert [photo.attempts for photo in photos] == [1, 1, 1, 1]
        assert {photo.status for photo in photos} == {PhotoStatus.IDENTIFIED.value}
        # And each produced its own drafts rather than two loops doubling one photo's.
        items = (await session.scalars(select(Item))).all()
        assert len(items) == 4 * 3


async def test_the_number_of_readers_is_configurable(settings):
    """One is the old behaviour; more is what keeps a reviewer from waiting on the queue."""
    from leltar.worker import IdentificationWorker

    worker = IdentificationWorker(settings.model_copy(update={"worker_concurrency": 3}))
    worker._identifier = StubIdentifier()
    worker.start()
    try:
        assert len(worker._tasks) == 3
        # Starting twice must not silently double the readers.
        worker.start()
        assert len(worker._tasks) == 3
    finally:
        await worker.stop()
    assert worker._tasks == []
