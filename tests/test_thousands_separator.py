"""The dropped-thousands-group failure, from a real Rossmann receipt.

The receipt printed:

    CIKKSZ M:  67960 1 DB X 8 999 Ft
    * POLICE TO BE EXOTI          8 999   C00
    ENGEDMÉNY                    -4 500e  C00
    [AKCIÓ                    ]
    CIKKSZ M:  67960 1 DB X 8 999 Ft
    * POLICE FREETODARE           8 999   C00
    ENGEDMÉNY                    -4 500e  C00
    [AKCIÓ                    ]
    CIKKSZ M:  59028 1 DB X 929 Ft
    VIGO SZ.ZSAK 60L               929    C00
    ÖSSZESEN:                    9 927 Ft

and the model returned 999, -500, 999, -500, 929. Every amount containing a thousands
space lost the group before it; the one amount without a space was read correctly. That is
a parsing error, not an OCR error - the product names came back perfect, and the model's
own note said the text was clearly readable.

What matters here is not that it happened but what catches it. The arithmetic check is a
*relative* one: lines against total. It caught this receipt only because `929` has no space
and so survived, breaking the ratio. On a receipt where every amount carries a separator the
same misreading balances perfectly - see TestTheBlindSpot, which is why `total_printed`
exists.
"""

from __future__ import annotations

from decimal import Decimal

from app.extraction.hu_rules import to_decimal, validate
from tests.conftest import build_receipt, item

# What the receipt actually says.
CORRECT = [
    item(1, "POLICE TO BE EXOTI", 8999.0, unit_price=8999.0, vat_code="C", vat_rate=5),
    item(2, "ENGEDMÉNY", -4500.0, kind="discount", vat_code=None, vat_rate=None),
    item(3, "POLICE FREETODARE", 8999.0, unit_price=8999.0, vat_code="C", vat_rate=5),
    item(4, "ENGEDMÉNY", -4500.0, kind="discount", vat_code=None, vat_rate=None),
    item(5, "VIGO SZ.ZSAK 60L", 929.0, unit_price=929.0, vat_code="C", vat_rate=5),
]

# What came back: the group before each thousands space is gone.
MISREAD = [
    item(1, "POLICE TO BE EXOTI", 999.0, unit_price=999.0, vat_code="C", vat_rate=5),
    item(2, "ENGEDMÉNY", -500.0, kind="discount", vat_code=None, vat_rate=None),
    item(3, "POLICE FREETODARE", 999.0, unit_price=999.0, vat_code="C", vat_rate=5),
    item(4, "ENGEDMÉNY", -500.0, kind="discount", vat_code=None, vat_rate=None),
    item(5, "VIGO SZ.ZSAK 60L", 929.0, unit_price=929.0, vat_code="C", vat_rate=5),
]


def rossmann(**overrides):
    """The Rossmann receipt: card payment, so no rounding line."""
    defaults = dict(
        merchant_name="ROSSMANN MAGYARORSZÁG KFT",
        merchant_address="1138 Budapest, Váci út 178.",
        tax_number="11149769-2-44",
        purchased_at="2026-09-06T10:35:00",
        receipt_no="1512/00009",
        nav_ap_code="AP A27700227",
        payment_method="card",
        total_gross=9927.0,
        total_printed="9 927",
        rounding=0.0,
        discount_total=9000.0,
        items=CORRECT,
        vat_summary=[],
    )
    defaults.update(overrides)
    return build_receipt(**defaults)


class TestTheParser:
    """`to_decimal` was never the problem - it handles all of these. The model was."""

    def test_a_thousands_space_is_not_a_delimiter(self):
        assert to_decimal("8 999") == Decimal("8999.00")
        assert to_decimal("-4 500") == Decimal("-4500.00")
        assert to_decimal("9 927") == Decimal("9927.00")

    def test_a_narrow_no_break_space_counts_too(self):
        """Some tills print U+00A0 between the groups rather than a plain space."""
        assert to_decimal("12 480") == Decimal("12480.00")

    def test_a_dot_separator_is_handled(self):
        assert to_decimal("1.234") == Decimal("1234.00")

    def test_a_comma_is_a_decimal_point(self):
        assert to_decimal("1 234,56") == Decimal("1234.56")

    def test_a_trailing_unit_is_ignored(self):
        assert to_decimal("9 927 Ft") == Decimal("9927.00")


class TestTheRealReceipt:
    def test_read_correctly_it_balances(self):
        verdict = validate(rossmann())
        assert verdict.ok, verdict.reasons
        assert verdict.computed_total == Decimal("9927.00")

    def test_the_misreading_is_caught(self):
        """8999 - 4500 + 8999 - 4500 + 929 = 9927; the misread lines come to 1927."""
        verdict = validate(rossmann(items=MISREAD, discount_total=1000.0))
        assert not verdict.ok
        assert "items_total_mismatch" in verdict.reasons
        assert verdict.computed_total == Decimal("1927.00")

    def test_it_is_caught_even_when_the_total_is_misread_the_same_way(self):
        """The item that has no thousands space is what keeps the two sides from agreeing."""
        verdict = validate(
            rossmann(items=MISREAD, discount_total=1000.0, total_gross=927.0, total_printed="9 927")
        )
        assert not verdict.ok
        assert "items_total_mismatch" in verdict.reasons


class TestTheBlindSpot:
    """The arithmetic check compares lines to a total. It cannot see a uniform error.

    This is the dangerous shape: one item, one total, both carrying a thousands separator,
    both misread the same way. Nothing about the relationship between them is wrong, so a
    receipt off by a factor of nine would have been stored as `parsed`.
    """

    ONE_ITEM = [item(1, "POLICE TO BE EXOTI", 8999.0, unit_price=8999.0)]
    MISREAD_ONE = [item(1, "POLICE TO BE EXOTI", 999.0, unit_price=999.0)]

    def base(self, **overrides):
        defaults = dict(
            payment_method="card", rounding=0.0, discount_total=0.0, vat_summary=[],
        )
        defaults.update(overrides)
        return rossmann(**defaults)

    def test_the_arithmetic_alone_would_pass_a_receipt_that_is_wrong_by_9x(self):
        blind = self.base(
            items=self.MISREAD_ONE, total_gross=999.0,
            total_printed=None,  # nothing to cross-check against
        )
        verdict = validate(blind)
        assert verdict.ok, (
            "this is the point of the test: a uniformly scaled misreading balances, "
            f"but got {verdict.reasons}"
        )

    def test_the_transcription_of_the_total_catches_it(self):
        """Copying the characters and converting them are different jobs, so they disagree."""
        caught = self.base(
            items=self.MISREAD_ONE, total_gross=999.0, total_printed="8 999",
        )
        verdict = validate(caught)
        assert "total_transcription_mismatch" in verdict.reasons

    def test_a_correct_reading_still_passes(self):
        verdict = validate(
            self.base(items=self.ONE_ITEM, total_gross=8999.0, total_printed="8 999")
        )
        assert verdict.ok, verdict.reasons

    def test_a_missing_transcription_is_not_itself_a_problem(self):
        """An engine that cannot supply it must not flag every receipt it reads."""
        verdict = validate(
            self.base(items=self.ONE_ITEM, total_gross=8999.0, total_printed=None)
        )
        assert verdict.ok, verdict.reasons

    def test_an_unparsable_transcription_is_ignored_rather_than_flagged(self):
        verdict = validate(
            self.base(items=self.ONE_ITEM, total_gross=8999.0, total_printed="illegible")
        )
        assert verdict.ok, verdict.reasons


class TestThePrompt:
    """The prompt is the actual fix; these assert the rule is stated, not merely implied."""

    def test_it_shows_the_failing_case_verbatim(self):
        from app.extraction.prompt import SYSTEM_PROMPT

        assert "8 999" in SYSTEM_PROMPT
        assert "1 DB X 8 999 Ft" in SYSTEM_PROMPT, "the layout that caused the misparse"

    def test_it_asks_for_the_total_to_be_transcribed_as_well_as_converted(self):
        from app.extraction.prompt import SYSTEM_PROMPT

        assert "total_printed" in SYSTEM_PROMPT

    def test_it_forbids_emitting_a_bracketed_label_as_a_line(self):
        """`[AKCIÓ    ]` is a caption; it became two 0 Ft discount lines."""
        from app.extraction.prompt import SYSTEM_PROMPT

        assert "[AKCIÓ" in SYSTEM_PROMPT


class TestTheWidthFloor:
    """Capping the longest edge starves a receipt of the dimension that carries legibility.

    Not the cause of the Rossmann misread - the product names came back perfect, so the text
    was legible - but the margin was thinner than it looked, and the deploy guide's advice
    ("MAX_IMAGE_EDGE below 1000 starts to fail") was misleading: for a 1:3 ribbon a 1600px
    long edge already means about 500px of width.
    """

    ROSSMANN = (1200, 3757)  # the photograph that produced the misreading

    def test_a_long_edge_cap_alone_leaves_a_receipt_barely_500px_wide(self):
        from app.extraction.preprocess import target_size

        width, _ = target_size(*self.ROSSMANN, max_edge=1600, min_width=0)
        assert width == 511, "the old behaviour, kept here so the change is visible"

    def test_the_floor_restores_a_readable_width(self):
        from app.extraction.preprocess import target_size

        width, height = target_size(*self.ROSSMANN, max_edge=1600, min_width=800)
        assert width == 800
        assert height > 1600, "the long edge deliberately gives way to the width"

    def test_an_ordinary_photo_is_unaffected(self):
        """The floor must not quietly raise the bill on every receipt."""
        from app.extraction.preprocess import target_size

        for size in [(900, 1600), (1200, 1250), (3000, 4000)]:
            assert target_size(*size, max_edge=1600, min_width=800) == target_size(
                *size, max_edge=1600, min_width=0
            )

    def test_a_low_resolution_photo_is_never_upscaled(self):
        """A floor cannot invent detail the camera did not capture."""
        from app.extraction.preprocess import target_size

        assert target_size(400, 1400, max_edge=1600, min_width=800) == (400, 1400)

    def test_sectioned_capture_needs_no_floor_at_all(self):
        """Three sections of the same receipt are near-square, so the edge cap never bites.

        This is the cheaper answer to the same problem, and the reason multi-part capture
        earns its place beyond just fitting the phone frame.
        """
        from app.extraction.preprocess import estimate_image_tokens, target_size

        whole = target_size(1200, 3757, max_edge=1600, min_width=800)
        section = target_size(1200, 1252, max_edge=1600, min_width=800)

        assert section[0] == 1200, "a section keeps its full width untouched"
        assert section[0] > whole[0]
        # Three sections cost more than one squeezed image, but not wildly so.
        assert estimate_image_tokens(*section) * 3 < estimate_image_tokens(*whole) * 3
