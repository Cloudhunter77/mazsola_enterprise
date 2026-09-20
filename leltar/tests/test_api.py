"""The HTTP surface, against a real database."""

from __future__ import annotations

from tests.conftest import TEST_PASSWORD, requires_db

pytestmark = requires_db


# --- auth --------------------------------------------------------------------
async def test_the_api_is_closed_without_credentials(client):
    assert (await client.get("/api/items")).status_code == 401
    assert (await client.get("/api/stats/summary")).status_code == 401


async def test_a_wrong_password_is_refused_and_a_right_one_sets_a_cookie(client):
    assert (await client.post("/api/auth/login", json={"password": "rossz"})).status_code == 401

    response = await client.post("/api/auth/login", json={"password": TEST_PASSWORD})
    assert response.status_code == 200
    assert response.json()["authenticated"] is True
    # The cookie now stands in for the API key on every later call.
    assert (await client.get("/api/items")).status_code == 200


async def test_the_spa_shell_is_served_without_authentication(client):
    """The login screen itself cannot require a login."""
    response = await client.get("/valami/ismeretlen/utvonal")
    assert response.status_code in (200, 404)  # 404 only when the SPA is not built


# --- upload and review -------------------------------------------------------
async def test_uploading_a_photo_queues_it(seeded_client, item_photo):
    response = await seeded_client.post(
        "/api/photos", files={"file": ("polc.jpg", item_photo, "image/jpeg")}
    )
    assert response.status_code == 202
    body = response.json()
    assert body["queued"] == 1
    assert body["duplicates"] == 0
    assert body["photos"][0]["status"] == "pending"

    again = await seeded_client.post(
        "/api/photos", files={"file": ("polc.jpg", item_photo, "image/jpeg")}
    )
    assert again.json()["duplicates"] == 1


async def test_several_photos_in_one_request_are_several_photos(seeded_client, item_photo):
    import io

    from PIL import Image

    def jpeg(colour):
        buffer = io.BytesIO()
        Image.new("RGB", (800, 600), colour).save(buffer, format="JPEG")
        return buffer.getvalue()

    response = await seeded_client.post(
        "/api/photos",
        files=[
            ("file", ("a.jpg", jpeg((10, 20, 30)), "image/jpeg")),
            ("file", ("b.jpg", jpeg((200, 100, 50)), "image/jpeg")),
        ],
    )
    assert response.status_code == 202
    assert response.json()["queued"] == 2
    assert len((await seeded_client.get("/api/photos")).json()) == 2


async def test_a_photo_that_is_not_an_image_is_a_400(seeded_client):
    response = await seeded_client.post(
        "/api/photos", files={"file": ("nem-kep.txt", b"hello", "text/plain")}
    )
    assert response.status_code == 400


async def test_the_image_can_be_fetched_back(seeded_client, item_photo):
    upload = await seeded_client.post(
        "/api/photos", files={"file": ("polc.jpg", item_photo, "image/jpeg")}
    )
    photo_id = upload.json()["photos"][0]["id"]

    response = await seeded_client.get(f"/api/photos/{photo_id}/image")
    assert response.status_code == 200
    assert response.content == item_photo


# --- items -------------------------------------------------------------------
async def test_typing_in_an_item_stores_it_confirmed(seeded_client):
    places = (await seeded_client.get("/api/places")).json()
    categories = (await seeded_client.get("/api/categories")).json()

    response = await seeded_client.post(
        "/api/items",
        json={
            "name": "Makita akkus fúró",
            "place_id": places[0]["id"],
            "category_id": next(c["id"] for c in categories if c["slug"] == "szerszam"),
            "value_low": 30000,
            "value_high": 50000,
            "quantity": 1,
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "confirmed"
    assert body["source"] == "manual"
    # The midpoint is computed, not asked for.
    assert float(body["estimated_value"]) == 40000.0
    assert body["place_path"] == places[0]["path"]


async def test_editing_the_name_marks_the_suggestion_as_corrected(seeded_client, session):
    from leltar.models import Item, ItemStatus

    item = Item(name="bögre", suggested_name="bögre", status=ItemStatus.DRAFT.value)
    session.add(item)
    await session.commit()

    unchanged = await seeded_client.patch(f"/api/items/{item.id}", json={"name": "Bögre"})
    assert unchanged.json()["edited"] is False  # same word, different capital

    corrected = await seeded_client.patch(
        f"/api/items/{item.id}", json={"name": "fehér porcelán bögre"}
    )
    assert corrected.json()["edited"] is True
    assert corrected.json()["suggested_name"] == "bögre"


async def test_editing_the_value_range_moves_the_midpoint(seeded_client, session):
    from leltar.models import Item

    item = Item(name="szék", value_low=1000, value_high=3000, estimated_value=2000)
    session.add(item)
    await session.commit()

    response = await seeded_client.patch(
        f"/api/items/{item.id}", json={"value_low": 5000, "value_high": 9000}
    )
    assert float(response.json()["estimated_value"]) == 7000.0


async def test_an_explicit_value_survives_a_range_edit(seeded_client, session):
    """"I know what this is worth" must win over the midpoint arithmetic."""
    from leltar.models import Item

    item = Item(name="óra", value_low=1000, value_high=3000)
    session.add(item)
    await session.commit()

    response = await seeded_client.patch(
        f"/api/items/{item.id}",
        json={"value_low": 5000, "value_high": 9000, "estimated_value": 8500},
    )
    assert float(response.json()["estimated_value"]) == 8500.0


async def test_confirming_every_draft_of_a_photo_closes_its_review(
    seeded_client, session, item_photo
):
    from leltar.models import Item, ItemStatus, Photo, PhotoStatus

    photo = Photo(path="/tmp/x.jpg", sha256="a" * 64, status=PhotoStatus.NEEDS_REVIEW.value)
    session.add(photo)
    await session.flush()
    session.add_all([
        Item(photo_id=photo.id, name="bögre", suggested_name="bögre"),
        Item(photo_id=photo.id, name="tányér", suggested_name="tányér"),
        Item(
            photo_id=photo.id,
            name="kés",
            suggested_name="kés",
            status=ItemStatus.REJECTED.value,
        ),
    ])
    await session.commit()

    response = await seeded_client.post(f"/api/items/confirm-photo/{photo.id}")
    assert response.status_code == 200
    assert len(response.json()) == 2  # the rejected one is left alone

    detail = (await seeded_client.get(f"/api/photos/{photo.id}")).json()
    assert detail["status"] == "reviewed"
    assert detail["draft_count"] == 0


async def test_searching_matches_name_brand_and_serial(seeded_client, session):
    from leltar.models import Item, ItemStatus

    session.add_all([
        Item(name="konyhai mérleg", brand="Soehnle", status=ItemStatus.CONFIRMED.value),
        Item(name="porszívó", serial_number="XY-99", status=ItemStatus.CONFIRMED.value),
    ])
    await session.commit()

    assert len((await seeded_client.get("/api/items?q=mérleg")).json()) == 1
    assert len((await seeded_client.get("/api/items?q=Soehnle")).json()) == 1
    assert len((await seeded_client.get("/api/items?q=XY-99")).json()) == 1
    assert len((await seeded_client.get("/api/items?q=nincs-ilyen")).json()) == 0


async def test_the_csv_export_holds_the_confirmed_inventory_only(seeded_client, session):
    from leltar.models import Item, ItemStatus

    session.add_all([
        Item(name="régi biciklim", status=ItemStatus.CONFIRMED.value, quantity=1),
        Item(name="bizonytalan tárgy", status=ItemStatus.DRAFT.value),
    ])
    await session.commit()

    response = await seeded_client.get("/api/items/export.csv")
    assert response.status_code == 200
    body = response.text
    assert body.startswith("﻿")  # Excel needs the BOM to read the accents
    assert "régi biciklim" in body
    assert "bizonytalan tárgy" not in body


async def test_deleting_a_photo_keeps_the_items_you_confirmed(seeded_client, session):
    from leltar.models import Item, ItemStatus, Photo

    photo = Photo(path="/tmp/gone.jpg", sha256="b" * 64)
    session.add(photo)
    await session.flush()
    session.add_all([
        Item(photo_id=photo.id, name="megtartott szék", status=ItemStatus.CONFIRMED.value),
        Item(photo_id=photo.id, name="tipp", status=ItemStatus.DRAFT.value),
    ])
    await session.commit()

    assert (await seeded_client.delete(f"/api/photos/{photo.id}")).status_code == 204

    names = [row["name"] for row in (await seeded_client.get("/api/items")).json()]
    assert names == ["megtartott szék"]


# --- places ------------------------------------------------------------------
async def test_places_nest_and_report_their_full_path(seeded_client):
    garage = (
        await seeded_client.post("/api/places", json={"name": "Garázs", "kind": "building"})
    ).json()
    shelf = (
        await seeded_client.post(
            "/api/places",
            json={"name": "Fém polc", "kind": "storage", "parent_id": garage["id"]},
        )
    ).json()
    assert shelf["path"] == "Garázs › Fém polc"


async def test_a_place_cannot_become_its_own_ancestor(seeded_client):
    parent = (await seeded_client.post("/api/places", json={"name": "Pince"})).json()
    child = (
        await seeded_client.post(
            "/api/places", json={"name": "Állvány", "parent_id": parent["id"]}
        )
    ).json()

    response = await seeded_client.patch(
        f"/api/places/{parent['id']}", json={"parent_id": child["id"]}
    )
    assert response.status_code == 400


async def test_a_place_with_things_in_it_is_not_deleted(seeded_client, session):
    from leltar.models import Item, ItemStatus

    place = (await seeded_client.post("/api/places", json={"name": "Műhely"})).json()
    session.add(
        Item(name="satu", place_id=place["id"], status=ItemStatus.CONFIRMED.value)
    )
    await session.commit()

    response = await seeded_client.delete(f"/api/places/{place['id']}")
    assert response.status_code == 409
    assert "tárgyak" in response.json()["detail"]


async def test_an_empty_place_is_deleted(seeded_client):
    place = (await seeded_client.post("/api/places", json={"name": "Ideiglenes"})).json()
    assert (await seeded_client.delete(f"/api/places/{place['id']}")).status_code == 204


# --- catalogue and system ----------------------------------------------------
async def test_the_category_list_matches_the_one_the_prompt_offers(seeded_client):
    from leltar.extraction.categories import SLUGS

    slugs = {row["slug"] for row in (await seeded_client.get("/api/categories")).json()}
    assert slugs == set(SLUGS)


async def test_the_system_endpoint_reports_the_build_and_the_queue(seeded_client):
    body = (await seeded_client.get("/api/system")).json()
    assert body["identifier"] == "stub"
    assert body["worker_enabled"] is False
    assert set(body["photos"]) == {"total", "pending", "needs_review", "failed"}
    assert set(body["schema"]) == {"expected", "applied", "up_to_date"}


async def test_health_needs_no_credentials(client):
    response = await client.get("/health")
    assert response.status_code in (200, 503)
    assert "version" in response.json()


async def test_an_empty_place_parameter_means_no_place(seeded_client, item_photo):
    """A phone shortcut with no room chosen sends `?place_id=`; that is not an error."""
    response = await seeded_client.post(
        "/api/photos?place_id=&source=shortcut",
        files={"file": ("polc.jpg", item_photo, "image/jpeg")},
    )
    assert response.status_code == 202
    assert (await seeded_client.get("/api/items?place_id=")).status_code == 200


async def test_a_malformed_place_parameter_is_still_rejected(seeded_client):
    assert (await seeded_client.get("/api/items?place_id=nem-uuid")).status_code == 422
