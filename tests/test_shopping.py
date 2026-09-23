"""The shopping list, and when a photograph is allowed to become a product.

Most of this feature is forgiving by design: a list entry only has to be recognisable to
the person holding the phone, and a photograph manages that without any help. The one place
that needs to be strict is the match. A photograph that could have been matched and was not
costs nothing - you see the picture and know exactly what you meant. A wrong match is
silent, and it attaches this item to another product's price history.
"""

from __future__ import annotations

import io
from decimal import Decimal

import pytest
from PIL import Image
from sqlalchemy import select

from app.config import Settings
from app.extraction.base import ProductPhotoResult
from app.models import ItemSource, Product, ScanStatus, ShoppingItem
from app.schemas.product_photo import ExtractedProductPhoto
from app.services.catalog import link_product
from app.services.shopping import (
    READ_IT_CONFIDENCE,
    add_item,
    add_photo,
    apply_recognition,
    clear_done,
    set_done,
)
from tests.conftest import requires_db

pytestmark = requires_db


def seen(
    raw_name: str | None = "Pepsi Cola 1,5 l",
    confidence: float = 0.95,
    category_hint: str | None = "üdítő",
) -> ProductPhotoResult:
    return ProductPhotoResult(
        photo=ExtractedProductPhoto(
            raw_name=raw_name,
            brand=None,
            package_size=None,
            package_unit=None,
            category_hint=category_hint,
            confidence=confidence,
            notes=None,
        ),
        extractor="stub",
        model="stub-1",
        cost_usd=Decimal("0.000300"),
        raw={},
    )


@pytest.fixture
def product_photo() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (800, 800), (250, 250, 248)).save(buffer, format="JPEG")
    return buffer.getvalue()


@pytest.fixture
def shopping_settings(tmp_path) -> Settings:
    return Settings(data_dir=tmp_path, secret_key="x" * 64, extractor="stub")


async def _known_product(session, canonical: str, *spellings: str) -> Product:
    product = Product(canonical_name=canonical)
    session.add(product)
    await session.flush()
    for spelling in spellings:
        await link_product(session, product.id, spelling, None)
    await session.commit()
    return product


class TestWhenAPhotoBecomesAProduct:
    async def test_a_name_it_read_that_resolves_exactly_is_matched(
        self, session, shopping_settings, product_photo
    ):
        product = await _known_product(session, "Pepsi 1,5 l", "PEPSI 1,5L")

        item = await add_photo(session, product_photo, shopping_settings)
        await apply_recognition(session, item, seen("PEPSI 1500ML", confidence=0.95))
        await session.commit()

        assert item.product_id == product.id
        assert item.status == ScanStatus.READY.value

    async def test_a_name_it_guessed_is_never_matched(
        self, session, shopping_settings, product_photo
    ):
        """Low confidence means it recognised the object, not the writing on it."""
        await _known_product(session, "Pepsi 1,5 l", "PEPSI 1,5L")

        item = await add_photo(session, product_photo, shopping_settings)
        await apply_recognition(session, item, seen("PEPSI 1,5L", confidence=0.4))
        await session.commit()

        assert item.product_id is None
        assert item.raw_name == "PEPSI 1,5L", "still worth showing, just not worth matching on"

    async def test_a_merely_similar_name_is_never_matched(
        self, session, shopping_settings, product_photo
    ):
        """The same exact-match rule the receipts use. Similar is not the same."""
        await _known_product(session, "Pepsi 1,5 l", "PEPSI 1,5L")

        item = await add_photo(session, product_photo, shopping_settings)
        await apply_recognition(session, item, seen("Pepsi Cola Zero 1,5L", confidence=0.98))
        await session.commit()

        assert item.product_id is None

    async def test_a_different_size_is_never_matched(
        self, session, shopping_settings, product_photo
    ):
        await _known_product(session, "Pepsi 1,5 l", "PEPSI 1,5L")

        item = await add_photo(session, product_photo, shopping_settings)
        await apply_recognition(session, item, seen("PEPSI 0,5L", confidence=0.98))
        await session.commit()

        assert item.product_id is None

    def test_the_threshold_is_where_reading_stops_and_guessing_starts(self):
        assert 0.5 < READ_IT_CONFIDENCE < 1.0


class TestAPhotographIsACompleteEntry:
    async def test_it_is_on_the_list_before_anything_has_looked_at_it(
        self, session, shopping_settings, product_photo
    ):
        """The list is useful immediately; recognition is an improvement, not a gate."""
        item = await add_photo(session, product_photo, shopping_settings)
        await session.commit()

        assert item.status == ScanStatus.PENDING.value
        assert item.source == ItemSource.SCAN.value
        stored = (await session.scalars(select(ShoppingItem))).one()
        assert stored.image_path

    async def test_an_unreadable_photo_still_leaves_an_item(
        self, session, shopping_settings, product_photo
    ):
        item = await add_photo(session, product_photo, shopping_settings)
        await apply_recognition(session, item, seen(raw_name=None, category_hint="tej"))
        await session.commit()

        assert item.product_id is None
        assert item.raw_name == "tej", "a hint is better than nothing to read in an aisle"
        assert item.status == ScanStatus.READY.value

    async def test_a_photo_with_nothing_readable_at_all_is_still_an_item(
        self, session, shopping_settings, product_photo
    ):
        item = await add_photo(session, product_photo, shopping_settings)
        await apply_recognition(
            session, item, seen(raw_name=None, category_hint=None, confidence=0.2)
        )
        await session.commit()

        assert item.raw_name is None
        assert item.label == "Fotó", "the picture carries it"

    async def test_the_original_bytes_are_kept(
        self, session, shopping_settings, product_photo
    ):
        from pathlib import Path

        item = await add_photo(session, product_photo, shopping_settings)
        await session.commit()

        assert Path(item.image_path).read_bytes() == product_photo


class TestAddingAndTicking:
    async def test_a_product_goes_on_by_its_id(self, session):
        product = await _known_product(session, "Tej 1 l")
        item = await add_item(session, product_id=product.id)
        await session.commit()

        assert item.product_id == product.id
        assert item.label == "Tej 1 l"

    async def test_a_typed_name_needs_no_product(self, session):
        item = await add_item(session, raw_name="Valami a boltból")
        await session.commit()
        assert item.label == "Valami a boltból"

    async def test_an_empty_item_is_refused(self, session):
        from app.services.ingest import IngestError

        with pytest.raises(IngestError):
            await add_item(session, raw_name="   ")

    async def test_adding_the_same_product_twice_bumps_it(self, session):
        """A list with `Tej` on it three times is a worse list, not a more emphatic one."""
        product = await _known_product(session, "Tej 1 l")
        await add_item(session, product_id=product.id)
        await session.commit()
        await add_item(session, product_id=product.id, quantity="2 db")
        await session.commit()

        items = (await session.scalars(select(ShoppingItem))).all()
        assert len(items) == 1
        assert items[0].quantity == "2 db"

    async def test_adding_it_again_after_ticking_it_off_starts_a_new_item(self, session):
        """Last week's shopping is done with; this week's is a fresh thing to buy."""
        product = await _known_product(session, "Tej 1 l")
        first = await add_item(session, product_id=product.id)
        await set_done(session, first, True)
        await session.commit()

        await add_item(session, product_id=product.id)
        await session.commit()

        assert len((await session.scalars(select(ShoppingItem))).all()) == 2

    async def test_quantity_is_whatever_you_wrote(self, session):
        """A shopping list is not arithmetic: `amennyi kell` is a perfectly good quantity."""
        item = await add_item(session, raw_name="Krumpli", quantity="amennyi kell")
        await session.commit()
        assert item.quantity == "amennyi kell"

    async def test_clearing_ticked_items_removes_their_photos(
        self, session, shopping_settings, product_photo
    ):
        from pathlib import Path

        item = await add_photo(session, product_photo, shopping_settings)
        await set_done(session, item, True)
        await session.commit()
        path = Path(item.image_path)
        assert path.is_file()

        assert await clear_done(session) == 1
        await session.commit()
        assert not path.exists()

    async def test_clearing_leaves_what_is_still_to_buy(self, session):
        product = await _known_product(session, "Tej 1 l")
        keep = await add_item(session, product_id=product.id)
        gone = await add_item(session, raw_name="Kenyér")
        await set_done(session, gone, True)
        await session.commit()

        await clear_done(session)
        await session.commit()

        remaining = (await session.scalars(select(ShoppingItem))).all()
        assert [item.id for item in remaining] == [keep.id]


class TestItIsNotSpending:
    async def test_the_list_creates_no_receipt(self, session, shopping_settings, product_photo):
        from app.models import Receipt

        await add_item(session, raw_name="Tej")
        await add_photo(session, product_photo, shopping_settings)
        await session.commit()

        assert (await session.scalars(select(Receipt))).all() == []


@requires_db
class TestTheApi:
    async def test_add_and_list(self, auth_client):
        added = await auth_client.post("/api/shopping", json={"raw_name": "Kenyér"})
        assert added.status_code == 201
        assert added.json()["label"] == "Kenyér"

        rows = (await auth_client.get("/api/shopping")).json()
        assert [row["label"] for row in rows] == ["Kenyér"]

    async def test_an_unknown_product_id_is_a_404(self, auth_client):
        import uuid

        response = await auth_client.post(
            "/api/shopping", json={"product_id": str(uuid.uuid4())}
        )
        assert response.status_code == 404

    async def test_scanning_returns_an_item_immediately(self, auth_client, product_photo):
        response = await auth_client.post(
            "/api/shopping/scan",
            files={"file": ("thing.jpg", product_photo, "image/jpeg")},
        )
        assert response.status_code == 202
        body = response.json()
        assert body["status"] == "pending"
        assert body["has_photo"] is True

    async def test_ticking_it_off(self, auth_client):
        item = (await auth_client.post("/api/shopping", json={"raw_name": "Tej"})).json()
        done = await auth_client.patch(f"/api/shopping/{item['id']}", json={"done": True})
        assert done.status_code == 200
        assert done.json()["done"] is True

    async def test_the_photo_is_served_back(self, auth_client, product_photo):
        item = (
            await auth_client.post(
                "/api/shopping/scan",
                files={"file": ("thing.jpg", product_photo, "image/jpeg")},
            )
        ).json()

        image = await auth_client.get(f"/api/shopping/{item['id']}/image")
        assert image.status_code == 200
        assert image.content == product_photo

    async def test_an_item_with_no_photo_has_no_image(self, auth_client):
        item = (await auth_client.post("/api/shopping", json={"raw_name": "Tej"})).json()
        assert (await auth_client.get(f"/api/shopping/{item['id']}/image")).status_code == 404

    async def test_it_needs_a_login(self, client):
        assert (await client.get("/api/shopping")).status_code == 401
