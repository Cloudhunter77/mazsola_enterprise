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
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import delete, select  # noqa: E402

from leltar.db import SessionLocal  # noqa: E402
from leltar.models import Category, Item, ItemStatus, Place  # noqa: E402
from leltar.services.seed import seed_if_empty  # noqa: E402

MARKER = "demo-adat"

# name, category slug, value low, value high, quantity
THINGS: dict[str, list[tuple[str, str, int, int, int]]] = {
    "Nappali": [
        ("szürke szövet kanapé", "butor", 90_000, 180_000, 1),
        ("tömörfa dohányzóasztal", "butor", 20_000, 45_000, 1),
        ("55 colos LED televízió", "elektronika", 80_000, 160_000, 1),
        ("álló olvasólámpa", "dekoracio", 8_000, 18_000, 2),
        ("gyapjú szőnyeg 200x300", "textil", 35_000, 90_000, 1),
    ],
    "Konyha": [
        ("rozsdamentes vízforraló", "konyha", 6_000, 15_000, 1),
        ("kerámia tányérkészlet", "konyha", 12_000, 30_000, 1),
        ("konyhai robotgép", "haztartasi-gep", 40_000, 90_000, 1),
        ("fa vágódeszka", "konyha", 2_000, 6_000, 3),
    ],
    "Hálószoba": [
        ("kétszemélyes ágy matraccal", "butor", 70_000, 150_000, 1),
        ("négyajtós ruhásszekrény", "butor", 50_000, 120_000, 1),
        ("ébresztőóra", "elektronika", 3_000, 8_000, 1),
    ],
    "Garázs": [
        ("akkus fúró-csavarozó", "szerszam", 25_000, 60_000, 1),
        ("körfűrész", "szerszam", 30_000, 70_000, 1),
        ("városi kerékpár", "sport", 60_000, 140_000, 2),
        ("kerti fűnyíró", "kerti", 45_000, 110_000, 1),
        ("műanyag tárolódoboz", "egyeb", 1_500, 4_000, 6),
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

            for name, slug, low, high, quantity in things:
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
                        value_low=Decimal(low),
                        value_high=Decimal(high),
                        estimated_value=Decimal(round((low + high) / 2 / 100) * 100),
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
