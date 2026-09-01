"""Merchant and product resolution.

This is the layer that decides whether two receipts are talking about the same shop and
the same product. Get it wrong and the statistics are quietly meaningless - every Tesco
branch becomes its own merchant, and price history never accumulates.
"""

from __future__ import annotations

import pytest
from sqlalchemy import func, select

from app.models import Merchant, MerchantAlias, Product, ProductAlias
from app.services.catalog import (
    canonical_merchant_name,
    fold,
    link_product,
    resolve_merchant,
    resolve_product,
    slugify,
)
from tests.conftest import requires_db


class TestNameNormalisation:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("TESCO-GLOBAL ÁRUHÁZAK ZRT. 2040 BUDAÖRS", "Tesco"),
            ("Tesco Express Budapest", "Tesco"),
            ("TESCO EXTRA 1116 BUDAPEST", "Tesco"),
            ("LIDL MAGYARORSZÁG KERESKEDELMI BT.", "Lidl"),
            ("SPAR MAGYARORSZÁG KFT", "Spar"),
            ("INTERSPAR 1117", "Spar"),
            ("ALDI MAGYARORSZÁG ÉLELMISZER BT.", "Aldi"),
            ("PENNY MARKET KFT.", "Penny Market"),
            ("ROSSMANN MAGYARORSZÁG KFT.", "Rossmann"),
            ("dm-drogerie markt Kft.", "dm"),
            ("MOL NYRT. TÖLTŐÁLLOMÁS", "MOL"),
        ],
    )
    def test_chain_branches_collapse_onto_one_name(self, raw, expected):
        assert canonical_merchant_name(raw) == expected

    def test_an_unknown_shop_is_tidied_but_kept(self):
        assert canonical_merchant_name("Kis Sarki Bolt Kft. 1132 Budapest") == "Kis Sarki Bolt"

    def test_an_unknown_shop_in_capitals_is_title_cased(self):
        assert canonical_merchant_name("ZÖLDSÉGES PIAC BT.") == "Zöldséges Piac"

    def test_a_blank_name_never_produces_an_empty_merchant(self):
        assert canonical_merchant_name("   ") == "Ismeretlen bolt"

    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("Élelmiszer", "elelmiszer"),
            ("Zöldség és gyümölcs", "zoldseg-es-gyumolcs"),
            ("Hús és hal", "hus-es-hal"),
            ("dm", "dm"),
            ("!!!", "ismeretlen"),
        ],
    )
    def test_slugs_are_ascii_and_stable(self, text, expected):
        assert slugify(text) == expected

    def test_folding_survives_missing_accents(self):
        # OCR frequently drops diacritics; matching must not depend on them.
        assert fold("BETÉTDÍJ") == fold("BETETDIJ") == "betetdij"


@requires_db
class TestMerchantResolution:
    async def test_two_branches_become_one_merchant(self, session):
        first = await resolve_merchant(session, "TESCO-GLOBAL ÁRUHÁZAK ZRT. 2040 BUDAÖRS")
        second = await resolve_merchant(session, "TESCO EXPRESS 1052 BUDAPEST")
        await session.commit()

        assert first.id == second.id
        assert first.name == "Tesco"
        assert await session.scalar(select(func.count(Merchant.id))) == 1

    async def test_both_spellings_are_remembered(self, session):
        await resolve_merchant(session, "TESCO-GLOBAL ÁRUHÁZAK ZRT.")
        await resolve_merchant(session, "TESCO EXPRESS 1052 BUDAPEST")
        await session.commit()

        aliases = (await session.scalars(select(MerchantAlias.raw_name))).all()
        assert len(aliases) == 2, "each printed spelling should be learned once"

    async def test_the_same_raw_name_does_not_create_a_second_alias(self, session):
        for _ in range(3):
            await resolve_merchant(session, "SPAR MAGYARORSZÁG KFT")
        await session.commit()
        assert await session.scalar(select(func.count(MerchantAlias.id))) == 1

    async def test_a_shared_tax_number_links_an_unrecognised_spelling(self, session):
        known = await resolve_merchant(session, "Kis Sarki Bolt Kft.", tax_number="12345678-2-44")
        await session.commit()

        # A different printed name, but the same company.
        same = await resolve_merchant(session, "KIS SARKI ÉLELMISZER", tax_number="12345678-2-44")
        await session.commit()
        assert same.id == known.id

    async def test_different_shops_stay_separate(self, session):
        tesco = await resolve_merchant(session, "TESCO-GLOBAL ZRT.")
        lidl = await resolve_merchant(session, "LIDL MAGYARORSZÁG BT.")
        await session.commit()
        assert tesco.id != lidl.id

    async def test_a_missing_merchant_name_resolves_to_nothing(self, session):
        assert await resolve_merchant(session, None) is None
        assert await resolve_merchant(session, "   ") is None

    async def test_an_over_long_name_is_truncated_rather_than_erroring(self, session):
        merchant = await resolve_merchant(session, "A" * 500)
        await session.commit()
        assert merchant is not None


@requires_db
class TestProductResolution:
    @pytest.fixture
    async def product(self, session) -> Product:
        product = Product(canonical_name="Tej 2,8% 1L")
        session.add(product)
        await session.flush()
        return product

    async def test_an_unmapped_line_resolves_to_nothing(self, session, product):
        # Products are created deliberately in review, never guessed from receipt text.
        assert await resolve_product(session, "TEJ 2,8% 1L UHT", None) is None

    async def test_a_learned_mapping_is_reused(self, session, product):
        merchant = await resolve_merchant(session, "TESCO-GLOBAL ZRT.")
        await session.flush()

        await link_product(session, product.id, "TEJ 2,8% 1L UHT", merchant.id)
        await session.commit()

        found = await resolve_product(session, "TEJ 2,8% 1L UHT", merchant.id)
        assert found is not None and found.id == product.id

    async def test_a_shop_specific_mapping_wins_over_a_global_one(self, session):
        generic = Product(canonical_name="Tej (általános)")
        specific = Product(canonical_name="Tesco tej 2,8%")
        session.add_all([generic, specific])
        await session.flush()

        merchant = await resolve_merchant(session, "TESCO-GLOBAL ZRT.")
        await session.flush()

        await link_product(session, generic.id, "TEJ 1L", None)          # anywhere
        await link_product(session, specific.id, "TEJ 1L", merchant.id)  # at Tesco
        await session.commit()

        at_tesco = await resolve_product(session, "TEJ 1L", merchant.id)
        assert at_tesco.id == specific.id, "the shop-specific mapping should win"

    async def test_a_global_mapping_applies_where_there_is_no_specific_one(self, session):
        generic = Product(canonical_name="Tej (általános)")
        session.add(generic)
        await session.flush()
        await link_product(session, generic.id, "TEJ 1L", None)
        await session.commit()

        other = await resolve_merchant(session, "LIDL MAGYARORSZÁG BT.")
        await session.commit()

        found = await resolve_product(session, "TEJ 1L", other.id)
        assert found is not None and found.id == generic.id

    async def test_relinking_updates_rather_than_duplicates(self, session):
        first = Product(canonical_name="Rossz találat")
        second = Product(canonical_name="Helyes termék")
        session.add_all([first, second])
        await session.flush()

        await link_product(session, first.id, "TEJ 1L", None)
        await link_product(session, second.id, "TEJ 1L", None)  # you corrected it
        await session.commit()

        assert await session.scalar(select(func.count(ProductAlias.id))) == 1
        found = await resolve_product(session, "TEJ 1L", None)
        assert found.id == second.id

    async def test_a_blank_line_resolves_to_nothing(self, session):
        assert await resolve_product(session, "", None) is None
        assert await resolve_product(session, "   ", None) is None
