"""The numbers the app can honestly report.

This is a catalogue of what is in the house, so the numbers are counts of things - how
many, where, of what kind - rather than a total of what they are worth. The app does not
ask the model for prices at all, and adding up a column of guesses would produce a figure
that looks like a valuation and is not one.

One rule runs through all of it: **only confirmed items count.** A draft is the model's
guess, and a count that includes guesses would move every time the model had an opinion.
Drafts are reported separately, as a queue depth, because that is what they are.
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import Numeric, case, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from leltar.models import (
    Category,
    IdentificationAttempt,
    Item,
    ItemImage,
    ItemStatus,
    Photo,
    PhotoStatus,
)
from leltar.services.places import paths_for_all

# Two different questions, and both get asked: "how many entries" (four matching chairs
# are one line in the catalogue) and "how many things" (they are four chairs).
COPIES = func.coalesce(func.sum(Item.quantity), 0)

CONFIRMED = Item.status == ItemStatus.CONFIRMED.value


async def summary(session: AsyncSession) -> dict:
    total_items, total_copies, places_used, categories_used = (
        await session.execute(
            select(
                func.count(Item.id),
                COPIES,
                func.count(func.distinct(Item.place_id)),
                func.count(func.distinct(Item.category_id)),
            ).where(CONFIRMED)
        )
    ).one()

    # How much of the catalogue you could actually recognise from a list. The whole point
    # of the pictures, so it is worth watching rather than assuming.
    with_picture = await session.scalar(
        select(func.count(func.distinct(Item.id)))
        .select_from(Item)
        .join(ItemImage, ItemImage.item_id == Item.id)
        .where(CONFIRMED)
    )
    drafts = await session.scalar(
        select(func.count(Item.id)).where(Item.status == ItemStatus.DRAFT.value)
    )

    photo_counts = dict(
        (
            await session.execute(
                select(Photo.status, func.count(Photo.id)).group_by(Photo.status)
            )
        ).all()
    )
    last_added = await session.scalar(select(func.max(Item.created_at)))

    return {
        "items": int(total_items),
        "copies": int(total_copies),
        "places_used": int(places_used or 0),
        "categories_used": int(categories_used or 0),
        "with_picture": int(with_picture or 0),
        "drafts": int(drafts or 0),
        "photos": sum(photo_counts.values()),
        "photos_pending": photo_counts.get(PhotoStatus.PENDING.value, 0)
        + photo_counts.get(PhotoStatus.PROCESSING.value, 0),
        "photos_needing_review": photo_counts.get(PhotoStatus.NEEDS_REVIEW.value, 0)
        + photo_counts.get(PhotoStatus.IDENTIFIED.value, 0),
        "photos_failed": photo_counts.get(PhotoStatus.FAILED.value, 0),
        "last_added": last_added,
    }


async def by_place(session: AsyncSession) -> list[dict]:
    rows = (
        await session.execute(
            select(Item.place_id, func.count(Item.id), COPIES)
            .where(CONFIRMED)
            .group_by(Item.place_id)
        )
    ).all()

    paths = await paths_for_all(session)
    total = sum(int(items) for _, items, _ in rows) or 1
    result = [
        {
            "place_id": place_id,
            "place_path": paths.get(place_id, "Hely nélkül") if place_id else "Hely nélkül",
            "items": int(items),
            "copies": int(copies),
            "share": int(items) / total,
        }
        for place_id, items, copies in rows
    ]
    result.sort(key=lambda row: (-row["items"], row["place_path"]))
    return result


async def by_category(session: AsyncSession) -> list[dict]:
    rows = (
        await session.execute(
            select(Category.id, Category.name, Category.icon, func.count(Item.id), COPIES)
            .select_from(Item)
            .outerjoin(Category, Item.category_id == Category.id)
            .where(CONFIRMED)
            .group_by(Category.id, Category.name, Category.icon)
        )
    ).all()

    total = sum(int(items) for _, _, _, items, _ in rows) or 1
    result = [
        {
            "category_id": category_id,
            "category_name": name or "Besorolatlan",
            "icon": icon,
            "items": int(items),
            "copies": int(copies),
            "share": int(items) / total,
        }
        for category_id, name, icon, items, copies in rows
    ]
    result.sort(key=lambda row: -row["items"])
    return result


async def accuracy(session: AsyncSession) -> dict:
    """Is the model actually saving you typing?

    The only honest measure this app can take of itself: of the names it suggested and you
    then confirmed, how many did you keep as they were. `suggested_name` is never
    overwritten by an edit, which is what makes the comparison possible at all.
    """
    kept = func.sum(case((Item.edited.is_(False), 1), else_=0))
    rows = (
        await session.execute(
            select(
                func.count(Item.id),
                func.coalesce(kept, 0),
                func.avg(cast(Item.confidence, Numeric)),
            ).where(
                CONFIRMED,
                Item.source == "photo",
                Item.suggested_name.is_not(None),
            )
        )
    ).one()
    confirmed, unedited, mean_confidence = rows
    confirmed = int(confirmed)
    unedited = int(unedited)

    return {
        "confirmed_from_photos": confirmed,
        "kept_as_suggested": unedited,
        "edited": confirmed - unedited,
        "keep_rate": (unedited / confirmed) if confirmed else None,
        "mean_confidence": float(mean_confidence) if mean_confidence is not None else None,
    }


async def costs(session: AsyncSession) -> dict:
    """What identification has cost, and what it costs per item you ended up keeping.

    Per *item* rather than per photograph, because a photo of a shelf that yields eight
    entries and a photo of one chair cost nearly the same to read. The per-item figure is
    the one that tells you whether pointing the camera at a whole shelf is worth it.
    """
    total_cost, calls, mean_latency = (
        await session.execute(
            select(
                func.coalesce(func.sum(IdentificationAttempt.cost_usd), 0),
                func.count(IdentificationAttempt.id),
                func.avg(IdentificationAttempt.latency_ms),
            )
        )
    ).one()
    failures = await session.scalar(
        select(func.count(IdentificationAttempt.id)).where(
            IdentificationAttempt.ok.is_(False)
        )
    )
    items_found = await session.scalar(
        select(func.coalesce(func.sum(IdentificationAttempt.items_found), 0))
    )
    confirmed = await session.scalar(select(func.count(Item.id)).where(CONFIRMED))

    total_cost = Decimal(total_cost)
    by_month = [
        {
            "month": month,
            "model": model,
            "calls": int(count),
            "total_usd": Decimal(cost),
            "items_found": int(found or 0),
        }
        for month, model, count, cost, found in (
            await session.execute(
                select(
                    func.date_trunc("month", IdentificationAttempt.created_at).label("month"),
                    IdentificationAttempt.model,
                    func.count(IdentificationAttempt.id),
                    func.coalesce(func.sum(IdentificationAttempt.cost_usd), 0),
                    func.coalesce(func.sum(IdentificationAttempt.items_found), 0),
                )
                .group_by("month", IdentificationAttempt.model)
                .order_by("month")
            )
        ).all()
    ]

    return {
        "total_usd": total_cost,
        "calls": int(calls),
        "failures": int(failures or 0),
        "items_found": int(items_found or 0),
        "confirmed_items": int(confirmed or 0),
        "usd_per_photo": (total_cost / calls) if calls else Decimal(0),
        "usd_per_confirmed_item": (total_cost / confirmed) if confirmed else None,
        "mean_latency_ms": int(mean_latency) if mean_latency is not None else None,
        "by_month": by_month,
    }
