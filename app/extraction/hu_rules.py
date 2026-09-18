"""Hungarian receipt normalisation and validation.

Runs on every extraction regardless of engine. Two jobs:

1. **Normalise** - amounts to `Decimal`, dates to timezone-aware `datetime`, ÁFA letters to
   rates, and a keyword safety net that re-labels lines the engine mis-classified.
2. **Validate** - arithmetic that must hold on a real receipt. Anything that does not balance
   is not silently accepted: it sets a review reason and the receipt goes to the review screen
   rather than into your statistics as a wrong number.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from app.schemas.extraction import ExtractedItem, ExtractedReceipt

BUDAPEST = ZoneInfo("Europe/Budapest")

# Hungarian receipts print a collector letter per line; the legend is at the bottom of the
# receipt. These are the conventional meanings and act as a fallback when the model reads a
# letter but not the legend.
VAT_CODE_RATES: dict[str, Decimal] = {
    "A": Decimal("27"),
    "B": Decimal("18"),
    "C": Decimal("5"),
    "AM": Decimal("0"),
    "D": Decimal("0"),
}
VALID_VAT_RATES = {Decimal("27"), Decimal("18"), Decimal("5"), Decimal("0")}

# Amounts must balance to within one forint. Line-level rounding on weighed goods and the
# occasional half-forint unit price make an exact match unrealistic.
TOLERANCE = Decimal("1.00")

# Cash payments round to the nearest 5 Ft, so the kerekítés line is always in [-2, +2].
MAX_ROUNDING = Decimal("2")

# Above this, a total is far more likely to be a misread digit than a real grocery run.
IMPLAUSIBLE_TOTAL = Decimal("2000000")


def _fold(text: str) -> str:
    """Lowercase and strip accents, so matching survives OCR dropping diacritics."""
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


# Lines that are not purchases at all. `visszajaro` (change handed back) tops the list because
# treating it as an item is the single most common receipt-parsing error.
DROP_KEYWORDS = (
    "visszajaro", "keszpenz", "bankkartya", "osszesen", "fizetendo", "fizetendo osszeg",
    "megtakarit", "on ma megtakaritott", "pontegyenleg", "gyujtott pont",
    "hitelkartya",
    "adoszam", "nyugtaszam", "koszonjuk", "viszontlatasra", "afa osszesen", "vasarlas",
    # Footer furniture. A Café Frei receipt printed "Sorszám: 252" below the total and the
    # model billed it as a 490 Ft purchase - the queue number as a line item, priced with
    # digits borrowed from the item above.
    "sorszam", "nav ellenorzo", "ellenorzo kod", "ap kod", "terminal", "kartyaszam",
    "tranzakcio", "penztaros", "kassza", "bizonylatszam", "kostolta", "koszonjuk a",
)
DEPOSIT_KEYWORDS = ("betetdij", "betet dij", "repohar", "visszavalthato", "palack")
DISCOUNT_KEYWORDS = ("kedvezmeny", "akcio", "engedmeny", "kupon", "levonas", "torzsvasarlo")
ROUNDING_KEYWORDS = ("kerekit",)
FEE_KEYWORDS = ("szatyor", "reklamszatyor", "taska", "zacsko", "csomagolas", "szallitas")

_DATE_PATTERNS = (
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%dT%H:%M",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%d",
    "%Y.%m.%d. %H:%M:%S",
    "%Y.%m.%d. %H:%M",
    "%Y.%m.%d %H:%M",
    "%Y.%m.%d.",
    "%Y.%m.%d",
    "%Y/%m/%d %H:%M",
    "%Y/%m/%d",
)


def to_decimal(value: float | int | str | Decimal | None) -> Decimal | None:
    """Convert an engine-supplied number to money. Handles `1 234,56` as well as `1234.56`."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value.quantize(Decimal("0.01"))
    if isinstance(value, str):
        cleaned = value.replace(" ", " ").strip()
        cleaned = re.sub(r"(?<=\d)[ .](?=\d{3}\b)", "", cleaned)  # thousands separators
        cleaned = cleaned.replace(",", ".")
        cleaned = re.sub(r"[^0-9.\-]", "", cleaned)
        if not cleaned or cleaned in {"-", ".", "-."}:
            return None
        value = cleaned
    try:
        return Decimal(str(value)).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        return None


def parse_purchased_at(raw: str | None) -> datetime | None:
    """Parse a purchase timestamp and anchor it to Europe/Budapest."""
    if not raw:
        return None
    text = raw.strip().replace(" ", " ")
    text = re.sub(r"(\d{4})\.\s*(\d{1,2})\.\s*(\d{1,2})\.?", r"\1.\2.\3", text)
    text = re.sub(r"\s+", " ", text).strip()

    for pattern in _DATE_PATTERNS:
        try:
            naive = datetime.strptime(text, pattern)
        except ValueError:
            continue
        return naive.replace(tzinfo=BUDAPEST)

    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=BUDAPEST)


# Aldi, Spar, JYSK, Tiger and C&A all print a store-internal ÁFA category code at the start
# of each line: `C00`, `B00`, `A00`, `E00`. It is not the product's name and it is not the
# collector letter - Aldi puts `C00` on both soup vegetables and a chocolate bar, which cannot
# both be 5%.
#
# Left in place it does real damage twice over. In `raw_name` it means `COO Choceur
# tejcs.300g` never matches the same chocolate bought anywhere else, so the product never
# accumulates a price history - which is the thing the app is for. Read as a collector letter
# it puts 5% VAT on a plastic bag.
#
# A small vision model reads the zeros as letters, so the codes arrive spelled `COO`, `BDD`
# and `800` as often as `C00`. The pattern below accepts all of those.
CATEGORY_CODE = re.compile(r"^[A-Za-z0-9][0OoDd]{2}\s+(?=\S)")

# A unit right after the token means it was a size, not a code: `100 g fokhagyma` starts with
# something that looks exactly like a category code and is not one.
SIZE_UNITS = frozenset({"g", "dkg", "kg", "ml", "cl", "dl", "l", "db", "x"})


def strip_category_code(raw_name: str) -> str:
    """Remove a leading store ÁFA category code, so the name is just the product.

    Conservative on purpose: it only strips a three-character leading token, only when what
    follows is not a unit of measure, and never when that would leave nothing behind. A
    wrongly stripped name is a silently mismatched product, which is the failure this exists
    to prevent - so when in doubt it leaves the name alone.
    """
    match = CATEGORY_CODE.match(raw_name)
    if not match:
        return raw_name

    remainder = raw_name[match.end():]
    first_word = remainder.split(maxsplit=1)[0].lower().rstrip(".,")
    if first_word in SIZE_UNITS:
        return raw_name
    return remainder


def resolve_vat(
    code: str | None, rate: float | Decimal | None
) -> tuple[str | None, Decimal | None]:
    """Reconcile the printed ÁFA letter with the percent, preferring an explicit valid rate."""
    normalized_code = code.strip().upper() if code else None
    resolved_rate = to_decimal(rate)

    if resolved_rate is not None:
        resolved_rate = resolved_rate.quantize(Decimal("0.01"))
        if resolved_rate.to_integral_value() in VALID_VAT_RATES:
            resolved_rate = resolved_rate.to_integral_value()
        else:
            resolved_rate = None

    if resolved_rate is None and normalized_code in VAT_CODE_RATES:
        resolved_rate = VAT_CODE_RATES[normalized_code]

    return normalized_code, resolved_rate


def classify_line(item: ExtractedItem) -> str | None:
    """Keyword safety net over the engine's own `kind`. None means 'drop this line'."""
    name = _fold(item.raw_name)

    if any(keyword in name for keyword in DROP_KEYWORDS):
        return None
    if any(keyword in name for keyword in ROUNDING_KEYWORDS):
        return "rounding"
    if any(keyword in name for keyword in DEPOSIT_KEYWORDS):
        return "deposit"
    if any(keyword in name for keyword in DISCOUNT_KEYWORDS):
        return "discount"
    if any(keyword in name for keyword in FEE_KEYWORDS):
        return "fee"

    # No keyword matched: trust what the engine said.
    return item.kind


@dataclass(slots=True)
class Validation:
    """The verdict on one extraction."""

    reasons: list[str] = field(default_factory=list)
    computed_total: Decimal | None = None
    stated_total: Decimal | None = None

    @property
    def ok(self) -> bool:
        return not self.reasons

    def flag(self, reason: str) -> None:
        if reason not in self.reasons:
            self.reasons.append(reason)


def drop_captions(items: list[ExtractedItem]) -> list[ExtractedItem]:
    """Remove lines the receipt never gave an amount to.

    A bracketed label like `[AKCIÓ          ]` names the promotion behind the discount line
    above it; it is not a line and has no amount. Told merely not to emit it, a model has
    emitted it anyway - first as 0 Ft, and then, once the prompt said never to emit a zero,
    with an amount borrowed from the line above. That second version is the dangerous one,
    because zeros do not move a total and -500 does.

    So the model is asked to copy each line's printed amount, and a line that reports none
    is dropped here regardless of the number it invented. Engines that do not fill
    `amount_printed` at all are left alone - the rule needs at least one line to have used
    it before it can read silence as meaning anything.
    """
    if not any(item.amount_printed for item in items):
        return items
    return [item for item in items if item.amount_printed]


def items_subtotal(items: list[ExtractedItem]) -> Decimal:
    """Sum of what was actually charged, using each line's own sign."""
    total = Decimal("0.00")
    for item in items:
        kind = classify_line(item)
        if kind is None or kind == "rounding":
            continue
        amount = to_decimal(item.gross_amount) or Decimal("0.00")
        if kind == "discount":
            amount = -abs(amount)
        total += amount
    return total.quantize(Decimal("0.01"))


def validate(receipt: ExtractedReceipt, *, now: datetime | None = None) -> Validation:
    """Check a receipt against the arithmetic a genuine Hungarian receipt must satisfy."""
    result = Validation()
    now = now or datetime.now(UTC)

    total = to_decimal(receipt.total_gross)
    result.stated_total = total

    if total is None:
        result.flag("missing_total")
    elif total <= 0:
        result.flag("non_positive_total")
    elif total > IMPLAUSIBLE_TOTAL:
        result.flag("implausible_total")

    if not receipt.items:
        result.flag("no_items")

    if not receipt.merchant_name:
        result.flag("missing_merchant")

    purchased_at = parse_purchased_at(receipt.purchased_at)
    if purchased_at is None:
        result.flag("missing_or_unparsable_date")
    elif purchased_at > now + timedelta(days=1):
        result.flag("future_date")
    elif purchased_at < now - timedelta(days=365 * 10):
        result.flag("implausibly_old_date")

    rounding = to_decimal(receipt.rounding) or Decimal("0.00")

    # A cash total in Hungary is always a multiple of 5 Ft - that is the entire point of
    # the kerekítés line. A cash total that is not is a misread digit, every time.
    if receipt.payment_method == "cash" and total is not None and total % 5 != 0:
        result.flag("cash_total_not_multiple_of_five")

    if abs(rounding) > MAX_ROUNDING:
        # Cash rounding to the nearest 5 Ft can never exceed 2 Ft; a bigger value means the
        # engine put something else on this line.
        result.flag("rounding_out_of_range")

    # The arithmetic below is a *relative* check: it compares the lines against the total.
    # That makes it blind to an error that scales every number on the receipt the same way -
    # and a dropped thousands separator does exactly that. A receipt reading `8 999` as 999
    # with a total of `8 999` read as 999 balances perfectly and is wrong by a factor of nine.
    #
    # So cross-check the number against the model's own character-by-character transcription
    # of the same figure. Copying and converting are different jobs; when the conversion drops
    # a digit group the copy still has it, and the two stop agreeing.
    printed = to_decimal(receipt.total_printed)
    if printed is not None and total is not None and abs(printed - total) > TOLERANCE:
        result.flag("total_transcription_mismatch")

    # A caption the model emitted anyway is not a reason to send the receipt for review -
    # it is simply not a line, so it is dropped before the arithmetic rather than counted
    # and then complained about.
    receipt.items = drop_captions(receipt.items)

    # Each line's number against its own transcription, for the same reason the total has
    # one: copying and converting are different jobs, and only the conversion drops digits.
    for item in receipt.items:
        printed = to_decimal(item.amount_printed)
        stated = to_decimal(item.gross_amount)
        if printed is None or stated is None:
            continue
        # Compared unsigned: a discount prints as `-4 500` on some tills and `4 500` on
        # others, and the sign is the app's business, not the transcription's.
        if abs(abs(printed) - abs(stated)) > TOLERANCE:
            result.flag("line_transcription_mismatch")
            break

    subtotal = items_subtotal(receipt.items)
    computed = (subtotal + rounding).quantize(Decimal("0.01"))
    result.computed_total = computed

    if total is not None and abs(computed - total) > TOLERANCE:
        result.flag("items_total_mismatch")

    # Cross-check the ÁFA block against the stated total.
    if receipt.vat_summary:
        vat_gross = sum(
            (to_decimal(row.gross) or Decimal("0.00") for row in receipt.vat_summary),
            Decimal("0.00"),
        )
        vat_tolerance = TOLERANCE + abs(rounding)
        if total is not None and vat_gross > 0 and abs(vat_gross - total) > vat_tolerance:
            result.flag("vat_summary_mismatch")

        for row in receipt.vat_summary:
            net, vat, gross = to_decimal(row.net), to_decimal(row.vat), to_decimal(row.gross)
            if net is not None and vat is not None and gross is not None:
                if abs((net + vat) - gross) > TOLERANCE:
                    result.flag("vat_row_mismatch")

    for item in receipt.items:
        _, rate = resolve_vat(item.vat_code, item.vat_rate)
        if classify_line(item) == "item" and rate is None:
            result.flag("missing_vat_rate")
            break

    if receipt.confidence < 0.75:
        result.flag("low_confidence")
    elif any(i.confidence < 0.6 for i in receipt.items):
        result.flag("low_confidence_line")

    return result
