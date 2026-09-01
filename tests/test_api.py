"""HTTP-level tests: the endpoints as a client actually calls them.

The service layer is covered in test_pipeline.py; this checks the wiring around it -
status codes, serialisation, validation, and the review flow the web app depends on.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from app.models import Correction, Receipt, ReceiptStatus
from tests.conftest import requires_db

pytestmark = requires_db


async def upload(client, photo: bytes, name: str = "blokk.jpg"):
    return await client.post(
        "/api/receipts", files={"file": (name, photo, "image/jpeg")}
    )


class TestUploadEndpoint:
    async def test_upload_queues_a_receipt(self, auth_client, receipt_photo):
        response = await upload(auth_client, receipt_photo)
        assert response.status_code == 202

        body = response.json()
        assert body["status"] == ReceiptStatus.PENDING.value
        assert body["duplicate"] is False
        uuid.UUID(body["id"])

    async def test_uploading_the_same_photo_twice_is_not_a_second_receipt(
        self, auth_client, receipt_photo
    ):
        first = await upload(auth_client, receipt_photo)
        second = await upload(auth_client, receipt_photo)

        assert first.status_code == 202
        # 200 rather than 202: nothing new was accepted for processing.
        assert second.status_code == 200
        assert second.json()["duplicate"] is True
        assert second.json()["id"] == first.json()["id"]

    async def test_a_non_image_is_a_client_error_not_a_crash(self, auth_client):
        response = await upload(auth_client, b"this is not a photo", name="notes.txt")
        assert response.status_code == 400
        assert "image" in response.json()["detail"].lower()

    async def test_an_empty_upload_is_rejected(self, auth_client):
        assert (await upload(auth_client, b"")).status_code == 400

    async def test_a_decompression_bomb_is_rejected_over_http(self, auth_client):
        import io

        from PIL import Image

        buffer = io.BytesIO()
        Image.new("RGB", (12000, 12000)).save(buffer, format="PNG", compress_level=9)
        response = await upload(auth_client, buffer.getvalue(), name="bomb.png")
        assert response.status_code == 400, "a tiny upload that decodes to ~430 MB"


class TestReceiptEndpoints:
    @pytest.fixture
    async def receipt_id(self, auth_client, receipt_photo) -> str:
        return (await upload(auth_client, receipt_photo)).json()["id"]

    async def test_listing_and_fetching(self, auth_client, receipt_id):
        listing = await auth_client.get("/api/receipts")
        assert listing.status_code == 200
        assert any(row["id"] == receipt_id for row in listing.json())

        detail = await auth_client.get(f"/api/receipts/{receipt_id}")
        assert detail.status_code == 200
        assert detail.json()["items"] == []

    async def test_filtering_by_status(self, auth_client, receipt_id):
        pending = await auth_client.get("/api/receipts", params={"status": "pending"})
        assert [row["id"] for row in pending.json()] == [receipt_id]

        confirmed = await auth_client.get("/api/receipts", params={"status": "confirmed"})
        assert confirmed.json() == []

    async def test_unknown_receipt_is_404_not_500(self, auth_client):
        for suffix in ("", "/image"):
            response = await auth_client.get(f"/api/receipts/{uuid.uuid4()}{suffix}")
            assert response.status_code == 404

    async def test_a_malformed_id_is_a_validation_error(self, auth_client):
        assert (await auth_client.get("/api/receipts/not-a-uuid")).status_code == 422

    async def test_the_stored_photo_is_served_back(self, auth_client, receipt_id, receipt_photo):
        response = await auth_client.get(f"/api/receipts/{receipt_id}/image")
        assert response.status_code == 200
        assert response.content == receipt_photo, "the original must be served, not a re-encode"

    async def test_editing_the_header_records_a_correction(
        self, auth_client, receipt_id, session
    ):
        response = await auth_client.patch(
            f"/api/receipts/{receipt_id}",
            json={"merchant_name": "Lidl", "total_gross": "4200.00"},
        )
        assert response.status_code == 200
        assert response.json()["merchant_name"] == "Lidl"
        assert Decimal(response.json()["total_gross"]) == Decimal("4200.00")

        from sqlalchemy import select

        fields = set(
            (
                await session.scalars(
                    select(Correction.field).where(Correction.receipt_id == uuid.UUID(receipt_id))
                )
            ).all()
        )
        assert {"merchant_id", "total_gross"} <= fields, "edits must be auditable"

    async def test_confirming(self, auth_client, receipt_id):
        response = await auth_client.post(f"/api/receipts/{receipt_id}/confirm")
        assert response.status_code == 200
        assert response.json()["status"] == ReceiptStatus.CONFIRMED.value
        assert response.json()["confirmed_at"] is not None

    async def test_reprocessing_requeues_and_clears_the_error(
        self, auth_client, receipt_id, session
    ):
        stored = await session.get(Receipt, uuid.UUID(receipt_id))
        stored.status = ReceiptStatus.FAILED.value
        stored.attempts = 3
        stored.error = "the model was unreachable"
        await session.commit()

        response = await auth_client.post(f"/api/receipts/{receipt_id}/reprocess")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == ReceiptStatus.PENDING.value
        assert body["attempts"] == 0 and body["error"] is None

    async def test_deleting_removes_the_row_and_the_file(
        self, auth_client, receipt_id, session
    ):
        from pathlib import Path

        stored = await session.get(Receipt, uuid.UUID(receipt_id))
        path = Path(stored.image_path)
        assert path.is_file()

        assert (await auth_client.delete(f"/api/receipts/{receipt_id}")).status_code == 204
        assert (await auth_client.get(f"/api/receipts/{receipt_id}")).status_code == 404
        assert not path.exists(), "the photo should not be left behind on disk"

    async def test_delete_can_keep_the_photo(self, auth_client, receipt_id, session):
        from pathlib import Path

        stored = await session.get(Receipt, uuid.UUID(receipt_id))
        path = Path(stored.image_path)

        await auth_client.delete(f"/api/receipts/{receipt_id}", params={"keep_image": "true"})
        assert path.is_file()


class TestItemEditing:
    """The review screen's core interaction. Every one of these edits used to return 500:
    the handler read `item.receipt`, a lazy relationship, on an async session."""

    @pytest.fixture
    async def item_id(self, auth_client, session, receipt_photo, app_settings) -> str:
        from app.models import LineKind, ReceiptItem
        from app.services.ingest import ingest_image

        receipt, _ = await ingest_image(session, receipt_photo, app_settings)
        item = ReceiptItem(
            receipt_id=receipt.id, line_no=1, raw_name="TEJ 2,8% 1L UHT",
            gross_amount=Decimal("379.00"), kind=LineKind.ITEM.value,
        )
        session.add(item)
        await session.commit()
        return str(item.id)

    async def test_correcting_an_amount(self, auth_client, item_id):
        response = await auth_client.patch(
            f"/api/receipts/items/{item_id}", json={"gross_amount": "400.00"}
        )
        assert response.status_code == 200
        assert Decimal(response.json()["gross_amount"]) == Decimal("400.00")

    async def test_changing_the_line_kind(self, auth_client, item_id):
        response = await auth_client.patch(
            f"/api/receipts/items/{item_id}", json={"kind": "deposit"}
        )
        assert response.status_code == 200
        assert response.json()["kind"] == "deposit"

    async def test_an_unknown_kind_is_rejected(self, auth_client, item_id):
        response = await auth_client.patch(
            f"/api/receipts/items/{item_id}", json={"kind": "nonsense"}
        )
        assert response.status_code == 400

    async def test_edits_are_recorded_as_corrections(self, auth_client, item_id, session):
        from sqlalchemy import select

        from app.models import Correction

        await auth_client.patch(f"/api/receipts/items/{item_id}", json={"gross_amount": "450.00"})
        rows = (
            await session.scalars(
                select(Correction).where(Correction.item_id == uuid.UUID(item_id))
            )
        ).all()
        assert [row.field for row in rows] == ["gross_amount"]
        assert rows[0].new_value == "450.00"

    async def test_mapping_a_line_to_a_product_is_remembered(self, auth_client, item_id, session):
        from sqlalchemy import select

        from app.models import ProductAlias

        product = (await auth_client.post(
            "/api/products", json={"canonical_name": "Tej 2,8% 1L"}
        )).json()

        response = await auth_client.patch(
            f"/api/receipts/items/{item_id}",
            json={"product_id": product["id"], "remember_mapping": True},
        )
        assert response.status_code == 200
        assert response.json()["product_id"] == product["id"]

        aliases = (await session.scalars(select(ProductAlias))).all()
        assert any(a.raw_name == "TEJ 2,8% 1L UHT" for a in aliases), (
            "the mapping should apply to future receipts without asking again"
        )

    async def test_editing_an_unknown_item_is_404(self, auth_client):
        response = await auth_client.patch(
            f"/api/receipts/items/{uuid.uuid4()}", json={"gross_amount": "1.00"}
        )
        assert response.status_code == 404


class TestStatsEndpoints:
    async def test_an_empty_database_returns_zeroes_rather_than_errors(self, auth_client):
        summary = await auth_client.get("/api/stats/summary")
        assert summary.status_code == 200
        body = summary.json()
        assert Decimal(body["total"]) == Decimal("0.00")
        assert body["receipt_count"] == 0

        for path in ("/api/stats/monthly", "/api/stats/by-category", "/api/stats/by-merchant",
                     "/api/stats/inflation"):
            response = await auth_client.get(path)
            assert response.status_code == 200, path
            assert response.json() == [], path

    async def test_basket_comparison_with_no_data(self, auth_client):
        response = await auth_client.get("/api/stats/basket-comparison")
        assert response.status_code == 200
        assert response.json()["product_count"] == 0

    async def test_price_history_of_an_unknown_product_is_404(self, auth_client):
        response = await auth_client.get(f"/api/stats/price-history/{uuid.uuid4()}")
        assert response.status_code == 404

    async def test_costs_with_no_extractions(self, auth_client):
        response = await auth_client.get("/api/costs/summary")
        assert response.status_code == 200
        assert response.json()["receipts_extracted"] == 0


class TestCatalogEndpoints:
    async def test_categories_are_seeded_on_demand(self, auth_client, session):
        from app.services.seed import seed_categories

        await seed_categories(session)
        response = await auth_client.get("/api/categories")
        names = [row["name"] for row in response.json()]
        assert "Élelmiszer" in names and "Tejtermék" in names

    async def test_creating_a_product_and_mapping_a_receipt_line_to_it(self, auth_client):
        response = await auth_client.post(
            "/api/products",
            json={"canonical_name": "Tej 2,8% 1L"},
            params={"from_raw_name": "TEJ 2,8% 1L UHT"},
        )
        assert response.status_code == 201
        assert response.json()["canonical_name"] == "Tej 2,8% 1L"

        # Creating it twice must not produce a duplicate catalogue entry.
        again = await auth_client.post("/api/products", json={"canonical_name": "Tej 2,8% 1L"})
        assert again.json()["id"] == response.json()["id"]

    async def test_product_search(self, auth_client):
        await auth_client.post("/api/products", json={"canonical_name": "Trappista sajt"})
        await auth_client.post("/api/products", json={"canonical_name": "Fehér kenyér"})

        found = await auth_client.get("/api/products", params={"q": "sajt"})
        assert [p["canonical_name"] for p in found.json()] == ["Trappista sajt"]

    async def test_budget_upsert_replaces_rather_than_duplicates(self, auth_client):
        first = await auth_client.put(
            "/api/budgets", json={"month": "2026-09-01", "amount": "150000.00"}
        )
        assert first.status_code == 200

        second = await auth_client.put(
            "/api/budgets", json={"month": "2026-09-15", "amount": "180000.00"}
        )
        # The same month, normalised to the first of the month: one budget, updated.
        assert second.json()["id"] == first.json()["id"]
        assert Decimal(second.json()["amount"]) == Decimal("180000.00")
        assert second.json()["month"] == "2026-09-01"

        assert len((await auth_client.get("/api/budgets")).json()) == 1
