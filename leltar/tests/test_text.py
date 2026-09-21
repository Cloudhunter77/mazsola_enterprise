"""Folding Hungarian text flat, which is what makes search usable on a phone."""

from __future__ import annotations

from leltar.text import fold, fold_tight, searchable


def test_accents_and_case_come_out_flat():
    assert fold("Fehér Porcelán Bögre") == "feher porcelan bogre"
    assert fold("ŐRLŐ, fűnyíró") == "orlo funyiro"


def test_punctuation_becomes_a_word_boundary_not_a_join():
    """"XY-99" must be findable as "xy 99" and as "xy99" - people type both."""
    assert fold("XY-99") == "xy 99"
    assert fold_tight("XY-99") == "xy99"


def test_nothing_in_nothing_out():
    assert fold(None) == ""
    assert fold("   ") == ""
    assert fold("!!!") == ""


def test_the_haystack_skips_the_fields_an_item_does_not_have():
    assert searchable("Bögre", None, "Zsolnay", "", None) == "bogre zsolnay"
