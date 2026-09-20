"""The numbers the app can honestly report.

One rule runs through all of this: **only confirmed items count.** A draft is the model's
guess, and a total that includes guesses would move every time the model had an opinion,
which is precisely the number nobody can use. Drafts are reported separately, as a queue
depth, because that is what they are.
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import Numeric, case, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from leltar.models import Category, IdentificationAttempt, Item, ItemStatus, Photo, PhotoStatus
from leltar.services.places import paths_for_all

# `estimated_value` is per copy, so an entry of four matching chairs is worth four times
# its midpoint. Written once here rather than repeated in every query below.
VALUE = func.coalesce(Item.estimated_value, 0) * Item.quantity

CONFIRMED = Item.status == ItemStatus.CONFIRMED.value


async def summary(session: AsyncSession) -> dict:
    total_items, total_copies, total_value = (
        await session.execute(
            select(
                func.count(Item.id),
                func.coalesce(func.sum(Item.quantity), 0),
                func.coalesce(func.sum(VALUE), 0),
            ).where(CONFIRMED)
        )
    ).one()

    valued = await session.scalar(
        select(func.count(Item.id)).where(CONFIRMED, Item.estimated_value.is_not(None))
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
        "total_value": Decimal(total_value),
        # How much of the total rests on an actual estimate. A value built from a third of
        # the inventory is not wrong, but it is not a household's worth either.
        "valued_items": int(valued or 0),
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
            select(
                Item.place_id,
                func.count(Item.id),
                func.coalesce(func.sum(Item.quantity), 0),
                func.coalesce(func.sum(VALUE), 0),
            )
            .where(CONFIRMED)
            .group_by(Item.place_id)
        )
    ).all()

    paths = await paths_for_all(session)
    result = [
        {
            "place_id": place_id,
            "place_path": paths.get(place_id, "Hely nélkül") if place_id else "Hely nélkül",
            "items": int(items),
            "copies": int(copies),
            "total_value": Decimal(value),
        }
        for place_id, items, copies, value in rows
    ]
    result.sort(key=lambda row: (-row["total_value"], row["place_path"]))
    return result


async def by_category(session: AsyncSession) -> list[dict]:
    rows = (
        await session.execute(
            select(
                Category.id,
                Category.name,
                Category.icon,
                func.count(Item.id),
                func.coalesce(func.sum(VALUE), 0),
            )
            .select_from(Item)
            .outerjoin(Category, Item.category_id == Category.id)
            .where(CONFIRMED)
            .group_by(Category.id, Category.name, Category.icon)
        )
    ).all()

    total = sum(Decimal(value) for _, _, _, _, value in rows) or Decimal(1)
    result = [
        {
            "category_id": category_id,
            "category_name": name or "Besorolatlan",
            "icon": icon,
            "items": int(items),
            "total_value": Decimal(value),
            "share": float(Decimal(value) / total),
        }
        for category_id, name, icon, items, value in rows
    ]
    result.sort(key=lambda row: -row["total_value"])
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
