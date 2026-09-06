"""The extraction contract.

`ExtractedReceipt` is the single interface between *any* extraction engine and the rest of
the app: the Claude extractor produces it via structured output, and a future local OCR
engine only has to produce the same shape. Nothing downstream knows which engine ran.

Every field is required-but-nullable on purpose. Strict JSON-schema output works best when
the model must emit each key explicitly and say `null` when a receipt does not show it,
rather than silently omitting keys.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

LineKindLiteral = Literal["item", "deposit", "discount", "rounding", "fee"]
PaymentLiteral = Literal["cash", "card", "other", "unknown"]


class ExtractedItem(BaseModel):
    line_no: int = Field(description="1-based position of this line on the receipt.")
    raw_name: str = Field(description="The product text exactly as printed, abbreviations intact.")
    quantity: float | None = Field(description="Quantity, e.g. 2 or 0.412. Null if not printed.")
    unit: str | None = Field(description="Unit as printed: db, kg, l, csomag. Null if absent.")
    unit_price: float | None = Field(description="Price per unit, gross (VAT included).")
    gross_amount: float = Field(
        description="Line total in HUF, VAT included. Negative for discounts and rounding."
    )
    vat_code: str | None = Field(
        description="ÁFA collector letter printed beside the amount: A, B, C or AM."
    )
    vat_rate: float | None = Field(description="VAT percent: 27, 18, 5 or 0. Null if unknown.")
    kind: LineKindLiteral = Field(
        description=(
            "item for goods; deposit for betétdíj; discount for kedvezmény/akció reductions; "
            "rounding for the kerekítés line; fee for bag charges and service fees."
        )
    )
    confidence: float = Field(description="0-1 confidence that this line was read correctly.")


class ExtractedVatLine(BaseModel):
    """One row of the ÁFA summary block printed near the bottom of Hungarian receipts."""

    vat_code: str | None = Field(description="Collector letter: A, B, C, AM.")
    vat_rate: float | None = Field(description="Percent for that letter: 27, 18, 5, 0.")
    net: float | None = Field(description="Net (ÁFA alap) for this rate.")
    vat: float | None = Field(description="VAT amount (ÁFA összeg) for this rate.")
    gross: float | None = Field(description="Gross (bruttó) for this rate.")


class ExtractedReceipt(BaseModel):
    merchant_name: str | None = Field(description="Shop or company name as printed.")
    merchant_address: str | None = Field(description="Address line(s), joined with a comma.")
    tax_number: str | None = Field(description="Adószám, format 12345678-1-23.")

    purchased_at: str | None = Field(
        description=(
            "Purchase date and time as ISO 8601 'YYYY-MM-DDTHH:MM:SS' (or 'YYYY-MM-DD' when no "
            "time is printed). Hungarian receipts print 2026.09.01. 14:32 - convert it."
        )
    )
    receipt_no: str | None = Field(description="Nyugtaszám / bizonylatszám.")
    nav_ap_code: str | None = Field(description="AP code from the till, e.g. 'AP A12345678'.")
    payment_method: PaymentLiteral = Field(description="How it was paid.")

    currency: str = Field(description="ISO code, almost always HUF.")
    total_gross: float | None = Field(
        description="Final amount actually paid (ÖSSZESEN / FIZETENDŐ)."
    )
    total_printed: str | None = Field(
        description=(
            "The ÖSSZESEN / FIZETENDŐ amount copied character for character as printed, "
            "including any spaces inside the number, e.g. '9 927' or '12 480'. "
            "Transcribe what you see; do not convert or tidy it."
        )
    )
    total_net: float | None = Field(description="Sum of net amounts, if the ÁFA block prints it.")
    total_vat: float | None = Field(description="Sum of VAT amounts, if printed.")
    rounding: float | None = Field(
        description="Kerekítés line value, signed (-2, +3...). 0 or null for card payments."
    )
    discount_total: float | None = Field(
        description="Total of all discount lines, as a positive number."
    )

    items: list[ExtractedItem] = Field(description="Every printed line, in order.")
    vat_summary: list[ExtractedVatLine] = Field(description="The ÁFA summary rows, if printed.")

    confidence: float = Field(description="0-1 overall confidence in this extraction.")
    notes: str | None = Field(
        description="Anything illegible, torn, or ambiguous. Null when the receipt read cleanly."
    )
