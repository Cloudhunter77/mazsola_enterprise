"""Shelf labels: a price you saw, kept apart from money you spent.

The first class here is the one that matters. Everything else in this feature is a
convenience; the separation between an observation and a purchase is the correctness
property, and it is the kind that fails silently - a label added to a month's spending
would balance, look ordinary, and be discovered long afterwards, if ever.
"""

from __future__ import annotations

import io
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from PIL import Image
from sqlalchemy import select

from app.config import Settings
from app.extraction.base import ExtractionError, LabelResult
from app.models import (
    LabelStatus,
    Merchant,
    PriceLabelPhoto,
    PriceObservation,
    Product,
)
from app.schemas.price_label import ExtractedPriceLabel, ExtractedPriceLabels
from app.services import stats
from app.services.catalog import link_product
from app.services.labels import ingest_label_photo, persist_labels
from tests.conftest import requires_db

pytestmark = requires_db


def label(
    line_no: int = 1,
    raw_name: str = "Pepsi Cola 1,5 l",
    price: float | None = 598.0,
    unit_price: float | None = 398.67,
    unit: str | None = "l",
    package_size: float | None = 1.5,
    package_unit: str | None = "l",
    is_promotion: bool = False,
    regular_price: float | None = None,
    promotion_until: str | None = None,
    confidence: float = 0.92,
) -> ExtractedPriceLabel:
    return ExtractedPriceLabel(
        line_no=line_no,
        raw_name=raw_name,
        price=price,
        price_printed=None if price is None else f"{price:,.0f}".replace(",", " "),
        unit_price=unit_price,
        unit=unit,
        package_size=package_size,
        package_unit=package_unit,
        is_promotion=is_promotion,
        regular_price=regular_price,
        promotion_until=promotion_until,
        confidence=confidence,
    )


def labels_result(*items: ExtractedPriceLabel, merchant_name: str | None = None) -> LabelResult:
    return LabelResult(
        labels=ExtractedPriceLabels(
            merchant_name=merchant_name, labels=list(items), notes=None
        ),
        extractor="stub",
        model="stub-1",
        input_tokens=1200,
        output_tokens=300,
        cost_usd=Decimal("0.000200"),
        raw={},
    )


@pytest.fixture
def shelf_photo() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (1200, 900), (252, 252, 250)).save(buffer, format="JPEG")
    return buffer.getvalue()


@pytest.fixture
def label_settings(tmp_path) -> Settings:
    return Settings(data_dir=tmp_path, secret_key="x" * 64, extractor="stub")


async def _photo(session, settings, image, shop="Aldi", **overrides) -> PriceLabelPhoto:
    photo, _ = await ingest_label_photo(session, image, settings, merchant_name=shop)
    await session.commit()
    return photo


class TestItIsNeverSpending:
    """A shelf price must not be able to reach the monthly total, by any route."""

    async def test_a_label_creates_no_receipt(
        self, session, label_settings, shelf_photo
    ):
        from app.models import Receipt

        photo = await _photo(session, label_settings, shelf_photo)
        await persist_labels(session, photo, labels_result(label()))
        await session.commit()

        assert (await session.scalars(select(Receipt))).all() == []

    async def test_the_monthly_total_does_not_move(
        self, session, sessionmaker_fixture, label_settings, shelf_photo
    ):
        before = (await stats.summary(session)).total

        photo = await _photo(session, label_settings, shelf_photo)
        await persist_labels(
            session, photo, labels_result(label(price=98_000.0, unit_price=98_000.0))
        )
        await session.commit()

        after = (await stats.summary(session)).total
        assert after == before, "a price you looked at is not money you spent"

    async def test_no_line_item_is_written(self, session, label_settings, shelf_photo):
        from app.models import ReceiptItem

        photo = await _photo(session, label_settings, shelf_photo)
        await persist_labels(session, photo, labels_result(label(), label(line_no=2)))
        await session.commit()

        assert (await session.scalars(select(ReceiptItem))).all() == []


class TestReadingAShelf:
    async def test_one_photo_can_hold_several_labels(
        self, session, label_settings, shelf_photo
    ):
        """The whole point of the feature: a shelf strip is six products in one frame."""
        photo = await _photo(session, label_settings, shelf_photo)
        await persist_labels(
            session,
            photo,
            labels_result(
                label(1, "Pepsi Cola 1,5 l"),
                label(2, "Coca Cola 1,75 l", price=649.0, unit_price=370.86, package_size=1.75),
                label(3, "Fanta 0,5 l", price=349.0, unit_price=698.0, package_size=0.5),
            ),
        )
        await session.commit()

        stored = (await session.scalars(select(PriceObservation))).all()
        assert len(stored) == 3
        assert [o.line_no for o in stored] == [1, 2, 3]

    async def test_the_egysegar_is_kept(self, session, label_settings, shelf_photo):
        """It is the number the comparison actually uses, and the label prints it for us."""
        photo = await _photo(session, label_settings, shelf_photo)
        await persist_labels(session, photo, labels_result(label()))
        await session.commit()

        stored = (await session.scalars(select(PriceObservation))).one()
        assert stored.unit_price == Decimal("398.67")
        assert stored.unit == "l"

    async def test_it_links_to_a_product_you_already_track(
        self, session, label_settings, shelf_photo
    ):
        """A label and a receipt line for one product must land on one price history."""
        product = Product(canonical_name="Pepsi 1,5 l")
        session.add(product)
        await session.flush()
        await link_product(session, product.id, "PEPSI 1,5L", None)
        await session.commit()

        photo = await _photo(session, label_settings, shelf_photo)
        await persist_labels(session, photo, labels_result(label(raw_name="PEPSI 1500ML")))
        await session.commit()

        stored = (await session.scalars(select(PriceObservation))).one()
        assert stored.product_id == product.id

    async def test_a_label_with_no_price_is_not_an_observation(
        self, session, label_settings, shelf_photo
    ):
        """A name you could read and a price you could not is a photo, not a data point."""
        photo = await _photo(session, label_settings, shelf_photo)
        reasons = await persist_labels(
            session, photo, labels_result(label(price=None, unit_price=None))
        )
        await session.commit()

        assert (await session.scalars(select(PriceObservation))).all() == []
        assert "label_without_price" in reasons

    async def test_a_shop_from_the_app_beats_one_from_the_model(
        self, session, label_settings, shelf_photo
    ):
        """You are stating where you are; the model is guessing from branding."""
        photo = await _photo(session, label_settings, shelf_photo, shop="Aldi")
        await persist_labels(session, photo, labels_result(label(), merchant_name="Tesco"))
        await session.commit()

        merchant = await session.get(Merchant, photo.merchant_id)
        assert merchant.name == "Aldi"

    async def test_without_a_shop_it_asks(self, session, label_settings, shelf_photo):
        """A price with no shop cannot be compared with anything, which is the only use."""
        photo, _ = await ingest_label_photo(
            session, shelf_photo, label_settings, merchant_name=None
        )
        await session.commit()
        reasons = await persist_labels(session, photo, labels_result(label()))
        await session.commit()

        assert "shop_unknown" in reasons
        assert photo.status == LabelStatus.NEEDS_REVIEW.value


class TestCatchingAMisreadPrice:
    """A label has no total to balance, so price × size vs egységár is the only check."""

    async def test_a_consistent_label_passes(self, session, label_settings, shelf_photo):
        photo = await _photo(session, label_settings, shelf_photo)
        reasons = await persist_labels(session, photo, labels_result(label()))
        await session.commit()
        assert "unit_price_mismatch" not in reasons
        assert photo.status == LabelStatus.PARSED.value

    async def test_the_egysegar_read_as_the_price_is_caught(
        self, session, label_settings, shelf_photo
    ):
        """The commonest shelf mistake: 1 196 Ft/l copied into the price of a 0,5 l bottle."""
        photo = await _photo(session, label_settings, shelf_photo)
        reasons = await persist_labels(
            session,
            photo,
            labels_result(
                label(price=1196.0, unit_price=1196.0, package_size=0.5, unit="l")
            ),
        )
        await session.commit()
        assert "unit_price_mismatch" in reasons

    async def test_a_shop_rounding_its_egysegar_is_not_a_mismatch(
        self, session, label_settings, shelf_photo
    ):
        photo = await _photo(session, label_settings, shelf_photo)
        reasons = await persist_labels(
            session, photo, labels_result(label(price=598.0, unit_price=399.0))
        )
        await session.commit()
        assert "unit_price_mismatch" not in reasons

    async def test_an_implausible_price_is_dropped(
        self, session, label_settings, shelf_photo
    ):
        photo = await _photo(session, label_settings, shelf_photo)
        reasons = await persist_labels(
            session, photo, labels_result(label(price=99_000_000.0, unit_price=None))
        )
        await session.commit()
        assert "implausible_price" in reasons
        assert (await session.scalars(select(PriceObservation))).all() == []


class TestPromotions:
    async def test_both_prices_are_kept(self, session, label_settings, shelf_photo):
        photo = await _photo(session, label_settings, shelf_photo)
        await persist_labels(
            session,
            photo,
            labels_result(
                label(price=449.0, unit_price=299.33, is_promotion=True, regular_price=598.0,
                      promotion_until="2026-09-30")
            ),
        )
        await session.commit()

        stored = (await session.scalars(select(PriceObservation))).one()
        assert stored.is_promotion is True
        assert stored.price == Decimal("449.00")
        assert stored.regular_price == Decimal("598.00")
        assert stored.promotion_until.isoformat() == "2026-09-30"

    async def test_a_nonsense_date_does_not_lose_the_label(
        self, session, label_settings, shelf_photo
    ):
        photo = await _photo(session, label_settings, shelf_photo)
        await persist_labels(
            session, photo, labels_result(label(is_promotion=True, promotion_until="soon"))
        )
        await session.commit()

        stored = (await session.scalars(select(PriceObservation))).one()
        assert stored.promotion_until is None
        assert stored.price == Decimal("598.00")


class TestPriceHistory:
    async def _tracked(self, session, label_settings, shelf_photo, **label_kwargs):
        product = Product(canonical_name="Pepsi 1,5 l")
        session.add(product)
        await session.flush()
        await link_product(session, product.id, "Pepsi Cola 1,5 l", None)
        await session.commit()

        photo = await _photo(session, label_settings, shelf_photo)
        await persist_labels(session, photo, labels_result(label(**label_kwargs)))
        await session.commit()
        return product

    async def test_an_observation_appears_as_a_price_point(
        self, session, label_settings, shelf_photo
    ):
        product = await self._tracked(session, label_settings, shelf_photo)
        history = await stats.price_history(session, product.id)

        assert len(history.points) == 1
        assert history.points[0].unit_price == Decimal("398.67")

    async def test_it_is_marked_as_seen_not_bought(
        self, session, label_settings, shelf_photo
    ):
        """Otherwise you cannot tell whether you ever actually paid that price."""
        product = await self._tracked(session, label_settings, shelf_photo)
        history = await stats.price_history(session, product.id)

        point = history.points[0]
        assert point.source == "label"
        assert point.receipt_id is None
        assert point.observation_id is not None

    async def test_a_promotion_does_not_decide_the_cheapest_shop(
        self, session, label_settings, shelf_photo
    ):
        """A shop that happened to be running a sale is not permanently cheaper."""
        product = await self._tracked(
            session, label_settings, shelf_photo, is_promotion=True, regular_price=598.0
        )
        history = await stats.price_history(session, product.id)

        assert history.points[0].is_promotion is True
        assert history.cheapest_merchant is None, "nothing comparable was observed"

    async def test_a_label_without_an_egysegar_is_left_out(
        self, session, label_settings, shelf_photo
    ):
        """The value of this data is that it needed no assumption; a guess would spoil it."""
        product = await self._tracked(session, label_settings, shelf_photo, unit_price=None)
        history = await stats.price_history(session, product.id)

        assert history.points == []


class TestTheQueue:
    async def test_the_same_photo_twice_is_one_photo(
        self, session, label_settings, shelf_photo
    ):
        """A double-tap in an aisle must not pay to read the same shelf twice."""
        first, created_first = await ingest_label_photo(
            session, shelf_photo, label_settings, merchant_name="Aldi"
        )
        await session.commit()
        second, created_second = await ingest_label_photo(
            session, shelf_photo, label_settings, merchant_name="Aldi"
        )

        assert created_first is True and created_second is False
        assert first.id == second.id

    async def test_rereading_replaces_rather_than_doubles(
        self, session, label_settings, shelf_photo
    ):
        photo = await _photo(session, label_settings, shelf_photo)
        await persist_labels(session, photo, labels_result(label(), label(line_no=2)))
        await session.commit()

        await persist_labels(session, photo, labels_result(label()))
        await session.commit()

        assert len((await session.scalars(select(PriceObservation))).all()) == 1

    async def test_an_engine_that_cannot_read_labels_fails_the_photo_not_the_loop(
        self, session, sessionmaker_fixture, label_settings, shelf_photo
    ):
        """The Claude engine has no extract_labels; that must not stall the queue."""
        from app.worker import ExtractionWorker

        await _photo(session, label_settings, shelf_photo)

        class ReceiptsOnly:
            name = "receipts-only"

            async def extract(self, images, mime_type="image/jpeg"):
                raise ExtractionError("not used here")

        worker = ExtractionWorker(label_settings)
        worker._extractor = ReceiptsOnly()
        import app.worker as worker_module

        original = worker_module.SessionLocal
        worker_module.SessionLocal = sessionmaker_fixture
        try:
            assert await worker.process_next_label() is True
        finally:
            worker_module.SessionLocal = original

        session.expire_all()
        stored = (await session.scalars(select(PriceLabelPhoto))).one()
        assert stored.status == LabelStatus.FAILED.value
        assert "cannot read shelf labels" in (stored.error or "")


@requires_db
class TestTheApi:
    async def test_upload_needs_a_shop_to_be_useful_but_does_not_refuse(
        self, auth_client, shelf_photo
    ):
        response = await auth_client.post(
            "/api/labels", files={"file": ("shelf.jpg", shelf_photo, "image/jpeg")}
        )
        assert response.status_code == 202
        assert response.json()["status"] == "pending"

    async def test_upload_records_the_shop(self, auth_client, session, shelf_photo):
        response = await auth_client.post(
            "/api/labels?shop=Aldi",
            files={"file": ("shelf.jpg", shelf_photo, "image/jpeg")},
        )
        assert response.status_code == 202

        photo = (await session.scalars(select(PriceLabelPhoto))).one()
        merchant = await session.get(Merchant, photo.merchant_id)
        assert merchant.name == "Aldi"

    async def test_a_repeat_upload_says_so(self, auth_client, shelf_photo):
        files = {"file": ("shelf.jpg", shelf_photo, "image/jpeg")}
        await auth_client.post("/api/labels?shop=Aldi", files=files)
        again = await auth_client.post(
            "/api/labels?shop=Aldi",
            files={"file": ("shelf.jpg", shelf_photo, "image/jpeg")},
        )
        assert again.status_code == 200
        assert again.json()["duplicate"] is True

    async def test_a_non_image_is_refused(self, auth_client):
        response = await auth_client.post(
            "/api/labels", files={"file": ("notes.txt", b"not a photo", "text/plain")}
        )
        assert response.status_code == 400

    async def test_it_needs_a_login(self, client, shelf_photo):
        response = await client.post(
            "/api/labels", files={"file": ("shelf.jpg", shelf_photo, "image/jpeg")}
        )
        assert response.status_code == 401


def _jpeg_taken_at(stamp: str | None) -> bytes:
    """A JPEG carrying (or not carrying) an EXIF DateTimeOriginal."""
    buffer = io.BytesIO()
    image = Image.new("RGB", (900, 600), (250, 250, 248))
    if stamp is None:
        image.save(buffer, format="JPEG")
    else:
        exif = image.getexif()
        exif[36867] = stamp
        image.save(buffer, format="JPEG", exif=exif)
    return buffer.getvalue()


class TestWhenTheLabelWasSeen:
    """Uploading a photo from the gallery is only useful if it keeps its own date.

    Dated by upload instead, a shelf photographed last week files its price under today,
    and a batch of old photos lands as one flat snapshot of this afternoon - wrong in a way
    that looks entirely ordinary on a chart.
    """

    async def test_a_gallery_photo_keeps_the_day_it_was_taken(
        self, session, label_settings
    ):
        photo, _ = await ingest_label_photo(
            session, _jpeg_taken_at("2026:09:12 16:45:10"), label_settings, merchant_name="Aldi"
        )
        await session.commit()

        assert photo.observed_at.date().isoformat() == "2026-09-12"

    async def test_the_exif_time_is_read_as_local_and_stored_as_utc(
        self, session, label_settings
    ):
        """EXIF carries no zone; the camera was in Budapest, the database is in UTC."""
        photo, _ = await ingest_label_photo(
            session, _jpeg_taken_at("2026:09:12 16:45:10"), label_settings, merchant_name="Aldi"
        )
        await session.commit()

        assert photo.observed_at.hour == 14, "16:45 CEST is 14:45 UTC"

    async def test_a_photo_with_no_exif_falls_back_to_now(self, session, label_settings):
        """A screenshot or a stripped export still deserves to be recorded."""
        before = datetime.now(UTC)
        photo, _ = await ingest_label_photo(
            session, _jpeg_taken_at(None), label_settings, merchant_name="Aldi"
        )
        await session.commit()

        assert photo.observed_at >= before

    @pytest.mark.parametrize(
        "stamp", ["1970:01:01 00:00:00", "2099:01:01 00:00:00", "not a date", ""]
    )
    async def test_a_nonsense_camera_clock_is_ignored(self, session, label_settings, stamp):
        """A flat battery reports 1970; a mis-set clock reports next year. Neither is a date."""
        before = datetime.now(UTC)
        photo, _ = await ingest_label_photo(
            session, _jpeg_taken_at(stamp), label_settings, merchant_name="Aldi"
        )
        await session.commit()

        assert photo.observed_at >= before, "fell back to now rather than filing it in 1970"

    async def test_an_explicit_date_still_wins(self, session, label_settings):
        """The caller stating a date outranks the camera, which outranks the clock."""
        stated = datetime(2026, 8, 1, 9, 0, tzinfo=UTC)
        photo, _ = await ingest_label_photo(
            session,
            _jpeg_taken_at("2026:09:12 16:45:10"),
            label_settings,
            merchant_name="Aldi",
            observed_at=stated,
        )
        await session.commit()

        assert photo.observed_at == stated

    async def test_the_price_point_is_dated_by_the_photograph(
        self, session, label_settings
    ):
        """What all of the above is for: the time series has to be in the right order."""
        product = Product(canonical_name="Pepsi 1,5 l")
        session.add(product)
        await session.flush()
        await link_product(session, product.id, "Pepsi Cola 1,5 l", None)
        await session.commit()

        photo, _ = await ingest_label_photo(
            session, _jpeg_taken_at("2026:09:12 16:45:10"), label_settings, merchant_name="Aldi"
        )
        await session.commit()
        await persist_labels(session, photo, labels_result(label()))
        await session.commit()

        history = await stats.price_history(session, product.id)
        assert history.points[0].purchased_at.date().isoformat() == "2026-09-12"
