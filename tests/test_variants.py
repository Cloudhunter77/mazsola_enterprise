"""Lactose-free milk is not milk with a word missing.

Reported from the real suggestions screen: five spellings of UHT milk grouped at 87%, two
of them lactose-free. The grouping came from the containment rule - every word of `UHT tej
2.8% 1l` appears in `LM uht tej 2.8% 1l`, which is exactly how a till printing *less* looks.
But the extra word was the one that made it a different product, at a different price, and
confirming the group would have merged two price histories into one that jumps between them.

A variant marker is now part of identity, like a size. And because there are still groups
the rules cannot split, the screen lets you pick which spellings to merge - so the tests
below cover the rule and the choice separately.
"""

from __future__ import annotations

from sqlalchemy import select

from app.models import Product, ProductAlias, ReceiptItem
from app.services.catalog import link_product
from app.services.matching import cluster, fingerprint, parse_name, similarity
from tests.conftest import requires_db
from tests.test_matching import _receipt_with

# The five spellings from the screenshot, with the two lactose-free ones among them.
REGULAR = ["UHT tej 2.8% 1l", "SPAR UHT TEJ 2.8% 1L", "SPAR FF UHT TEJ 2.8% 1L"]
LACTOSE_FREE = ["LM uht tej 2.8% 1l", "BOO LM Uht tej 2,8% 1l"]


class TestTheRule:
    def test_lactose_free_and_regular_never_match(self):
        assert similarity(parse_name("UHT tej 2.8% 1l"), parse_name("LM uht tej 2.8% 1l")) == 0

    def test_the_abbreviation_and_the_full_word_are_the_same_variant(self):
        """A shelf label says laktózmentes where the till says LM."""
        assert fingerprint("LM UHT tej 1l") == fingerprint("Laktózmentes UHT tej 1 l")

    def test_two_lactose_free_spellings_still_find_each_other(self):
        score = similarity(parse_name(LACTOSE_FREE[0]), parse_name(LACTOSE_FREE[1]))
        assert score >= 0.72

    def test_zero_is_not_folded_into_cukormentes(self):
        """Folding two markers together would let an exact link be made on a guess."""
        assert fingerprint("Cola Zero 1,75l") != fingerprint("Cola cukormentes 1,75l")

    def test_a_name_with_no_marker_is_unaffected(self):
        """The ordinary case - a till printing less - must still group."""
        assert similarity(parse_name("PEPSI 1,5L"), parse_name("Pepsi Cola 1.5 l")) >= 0.72

    def test_the_screenshot_splits_into_two_groups(self):
        groups = cluster({name: 1 for name in REGULAR + LACTOSE_FREE})
        by_members = [set(group.members) for group in groups]
        assert set(LACTOSE_FREE) in by_members
        assert not any(set(LACTOSE_FREE) & members and set(REGULAR) & members
                       for members in by_members)


@requires_db
class TestStoredKeysFollowTheRules:
    async def test_an_alias_made_under_the_old_rules_is_found_again(self, session):
        """A key written before the rules changed would otherwise never match again."""
        from app.services.autolink import refresh_fingerprints

        product = Product(canonical_name="Laktózmentes tej 1l")
        session.add(product)
        await session.flush()
        alias = await link_product(session, product.id, "Laktózmentes tej 1l", None)
        alias.fingerprint = "laktozmentes tej|1l"  # what the old rules produced
        await session.commit()

        assert await refresh_fingerprints(session) == 1
        assert alias.fingerprint == fingerprint("LM tej 1l")
        assert await refresh_fingerprints(session) == 0


@requires_db
class TestPickingWhichToMerge:
    async def test_only_the_ticked_spellings_are_linked(self, auth_client, session):
        await _receipt_with(session, ["UHT tej 1l", "SPAR UHT tej 1l", "Pöttyös tej 1l"])

        response = await auth_client.post("/api/suggestions/apply", json={
            "raw_names": ["UHT tej 1l", "SPAR UHT tej 1l"],
            "canonical_name": "UHT tej 1l",
        })
        assert response.status_code == 201, response.text

        lines = (await session.execute(
            select(ReceiptItem.raw_name, ReceiptItem.product_id)
        )).all()
        linked = {name for name, product_id in lines if product_id}
        assert linked == {"UHT tej 1l", "SPAR UHT tej 1l"}

        # The one left out comes back on its own rather than disappearing.
        body = (await auth_client.get("/api/suggestions")).json()
        members = [m for group in body["groups"] for m in group["members"]]
        assert members == ["Pöttyös tej 1l"]

    async def test_the_screen_is_told_which_spellings_are_the_existing_product(
        self, auth_client, session
    ):
        """Without this, unticking the spelling that named a product would still file the
        rest under it."""
        # Bought before the product existed - the case where a group can be offered an
        # existing product at all, since anything arriving later links itself on the way in.
        await _receipt_with(session, ["PEPSI 1.5 L", "Pepsi Cola 1,5 l"])
        product = Product(canonical_name="Pepsi 1,5 l")
        session.add(product)
        await session.flush()
        await link_product(session, product.id, "PEPSI 1,5L", None)
        await session.commit()

        body = (await auth_client.get("/api/suggestions")).json()
        group = next(g for g in body["groups"] if "PEPSI 1.5 L" in g["members"])
        assert group["product_name"] == "Pepsi 1,5 l"
        assert group["product_members"] == ["PEPSI 1.5 L"]
        assert set(group["member_occurrences"]) == set(group["members"])

    async def test_the_old_key_does_not_hide_an_existing_product(self, auth_client, session):
        """Suggestions compute the key from the spelling, so a stale stored one is harmless."""
        await _receipt_with(session, ["LM tej 1l"])
        product = Product(canonical_name="LM tej 1l")
        session.add(product)
        await session.flush()
        alias = await link_product(session, product.id, "Laktózmentes tej 1l", None)
        alias.fingerprint = "stale"
        await session.commit()

        body = (await auth_client.get("/api/suggestions")).json()
        assert body["groups"][0]["product_name"] == "LM tej 1l"
        assert (await session.scalar(select(ProductAlias.fingerprint))) == "stale"


@requires_db
class TestThePriceBesideEachSpelling:
    """A 50% price gap between two near-identical names usually means two products."""

    async def _bought(self, session, items):
        from datetime import UTC, datetime

        from app.services.manual import create_manual_receipt

        await create_manual_receipt(
            session,
            merchant_name="Teszt Bolt",
            purchased_at=datetime(2026, 9, 1, 12, 0, tzinfo=UTC),
            items=items,
        )
        await session.commit()

    async def test_each_spelling_carries_its_typical_price(self, auth_client, session):
        await self._bought(session, [
            {"raw_name": "UHT tej 1l", "gross_amount": 379},
            {"raw_name": "SPAR UHT tej 1l", "gross_amount": 589},
        ])
        body = (await auth_client.get("/api/suggestions")).json()
        group = next(g for g in body["groups"] if "UHT tej 1l" in g["members"])
        assert {k: float(v) for k, v in group["member_prices"].items()} == {
            "UHT tej 1l": 379, "SPAR UHT tej 1l": 589,
        }

    async def test_it_is_the_price_of_one_not_of_the_line(self, auth_client, session):
        """Buying four must not make a spelling look four times dearer."""
        await self._bought(session, [
            {"raw_name": "UHT tej 1l", "gross_amount": 1516, "quantity": 4},
        ])
        body = (await auth_client.get("/api/suggestions")).json()
        assert float(body["groups"][0]["member_prices"]["UHT tej 1l"]) == 379

    async def test_one_sale_price_does_not_move_it(self, auth_client, session):
        """The median, so a single akciós purchase does not make it look like another product."""
        await self._bought(session, [
            {"raw_name": "UHT tej 1l", "gross_amount": 379},
            {"raw_name": "UHT tej 1l", "gross_amount": 389},
            {"raw_name": "UHT tej 1l", "gross_amount": 189},
        ])
        body = (await auth_client.get("/api/suggestions")).json()
        assert float(body["groups"][0]["member_prices"]["UHT tej 1l"]) == 379


@requires_db
class TestManualUnitPrice:
    """Found while adding the price column: a typed line with a quantity stored its whole
    total as the price of one, so price history recorded four litres of milk as one."""

    async def test_the_unit_price_is_the_line_split_by_its_quantity(self, session):
        from datetime import UTC, datetime
        from decimal import Decimal

        from app.services.manual import create_manual_receipt

        await create_manual_receipt(
            session,
            merchant_name="Teszt Bolt",
            purchased_at=datetime(2026, 9, 1, 12, 0, tzinfo=UTC),
            items=[
                {"raw_name": "UHT tej 1l", "gross_amount": 1516, "quantity": 4},
                {"raw_name": "Alma", "gross_amount": 247, "quantity": 0.412, "unit": "kg"},
                {"raw_name": "Kenyér", "gross_amount": 599},
            ],
        )
        await session.commit()

        lines = {
            line.raw_name: line
            for line in (await session.scalars(select(ReceiptItem))).all()
        }
        assert lines["UHT tej 1l"].unit_price == Decimal("379.00")
        assert lines["Alma"].quantity == Decimal("0.412")
        assert lines["Alma"].unit_price == Decimal("599.51")
        assert lines["Kenyér"].unit_price == Decimal("599.00")
