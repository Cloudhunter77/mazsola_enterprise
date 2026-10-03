"""Who paid, how a bill divides, and who owes whom.

The balance is the thing that has to be right: it is a number one person will hand
another money over. So most of these build a small, hand-checkable history and assert the
exact forint figure, including the awkward cases - an odd total split in half, a bill the
other person paid, a settlement recorded and then taken back.
"""

from __future__ import annotations

from decimal import Decimal

from tests.conftest import TEST_API_KEY, requires_db

pytestmark = requires_db

KEY = {"X-API-Key": TEST_API_KEY}


async def household(client):
    """The owner (acting through the API key) and Petra. Returns their ids."""
    petra = (await client.post("/api/users", headers=KEY, json={
        "username": "petra", "display_name": "Petra", "password": "petra-jelszava-123",
    })).json()
    users = (await client.get("/api/users", headers=KEY)).json()
    me = next(u for u in users if u["username"] == "admin")
    return me["id"], petra["id"]


async def bill(client, total: int, merchant: str = "Aldi") -> dict:
    return (await client.post("/api/receipts/manual", headers=KEY, json={
        "merchant_name": merchant,
        "purchased_at": "2026-09-20T10:00:00Z",
        "items": [{"raw_name": "Bevásárlás", "gross_amount": total}],
    })).json()


async def split(client, receipt_id: str, paid_by: str | None, shares: dict[str, float]):
    return await client.put(f"/api/receipts/{receipt_id}/split", headers=KEY, json={
        "paid_by_id": paid_by,
        "shares": [{"user_id": u, "percent": p} for u, p in shares.items()],
    })


async def summary(client) -> dict:
    return (await client.get("/api/split/summary", headers=KEY)).json()


def net(body: dict, user_id: str) -> Decimal:
    return next(
        (Decimal(b["net"]) for b in body["balances"] if b["user_id"] == user_id), Decimal(0)
    )


class TestWhoPaid:
    async def test_whoever_enters_a_receipt_is_taken_to_have_paid(self, client):
        me, _ = await household(client)
        receipt = await bill(client, 4000)
        assert receipt["paid_by_id"] == me
        assert receipt["uploaded_by_id"] == me

    async def test_an_upload_records_its_uploader(self, client, receipt_photo):
        me, _ = await household(client)
        uploaded = (await client.post(
            "/api/receipts", headers=KEY, files={"file": ("r.jpg", receipt_photo, "image/jpeg")}
        )).json()
        detail = (await client.get(f"/api/receipts/{uploaded['id']}", headers=KEY)).json()
        assert detail["paid_by_id"] == me

    async def test_the_payer_can_be_changed(self, client):
        _, petra = await household(client)
        receipt = await bill(client, 4000)
        response = await split(client, receipt["id"], petra, {})
        assert response.json()["paid_by_id"] == petra


class TestTheBalance:
    async def test_half_of_what_i_paid_is_owed_to_me(self, client):
        me, petra = await household(client)
        receipt = await bill(client, 10000)
        response = await split(client, receipt["id"], me, {me: 50, petra: 50})
        assert response.status_code == 200
        assert [Decimal(s["amount"]) for s in response.json()["shares"]] == [
            Decimal("5000.00"), Decimal("5000.00")
        ]

        body = await summary(client)
        assert net(body, me) == Decimal("5000.00")
        assert net(body, petra) == Decimal("-5000.00")
        assert body["transfers"] == [{
            "from_user_id": petra, "from_name": "Petra",
            "to_user_id": me, "to_name": "admin", "amount": "5000.00",
        }]

    async def test_bills_either_of_us_paid_net_off(self, client):
        me, petra = await household(client)
        mine = await bill(client, 10000)
        hers = await bill(client, 6000)
        await split(client, mine["id"], me, {me: 50, petra: 50})
        await split(client, hers["id"], petra, {me: 50, petra: 50})

        assert net(await summary(client), me) == Decimal("2000.00")

    async def test_an_uneven_split(self, client):
        me, petra = await household(client)
        receipt = await bill(client, 10000)
        await split(client, receipt["id"], me, {me: 70, petra: 30})
        assert net(await summary(client), petra) == Decimal("-3000.00")

    async def test_an_odd_total_halves_to_the_filler(self, client):
        me, petra = await household(client)
        receipt = await bill(client, 999)
        await split(client, receipt["id"], me, {me: 50, petra: 50})
        assert net(await summary(client), me) == Decimal("499.50")

    async def test_a_bill_nobody_split_owes_nothing(self, client):
        me, _ = await household(client)
        await bill(client, 10000)
        body = await summary(client)
        assert body["balances"] == [] and body["transfers"] == [] and body["receipts"] == []

    async def test_paying_for_the_other_person_entirely(self, client):
        """Petra's 100% of a bill I paid: she owes me all of it."""
        me, petra = await household(client)
        receipt = await bill(client, 3000)
        await split(client, receipt["id"], me, {petra: 100})
        assert net(await summary(client), me) == Decimal("3000.00")

    async def test_resplitting_changes_the_answer(self, client):
        """Nothing is stored as a running total, so a correction simply takes effect."""
        me, petra = await household(client)
        receipt = await bill(client, 10000)
        await split(client, receipt["id"], me, {me: 50, petra: 50})
        await split(client, receipt["id"], me, {me: 80, petra: 20})
        assert net(await summary(client), me) == Decimal("2000.00")


class TestSettlingUp:
    async def test_a_settlement_evens_the_balance(self, client):
        me, petra = await household(client)
        receipt = await bill(client, 10000)
        await split(client, receipt["id"], me, {me: 50, petra: 50})

        settled = await client.post("/api/split/settlements", headers=KEY, json={
            "from_user_id": petra, "to_user_id": me, "amount": 5000,
        })
        assert settled.status_code == 201
        body = await summary(client)
        assert net(body, me) == 0 and body["transfers"] == []

    async def test_a_mistaken_settlement_can_be_taken_back(self, client):
        me, petra = await household(client)
        receipt = await bill(client, 10000)
        await split(client, receipt["id"], me, {me: 50, petra: 50})
        settled = (await client.post("/api/split/settlements", headers=KEY, json={
            "from_user_id": petra, "to_user_id": me, "amount": 5000,
        })).json()

        await client.delete(f"/api/split/settlements/{settled['id']}", headers=KEY)
        assert net(await summary(client), me) == Decimal("5000.00")

    async def test_settling_with_yourself_or_nothing_is_refused(self, client):
        me, _ = await household(client)
        to_self = await client.post("/api/split/settlements", headers=KEY, json={
            "from_user_id": me, "to_user_id": me, "amount": 100,
        })
        nothing = await client.post("/api/split/settlements", headers=KEY, json={
            "from_user_id": me, "to_user_id": me, "amount": 0,
        })
        assert to_self.status_code == 422 and nothing.status_code == 422


class TestWhatASplitMayBe:
    async def test_the_parts_must_add_up_to_everything(self, client):
        me, petra = await household(client)
        receipt = await bill(client, 10000)
        response = await split(client, receipt["id"], me, {me: 50, petra: 40})
        assert response.status_code == 422

    async def test_a_split_needs_a_payer(self, client):
        me, petra = await household(client)
        receipt = await bill(client, 10000)
        response = await split(client, receipt["id"], None, {me: 50, petra: 50})
        assert response.status_code == 422

    async def test_the_payer_carrying_it_all_is_no_split(self, client):
        """Otherwise it would sit among the shared bills with nothing to settle."""
        me, petra = await household(client)
        receipt = await bill(client, 10000)
        response = await split(client, receipt["id"], me, {me: 100, petra: 0})
        assert response.json()["shares"] == []

    async def test_clearing_the_shares_unsplits_a_bill(self, client):
        me, petra = await household(client)
        receipt = await bill(client, 10000)
        await split(client, receipt["id"], me, {me: 50, petra: 50})
        await split(client, receipt["id"], me, {})
        assert (await summary(client))["receipts"] == []
