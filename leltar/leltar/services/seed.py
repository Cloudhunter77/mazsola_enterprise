"""First-run content: the category list, and a house to put things in.

Seeding runs at every start and is a no-op once anything exists, so an update never
resurrects a category you deleted or a room you renamed.
"""

from __future__ import annotations

import logging

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from leltar.extraction.categories import CATEGORIES
from leltar.models import Category, Place, PlaceKind

log = logging.getLogger(__name__)

# Somewhere to put the first photograph. Not a model of anyone's actual home - it is a
# starting point that makes the place picker useful on day one, and every one of these can
# be renamed or deleted.
DEFAULT_PLACES: tuple[tuple[str, str], ...] = (
    ("Nappali", PlaceKind.ROOM.value),
    ("Konyha", PlaceKind.ROOM.value),
    ("Hálószoba", PlaceKind.ROOM.value),
    ("Gyerekszoba", PlaceKind.ROOM.value),
    ("Fürdőszoba", PlaceKind.ROOM.value),
    ("Előszoba", PlaceKind.ROOM.value),
    ("Kamra", PlaceKind.STORAGE.value),
    ("Padlás", PlaceKind.STORAGE.value),
    ("Pince", PlaceKind.STORAGE.value),
    ("Garázs", PlaceKind.BUILDING.value),
)


async def seed_if_empty(session: AsyncSession) -> None:
    await _seed_categories(session)
    await _seed_places(session)
    await session.commit()


async def _seed_categories(session: AsyncSession) -> None:
    """The category list is the one the prompt offers the model, so the two cannot drift.

    Unlike the places below, a missing category is filled in even on a populated database:
    `rules` maps any slug the model returns to this table, and a slug with no row would
    leave those items uncategorised for no reason the person could see or fix.
    """
    existing = set(
        (await session.scalars(select(Category.slug))).all()
    )
    added = 0
    for order, (slug, name, icon) in enumerate(CATEGORIES):
        if slug in existing:
            continue
        session.add(
            Category(slug=slug, name=name, icon=icon, sort_order=(order + 1) * 10)
        )
        added += 1
    if added:
        log.info("seeded %d categor%s", added, "y" if added == 1 else "ies")


async def _seed_places(session: AsyncSession) -> None:
    count = await session.scalar(select(func.count(Place.id)))
    if count:
        return
    for order, (name, kind) in enumerate(DEFAULT_PLACES):
        session.add(Place(name=name, kind=kind, sort_order=(order + 1) * 10))
    log.info("seeded %d places", len(DEFAULT_PLACES))
