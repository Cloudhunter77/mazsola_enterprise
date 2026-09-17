"""Deciding when two printed line names are the same product.

The feature exists because typing every product by hand is tedious. The risk it carries is
the opposite of tedium: a wrong link is silent. It merges two products' price histories,
and nothing on any screen looks broken - the numbers are just quietly wrong for months. So
the tests here care less about matching aggressively than about never matching two things
that are not the same, and about only one case being automatic.
"""

from __future__ import annotations

from collections import Counter
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models import Product, ProductAlias
from app.services.catalog import link_product, resolve_product
from app.services.matching import band, cluster, fingerprint, parse_name, similarity
from tests.conftest import requires_db


def score(left: str, right: str) -> float:
    return similarity(parse_name(left), parse_name(right))


class TestReadingAName:
    @pytest.mark.parametrize(
        "raw, size, unit",
        [
            ("PEPSI 1,5L", Decimal("1.5"), "l"),
            ("Pepsi Cola 1.5 l", Decimal("1.5"), "l"),
            ("PEPSI COLA 1500ML", Decimal("1.5"), "l"),
            ("TEJFOL 20% 330G", Decimal("0.33"), "kg"),
            ("SAJT TRAPPISTA 1KG", Decimal("1"), "kg"),
            ("KENYER", None, None),
        ],
    )
    def test_the_package_size_is_normalised_to_a_base_unit(self, raw, size, unit):
        parts = parse_name(raw)
        assert parts.size == size
        assert parts.unit == unit

    def test_a_count_is_not_a_package_size(self):
        """`2 DB` says how many you bought, not which product it is."""
        assert parse_name("COCA COLA 2 DB").size is None

    def test_accents_case_and_word_order_do_not_matter(self):
        assert fingerprint("Tej 2,8% 1 l UHT") == fingerprint("TEJ UHT 1L 2,8%")

    def test_the_size_text_is_not_also_counted_as_a_word(self):
        assert "1" not in parse_name("PEPSI 1,5L").tokens


class TestSizeDecidesIdentity:
    """The rule agreed up front: different packaging is a different product."""

    def test_two_sizes_of_the_same_drink_never_match(self):
        assert score("PEPSI 1,5L", "PEPSI 0,5L") == 0.0

    def test_the_same_size_written_differently_does_match(self):
        assert score("PEPSI 1,5L", "PEPSI COLA 1500ML") >= 0.72

    def test_matching_sizes_do_not_make_unrelated_things_match(self):
        assert band(score("TEJ 1L", "NARANCSLE 1L")) == "red"

    def test_a_missing_size_on_one_side_is_not_fatal(self):
        assert score("PEPSI COLA", "PEPSI COLA 1,5L") > 0.5


class TestTheBands:
    def test_only_an_identical_reading_is_green(self):
        assert band(score("TEJ 2,8% 1L UHT", "Tej 2,8% 1 l UHT")) == "green"

    def test_a_longer_name_for_the_same_thing_is_yellow(self):
        """One till prints the brand, another prints brand and product. Ask, do not assume."""
        assert band(score("PEPSI 1,5L", "Pepsi Cola 1.5 l")) == "yellow"

    def test_an_abbreviation_is_yellow_not_green(self):
        assert band(score("COCA COLA ZERO 0,5L", "COCA C.ZERO 0,5L")) == "yellow"

    def test_two_different_products_are_red(self):
        assert band(score("KENYER FEHER 500G", "TEJFOL 20% 330G")) == "red"

    def test_a_near_match_can_never_reach_green(self):
        """Green is what links itself, so nothing uncertain may be scored into it."""
        for left, right in [
            ("PEPSI 1,5L", "Pepsi Cola 1.5 l"),
            ("COCA COLA ZERO 0,5L", "COCA C.ZERO 0,5L"),
            ("TEJ 1L", "TEJ UHT 1L"),
        ]:
            assert score(left, right) < 1.0, (left, right)


class TestGrouping:
    def test_spellings_of_one_drink_land_in_one_group(self):
        groups = cluster(Counter({"PEPSI 1,5L": 5, "Pepsi Cola 1.5 l": 2, "TEJ 1L": 1}))
        pepsi = next(g for g in groups if "PEPSI 1,5L" in g.members)
        assert sorted(pepsi.members) == ["PEPSI 1,5L", "Pepsi Cola 1.5 l"]
        assert pepsi.occurrences == 7

    def test_the_spelling_you_see_most_names_the_group(self):
        groups = cluster(Counter({"PEPSI 1,5L": 2, "Pepsi Cola 1.5 l": 9}))
        assert groups[0].suggested_name == "Pepsi Cola 1.5 l"

    def test_a_group_is_only_as_certain_as_its_weakest_member(self):
        groups = cluster(Counter({"PEPSI 1,5L": 5, "Pepsi Cola 1.5 l": 2}))
        assert groups[0].band == "yellow", "one uncertain member makes the group uncertain"

    def test_different_sizes_stay_in_different_groups(self):
        groups = cluster(Counter({"PEPSI 1,5L": 5, "PEPSI 0,5L": 4}))
        assert len(groups) == 2

    def test_the_most_bought_group_comes_first(self):
        groups = cluster(Counter({"RITKA": 1, "GYAKORI": 9}))
        assert groups[0].suggested_name == "GYAKORI"


async def _receipt_with(session, raw_names: list[str]):
    """A confirmed receipt carrying these line names, so they count as unmapped spending."""
    from datetime import UTC, datetime

    from app.services.manual import create_manual_receipt

    receipt = await create_manual_receipt(
        session,
        merchant_name="Teszt Bolt",
        purchased_at=datetime(2026, 9, 1, 12, 0, tzinfo=UTC),
        items=[{"raw_name": name, "gross_amount": 500} for name in raw_names],
    )
    await session.commit()
    return receipt


@requires_db
class TestAutomaticLinking:
    """Only an exact normalised match links itself. Everything else waits to be confirmed."""

    async def test_another_spelling_of_a_mapped_product_links_itself(self, session):
        product = Product(canonical_name="Pepsi 1,5 l")
        session.add(product)
        await session.flush()
        await link_product(session, product.id, "PEPSI 1,5L", None)
        await session.commit()

        # A different till, a different spelling, the same drink.
        found = await resolve_product(session, "Pepsi  1.5 L", None)
        assert found is not None and found.id == product.id

    async def test_the_new_spelling_is_remembered(self, session):
        product = Product(canonical_name="Pepsi 1,5 l")
        session.add(product)
        await session.flush()
        await link_product(session, product.id, "PEPSI 1,5L", None)
        await session.commit()

        await resolve_product(session, "Pepsi  1.5 L", None)
        await session.commit()

        aliases = {a.raw_name for a in (await session.scalars(select(ProductAlias))).all()}
        assert "Pepsi  1.5 L" in aliases, "learned, so the next receipt is a plain lookup"

    async def test_a_different_size_does_not_link_itself(self, session):
        product = Product(canonical_name="Pepsi 1,5 l")
        session.add(product)
        await session.flush()
        await link_product(session, product.id, "PEPSI 1,5L", None)
        await session.commit()

        assert await resolve_product(session, "PEPSI 0,5L", None) is None

    async def test_a_merely_similar_name_does_not_link_itself(self, session):
        """Yellow is a suggestion. Taking it automatically is the silent-corruption case."""
        product = Product(canonical_name="Pepsi 1,5 l")
        session.add(product)
        await session.flush()
        await link_product(session, product.id, "PEPSI 1,5L", None)
        await session.commit()

        assert await resolve_product(session, "Pepsi Cola Zero 1,5L", None) is None

    async def test_an_ambiguous_fingerprint_links_to_neither(self, session):
        """Two products normalising the same way means the rule cannot separate them."""
        first, second = Product(canonical_name="Alma A"), Product(canonical_name="Alma B")
        session.add_all([first, second])
        await session.flush()
        await link_product(session, first.id, "ALMA", None)
        await link_product(session, second.id, "Alma", merchant_id=None)
        await session.commit()

        # Both aliases normalise to the same key but point at different products.
        assert await resolve_product(session, "alma", None) is None


@requires_db
class TestTheApi:
    async def test_unmapped_lines_come_back_grouped(self, auth_client, session):
        await _receipt_with(session, ["PEPSI 1,5L", "Pepsi Cola 1.5 l", "KENYER"])

        body = (await auth_client.get("/api/suggestions")).json()
        assert body["unmapped_lines"] == 3
        names = {g["suggested_name"] for g in body["groups"]}
        assert "KENYER" in names

    async def test_confirming_a_group_backfills_what_is_already_stored(
        self, auth_client, session
    ):
        """Without this, mapping a product would only affect receipts scanned afterwards."""
        from app.models import ReceiptItem
        await _receipt_with(session, ["PEPSI 1,5L", "Pepsi Cola 1.5 l"])

        response = await auth_client.post("/api/suggestions/apply", json={
            "raw_names": ["PEPSI 1,5L", "Pepsi Cola 1.5 l"],
            "canonical_name": "Pepsi 1,5 l",
        })
        assert response.status_code == 201, response.text
        product_id = response.json()["id"]

        session.expire_all()
        linked = (await session.scalars(select(ReceiptItem))).all()
        assert {str(line.product_id) for line in linked} == {product_id}

    async def test_a_confirmed_group_stops_being_suggested(self, auth_client, session):
        await _receipt_with(session, ["PEPSI 1,5L", "Pepsi Cola 1.5 l"])
        await auth_client.post("/api/suggestions/apply", json={
            "raw_names": ["PEPSI 1,5L", "Pepsi Cola 1.5 l"],
            "canonical_name": "Pepsi 1,5 l",
        })

        body = (await auth_client.get("/api/suggestions")).json()
        assert body["unmapped_lines"] == 0

    async def test_the_package_size_is_taken_from_the_name(self, auth_client, session):
        await _receipt_with(session, ["PEPSI 1,5L"])
        product = (await auth_client.post("/api/suggestions/apply", json={
            "raw_names": ["PEPSI 1,5L"], "canonical_name": "Pepsi 1,5 l",
        })).json()

        assert product["package_size"] == 1.5
        assert product["package_unit"] == "l"

    async def test_it_needs_a_login(self, client):
        assert (await client.get("/api/suggestions")).status_code == 401


@requires_db
class TestLinkingWhatIsAlreadyStored:
    """Recognising a product must reach backwards, not only forwards.

    `resolve_product` runs on the way in, so it only ever helps the next receipt. Everything
    bought before the mapping existed was stored with no product, and nothing would look at
    those rows again - which would mean a year of shopping stays unmapped while every new
    receipt lands correctly.
    """

    async def test_an_old_line_gets_the_product_mapped_later(self, session):
        from app.models import ReceiptItem
        from app.services.autolink import autolink_stored

        receipt = await _receipt_with(session, ["PEPSI 1500ML"])

        # The mapping arrives afterwards, spelled the way a different till prints it.
        product = Product(canonical_name="Pepsi 1,5 l")
        session.add(product)
        await session.flush()
        await link_product(session, product.id, "PEPSI 1,5L", None)
        await session.commit()

        assert await autolink_stored(session) == 1
        await session.commit()

        line = (await session.scalars(
            select(ReceiptItem).where(ReceiptItem.receipt_id == receipt.id)
        )).one()
        assert line.product_id == product.id

    async def test_it_leaves_a_merely_similar_line_alone(self, session):
        """Yellow waits for you. Taking it automatically is the silent-corruption case."""
        from app.models import ReceiptItem
        from app.services.autolink import autolink_stored

        await _receipt_with(session, ["Pepsi Cola Zero 1,5L"])
        product = Product(canonical_name="Pepsi 1,5 l")
        session.add(product)
        await session.flush()
        await link_product(session, product.id, "PEPSI 1,5L", None)
        await session.commit()

        assert await autolink_stored(session) == 0
        await session.commit()
        line = (await session.scalars(select(ReceiptItem))).one()
        assert line.product_id is None

    async def test_it_does_not_touch_a_line_you_already_mapped(self, session):
        from app.models import ReceiptItem
        from app.services.autolink import autolink_stored

        await _receipt_with(session, ["PEPSI 1,5L"])
        mine, other = Product(canonical_name="Az én termékem"), Product(canonical_name="Másik")
        session.add_all([mine, other])
        await session.flush()
        await link_product(session, other.id, "PEPSI 1,5L", None)

        line = (await session.scalars(select(ReceiptItem))).one()
        line.product_id = mine.id
        await session.commit()

        assert await autolink_stored(session) == 0
        await session.commit()
        session.expire_all()
        line = (await session.scalars(select(ReceiptItem))).one()
        assert line.product_id == mine.id, "a link you made yourself is not ours to change"

    async def test_running_it_twice_changes_nothing_the_second_time(self, session):
        from app.services.autolink import autolink_stored

        await _receipt_with(session, ["PEPSI 1500ML"])
        product = Product(canonical_name="Pepsi 1,5 l")
        session.add(product)
        await session.flush()
        await link_product(session, product.id, "PEPSI 1,5L", None)
        await session.commit()

        assert await autolink_stored(session) == 1
        await session.commit()
        assert await autolink_stored(session) == 0, "the pass must be safe to run on a timer"

    async def test_the_button_reports_what_it_did(self, auth_client, session):
        await _receipt_with(session, ["PEPSI 1500ML"])
        product = Product(canonical_name="Pepsi 1,5 l")
        session.add(product)
        await session.flush()
        await link_product(session, product.id, "PEPSI 1,5L", None)
        await session.commit()

        response = await auth_client.post("/api/suggestions/autolink")
        assert response.status_code == 200, response.text
        assert response.json() == {"linked": 1}

        # And the line has stopped asking to be classified.
        assert (await auth_client.get("/api/suggestions")).json()["unmapped_lines"] == 0

    async def test_the_button_needs_a_login(self, client):
        assert (await client.post("/api/suggestions/autolink")).status_code == 401
