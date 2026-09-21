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
            "value": 40000,
            "quantity": 1,
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "confirmed"
    assert body["source"] == "manual"
    assert body["place_path"] == places[0]["path"]
    # The one figure the app keeps is the one you typed; nothing guesses it.
    assert float(body["value"]) == 40000.0


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


async def test_searching_ignores_accents_and_word_order(seeded_client, session):
    """Nobody hunting for a bögre on a phone is going to long-press for the umlaut."""
    from leltar.models import Item, ItemStatus

    session.add_all([
        Item(name="fehér porcelán bögre", brand="Zsolnay", status=ItemStatus.CONFIRMED.value),
        Item(name="fekete akkus fúró", brand="Makita", status=ItemStatus.CONFIRMED.value),
        Item(name="kerti fűnyíró", serial_number="XY-99", status=ItemStatus.CONFIRMED.value),
    ])
    await session.commit()

    async def names(query: str) -> list[str]:
        rows = (await seeded_client.get(f"/api/items?q={query}")).json()
        return sorted(row["name"] for row in rows)

    assert await names("bögre") == ["fehér porcelán bögre"]
    assert await names("bogre") == ["fehér porcelán bögre"]       # no accents typed
    assert await names("BÖGRE") == ["fehér porcelán bögre"]       # shouting
    assert await names("funyiro") == ["kerti fűnyíró"]
    assert await names("zsolnay") == ["fehér porcelán bögre"]     # brand
    assert await names("xy-99") == ["kerti fűnyíró"]              # serial

    # Several words narrow rather than widen, in any order.
    assert await names("fekete furo") == ["fekete akkus fúró"]
    assert await names("furo fekete") == ["fekete akkus fúró"]
    assert await names("fekete bogre") == []


async def test_search_follows_an_edited_name(seeded_client, session):
    """The folded column is maintained by the model, so no write path can forget it."""
    from leltar.models import Item, ItemStatus

    item = Item(name="ismeretlen doboz", status=ItemStatus.CONFIRMED.value)
    session.add(item)
    await session.commit()

    await seeded_client.patch(f"/api/items/{item.id}", json={"name": "karácsonyi díszek"})

    assert (await seeded_client.get("/api/items?q=karacsonyi")).json()[0]["name"] == (
        "karácsonyi díszek"
    )
    assert (await seeded_client.get("/api/items?q=doboz")).json() == []


async def test_a_place_means_everything_inside_it(seeded_client, session):
    """Asking for the garage must show what is in the boxes in the garage."""
    from leltar.models import Item, ItemStatus, Place

    garage = Place(name="Hátsó garázs")
    session.add(garage)
    await session.flush()
    shelf = Place(name="Fém polc", parent_id=garage.id)
    session.add(shelf)
    await session.flush()
    box = Place(name="Kék doboz", parent_id=shelf.id)
    session.add(box)
    await session.flush()

    session.add_all([
        Item(name="kerékpár", place_id=garage.id, status=ItemStatus.CONFIRMED.value),
        Item(name="körfűrész", place_id=shelf.id, status=ItemStatus.CONFIRMED.value),
        Item(name="csavarhúzó", place_id=box.id, status=ItemStatus.CONFIRMED.value),
    ])
    await session.commit()

    nested = (await seeded_client.get(f"/api/items?place_id={garage.id}")).json()
    assert len(nested) == 3

    # And the narrow reading is still available for "what is loose in the garage".
    shallow = (await seeded_client.get(f"/api/items?place_id={garage.id}&nested=false")).json()
    assert [row["name"] for row in shallow] == ["kerékpár"]


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
        await seeded_client.post("/api/places", json={"name": "Hátsó garázs", "kind": "building"})
    ).json()
    shelf = (
        await seeded_client.post(
            "/api/places",
            json={"name": "Fém polc", "kind": "storage", "parent_id": garage["id"]},
        )
    ).json()
    assert shelf["path"] == "Hátsó garázs › Fém polc"


async def test_a_place_cannot_become_its_own_ancestor(seeded_client):
    parent = (await seeded_client.post("/api/places", json={"name": "Hátsó pince"})).json()
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


# --- pictures ----------------------------------------------------------------
async def test_an_item_serves_its_picture_and_takes_more(seeded_client, session, item_photo):
    from leltar.models import Item, ItemStatus

    item = Item(name="Makita akkus fúró", status=ItemStatus.CONFIRMED.value)
    session.add(item)
    await session.commit()

    # Nothing attached yet: a 404 rather than a broken image on every row.
    assert (await seeded_client.get(f"/api/items/{item.id}/image")).status_code == 404
    assert (await seeded_client.get("/api/items")).json()[0]["image_count"] == 0

    added = await seeded_client.post(
        f"/api/items/{item.id}/images",
        files={"file": ("furo.jpg", item_photo, "image/jpeg")},
    )
    assert added.status_code == 201
    assert added.json()["kind"] == "upload"
    assert added.json()["is_primary"] is True

    served = await seeded_client.get(f"/api/items/{item.id}/image")
    assert served.status_code == 200
    assert served.headers["content-type"] == "image/jpeg"
    assert (await seeded_client.get("/api/items")).json()[0]["image_count"] == 1


async def test_only_one_picture_is_ever_the_primary(seeded_client, session, item_photo):
    """Two primaries is a state no screen can render, so the database forbids it."""
    import io

    from PIL import Image

    from leltar.models import Item

    item = Item(name="kerékpár")
    session.add(item)
    await session.commit()

    def jpeg(colour):
        buffer = io.BytesIO()
        Image.new("RGB", (600, 400), colour).save(buffer, format="JPEG")
        return buffer.getvalue()

    first = (await seeded_client.post(
        f"/api/items/{item.id}/images", files={"file": ("a.jpg", jpeg((10, 20, 30)), "image/jpeg")}
    )).json()
    second = (await seeded_client.post(
        f"/api/items/{item.id}/images", files={"file": ("b.jpg", jpeg((90, 20, 30)), "image/jpeg")}
    )).json()

    images = (await seeded_client.get(f"/api/items/{item.id}/images")).json()
    assert [row["is_primary"] for row in images] == [True, False]
    assert images[0]["id"] == second["id"]  # the newest upload took over

    await seeded_client.post(f"/api/items/images/{first['id']}/primary")
    images = (await seeded_client.get(f"/api/items/{item.id}/images")).json()
    assert sum(row["is_primary"] for row in images) == 1
    assert images[0]["id"] == first["id"]


async def test_deleting_the_primary_promotes_another(seeded_client, session, item_photo):
    import io

    from PIL import Image

    from leltar.models import Item

    item = Item(name="fúró")
    session.add(item)
    await session.commit()

    def jpeg(colour):
        buffer = io.BytesIO()
        Image.new("RGB", (600, 400), colour).save(buffer, format="JPEG")
        return buffer.getvalue()

    await seeded_client.post(
        f"/api/items/{item.id}/images", files={"file": ("a.jpg", jpeg((10, 20, 30)), "image/jpeg")}
    )
    newest = (await seeded_client.post(
        f"/api/items/{item.id}/images", files={"file": ("b.jpg", jpeg((90, 20, 30)), "image/jpeg")}
    )).json()

    assert (await seeded_client.delete(f"/api/items/images/{newest['id']}")).status_code == 204

    images = (await seeded_client.get(f"/api/items/{item.id}/images")).json()
    assert len(images) == 1
    # The item keeps a picture rather than silently losing the one its row shows.
    assert images[0]["is_primary"] is True
    assert (await seeded_client.get(f"/api/items/{item.id}/image")).status_code == 200


async def test_a_photo_can_be_uploaded_as_one_object(seeded_client, item_photo):
    response = await seeded_client.post(
        "/api/photos?mode=single",
        files={"file": ("furo.jpg", item_photo, "image/jpeg")},
    )
    assert response.status_code == 202
    assert (await seeded_client.get("/api/photos")).json()[0]["mode"] == "single"


async def test_an_unknown_capture_mode_is_refused(seeded_client, item_photo):
    response = await seeded_client.post(
        "/api/photos?mode=panorama", files={"file": ("x.jpg", item_photo, "image/jpeg")}
    )
    assert response.status_code == 400


async def test_a_place_can_be_renamed_and_moved(seeded_client):
    """The seeded rooms are a guess at somebody's house; making them yours is step one."""
    garage = (await seeded_client.post("/api/places", json={"name": "Hátsó garázs"})).json()
    shelf = (await seeded_client.post("/api/places", json={"name": "Polc"})).json()
    assert shelf["path"] == "Polc"

    renamed = await seeded_client.patch(f"/api/places/{shelf['id']}", json={"name": "Fém polc"})
    assert renamed.json()["name"] == "Fém polc"

    moved = await seeded_client.patch(
        f"/api/places/{shelf['id']}", json={"parent_id": garage["id"]}
    )
    assert moved.json()["path"] == "Hátsó garázs › Fém polc"

    # And moving it back out to the top level is expressible, rather than being mistaken
    # for "no change given".
    out = await seeded_client.patch(f"/api/places/{shelf['id']}", json={"parent_id": None})
    assert out.json()["path"] == "Fém polc"


async def test_two_places_cannot_share_a_name_at_the_top_level(seeded_client):
    """PostgreSQL counts NULLs as distinct, so the (parent_id, name) constraint alone
    never covered rooms with no parent - and a duplicate room splits a catalogue in two
    without saying so, half the things in one "Garázs" and half in the other."""
    first = await seeded_client.post("/api/places", json={"name": "Műhely"})
    assert first.status_code == 201

    again = await seeded_client.post("/api/places", json={"name": "Műhely"})
    assert again.status_code == 409
    assert "Műhely" in again.json()["detail"]

    # And the refusal did not leave a half-written row behind.
    names = [row["name"] for row in (await seeded_client.get("/api/places")).json()]
    assert names.count("Műhely") == 1


async def test_the_same_name_is_fine_in_two_different_places(seeded_client):
    """Every room may have a "Polc"; that is the point of the tree."""
    garage = (await seeded_client.post("/api/places", json={"name": "Garázs 2"})).json()
    kitchen = (await seeded_client.post("/api/places", json={"name": "Konyha 2"})).json()

    for parent in (garage, kitchen):
        created = await seeded_client.post(
            "/api/places", json={"name": "Polc", "parent_id": parent["id"]}
        )
        assert created.status_code == 201

    # But not twice in the same one.
    clash = await seeded_client.post(
        "/api/places", json={"name": "Polc", "parent_id": garage["id"]}
    )
    assert clash.status_code == 409


async def test_renaming_onto_a_sibling_is_refused_not_a_500(seeded_client):
    await seeded_client.post("/api/places", json={"name": "Padlás 2"})
    other = (await seeded_client.post("/api/places", json={"name": "Pince 2"})).json()

    response = await seeded_client.patch(f"/api/places/{other['id']}", json={"name": "Padlás 2"})
    assert response.status_code == 409

    # The place is still there under its own name rather than half-renamed.
    names = [row["name"] for row in (await seeded_client.get("/api/places")).json()]
    assert "Pince 2" in names
