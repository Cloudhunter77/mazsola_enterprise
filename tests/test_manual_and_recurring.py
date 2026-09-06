"""Spending that never produced a photograph.

Two ways in: a receipt you lost but remember, and a subscription that never printed one.
Both must land in the same tables as a photographed receipt, or the dashboard would be
quietly under-counting - which is the whole point of entering them.

The rule worth defending hardest is that materialising a subscription twice must not charge
twice. The worker runs it every hour, a restart repeats it, and a clock change can repeat a
period; none of those may invent a second Spotify payment.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.models import Receipt, RecurringCharge, RecurringPayment
from app.services.manual import ManualEntryError, create_manual_receipt
from app.services.recurring import charge_date, materialise_due, periods_due
from tests.conftest import requires_db

pytestmark = requires_db


def spotify(**overrides) -> RecurringPayment:
    defaults = dict(
        name="Spotify Premium",
        merchant_name="Spotify",
        amount=Decimal("1999.00"),
        currency="HUF",
        cadence="monthly",
        day_of_month=8,
        payment_method="card",
        starts_on=date(2026, 1, 8),
        active=True,
    )
    defaults.update(overrides)
    return RecurringPayment(**defaults)


class TestManualEntry:
    async def test_a_typed_receipt_is_stored_and_confirmed(self, session):
        receipt = await create_manual_receipt(
            session,
            merchant_name="Lidl",
            purchased_at=datetime(2026, 9, 1, 17, 30, tzinfo=UTC),
            items=[
                {"raw_name": "Tej 2,8% 1L", "gross_amount": 449, "quantity": 2},
                {"raw_name": "Kenyér", "gross_amount": 599},
            ],
        )
        await session.commit()

        assert receipt.total_gross == Decimal("1048.00"), "the total defaults to the lines"
        # Typed in means it is ground truth; there is nothing for the review queue to check.
        assert receipt.status == "confirmed"
        assert receipt.confirmed_at is not None
        assert len(receipt.items) == 2

    async def test_it_has_no_photograph_and_that_is_not_an_error(self, session):
        receipt = await create_manual_receipt(
            session, merchant_name="Lidl", purchased_at=datetime.now(UTC),
            items=[{"raw_name": "Kenyér", "gross_amount": 599}],
        )
        await session.commit()

        assert receipt.image_path is None
        assert receipt.image_sha256 is None

    async def test_several_photoless_receipts_do_not_collide(self, session):
        """image_sha256 is unique; Postgres allows any number of NULLs under that index."""
        for index in range(3):
            await create_manual_receipt(
                session, merchant_name=f"Bolt {index}", purchased_at=datetime.now(UTC),
                items=[{"raw_name": "Valami", "gross_amount": 100}],
            )
        await session.commit()

        assert await session.scalar(select(func.count(Receipt.id))) == 3

    async def test_it_joins_the_existing_merchant(self, session):
        first = await create_manual_receipt(
            session, merchant_name="Lidl", purchased_at=datetime.now(UTC),
            items=[{"raw_name": "Kenyér", "gross_amount": 599}],
        )
        second = await create_manual_receipt(
            session, merchant_name="Lidl", purchased_at=datetime.now(UTC),
            items=[{"raw_name": "Tej", "gross_amount": 449}],
        )
        await session.commit()

        assert first.merchant_id is not None
        assert first.merchant_id == second.merchant_id, "one shop, not two"

    async def test_a_discount_reduces_the_total_whichever_sign_was_typed(self, session):
        receipt = await create_manual_receipt(
            session, merchant_name="Lidl", purchased_at=datetime.now(UTC),
            items=[
                {"raw_name": "Kenyér", "gross_amount": 1000},
                {"raw_name": "Kupon", "gross_amount": 200, "kind": "discount"},
            ],
        )
        await session.commit()
        assert receipt.total_gross == Decimal("800.00")

    async def test_an_explicit_total_wins_over_the_lines(self, session):
        """You remember the total but only some of what you bought."""
        receipt = await create_manual_receipt(
            session, merchant_name="Lidl", purchased_at=datetime.now(UTC),
            items=[{"raw_name": "Bevásárlás", "gross_amount": 1000}],
            total_gross=4200,
        )
        await session.commit()
        assert receipt.total_gross == Decimal("4200.00")

    @pytest.mark.parametrize(
        "kwargs, message",
        [
            ({"merchant_name": "  "}, "shop name"),
            ({"items": []}, "at least one"),
            ({"items": [{"raw_name": "", "gross_amount": 100}]}, "no description"),
            ({"items": [{"raw_name": "x", "gross_amount": 0}]}, "more than zero"),
            ({"items": [{"raw_name": "x", "gross_amount": 1, "kind": "nonsense"}]}, "unknown kind"),
        ],
    )
    async def test_nonsense_is_refused(self, session, kwargs, message):
        call = dict(
            merchant_name="Lidl",
            purchased_at=datetime.now(UTC),
            items=[{"raw_name": "Kenyér", "gross_amount": 599}],
        )
        call.update(kwargs)
        with pytest.raises(ManualEntryError, match=message):
            await create_manual_receipt(session, **call)

    async def test_a_future_date_is_refused(self, session):
        with pytest.raises(ManualEntryError, match="future"):
            await create_manual_receipt(
                session, merchant_name="Lidl",
                purchased_at=datetime.now(UTC) + timedelta(days=3),
                items=[{"raw_name": "Kenyér", "gross_amount": 599}],
            )


class TestTheSchedule:
    """Pure date arithmetic, no database: which periods a rule has come due for."""

    def test_a_short_month_charges_on_its_last_day_rather_than_skipping(self):
        rule = spotify(day_of_month=31)
        assert charge_date(rule, date(2026, 2, 1)) == date(2026, 2, 28)
        assert charge_date(rule, date(2026, 1, 1)) == date(2026, 1, 31)

    def test_periods_run_from_the_start_date_to_today(self):
        rule = spotify(starts_on=date(2026, 1, 8))
        due = periods_due(rule, date(2026, 4, 10))
        assert due == [date(2026, 1, 1), date(2026, 2, 1), date(2026, 3, 1), date(2026, 4, 1)]

    def test_a_period_is_not_due_until_its_charge_date_arrives(self):
        """Adding a rule on the 3rd that bills on the 20th must not invent this month."""
        rule = spotify(day_of_month=20, starts_on=date(2026, 4, 1))
        assert periods_due(rule, date(2026, 4, 3)) == []
        assert periods_due(rule, date(2026, 4, 20)) == [date(2026, 4, 1)]

    def test_an_inactive_rule_is_never_due(self):
        assert periods_due(spotify(active=False), date(2026, 6, 1)) == []

    def test_nothing_is_due_after_the_end_date(self):
        rule = spotify(starts_on=date(2026, 1, 8), ends_on=date(2026, 2, 28))
        assert periods_due(rule, date(2026, 6, 10)) == [date(2026, 1, 1), date(2026, 2, 1)]

    def test_a_yearly_payment_charges_in_one_month_only(self):
        rule = spotify(cadence="yearly", month_of_year=3, day_of_month=8,
                       starts_on=date(2025, 3, 8))
        due = periods_due(rule, date(2027, 6, 1))
        assert due == [date(2025, 3, 1), date(2026, 3, 1), date(2027, 3, 1)]


@requires_db
class TestMaterialising:
    async def test_a_receipt_is_created_for_each_due_period(self, session):
        session.add(spotify(starts_on=date(2026, 1, 8)))
        await session.flush()

        created = await materialise_due(session, today=date(2026, 3, 10))
        await session.commit()

        assert len(created) == 3, "January, February, March"
        assert all(receipt.source == "recurring" for receipt in created)
        assert all(receipt.total_gross == Decimal("1999.00") for receipt in created)
        assert [r.purchased_at.date() for r in created] == [
            date(2026, 1, 8), date(2026, 2, 8), date(2026, 3, 8)
        ]

    async def test_running_it_again_charges_nothing(self, session):
        """The whole design rests on this: the worker calls it every hour, forever."""
        session.add(spotify(starts_on=date(2026, 1, 8)))
        await session.flush()

        first = await materialise_due(session, today=date(2026, 3, 10))
        await session.commit()
        second = await materialise_due(session, today=date(2026, 3, 10))
        await session.commit()

        assert len(first) == 3
        assert second == []
        assert await session.scalar(select(func.count(Receipt.id))) == 3

    async def test_a_later_run_picks_up_only_the_new_month(self, session):
        session.add(spotify(starts_on=date(2026, 1, 8)))
        await session.flush()
        await materialise_due(session, today=date(2026, 3, 10))
        await session.commit()

        later = await materialise_due(session, today=date(2026, 4, 10))
        await session.commit()

        assert len(later) == 1
        assert later[0].purchased_at.date() == date(2026, 4, 8)

    async def test_a_deleted_charge_is_not_resurrected(self, session):
        """Deleting a generated receipt is a decision, not a gap to be refilled."""
        session.add(spotify(starts_on=date(2026, 1, 8)))
        await session.flush()
        created = await materialise_due(session, today=date(2026, 1, 10))
        await session.commit()

        await session.delete(created[0])
        await session.commit()

        again = await materialise_due(session, today=date(2026, 1, 10))
        await session.commit()

        assert again == [], "the charge row survives the receipt on purpose"
        # The tombstone is still there, now pointing at nothing.
        charge = await session.scalar(select(RecurringCharge))
        assert charge is not None and charge.receipt_id is None

    async def test_deactivating_stops_future_charges_and_keeps_past_ones(self, session):
        rule = spotify(starts_on=date(2026, 1, 8))
        session.add(rule)
        await session.flush()
        await materialise_due(session, today=date(2026, 2, 10))
        await session.commit()

        rule.active = False
        await session.commit()
        later = await materialise_due(session, today=date(2026, 6, 10))
        await session.commit()

        assert later == []
        assert await session.scalar(select(func.count(Receipt.id))) == 2

    async def test_deleting_the_rule_leaves_the_spending_behind(self, session):
        rule = spotify(starts_on=date(2026, 1, 8))
        session.add(rule)
        await session.flush()
        await materialise_due(session, today=date(2026, 2, 10))
        await session.commit()

        await session.delete(rule)
        await session.commit()

        assert await session.scalar(select(func.count(Receipt.id))) == 2, (
            "a cancelled subscription is still part of last year's spending"
        )
        assert await session.scalar(select(func.count(RecurringCharge.id))) == 0


@requires_db
class TestTheApi:
    async def test_typing_in_a_receipt(self, auth_client):
        response = await auth_client.post("/api/receipts/manual", json={
            "merchant_name": "Lidl",
            "purchased_at": "2026-09-01T17:30:00Z",
            "items": [{"raw_name": "Tej", "gross_amount": 449, "quantity": 2}],
        })
        assert response.status_code == 201, response.text

        body = response.json()
        assert body["status"] == "confirmed"
        assert body["source"] == "manual"
        assert body["pages"] == 1

    async def test_a_typed_receipt_has_no_image_to_serve(self, auth_client):
        created = (await auth_client.post("/api/receipts/manual", json={
            "merchant_name": "Lidl",
            "purchased_at": "2026-09-01T17:30:00Z",
            "items": [{"raw_name": "Tej", "gross_amount": 449}],
        })).json()

        image = await auth_client.get(f"/api/receipts/{created['id']}/image")
        assert image.status_code == 404, "a 404, not a 500 - there is nothing missing"

    async def test_a_typed_receipt_can_be_deleted(self, auth_client):
        """Deletion reads image paths; a receipt with none must not trip over that."""
        created = (await auth_client.post("/api/receipts/manual", json={
            "merchant_name": "Lidl",
            "purchased_at": "2026-09-01T17:30:00Z",
            "items": [{"raw_name": "Tej", "gross_amount": 449}],
        })).json()

        assert (await auth_client.delete(f"/api/receipts/{created['id']}")).status_code == 204

    async def test_adding_a_subscription_charges_what_is_already_due(self, auth_client):
        start = (datetime.now(UTC).date() - timedelta(days=70)).isoformat()
        response = await auth_client.post("/api/recurring", json={
            "name": "Spotify Premium", "merchant_name": "Spotify",
            "amount": 1999, "starts_on": start, "day_of_month": 1,
        })
        assert response.status_code == 201, response.text
        assert response.json()["charge_count"] >= 2, "a past start date backfills"

    async def test_the_generated_receipts_are_ordinary_receipts(self, auth_client):
        start = (datetime.now(UTC).date() - timedelta(days=40)).isoformat()
        await auth_client.post("/api/recurring", json={
            "name": "YouTube Premium", "merchant_name": "YouTube",
            "amount": 2390, "starts_on": start, "day_of_month": 1,
        })

        receipts = (await auth_client.get("/api/receipts")).json()
        assert any(r["source"] == "recurring" for r in receipts)
        assert all(r["status"] == "confirmed" for r in receipts if r["source"] == "recurring")

    async def test_running_the_generator_twice_over_the_api_is_harmless(self, auth_client):
        start = (datetime.now(UTC).date() - timedelta(days=40)).isoformat()
        await auth_client.post("/api/recurring", json={
            "name": "Spotify", "merchant_name": "Spotify",
            "amount": 1999, "starts_on": start, "day_of_month": 1,
        })
        before = len((await auth_client.get("/api/receipts")).json())

        await auth_client.post("/api/recurring/run")
        await auth_client.post("/api/recurring/run")

        assert len((await auth_client.get("/api/receipts")).json()) == before

    async def test_the_csv_export_has_a_row_per_receipt(self, auth_client):
        await auth_client.post("/api/receipts/manual", json={
            "merchant_name": "Lidl",
            "purchased_at": "2026-09-01T17:30:00Z",
            "items": [{"raw_name": "Tej", "gross_amount": 1449}],
        })

        response = await auth_client.get("/api/receipts/export.csv")
        assert response.status_code == 200
        assert "text/csv" in response.headers["content-type"]

        lines = response.text.lstrip("﻿").strip().splitlines()
        assert lines[0].startswith("Dátum;Bolt;Összeg")
        assert lines[1].startswith("2026-09-01;Lidl;1449,00"), (
            "a Hungarian Excel needs semicolons and a comma decimal"
        )

    async def test_the_export_needs_a_login(self, client):
        assert (await client.get("/api/receipts/export.csv")).status_code == 401
