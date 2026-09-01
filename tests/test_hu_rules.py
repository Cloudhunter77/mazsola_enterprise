"""Rules that make the difference between a database and a pile of guesses."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.extraction.hu_rules import (
    classify_line,
    items_subtotal,
    parse_purchased_at,
    resolve_vat,
    to_decimal,
    validate,
)
from tests.conftest import build_receipt, item

NOW = datetime(2026, 9, 1, tzinfo=UTC)


class TestAmountParsing:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("1 234,56", Decimal("1234.56")),
            ("1.234", Decimal("1234.00")),
            ("1 234", Decimal("1234.00")),
            ("549", Decimal("549.00")),
            ("-2", Decimal("-2.00")),
            ("1 234 567,89", Decimal("1234567.89")),
            ("3 695 Ft", Decimal("3695.00")),
            (1098.0, Decimal("1098.00")),
            (None, None),
            ("", None),
        ],
    )
    def test_hungarian_number_formats(self, raw, expected):
        assert to_decimal(raw) == expected


class TestDateParsing:
    @pytest.mark.parametrize(
        "raw",
        [
            "2026-08-14T17:22:00",
            "2026-08-14 17:22",
            "2026.08.14. 17:22",
            "2026. 08. 14. 17:22",
            "2026.08.14 17:22",
        ],
    )
    def test_accepts_printed_and_iso_forms(self, raw):
        parsed = parse_purchased_at(raw)
        assert parsed is not None
        assert (parsed.year, parsed.month, parsed.day) == (2026, 8, 14)
        assert parsed.tzinfo is not None, "must be anchored to Europe/Budapest"

    def test_date_only(self):
        parsed = parse_purchased_at("2026.08.14.")
        assert parsed is not None and parsed.hour == 0

    def test_unparsable_returns_none(self):
        assert parse_purchased_at("tegnap") is None
        assert parse_purchased_at(None) is None


class TestLineClassification:
    def test_change_line_is_dropped(self):
        # The most common failure mode: change handed back read as a purchase.
        assert classify_line(item(9, "VISSZAJÁRÓ", 1305.0)) is None

    @pytest.mark.parametrize(
        "name", ["KÉSZPÉNZ", "BANKKÁRTYA", "ÖSSZESEN", "Ön ma megtakarított", "PONTEGYENLEG"]
    )
    def test_payment_and_summary_lines_are_dropped(self, name):
        assert classify_line(item(9, name, 100.0)) is None

    def test_accent_stripped_ocr_still_matches(self):
        assert classify_line(item(9, "VISSZAJARO", 1305.0)) is None

    @pytest.mark.parametrize(
        ("name", "expected"),
        [
            ("BETÉTDÍJ", "deposit"),
            ("KEDVEZMÉNY", "discount"),
            ("KEREKÍTÉS", "rounding"),
            ("REKLÁMSZATYOR", "fee"),
        ],
    )
    def test_keyword_kinds(self, name, expected):
        assert classify_line(item(9, name, 50.0, kind="item")) == expected

    def test_unknown_name_trusts_the_engine(self):
        assert classify_line(item(9, "TRAPPISTA SAJT", 900.0, kind="item")) == "item"


class TestVatResolution:
    @pytest.mark.parametrize(
        ("code", "rate", "expected"),
        [
            ("A", 27, Decimal("27")),
            ("B", None, Decimal("18")),
            ("C", None, Decimal("5")),
            ("AM", None, Decimal("0")),
            ("A", 99, Decimal("27")),  # nonsense rate falls back to the letter
            (None, 27, Decimal("27")),
            (None, None, None),
        ],
    )
    def test_letter_and_percent_reconciled(self, code, rate, expected):
        assert resolve_vat(code, rate)[1] == expected


class TestBalance:
    def test_realistic_receipt_balances(self, receipt):
        result = validate(receipt, now=NOW)
        assert result.ok, f"unexpected review reasons: {result.reasons}"
        assert result.computed_total == Decimal("3595.00")

    def test_subtotal_excludes_rounding_and_negates_discounts(self, receipt):
        # 1098 + 100 + 247 + 1452 + 900 - 200 = 3597; rounding is added separately.
        assert items_subtotal(receipt.items) == Decimal("3597.00")

    def test_missed_line_is_caught(self, receipt):
        receipt.items = [i for i in receipt.items if i.line_no != 5]  # drop the cheese
        result = validate(receipt, now=NOW)
        assert "items_total_mismatch" in result.reasons

    def test_change_counted_as_item_is_caught(self, receipt):
        receipt.items.append(item(8, "VISSZAJÁRÓ", 1305.0))
        # The keyword net drops it, so the receipt still balances - that is the point.
        assert validate(receipt, now=NOW).ok

    def test_one_forint_drift_is_tolerated(self, receipt):
        receipt.total_gross = 3596.0
        assert validate(receipt, now=NOW).ok

    def test_three_forint_drift_is_not(self, receipt):
        receipt.total_gross = 3598.0
        assert "items_total_mismatch" in validate(receipt, now=NOW).reasons


class TestSanityChecks:
    def test_future_date_flagged(self, receipt):
        receipt.purchased_at = "2027-01-01T10:00:00"
        assert "future_date" in validate(receipt, now=NOW).reasons

    def test_rounding_beyond_two_forint_flagged(self, receipt):
        receipt.rounding = -7.0
        assert "rounding_out_of_range" in validate(receipt, now=NOW).reasons

    def test_missing_merchant_flagged(self, receipt):
        receipt.merchant_name = None
        assert "missing_merchant" in validate(receipt, now=NOW).reasons

    def test_low_confidence_routes_to_review(self, receipt):
        receipt.confidence = 0.4
        assert "low_confidence" in validate(receipt, now=NOW).reasons

    def test_vat_row_arithmetic_checked(self, receipt):
        receipt.vat_summary[0].vat = 999.0
        assert "vat_row_mismatch" in validate(receipt, now=NOW).reasons

    def test_empty_receipt_flags_everything_important(self):
        blank = build_receipt(
            items=[], vat_summary=[], total_gross=None, merchant_name=None,
            purchased_at=None, rounding=None, discount_total=None,
        )
        reasons = validate(blank, now=NOW).reasons
        assert {"missing_total", "no_items", "missing_merchant",
                "missing_or_unparsable_date"} <= set(reasons)
