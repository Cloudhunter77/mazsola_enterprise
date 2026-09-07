"""A Café Frei receipt: two invented lines from below the total, one real item missed.

    PISZTÁCIA-MALNA - PALERMOI      1 490   A00
    ÖSSZESEN:                       4 820 Ft
    BANKKÁRTYA:                     4 820 Ft
    Kóstolta már? Csak ebben a hónapban:
    Bodrum Yaz Áfonyás Iced Latte
    Sorszám: 252

The model billed the advertisement and the queue number as purchases - the queue number at
490 Ft, digits taken from the `1 490` above it - and dropped the PISZTÁCIA-MALNA line that
those digits belonged to. 3180 + 150 + 252 + 490 = 4072 against a printed 4820.

The structural rule that prevents the whole class: the item list ends at ÖSSZESEN, and
nothing below it was bought.
"""

from __future__ import annotations

from app.extraction.hu_rules import classify_line, items_subtotal
from tests.conftest import item


class TestFooterIsNotShopping:
    def test_the_queue_number_is_not_a_purchase(self):
        assert classify_line(item(1, "Sorszám: 252", 490.0)) is None

    def test_the_nav_code_is_not_a_purchase(self):
        assert classify_line(item(1, "NAV ELLENŐRZŐ KÓD:0223B", 223.0)) is None

    def test_card_terminal_furniture_is_not_a_purchase(self):
        for name in ("TERMINAL ID", "TRANZAKCIÓ:0010", "PÉNZTÁROS:102", "KÁRTYASZÁM"):
            assert classify_line(item(1, name, 100.0)) is None, name

    def test_the_keyword_list_stays_narrow_on_purpose(self):
        """`kartya` alone would catch KÁRTYA/CARD - and also a gift card someone bought.

        The keyword list is a safety net for footer lines that are unambiguous. Deciding
        that a line is furniture because of where it sits is the prompt's job, and it can
        see the position; this function only sees a name.
        """
        assert classify_line(item(1, "AJÁNDÉKKÁRTYA", 5000.0)) == "item"

    def test_a_real_drink_is_still_a_purchase(self):
        """The drop list must not swallow the coffee shop's actual menu."""
        for name in ("JEGES MANILA UBE LATTE", "PISZTÁCIA-MALNA - PALERMOI",
                     "LAKTÓZMENTES TEJ (150ML)", "Bodrum Yaz Áfonyás Iced Latte"):
            assert classify_line(item(1, name, 1490.0)) == "item", name

    def test_the_footer_lines_drop_out_of_the_subtotal(self):
        """`Sorszám` was the one that moved the total; the advert had to be caught elsewhere."""
        lines = [
            item(1, "JEGES MANILA UBE LATTE", 3180.0, quantity=2, unit_price=1590.0),
            item(2, "LAKTÓZMENTES TEJ (150ML)", 150.0),
            item(3, "PISZTÁCIA-MALNA - PALERMOI", 1490.0),
            item(4, "Sorszám: 252", 490.0),
        ]
        assert items_subtotal(lines) == 4820, "the printed total"


class TestThePromptSaysWhereItemsEnd:
    """The advert is a real product name with no price - only its position gives it away."""

    def test_it_names_the_boundary(self):
        from app.extraction.prompt import SYSTEM_PROMPT

        assert "The items end at `ÖSSZESEN`" in SYSTEM_PROMPT

    def test_it_shows_the_receipt_that_failed(self):
        from app.extraction.prompt import SYSTEM_PROMPT

        assert "Sorszám: 252" in SYSTEM_PROMPT
        assert "Bodrum Yaz Áfonyás Iced Latte" in SYSTEM_PROMPT
