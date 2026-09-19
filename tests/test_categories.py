"""Giving a line a category without being asked.

The rules are cheap, instant and explainable, which is why they are rules and not a model
call. What makes them safe to run unattended is not their accuracy - they will be wrong
sometimes - but that every assignment records which rule made it. A mis-categorised line
is the quiet kind of wrong: your Élelmiszer total is off and no screen looks broken. Knowing
a category came from a keyword means you can find every line that keyword touched and fix
them together, instead of discovering one at a time for a year.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.services.categorise import (
    KEYWORD_CATEGORIES,
    MERCHANT_CATEGORIES,
    SOURCE_STRENGTH,
    categorise_stored,
    category_for_merchant,
    category_for_name,
)
from app.services.seed import CATEGORY_TREE
from tests.conftest import requires_db


def _every_category_name() -> set[str]:
    names = set()
    for parent, children in CATEGORY_TREE:
        names.add(parent)
        names.update(children)
    return names


class TestTheTableIsWellFormed:
    def test_every_keyword_points_at_a_real_category(self):
        """A rule naming a category that does not exist silently does nothing at all."""
        known = _every_category_name()
        for pattern, category in KEYWORD_CATEGORIES:
            assert category in known, f"{pattern!r} -> {category!r} is not in the tree"

    def test_every_shop_points_at_a_real_category(self):
        known = _every_category_name()
        for shop, category in MERCHANT_CATEGORIES.items():
            assert category in known, f"{shop} -> {category!r} is not in the tree"

    def test_no_supermarket_has_a_default(self):
        """They sell food, bin bags and socks. A grocery default would be plausibly wrong.

        Plausibly wrong is the worst kind here: it looks like a categorised receipt.
        """
        for chain in ("Tesco", "Lidl", "Aldi", "Spar", "Penny Market", "Auchan", "CBA"):
            assert category_for_merchant(chain) is None, chain


class TestReadingAHungarianName:
    @pytest.mark.parametrize(
        "name, category",
        [
            # Every one of these is a line off a real receipt in this project's export.
            ("UHT tej 2,8% 1l", "Tejtermék"),
            ("Tejföl 20% 330g", "Tejtermék"),
            ("kovászos cipó", "Pékáru"),
            ("Vöröshagyma lédig", "Zöldség és gyümölcs"),
            ("Burgonya p. ldg", "Zöldség és gyümölcs"),
            ("Choceur tejcs.300g", "Édesség és snack"),
            ("Premium Ketchup", "Konzerv és készétel"),
            ("Teekanne tea 20f", "Kávé és tea"),
            ("Soproni Meggy 0,5l", "Alkohol"),
            ("Club-Mate Cola 0,33", "Üdítő"),
            ("PAPÍRSZALVÉTA LERSSO", "Papíráru"),
            ("FÜRDŐSZOBAI SZEMETES", "Konyhai eszköz"),
            ("SUPRAX 200MG FILMTABL. 10X", "Gyógyszer és vitamin"),
            ("Visszaváltási díj", "Betétdíj"),
            ("Szállítási díj", "Szolgáltatás"),
        ],
    )
    def test_it_reads_a_real_line(self, name, category):
        assert category_for_name(name) == category

    def test_a_short_word_does_not_match_inside_another(self):
        """`só` matched the end of `LERSSO` and filed napkins under groceries."""
        assert category_for_name("PAPÍRSZALVÉTA LERSSO") != "Alapvető élelmiszer"
        assert category_for_name("presszó kávé") == "Kávé és tea"

    def test_the_specific_rule_wins_over_the_word_it_contains(self):
        """`tejföl` and `tejcsokoládé` both contain `tej`, and neither is milk."""
        assert category_for_name("Tejföl 20%") == "Tejtermék"
        assert category_for_name("tejcsoki") == "Édesség és snack"
        assert category_for_name("UHT tej 1l") == "Tejtermék"

    def test_an_unknown_name_is_left_alone(self):
        """Guessing would be worse than a visible blank."""
        assert category_for_name("MY BLUE BAG 18X36X30") is None
        assert category_for_name("Nol taska") is None


class TestTheShopItself:
    @pytest.mark.parametrize(
        "shop, category",
        [
            ("Rossmann", "Drogéria"),
            ("dm", "Drogéria"),
            ("MOL", "Üzemanyag"),
            ("JYSK", "Lakás és otthon"),
            ("C&A", "Ruházat"),
            # Not a chain but a kind of shop, so matched on the name.
            ("Nővér Gyógyszertár", "Gyógyszer és vitamin"),
            ("Café Frei", "Vendéglátás"),
        ],
    )
    def test_a_single_purpose_shop_implies_its_category(self, shop, category):
        assert category_for_merchant(shop) == category


class TestTheOrderOfAuthority:
    def test_manual_outranks_everything(self):
        """A rule may improve on a weaker rule; none may overrule a person."""
        assert SOURCE_STRENGTH["manual"] == max(SOURCE_STRENGTH.values())

    def test_a_guess_from_the_shop_is_the_weakest(self):
        assert SOURCE_STRENGTH["merchant"] == min(SOURCE_STRENGTH.values())
        assert SOURCE_STRENGTH["merchant"] < SOURCE_STRENGTH["keyword"]


@requires_db
class TestApplyingItToStoredLines:
    async def _receipt(self, session, shop: str, *names: str):
        from datetime import UTC, datetime

        from app.services.manual import create_manual_receipt
        from app.services.seed import seed_categories

        await seed_categories(session)
        receipt = await create_manual_receipt(
            session,
            merchant_name=shop,
            purchased_at=datetime(2026, 9, 1, 12, 0, tzinfo=UTC),
            items=[{"raw_name": name, "gross_amount": 500} for name in names],
        )
        await session.commit()
        return receipt

    async def _rows(self, session):
        from app.models import Category, ReceiptItem

        return (
            await session.execute(
                select(ReceiptItem.raw_name, Category.name, ReceiptItem.category_source)
                .outerjoin(Category, ReceiptItem.category_id == Category.id)
                .order_by(ReceiptItem.line_no)
            )
        ).all()

    async def test_a_keyword_categorises_a_line(self, session):
        await self._receipt(session, "Aldi", "UHT tej 2,8% 1l")
        await categorise_stored(session)
        await session.commit()

        (name, category, source), = await self._rows(session)
        assert category == "Tejtermék"
        assert source == "keyword"

    async def test_the_shop_covers_what_the_keywords_miss(self, session):
        """`MY BLUE BAG` means nothing; bought at JYSK it is still homeware."""
        await self._receipt(session, "JYSK", "MY BLUE BAG 18X36X30")
        await categorise_stored(session)
        await session.commit()

        (_, category, source), = await self._rows(session)
        assert category == "Lakás és otthon"
        assert source == "merchant"

    async def test_a_keyword_beats_the_shop(self, session):
        """A named product is better evidence than the building it was bought in."""
        await self._receipt(session, "Rossmann", "Fogkrém 75ml", "Valami ismeretlen")
        await categorise_stored(session)
        await session.commit()

        rows = {name: (category, source) for name, category, source in await self._rows(session)}
        assert rows["Fogkrém 75ml"] == ("Testápolás", "keyword")
        assert rows["Valami ismeretlen"] == ("Drogéria", "merchant")

    async def test_a_supermarket_line_it_cannot_read_is_left_blank(self, session):
        """Better a visible gap than a plausible wrong answer."""
        await self._receipt(session, "Tesco", "Nol taska")
        await categorise_stored(session)
        await session.commit()

        (_, category, source), = await self._rows(session)
        assert category is None and source is None

    async def test_it_never_overwrites_a_category_already_there(self, session):
        from app.models import Category, ReceiptItem

        await self._receipt(session, "Aldi", "UHT tej 2,8% 1l")
        chosen = await session.scalar(select(Category).where(Category.name == "Alkohol"))
        line = (await session.scalars(select(ReceiptItem))).one()
        line.category_id = chosen.id
        line.category_source = "manual"
        await session.commit()

        await categorise_stored(session)
        await session.commit()

        (_, category, source), = await self._rows(session)
        assert (category, source) == ("Alkohol", "manual"), "a person said so"

    async def test_running_it_twice_changes_nothing(self, session):
        await self._receipt(session, "Aldi", "UHT tej 2,8% 1l", "kovászos cipó")
        first = await categorise_stored(session)
        await session.commit()
        second = await categorise_stored(session)
        await session.commit()

        assert sum(first.values()) == 2
        assert second == {}, "safe to run on a timer"


@requires_db
class TestTheUnambiguousOnesNeverReachYou:
    """"Too many products to match" is the problem; only ambiguity deserves a question."""

    async def _receipt(self, session, *names: str):
        from datetime import UTC, datetime

        from app.services.manual import create_manual_receipt

        receipt = await create_manual_receipt(
            session,
            merchant_name="Aldi",
            purchased_at=datetime(2026, 9, 1, 12, 0, tzinfo=UTC),
            items=[{"raw_name": name, "gross_amount": 500} for name in names],
        )
        await session.commit()
        return receipt

    async def test_an_unambiguous_line_becomes_a_product_by_itself(self, session):
        from app.models import Product, ReceiptItem
        from app.services.autolink import autocreate_exact_groups

        await self._receipt(session, "Kovászos cipó 500g")
        assert await autocreate_exact_groups(session) == 1
        await session.commit()

        product = (await session.scalars(select(Product))).one()
        assert product.canonical_name == "Kovászos cipó 500g"
        line = (await session.scalars(select(ReceiptItem))).one()
        assert line.product_id == product.id

    async def test_two_spellings_that_normalise_alike_make_one_product(self, session):
        from app.models import Product
        from app.services.autolink import autocreate_exact_groups

        await self._receipt(session, "PEPSI 1,5L", "Pepsi  1.5 L")
        assert await autocreate_exact_groups(session) == 1
        await session.commit()

        assert len((await session.scalars(select(Product))).all()) == 1

    async def test_a_merely_similar_pair_is_still_asked_about(self, session):
        """Yellow is where a person knows something the rules do not."""
        from app.models import Product
        from app.services.autolink import autocreate_exact_groups

        await self._receipt(session, "PEPSI 1,5L", "Pepsi Cola 1.5 l")
        assert await autocreate_exact_groups(session) == 0
        await session.commit()

        assert (await session.scalars(select(Product))).all() == []

    async def test_different_sizes_never_merge(self, session):
        from app.models import Product
        from app.services.autolink import autocreate_exact_groups

        await self._receipt(session, "PEPSI 1,5L", "PEPSI 0,5L")
        await autocreate_exact_groups(session)
        await session.commit()

        names = {p.canonical_name for p in (await session.scalars(select(Product))).all()}
        assert len(names) == 2, "1,5 l and 0,5 l are different products"

    async def test_it_leaves_a_line_you_already_mapped_alone(self, session):
        from app.models import Product, ReceiptItem
        from app.services.autolink import autocreate_exact_groups

        await self._receipt(session, "Kovászos cipó 500g")
        mine = Product(canonical_name="Az én kenyerem")
        session.add(mine)
        await session.flush()
        line = (await session.scalars(select(ReceiptItem))).one()
        line.product_id = mine.id
        await session.commit()

        assert await autocreate_exact_groups(session) == 0

    async def test_running_it_twice_creates_nothing_new(self, session):
        from app.services.autolink import autocreate_exact_groups

        await self._receipt(session, "Kovászos cipó 500g", "Tej 1l")
        assert await autocreate_exact_groups(session) == 2
        await session.commit()
        assert await autocreate_exact_groups(session) == 0
