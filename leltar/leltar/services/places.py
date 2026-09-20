"""Reading and writing the place tree."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from leltar.models import Item, Photo, Place

SEPARATOR = " › "

# A place inside itself would make every path walk loop forever; the depth cap is the
# belt to that braces, since a cycle can also be formed by two separate edits racing.
MAX_DEPTH = 12


class PlaceError(ValueError):
    """The place tree would stop being a tree."""


async def path_of(session: AsyncSession, place_id: uuid.UUID | None) -> str | None:
    """"Garázs › Fém polc › Kék doboz" - what a person needs to actually go and find it."""
    if place_id is None:
        return None
    names: list[str] = []
    current: uuid.UUID | None = place_id
    seen: set[uuid.UUID] = set()
    while current is not None and len(names) < MAX_DEPTH:
        if current in seen:
            break
        seen.add(current)
        place = await session.get(Place, current)
        if place is None:
            break
        names.append(place.name)
        current = place.parent_id
    return SEPARATOR.join(reversed(names)) if names else None


async def paths_for_all(session: AsyncSession) -> dict[uuid.UUID, str]:
    """Every place's full path, in one query.

    The tree is small - rooms and boxes, not a filesystem - so building it in memory beats
    a recursive CTE, and beats asking for one path per row on a list of 500 items.
    """
    places = (await session.scalars(select(Place))).all()
    by_id = {place.id: place for place in places}

    paths: dict[uuid.UUID, str] = {}

    def resolve(place_id: uuid.UUID, depth: int = 0) -> str:
        if place_id in paths:
            return paths[place_id]
        place = by_id[place_id]
        if place.parent_id is None or place.parent_id not in by_id or depth >= MAX_DEPTH:
            paths[place_id] = place.name
        else:
            paths[place_id] = resolve(place.parent_id, depth + 1) + SEPARATOR + place.name
        return paths[place_id]

    for place_id in by_id:
        resolve(place_id)
    return paths


async def check_parent(
    session: AsyncSession, place_id: uuid.UUID, parent_id: uuid.UUID | None
) -> None:
    """Refuse a move that would make a place its own ancestor."""
    if parent_id is None:
        return
    if parent_id == place_id:
        raise PlaceError("A hely nem lehet önmaga szülője.")
    current: uuid.UUID | None = parent_id
    for _ in range(MAX_DEPTH):
        if current is None:
            return
        if current == place_id:
            raise PlaceError("Ez a lépés kört hozna létre a helyek fájában.")
        parent = await session.get(Place, current)
        if parent is None:
            return
        current = parent.parent_id


async def descendants(session: AsyncSession, place_id: uuid.UUID) -> list[uuid.UUID]:
    """A place and everything nested inside it - what "show me the garage" has to mean."""
    places = (await session.scalars(select(Place))).all()
    children: dict[uuid.UUID | None, list[uuid.UUID]] = {}
    for place in places:
        children.setdefault(place.parent_id, []).append(place.id)

    found = [place_id]
    queue = [place_id]
    while queue:
        current = queue.pop()
        for child in children.get(current, []):
            if child not in found:
                found.append(child)
                queue.append(child)
    return found


async def in_use(session: AsyncSession, place_id: uuid.UUID) -> int:
    """How many items and photos point here. Deleting a place must not silently orphan them."""
    item_count = await session.scalar(
        select(Item.id).where(Item.place_id == place_id).limit(1)
    )
    photo_count = await session.scalar(
        select(Photo.id).where(Photo.place_id == place_id).limit(1)
    )
    return int(item_count is not None) + int(photo_count is not None)
