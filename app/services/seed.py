"""Seed data: the Hungarian category tree.

Run at every start. Categories are matched by slug, so re-running is safe, and a category
added here later reaches a database that already has the rest without disturbing anything
in it. Nothing in the app deletes or renames a category, so a seeded one can never come back
against your wishes.
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Category
from app.services.catalog import slugify

log = logging.getLogger(__name__)

# (parent, [children]) - the shape a Hungarian household actually shops in.
CATEGORY_TREE: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "Élelmiszer",
        (
            "Pékáru",
            "Tejtermék",
            "Hús és hal",
            "Zöldség és gyümölcs",
            "Alapvető élelmiszer",
            "Édesség és snack",
            "Fagyasztott",
            "Konzerv és készétel",
        ),
    ),
    ("Ital", ("Üdítő", "Ásványvíz", "Kávé és tea", "Alkohol")),
    ("Háztartás", ("Tisztítószer", "Papíráru", "Konyhai eszköz", "Izzó és elem")),
    ("Drogéria", ("Testápolás", "Kozmetikum", "Gyógyszer és vitamin", "Baba")),
    ("Háziállat", ("Állateledel", "Állatfelszerelés")),
    ("Ruházat", ("Felsőruházat", "Cipő", "Kiegészítő")),
    ("Elektronika", ("Műszaki cikk", "Számítástechnika")),
    ("Lakás és otthon", ("Bútor", "Barkács", "Kert", "Dekoráció")),
    ("Közlekedés", ("Üzemanyag", "Tömegközlekedés", "Parkolás", "Autó szerviz")),
    (
        "Szabadidő",
        ("Vendéglátás", "Kultúra", "Sport", "Könyv és újság", "Programok", "Utazás", "Hobbi"),
    ),
    # Bills of the home: electricity, gas, water, internet. One category rather than a
    # subtree on purpose - each bill is its own Rendszeres item, which already tells them
    # apart; the category only has to say which line of the budget they belong to.
    ("Rezsi", ()),
    (
        "Egyéb",
        ("Betétdíj", "Szolgáltatás", "Ajándék", "Besorolatlan", "Váratlan kiadások"),
    ),
)


async def seed_categories(session: AsyncSession) -> int:
    """Create any missing categories. Returns how many were added."""
    existing = {
        slug for slug in (await session.scalars(select(Category.slug))).all()
    }
    added = 0
    order = 0

    for parent_name, children in CATEGORY_TREE:
        order += 100
        parent_slug = slugify(parent_name)
        parent = await session.scalar(select(Category).where(Category.slug == parent_slug))
        if parent is None:
            parent = Category(name=parent_name, slug=parent_slug, sort_order=order)
            session.add(parent)
            await session.flush()
            added += 1

        for index, child_name in enumerate(children, start=1):
            child_slug = slugify(child_name)
            if child_slug in existing or child_slug == parent_slug:
                continue
            session.add(
                Category(
                    name=child_name,
                    slug=child_slug,
                    parent_id=parent.id,
                    sort_order=order + index,
                )
            )
            existing.add(child_slug)
            added += 1

    if added:
        await session.commit()
        log.info("seeded %d categories", added)
    return added
