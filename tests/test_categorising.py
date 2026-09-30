"""Filing what nothing could categorise, once per name instead of once per line.

Two things are under test. The screen: a name appears once, filing it files every line
printed that way, and it can be taken back exactly. And the rule underneath it, which had
been described in `categorise.py` and never run: a category you set by hand now reaches
the other lines that normalise the same way, so the next receipt with that milk on it
arrives categorised instead of joining "Besorolatlan" again.
"""

from __future__ import annotations

from sqlalchemy import select

from app.models import Category, Product, ReceiptItem
from app.services.categorise import categorise_stored
from app.services.seed import seed_categories
from tests.conftest import requires_db
from tests.test_matching import _receipt_with

pytestmark = requires_db


async def category(session, name: str):
    await seed_categories(session)
    await session.commit()
    return await session.scalar(select(Category.id).where(Category.name == name))


async def file(client, raw_name: str, category_id):
    """File a name under a category through the API, as the screen does."""
    return await client.post(
        "/api/categorise/assign", json={"raw_name": raw_name, "category_id": str(category_id)}
    )


async def lines(session) -> dict[str, tuple]:
    session.expire_all()
    rows = (await session.execute(
        select(ReceiptItem.raw_name, ReceiptItem.category_id, ReceiptItem.category_source)
    )).all()
    return {name: (cat, source) for name, cat, source in rows}


class TestTheLearnedRule:
    async def test_a_hand_set_category_reaches_another_spelling(self, session):
        dairy = await category(session, "Tejtermék")
        await _receipt_with(session, ["UHT TEJ 1L", "uht tej 1 l"])
        item = await session.scalar(select(ReceiptItem).where(ReceiptItem.raw_name == "UHT TEJ 1L"))
        item.category_id, item.category_source = dairy, "manual"
        await session.commit()

        applied = await categorise_stored(session)
        await session.commit()

        assert applied.get("learned") == 1
        assert (await lines(session))["uht tej 1 l"] == (dairy, "learned")

    async def test_a_name_filed_two_ways_teaches_nothing(self, session):
        """The rule cannot know which you meant, and guessing is the quiet kind of wrong.

        A name no keyword knows, so nothing else can file it either.
        """
        dairy = await category(session, "Tejtermék")
        other = await session.scalar(select(Category.id).where(Category.name == "Egyéb"))
        await _receipt_with(session, ["ZORBA 1L", "ZORBA 1L", "zorba 1 l"])
        first, second = (await session.scalars(
            select(ReceiptItem).where(ReceiptItem.raw_name == "ZORBA 1L")
        )).all()
        first.category_id, first.category_source = dairy, "manual"
        second.category_id, second.category_source = other, "manual"
        await session.commit()

        await categorise_stored(session)
        await session.commit()
        assert (await lines(session))["zorba 1 l"] == (None, None)


class TestTheList:
    async def test_each_name_appears_once_most_money_first(self, auth_client, session):
        await category(session, "Tejtermék")
        await _receipt_with(session, ["Kenyér", "Tej", "Tej", "Tej"])

        body = (await auth_client.get("/api/categorise/uncategorised")).json()
        assert [(row["raw_name"], row["lines"]) for row in body] == [("Tej", 3), ("Kenyér", 1)]
        assert float(body[0]["total"]) == 1500

    async def test_a_categorised_line_is_not_listed(self, auth_client, session):
        dairy = await category(session, "Tejtermék")
        await _receipt_with(session, ["Tej"])
        await file(auth_client, "Tej", str(dairy))

        assert (await auth_client.get("/api/categorise/uncategorised")).json() == []


class TestFilingAName:
    async def test_every_line_with_that_name_is_filed_as_yours(self, auth_client, session):
        dairy = await category(session, "Tejtermék")
        await _receipt_with(session, ["Tej", "Tej"])
        await _receipt_with(session, ["Tej"])

        body = (await file(auth_client, "Tej", str(dairy))).json()
        assert body["lines"] == 3 and body["spread"] == 0
        items = (await session.execute(
            select(ReceiptItem.category_id, ReceiptItem.category_source)
        )).all()
        assert set(items) == {(dairy, "manual")}

    async def test_the_product_learns_it_for_next_time(self, auth_client, session):
        dairy = await category(session, "Tejtermék")
        await _receipt_with(session, ["TEJ 1L", "Pöttyös tej 1l"])
        product = (await auth_client.post("/api/suggestions/apply", json={
            "raw_names": ["TEJ 1L", "Pöttyös tej 1l"], "canonical_name": "Tej 1l",
        })).json()

        body = (await file(auth_client, "TEJ 1L", str(dairy))).json()

        session.expire_all()
        assert (await session.get(Product, product["id"])).category_id == dairy
        # The other spelling of the same product came along, through the product.
        assert (await lines(session))["Pöttyös tej 1l"] == (dairy, "product")
        assert body["spread"] == 1

    async def test_it_never_overrides_a_category_already_set(self, auth_client, session):
        dairy = await category(session, "Tejtermék")
        other = await session.scalar(select(Category.id).where(Category.name == "Egyéb"))
        await _receipt_with(session, ["Tej", "Tej"])
        first = await session.scalar(select(ReceiptItem).where(ReceiptItem.raw_name == "Tej"))
        first.category_id, first.category_source = other, "manual"
        await session.commit()

        body = (await file(auth_client, "Tej", str(dairy))).json()
        assert body["lines"] == 1
        session.expire_all()
        cats = set((await session.scalars(select(ReceiptItem.category_id))).all())
        assert cats == {dairy, other}

    async def test_an_unknown_category_is_refused(self, auth_client, session):
        import uuid
        await _receipt_with(session, ["Tej"])
        response = await file(auth_client, "Tej", str(uuid.uuid4()))
        assert response.status_code == 404


class TestTakingItBack:
    async def test_undo_restores_exactly_what_was_changed(self, auth_client, session):
        dairy = await category(session, "Tejtermék")
        await _receipt_with(session, ["TEJ 1L", "Pöttyös tej 1l"])
        product = (await auth_client.post("/api/suggestions/apply", json={
            "raw_names": ["TEJ 1L", "Pöttyös tej 1l"], "canonical_name": "Tej 1l",
        })).json()
        done = (await file(auth_client, "TEJ 1L", str(dairy))).json()

        response = await auth_client.post("/api/categorise/undo", json={
            "category_id": done["category_id"],
            "item_ids": done["item_ids"],
            "product_ids": done["product_ids"],
        })
        assert response.json()["reverted"] == 2

        session.expire_all()
        assert set((await lines(session)).values()) == {(None, None)}
        assert (await session.get(Product, product["id"])).category_id is None

    async def test_undo_leaves_a_line_moved_on_since(self, auth_client, session):
        dairy = await category(session, "Tejtermék")
        other = await session.scalar(select(Category.id).where(Category.name == "Egyéb"))
        await _receipt_with(session, ["Tej"])
        done = (await file(auth_client, "Tej", str(dairy))).json()
        item = await session.scalar(select(ReceiptItem))
        item.category_id = other
        await session.commit()

        await auth_client.post("/api/categorise/undo", json={
            "category_id": done["category_id"], "item_ids": done["item_ids"],
        })
        session.expire_all()
        assert (await session.scalar(select(ReceiptItem.category_id))) == other

    async def test_it_needs_a_login(self, client):
        assert (await client.get("/api/categorise/uncategorised")).status_code == 401
