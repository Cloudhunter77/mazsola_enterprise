"""Filing what nothing could categorise, a receipt at a time.

Under test: the screen - a receipt with blank lines appears once, filing it fills those
blanks and nothing else, a shop can be told to always mean a category, and all of it can be
taken back exactly - and the learning rule, which had been described in `categorise.py` and
never run: a category you set on a line by hand reaches the lines that normalise the same
way, while a whole receipt filed at once teaches nothing about the names on it.
"""

from __future__ import annotations

from sqlalchemy import select

from app.models import Category, ReceiptItem
from app.services.categorise import categorise_stored
from app.services.seed import seed_categories
from tests.conftest import requires_db
from tests.test_matching import _receipt_with

pytestmark = requires_db


async def category(session, name: str):
    await seed_categories(session)
    await session.commit()
    return await session.scalar(select(Category.id).where(Category.name == name))


async def file(client, receipt, category_id, remember_shop: bool = False):
    """File a receipt under a category through the API, as the screen does."""
    return await client.post("/api/categorise/receipt", json={
        "receipt_id": str(receipt.id),
        "category_id": str(category_id),
        "remember_shop": remember_shop,
    })


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
    async def test_a_receipt_with_blank_lines_is_listed_once(self, auth_client, session):
        await category(session, "Egyéb")
        await _receipt_with(session, ["Kenyér", "ZORBA", "ZORBA"])

        body = (await auth_client.get("/api/categorise/receipts")).json()
        assert len(body) == 1
        row = body[0]
        assert row["uncategorised_lines"] == 3 and row["item_lines"] == 3
        assert float(row["uncategorised_amount"]) == 1500
        assert set(row["names"]) == {"Kenyér", "ZORBA"}

    async def test_most_uncategorised_money_comes_first(self, auth_client, session):
        await category(session, "Egyéb")
        small = await _receipt_with(session, ["ZORBA"])
        big = await _receipt_with(session, ["ZORBA", "ZORBA", "ZORBA"])

        body = (await auth_client.get("/api/categorise/receipts")).json()
        assert [row["receipt_id"] for row in body] == [str(big.id), str(small.id)]

    async def test_a_filed_receipt_leaves_the_list(self, auth_client, session):
        other = await category(session, "Egyéb")
        receipt = await _receipt_with(session, ["ZORBA"])
        await file(auth_client, receipt, other)

        assert (await auth_client.get("/api/categorise/receipts")).json() == []


class TestFilingAReceipt:
    async def test_every_blank_line_follows_and_nothing_else_moves(self, auth_client, session):
        """A mixed shop keeps what the keywords already filed."""
        other = await category(session, "Egyéb")
        dairy = await session.scalar(select(Category.id).where(Category.name == "Tejtermék"))
        receipt = await _receipt_with(session, ["Tej", "ZORBA", "KAPAX"])
        milk = await session.scalar(select(ReceiptItem).where(ReceiptItem.raw_name == "Tej"))
        milk.category_id, milk.category_source = dairy, "keyword"
        await session.commit()

        body = (await file(auth_client, receipt, other)).json()
        assert body["lines"] == 2 and body["spread"] == 0
        assert await lines(session) == {
            "Tej": (dairy, "keyword"),
            "ZORBA": (other, "receipt"),
            "KAPAX": (other, "receipt"),
        }

    async def test_a_filed_receipt_teaches_no_names(self, session, auth_client):
        """One choice for a whole supermarket shop must not become a rule for each item."""
        food = await category(session, "Élelmiszer")
        first = await _receipt_with(session, ["ZORBA"])
        await _receipt_with(session, ["zorba"])
        await file(auth_client, first, food)

        await categorise_stored(session)
        await session.commit()
        assert (await lines(session))["zorba"] == (None, None)

    async def test_an_unknown_category_is_refused(self, auth_client, session):
        import uuid

        receipt = await _receipt_with(session, ["ZORBA"])
        assert (await file(auth_client, receipt, uuid.uuid4())).status_code == 404


class TestRememberingTheShop:
    async def test_the_shops_other_receipts_follow_at_once(self, auth_client, session):
        eating_out = await category(session, "Vendéglátás")
        first = await _receipt_with(session, ["Gulyásleves"])
        await _receipt_with(session, ["Rántott sajt", "Limonádé"])

        body = (await file(auth_client, first, eating_out, remember_shop=True)).json()
        assert body["lines"] == 1 and body["spread"] == 2
        assert {cat for cat, _ in (await lines(session)).values()} == {eating_out}

    async def test_future_receipts_follow_too(self, auth_client, session):
        eating_out = await category(session, "Vendéglátás")
        first = await _receipt_with(session, ["Gulyásleves"])
        await file(auth_client, first, eating_out, remember_shop=True)

        await _receipt_with(session, ["Palacsinta"])  # the next visit
        await categorise_stored(session)
        await session.commit()
        assert (await lines(session))["Palacsinta"] == (eating_out, "merchant")

    async def test_your_shop_beats_a_keyword(self, auth_client, session):
        """In a café filed as Vendéglátás, a tejeskávé is not a dairy purchase."""
        eating_out = await category(session, "Vendéglátás")
        first = await _receipt_with(session, ["Croissant"])
        await file(auth_client, first, eating_out, remember_shop=True)

        await _receipt_with(session, ["Tej"])
        await categorise_stored(session)
        await session.commit()
        assert (await lines(session))["Tej"] == (eating_out, "merchant")

    async def test_not_ticking_it_leaves_the_shop_alone(self, auth_client, session):
        eating_out = await category(session, "Vendéglátás")
        first = await _receipt_with(session, ["Gulyásleves"])
        await _receipt_with(session, ["ZORBA"])
        await file(auth_client, first, eating_out)

        assert (await lines(session))["ZORBA"] == (None, None)


class TestTakingItBack:
    async def test_undo_restores_the_lines_and_the_shop(self, auth_client, session):
        from app.models import Merchant

        eating_out = await category(session, "Vendéglátás")
        first = await _receipt_with(session, ["Gulyásleves"])
        await _receipt_with(session, ["Palacsinta"])
        done = (await file(auth_client, first, eating_out, remember_shop=True)).json()

        response = await auth_client.post("/api/categorise/undo", json={
            key: done[key]
            for key in ("category_id", "item_ids", "merchant_id", "previous_default")
        })
        assert response.json()["reverted"] == 2
        assert set((await lines(session)).values()) == {(None, None)}
        assert await session.scalar(select(Merchant.default_category_id)) is None

    async def test_undo_leaves_a_line_moved_on_since(self, auth_client, session):
        eating_out = await category(session, "Vendéglátás")
        other = await session.scalar(select(Category.id).where(Category.name == "Egyéb"))
        receipt = await _receipt_with(session, ["Gulyásleves"])
        done = (await file(auth_client, receipt, eating_out)).json()
        item = await session.scalar(select(ReceiptItem))
        item.category_id, item.category_source = other, "manual"
        await session.commit()

        await auth_client.post("/api/categorise/undo", json={
            "category_id": done["category_id"], "item_ids": done["item_ids"],
        })
        assert (await lines(session))["Gulyásleves"] == (other, "manual")

    async def test_it_needs_a_login(self, client):
        assert (await client.get("/api/categorise/receipts")).status_code == 401
