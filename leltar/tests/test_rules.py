"""The rules are what separates a useful draft from a confident fiction. Test them hard."""

from __future__ import annotations

from leltar.extraction.rules import (
    MAX_QUANTITY,
    clean_box,
    clean_object,
    clean_photo,
    is_generic,
    names_match,
    needs_review,
)
from leltar.schemas.identification import Box
from tests.conftest import build_photo, obj


def test_a_clean_photo_needs_no_review(photo):
    cleaned, photo_reasons, object_reasons = clean_photo(photo, max_items=12)
    assert photo_reasons == []
    assert object_reasons == [[], [], []]
    assert needs_review(photo_reasons, object_reasons) is False
    assert len(cleaned.objects) == 3


# --- the evidence rules ------------------------------------------------------
def test_a_brand_that_was_not_legible_is_dropped():
    """The whole point: an inferred brand is indistinguishable from a read one once saved."""
    clean, reasons = clean_object(
        obj("laptop", brand="Dell", product_model="XPS 13", markings_legible=False)
    )
    assert clean.brand is None
    assert clean.product_model is None
    assert "unverifiable_brand" in reasons


def test_a_legible_brand_survives():
    clean, reasons = clean_object(obj("kézi mixer", brand="Bosch", markings_legible=True))
    assert clean.brand == "Bosch"
    assert "unverifiable_brand" not in reasons


def test_a_serial_number_not_read_from_the_image_is_dropped():
    clean, reasons = clean_object(
        obj("router", serial_number="SN-12345678", serial_visible=False)
    )
    assert clean.serial_number is None
    assert "unverifiable_serial" in reasons


def test_a_visible_serial_survives():
    clean, reasons = clean_object(obj("router", serial_number="SN-123", serial_visible=True))
    assert clean.serial_number == "SN-123"
    assert reasons == []


# --- names -------------------------------------------------------------------
def test_generic_names_are_flagged():
    for name in ("tárgy", "dolog", "eszköz", "Ismeretlen", "egy tárgy", "valami"):
        assert is_generic(name), name


def test_real_names_are_not_generic():
    for name in ("fehér porcelán bögre", "Bosch kézi mixer", "kék IKEA tárolódoboz"):
        assert not is_generic(name), name


def test_a_generic_name_routes_to_review():
    _, reasons = clean_object(obj("tárgy"))
    assert "generic_name" in reasons


def test_names_match_ignores_case_accents_and_spacing():
    assert names_match("Fehér  bögre", "feher bogre")
    assert not names_match("fehér bögre", "fehér tányér")
    assert not names_match(None, "bögre")


# --- categories --------------------------------------------------------------
def test_an_unknown_category_falls_back_rather_than_being_trusted():
    clean, reasons = clean_object(obj("bögre", category="konyhai-eszkozok"))
    assert clean.category == "egyeb"
    assert "unknown_category" in reasons


# --- quantity and alternatives ----------------------------------------------
def test_quantity_is_clamped_into_the_possible():
    clean, _ = clean_object(obj(quantity=0))
    assert clean.quantity == 1

    clean, reasons = clean_object(obj(quantity=5000))
    assert clean.quantity == MAX_QUANTITY
    assert "implausible_quantity" in reasons


def test_alternatives_drop_the_name_itself_and_stop_at_three():
    clean, _ = clean_object(
        obj("bögre", alternatives=["Bögre", "csésze", "kávéscsésze", "pohár", "korsó"])
    )
    assert "Bögre" not in clean.alternatives
    assert clean.alternatives == ["csésze", "kávéscsésze", "pohár"]


# --- whole photographs -------------------------------------------------------
def test_an_empty_photo_is_flagged():
    _, photo_reasons, _ = clean_photo(build_photo(objects=[]), max_items=12)
    assert "no_objects" in photo_reasons


def test_too_many_objects_keeps_the_confident_ones():
    crowd = [obj(f"tárgy {index}", confidence=index / 20) for index in range(20)]
    cleaned, photo_reasons, _ = clean_photo(build_photo(objects=crowd), max_items=5)
    assert "too_many_objects" in photo_reasons
    assert len(cleaned.objects) == 5
    assert all(candidate.confidence >= 0.75 for candidate in cleaned.objects)


def test_the_same_thing_named_twice_in_one_photo_is_merged():
    """One bookshelf seen from two angles in one frame is one bookshelf."""
    cleaned, _, object_reasons = clean_photo(
        build_photo(objects=[obj("könyvespolc", quantity=1), obj("Könyvespolc", quantity=3)]),
        max_items=12,
    )
    assert len(cleaned.objects) == 1
    assert cleaned.objects[0].quantity == 3
    assert len(object_reasons) == 1


def test_a_low_confidence_photo_goes_to_review():
    _, photo_reasons, _ = clean_photo(build_photo(confidence=0.2), max_items=12)
    assert "low_confidence" in photo_reasons


def test_one_bad_object_does_not_discard_the_good_ones():
    cleaned, photo_reasons, object_reasons = clean_photo(
        build_photo(objects=[obj("fa vágódeszka"), obj("tárgy", confidence=0.2)]),
        max_items=12,
    )
    assert len(cleaned.objects) == 2
    assert object_reasons[0] == []
    assert set(object_reasons[1]) == {"generic_name", "low_confidence_object"}
    assert needs_review(photo_reasons, object_reasons) is True


def test_cleaning_never_mutates_what_the_model_returned():
    """The raw reply is kept for the costs record, so it must survive the rules unchanged."""
    original = build_photo(objects=[obj("laptop", brand="Dell", markings_legible=False)])
    clean_photo(original, max_items=12)
    assert original.objects[0].brand == "Dell"


# --- boxes -------------------------------------------------------------------
# A box becomes the item's photograph, so a wrong one is not a cosmetic problem: it is a
# picture of the wrong object filed under the right name.
def test_a_good_box_survives():
    clean, reasons = clean_object(obj(box=(100, 200, 400, 600)))
    assert clean.box is not None
    assert (clean.box.x0, clean.box.y0, clean.box.x1, clean.box.y1) == (100, 200, 400, 600)
    assert reasons == []


def test_an_inside_out_box_is_straightened_rather_than_thrown_away():
    clean, reasons = clean_object(obj(box=(400, 600, 100, 200)))
    assert (clean.box.x0, clean.box.x1) == (100, 400)
    assert (clean.box.y0, clean.box.y1) == (200, 600)
    assert reasons == []


def test_a_box_that_runs_past_the_edge_is_clamped():
    """A few thousandths over the edge still located the object correctly."""
    clean, _ = clean_box(Box(x0=0, y0=0, x1=1000, y1=900))
    assert clean is not None
    assert (clean.x0, clean.y1) == (0, 900)


def test_a_pinprick_box_is_dropped_and_said_so():
    _, flagged = clean_box(Box(x0=500, y0=500, x1=505, y1=505))
    assert flagged is True

    clean, reasons = clean_object(obj(box=(500, 500, 505, 505)))
    assert clean.box is None
    assert "unusable_box" in reasons


def test_a_box_around_the_whole_frame_is_not_a_crop():
    """"The object is the photograph" is what an item gets anyway when there is no box."""
    clean, flagged = clean_box(Box(x0=0, y0=0, x1=1000, y1=1000))
    assert clean is None
    assert flagged is True


def test_no_box_is_not_an_error():
    clean, reasons = clean_object(obj(box=None))
    assert clean.box is None
    assert "unusable_box" not in reasons


def test_merging_duplicates_keeps_whichever_copy_had_a_box():
    cleaned, _, _ = clean_photo(
        build_photo(objects=[
            obj("könyvespolc", box=None),
            obj("könyvespolc", box=(100, 100, 400, 800)),
        ]),
        max_items=12,
    )
    assert len(cleaned.objects) == 1
    assert cleaned.objects[0].box is not None
