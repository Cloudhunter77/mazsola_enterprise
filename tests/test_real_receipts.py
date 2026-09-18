"""Regressions taken from receipts that were read wrong in the field.

Every case here is a line the app actually got wrong on a real photograph, found by
exporting the receipts that were never confirmed and comparing each reading against the
paper it came from. They are kept as tests rather than fixed and forgotten because the
extraction engine is deliberately a cheap one: the defence against a small model is a set
of rules that hold whatever it returns, and a rule with no test is a rule that quietly
stops holding.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.extraction.hu_rules import strip_category_code
from app.extraction.prompt import SYSTEM_PROMPT
from app.schemas.extraction import ExtractedReceipt


class TestTheShopsOwnCategoryCode:
    """Aldi, Spar, JYSK, Tiger and C&A print an internal ÁFA code before the product name.

    Two separate harms: in the name it starts a second price history for a product you
    already track, and read as a collector letter it puts 5% VAT on a carrier bag.
    """

    @pytest.mark.parametrize(
        "printed, product",
        [
            # Exactly as the model returned them - it reads the narrow zeros as letters.
            ("COO Choceur tejcs.300g", "Choceur tejcs.300g"),
            ("BDD kovászos cipó", "kovászos cipó"),
            ("800 Maretti Bruschette chips 70g fokh.", "Maretti Bruschette chips 70g fokh."),
            ("A00 DORITHRICIN ERDEI GYUMOLCS", "DORITHRICIN ERDEI GYUMOLCS"),
            ("E00 SUPRAX 200MG FILMTABL. 10X", "SUPRAX 200MG FILMTABL. 10X"),
            ("C00 Leveszöldség 1kg", "Leveszöldség 1kg"),
        ],
    )
    def test_the_code_is_not_part_of_the_name(self, printed, product):
        assert strip_category_code(printed) == product

    @pytest.mark.parametrize(
        "name",
        [
            "American Cookies",
            "Club-Mate Cola 0,33",
            "MY BLUE BAG 18X36X30",
            "JUTALÉK",
            "Passata 500 g",
            "Fagy.Pizza 2x",
        ],
    )
    def test_an_ordinary_name_is_left_alone(self, name):
        assert strip_category_code(name) == name

    @pytest.mark.parametrize("name", ["100 g fokhagyma", "500 ml tej", "250 dkg valami"])
    def test_a_size_is_never_mistaken_for_a_code(self, name):
        """`100 g` opens exactly like a category code. Stripping it would rename the product."""
        assert strip_category_code(name) == name

    def test_a_bare_code_is_left_alone(self):
        """Nothing follows it, so there is no product name to recover - do not blank the line."""
        assert strip_category_code("C00") == "C00"

    def test_the_same_product_from_two_tills_now_matches(self):
        """The point of all of it: one product, one price history."""
        from app.services.matching import fingerprint

        aldi = strip_category_code("COO Choceur tejcs.300g")
        spar = strip_category_code("Choceur tejcs. 300g")
        assert fingerprint(aldi) == fingerprint(spar)


class TestThePromptDoesNotHandOutAnswers:
    def test_it_no_longer_carries_a_specimen_ap_code(self):
        """A model copied this example onto two invoices that had no AP code at all.

        An identifier is the worst field to illustrate with a sample: an invented one is
        indistinguishable from a real one on the screen.
        """
        assert "A12345678" not in SYSTEM_PROMPT

        schema = ExtractedReceipt.model_json_schema()
        description = schema["properties"]["nav_ap_code"]["description"]
        assert "A12345678" not in description
        assert "AP" in description, "the shape still has to be described"

    def test_it_states_the_category_code_rule(self):
        for fragment in ("C00", "category code", "Choceur"):
            assert fragment in SYSTEM_PROMPT, fragment

    def test_it_forbids_rounding_a_weight(self):
        """`0,684 kg` came back as 0.690 and `0,124 kg` as 0.120, both from the tare block."""
        assert "0.684" in SYSTEM_PROMPT or "0,684" in SYSTEM_PROMPT
        assert "Tára" in SYSTEM_PROMPT

    def test_it_says_merchandise_is_an_item(self):
        """A handbag came back as `fee`, which removes it from what you spent on goods."""
        assert "Női táska" in SYSTEM_PROMPT


class TestWhichModelIsRunning:
    def test_the_active_model_follows_the_engine(self):
        """The worker logged the Anthropic model against OpenRouter failures."""
        from app.config import Settings

        common = dict(secret_key="x" * 64, openrouter_model="mistralai/small", 
                      extractor_model="claude-opus-5")
        assert Settings(extractor="openrouter", **common).active_model == "mistralai/small"
        assert Settings(extractor="claude", **common).active_model == "claude-opus-5"


class TestSamplingIsDeterministic:
    def test_the_request_asks_for_the_most_likely_reading(self):
        """Copying digits has one right answer; a default temperature makes it irreproducible."""
        from app.config import Settings
        from app.extraction.openrouter import OpenRouterExtractor

        extractor = OpenRouterExtractor(
            Settings(secret_key="x" * 64, openrouter_api_key="sk-or-test")
        )
        assert extractor._payload(["dGVzdA=="])["temperature"] == 0


def test_the_arithmetic_that_let_these_through_still_holds():
    """Every silently-wrong receipt in the export balanced perfectly.

    Worth stating outright: the totals check cannot catch a misread name, a wrong VAT rate
    or a rounded weight, because none of those change the sum. It is not a quality gate.
    """
    from app.extraction.hu_rules import validate
    from tests.conftest import build_receipt, item

    # The Aldi receipt as it was read: every amount right, every name and rate wrong.
    receipt = build_receipt(
        merchant_name="ALDI MAGYARORSZÁG ÉLELMISZER Bt.",
        total_gross=3454.0,
        total_printed="3 454",
        rounding=0.0,
        discount_total=0.0,
        vat_summary=[],
        items=[
            item(1, "COO Leveszöldség 1kg", 699.0, vat_code="C", vat_rate=5),
            item(2, "COO ZÖV zacskó", 15.0, vat_code="C", vat_rate=5),
            item(3, "COO ZÖV zacskó", 15.0, vat_code="C", vat_rate=5),
            item(4, "COO Voroshagyma lédig", 140.0, vat_code="C", vat_rate=5),
            item(5, "COO Burgonya p. 1dg", 288.0, vat_code="C", vat_rate=5),
            item(6, "COO Eperlevel 200g", 299.0, vat_code="C", vat_rate=5),
            item(7, "BDD kovászos cipó", 549.0, vat_code="A", vat_rate=27),
            item(8, "COO Choceur tejcs.300g", 1449.0, vat_code="A", vat_rate=27),
        ],
    )
    verdict = validate(receipt)
    assert verdict.computed_total == Decimal("3454.00")
    assert "items_total_mismatch" not in verdict.reasons


# --- the same receipt, photographed twice ------------------------------------

from app.extraction.base import ExtractionResult  # noqa: E402
from app.models import Receipt, ReceiptStatus  # noqa: E402
from app.services.persist import persist_extraction  # noqa: E402
from tests.conftest import build_receipt, requires_db  # noqa: E402


def _result(**overrides) -> ExtractionResult:
    return ExtractionResult(
        receipt=build_receipt(**overrides),
        extractor="stub",
        model="stub-1",
        raw={},
    )


async def _store(session, sha: str, **overrides) -> Receipt:
    """Ingest-and-extract one photograph, the way the worker does."""
    receipt = Receipt(image_path=f"/data/{sha}.jpg", image_sha256=sha, source="web")
    session.add(receipt)
    await session.flush()
    await persist_extraction(session, receipt, _result(**overrides))
    await session.commit()
    return receipt


@requires_db
class TestASecondPhotoOfOneReceipt:
    """A retake, a clearer angle, a PDF screenshotted: a different file, the same purchase.

    `image_sha256` only catches the identical bytes arriving twice, so these became two
    receipts and the month was counted twice. It happened to a currency-exchange slip and a
    delivery invoice inside one fortnight.
    """

    async def test_the_second_copy_is_flagged(self, session):
        await _store(session, "a" * 64, receipt_no="2255/00066", total_gross=325.0)
        second = await _store(session, "b" * 64, receipt_no="2255/00066", total_gross=325.0)

        assert second.status == ReceiptStatus.NEEDS_REVIEW.value
        assert "duplicate_receipt" in (second.review_reasons or [])

    async def test_the_first_copy_is_left_alone(self, session):
        """Only the later arrival is questioned; the one already in your statistics stands."""
        first = await _store(session, "a" * 64, receipt_no="2255/00066", total_gross=325.0)
        await _store(session, "b" * 64, receipt_no="2255/00066", total_gross=325.0)

        session.expire_all()
        stored = await session.get(Receipt, first.id)
        assert "duplicate_receipt" not in (stored.review_reasons or [])

    async def test_it_is_flagged_not_refused(self, session):
        """A wrongly refused upload loses a receipt; a wrongly flagged one costs a glance."""
        await _store(session, "a" * 64, receipt_no="2255/00066", total_gross=325.0)
        second = await _store(session, "b" * 64, receipt_no="2255/00066", total_gross=325.0)

        assert second.total_gross == Decimal("325.00")
        assert second.items, "the reading is kept in full, so it can be compared and judged"

    async def test_two_real_receipts_from_one_till_are_not_duplicates(self, session):
        """A nyugtaszám only counts up within one shop, so the amount has to agree too."""
        await _store(session, "a" * 64, receipt_no="2255/00066", total_gross=325.0)
        other = await _store(session, "b" * 64, receipt_no="2255/00067", total_gross=325.0)

        assert "duplicate_receipt" not in (other.review_reasons or [])

    async def test_the_same_number_for_a_different_amount_is_not_a_duplicate(self, session):
        await _store(session, "a" * 64, receipt_no="2255/00066", total_gross=325.0)
        other = await _store(session, "b" * 64, receipt_no="2255/00066", total_gross=1250.0)

        assert "duplicate_receipt" not in (other.review_reasons or [])

    async def test_a_receipt_with_no_number_is_never_called_a_duplicate(self, session):
        """Two small shops both printing nothing must not collapse into one purchase."""
        await _store(session, "a" * 64, receipt_no=None, total_gross=325.0)
        other = await _store(session, "b" * 64, receipt_no=None, total_gross=325.0)

        assert "duplicate_receipt" not in (other.review_reasons or [])

    async def test_reprocessing_a_receipt_does_not_make_it_its_own_duplicate(self, session):
        """Újrafeldolgozás runs persist again over the same row - it must not self-match."""
        receipt = await _store(session, "a" * 64, receipt_no="2255/00066", total_gross=325.0)

        await persist_extraction(
            session, receipt, _result(receipt_no="2255/00066", total_gross=325.0)
        )
        await session.commit()

        assert "duplicate_receipt" not in (receipt.review_reasons or [])
