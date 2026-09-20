"""The numbers, and the one rule behind them: a draft is not an inventory entry."""

from __future__ import annotations

from decimal import Decimal

from leltar.models import IdentificationAttempt, Item, ItemStatus, Photo, PhotoStatus, Place
from leltar.services import stats
from tests.conftest import requires_db

pytestmark = requires_db


async def _furnish(session) -> dict:
    living_room = Place(name="Nappali")
    garage = Place(name="Garázs")
    session.add_all([living_room, garage])
    await session.flush()

    session.add_all([
        Item(
            name="kanapé",
            place_id=living_room.id,
            status=ItemStatus.CONFIRMED.value,
            estimated_value=Decimal(120000),
            quantity=1,
            source="photo",
            suggested_name="kanapé",
            edited=False,
        ),
        Item(
            name="étkezőszék",
            place_id=living_room.id,
            status=ItemStatus.CONFIRMED.value,
            estimated_value=Decimal(9000),
            quantity=4,
            source="photo",
            suggested_name="szék",
            edited=True,
        ),
        Item(
            name="kerékpár",
            place_id=garage.id,
            status=ItemStatus.CONFIRMED.value,
            estimated_value=Decimal(80000),
            quantity=1,
            source="manual",
        ),
        # A draft, and it must not appear in a single total below.
        Item(
            name="talán egy fúró",
            place_id=garage.id,
            status=ItemStatus.DRAFT.value,
            estimated_value=Decimal(999999),
            quantity=1,
            source="photo",
            suggested_name="talán egy fúró",
        ),
    ])
    await session.commit()
    return {"living_room": living_room, "garage": garage}


async def test_the_summary_counts_copies_and_ignores_drafts(session):
    await _furnish(session)
    summary = await stats.summary(session)

    assert summary["items"] == 3
    assert summary["copies"] == 6  # four chairs count four times
    assert summary["total_value"] == Decimal(236000)  # 120000 + 4*9000 + 80000
    assert summary["drafts"] == 1


async def test_a_value_is_reported_against_how_much_of_it_was_estimated(session):
    session.add_all([
        Item(name="a", status=ItemStatus.CONFIRMED.value, estimated_value=Decimal(1000)),
        Item(name="b", status=ItemStatus.CONFIRMED.value, estimated_value=None),
    ])
    await session.commit()

    summary = await stats.summary(session)
    assert summary["items"] == 2
    assert summary["valued_items"] == 1


async def test_totals_by_place_use_the_full_path(session):
    places = await _furnish(session)
    garage = places["garage"]
    shelf = Place(name="Fém polc", parent_id=garage.id)
    session.add(shelf)
    await session.flush()
    session.add(
        Item(
            name="fűnyíró",
            place_id=shelf.id,
            status=ItemStatus.CONFIRMED.value,
            estimated_value=Decimal(45000),
        )
    )
    await session.commit()

    rows = {row["place_path"]: row for row in await stats.by_place(session)}
    assert rows["Garázs › Fém polc"]["total_value"] == Decimal(45000)
    assert rows["Nappali"]["items"] == 2


async def test_items_with_no_place_are_reported_rather_than_dropped(session):
    session.add(
        Item(name="hontalan lámpa", status=ItemStatus.CONFIRMED.value,
             estimated_value=Decimal(5000))
    )
    await session.commit()

    rows = await stats.by_place(session)
    assert rows[0]["place_path"] == "Hely nélkül"


async def test_accuracy_measures_the_names_you_kept(session):
    await _furnish(session)
    accuracy = await stats.accuracy(session)

    # The manually typed bicycle has no suggestion, so it is not part of the measure.
    assert accuracy["confirmed_from_photos"] == 2
    assert accuracy["kept_as_suggested"] == 1
    assert accuracy["edited"] == 1
    assert accuracy["keep_rate"] == 0.5


async def test_accuracy_is_none_rather_than_zero_before_anything_is_confirmed(session):
    assert (await stats.accuracy(session))["keep_rate"] is None


async def test_cost_is_reported_per_confirmed_item(session):
    await _furnish(session)
    session.add_all([
        IdentificationAttempt(
            engine="claude", model="claude-sonnet-5", ok=True,
            cost_usd=Decimal("0.004"), items_found=3, latency_ms=2000,
        ),
        IdentificationAttempt(
            engine="claude", model="claude-sonnet-5", ok=False,
            cost_usd=Decimal("0.002"), latency_ms=1000,
        ),
    ])
    await session.commit()

    costs = await stats.costs(session)
    assert costs["calls"] == 2
    assert costs["failures"] == 1
    # A failed call is billed, so it counts towards the total.
    assert costs["total_usd"] == Decimal("0.006")
    assert costs["usd_per_confirmed_item"] == Decimal("0.006") / 3
    assert costs["by_month"][0]["items_found"] == 3


async def test_photo_queue_depth_is_visible_in_the_summary(session):
    session.add_all([
        Photo(path="/tmp/1.jpg", sha256="1" * 64, status=PhotoStatus.PENDING.value),
        Photo(path="/tmp/2.jpg", sha256="2" * 64, status=PhotoStatus.NEEDS_REVIEW.value),
        Photo(path="/tmp/3.jpg", sha256="3" * 64, status=PhotoStatus.FAILED.value),
    ])
    await session.commit()

    summary = await stats.summary(session)
    assert summary["photos"] == 3
    assert summary["photos_pending"] == 1
    assert summary["photos_needing_review"] == 1
    assert summary["photos_failed"] == 1
