"""The place tree: rooms, cupboards, boxes."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import func, select

from leltar.api.deps import AuthDep, SessionDep
from leltar.models import Item, ItemStatus, Place, PlaceKind
from leltar.schemas.api import PlaceIn, PlaceOut, PlacePatch
from leltar.services.places import PlaceError, check_parent, descendants, in_use, paths_for_all

router = APIRouter(prefix="/api/places", tags=["places"])


@router.get("", response_model=list[PlaceOut])
async def list_places(_: AuthDep, session: SessionDep) -> list[PlaceOut]:
    places = list((await session.scalars(select(Place))).all())
    paths = await paths_for_all(session)
    counts = dict(
        (
            await session.execute(
                select(Item.place_id, func.count(Item.id))
                .where(Item.status == ItemStatus.CONFIRMED.value)
                .group_by(Item.place_id)
            )
        ).all()
    )

    rows = []
    for place in places:
        row = PlaceOut.model_validate(place)
        row.path = paths.get(place.id, place.name)
        row.item_count = int(counts.get(place.id, 0))
        rows.append(row)
    # Sorted by path, so the list reads as the tree it is rather than by insertion order.
    rows.sort(key=lambda row: (row.sort_order, row.path))
    return rows


@router.post("", response_model=PlaceOut, status_code=status.HTTP_201_CREATED)
async def create_place(_: AuthDep, session: SessionDep, body: PlaceIn) -> PlaceOut:
    if body.kind not in set(PlaceKind):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=f"Ismeretlen típus: {body.kind}."
        )
    if body.parent_id is not None and await session.get(Place, body.parent_id) is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="A megadott szülő nem létezik."
        )

    place = Place(**body.model_dump())
    session.add(place)
    await session.commit()
    return (await _one(session, place.id))


@router.patch("/{place_id}", response_model=PlaceOut)
async def patch_place(
    _: AuthDep, session: SessionDep, place_id: uuid.UUID, body: PlacePatch
) -> PlaceOut:
    place = await session.get(Place, place_id)
    if place is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Nincs ilyen hely.")

    changes = body.model_dump(exclude_unset=True)
    if "kind" in changes and changes["kind"] not in set(PlaceKind):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Ismeretlen típus: {changes['kind']}.",
        )
    if "parent_id" in changes:
        try:
            await check_parent(session, place_id, changes["parent_id"])
        except PlaceError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
            ) from exc

    for field, value in changes.items():
        setattr(place, field, value)
    await session.commit()
    return await _one(session, place_id)


@router.delete("/{place_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_place(_: AuthDep, session: SessionDep, place_id: uuid.UUID) -> None:
    """Delete an empty place.

    A place holding things is not deleted, because the alternative - quietly setting a
    hundred items to "hely nélkül" - loses information you cannot get back from the
    photographs. Move or delete the contents first; the error says how many there are.
    """
    place = await session.get(Place, place_id)
    if place is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Nincs ilyen hely.")

    nested = await descendants(session, place_id)
    if len(nested) > 1:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Ebben a helyben még {len(nested) - 1} másik hely van.",
        )
    if await in_use(session, place_id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Ehhez a helyhez még tartoznak tárgyak vagy fényképek.",
        )

    await session.delete(place)
    await session.commit()


async def _one(session: SessionDep, place_id: uuid.UUID) -> PlaceOut:
    place = await session.get(Place, place_id)
    if place is None:  # pragma: no cover - only reachable if deleted mid-request
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Nincs ilyen hely.")
    paths = await paths_for_all(session)
    row = PlaceOut.model_validate(place)
    row.path = paths.get(place.id, place.name)
    return row
