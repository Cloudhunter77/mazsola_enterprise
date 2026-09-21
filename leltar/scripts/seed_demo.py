"""Fill an empty install with plausible contents, so the screens can be looked at.

    python scripts/seed_demo.py --yes       # add demo rooms and things
    python scripts/seed_demo.py --clear     # remove exactly what it created

Everything it writes is marked in `notes`, and `--clear` deletes on that marker alone - so
it can never take one of your own entries with it. No photographs and no API calls: these
items are entered as if typed in by hand.
"""

from __future__ import annotations

import argparse
import asyncio
import random
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import delete, select  # noqa: E402

from leltar.db import SessionLocal  # noqa: E402
from leltar.models import Category, Item, ItemStatus, Place  # noqa: E402
from leltar.services.seed import seed_if_empty  # noqa: E402

MARKER = "demo-adat"

# name, category slug, quantity
THINGS: dict[str, list[tuple[str, str, int]]] = {
    "Nappali": [
        ("szürke szövet kanapé", "butor", 1),
        ("tömörfa dohányzóasztal", "butor", 1),
        ("55 colos LED televízió", "elektronika", 1),
        ("álló olvasólámpa", "dekoracio", 2),
        ("gyapjú szőnyeg 200x300", "textil", 1),
    ],
    "Konyha": [
        ("rozsdamentes vízforraló", "konyha", 1),
        ("kerámia tányérkészlet", "konyha", 1),
        ("konyhai robotgép", "haztartasi-gep", 1),
        ("fa vágódeszka", "konyha", 3),
    ],
    "Hálószoba": [
        ("kétszemélyes ágy matraccal", "butor", 1),
        ("négyajtós ruhásszekrény", "butor", 1),
        ("ébresztőóra", "elektronika", 1),
    ],
    "Garázs": [
        ("akkus fúró-csavarozó", "szerszam", 1),
        ("körfűrész", "szerszam", 1),
        ("városi kerékpár", "sport", 2),
        ("kerti fűnyíró", "kerti", 1),
        ("műanyag tárolódoboz", "egyeb", 6),
    ],
}


async def add() -> None:
    random.seed(20260920)
    async with SessionLocal() as session:
        await seed_if_empty(session)

        categories = dict(
            (await session.execute(select(Category.slug, Category.id))).all()
        )
        places = dict((await session.execute(select(Place.name, Place.id))).all())

        created = 0
        for room, things in THINGS.items():
            place_id = places.get(room)
            if place_id is None:
                place = Place(name=room)
                session.add(place)
                await session.flush()
                place_id = place.id

            for name, slug, quantity in things:
                session.add(
                    Item(
                        name=name,
                        # Demo rows are "typed in", so they never pretend the model got
                        # something right: the accuracy page stays honest on a demo install.
                        source="manual",
                        status=ItemStatus.CONFIRMED.value,
                        confirmed_at=datetime.now(UTC),
                        place_id=place_id,
                        category_id=categories.get(slug),
                        quantity=quantity,
                        condition=random.choice(["good", "used", "new"]),
                        notes=MARKER,
                    )
                )
                created += 1

        await session.commit()
        print(f"added {created} demo items across {len(THINGS)} places")


async def clear() -> None:
    async with SessionLocal() as session:
        result = await session.execute(delete(Item).where(Item.notes == MARKER))
        await session.commit()
        print(f"removed {result.rowcount} demo items")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--yes", action="store_true", help="Add the demo data.")
    parser.add_argument("--clear", action="store_true", help="Remove it again.")
    args = parser.parse_args()

    if args.clear:
        asyncio.run(clear())
    elif args.yes:
        asyncio.run(add())
    else:
        parser.error("pass --yes to add demo data, or --clear to remove it")


if __name__ == "__main__":
    main()
