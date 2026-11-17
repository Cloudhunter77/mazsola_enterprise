"""Revolut pockets, goals and the wishlist.

The rules worth defending are the ones that could quietly put a forint in the wrong place:

- a pocket's balance is only what actually reached it: a planned transfer nobody sent does
  not count;
- a purchase paid from a pocket is the pocket's, never also the month's;
- a pocket pays only up to what it holds, and the rest is ordinary spending of that month;
- a goal's purchase draws from the goal, and only the lines that were the goal's thing;
- a choice made by a person always beats a guess.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, time
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models import (
    BudgetLine,
    Category,
    Pocket,
    PocketTransfer,
    Receipt,
    RecurringPayment,
    User,
)
from app.services import budget
from app.services import pockets as pk
from app.services.manual import create_manual_receipt
from app.services.recurring import materialise_due
from app.services.splits import set_split
from app.services.stats import LOCAL_TZ
from tests.conftest import requires_db

pytestmark = requires_db

TODAY = date(2026, 11, 17)
START = date(2026, 10, 1)


async def person(session, name: str) -> User:
    user = User(username=name.lower(), display_name=name, password_hash="x")
    session.add(user)
    await session.flush()
    return user


async def category(session, name: str, parent: Category | None = None) -> Category:
    row = Category(name=name, slug=f"{name.lower()}-{uuid.uuid4().hex[:6]}",
                   parent_id=parent.id if parent else None)
    session.add(row)
    await session.flush()
    return row


async def pocket(session, name: str, holder: User | None = None, opening: float = 0,
                 opened_on: date = START) -> Pocket:
    row = Pocket(name=name, holder_id=holder.id if holder else None,
                 opening_balance=Decimal(str(opening)), opened_on=opened_on)
    session.add(row)
    await session.flush()
    return row


async def earmark(session, name: str, into: Pocket, *, owner: User | None = None,
                  categories: list[Category] = (), kind: str = "valtozo",
                  target: float | None = None, by: date | None = None,
                  amount: float | None = None, wishlist: bool = False) -> BudgetLine:
    line = BudgetLine(name=name, owner_id=owner.id if owner else None, kind=kind, active=True,
                      pocket_id=into.id, is_wishlist=wishlist,
                      target_amount=Decimal(str(target)) if target else None, target_date=by)
    session.add(line)
    await session.flush()
    await budget.set_line_categories(session, line, [c.id for c in categories])
    if amount is not None:
        await budget.set_amount(session, line, START, Decimal(str(amount)))
    return line


async def deposit(session, into: Pocket, amount: float, line: BudgetLine | None = None,
                  on: date = START, done: bool = True) -> PocketTransfer:
    transfer = PocketTransfer(pocket_id=into.id, line_id=line.id if line else None,
                              amount=Decimal(str(amount)), on=on, kind="manual", done=done)
    session.add(transfer)
    await session.flush()
    return transfer


async def receipt(session, day: date, lines: list[tuple[float, Category | None]], *,
                  paid_by: User | None = None, from_pocket: Pocket | None | str = "guess",
                  merchant: str = "Bolt") -> Receipt:
    stored = await create_manual_receipt(
        session, merchant_name=merchant,
        purchased_at=datetime.combine(day, time(12, 0), tzinfo=LOCAL_TZ),
        items=[{"raw_name": f"tétel {i}", "gross_amount": amount,
                "category_id": cat.id if cat else None}
               for i, (amount, cat) in enumerate(lines, start=1)],
    )
    if paid_by is not None:
        await set_split(session, stored, paid_by.id, [])
    if from_pocket != "guess":
        stored.pocket_id = from_pocket.id if from_pocket else None
        stored.pocket_source = "manual"
    await session.flush()
    return stored


async def balance(session, bucket) -> Decimal:
    return (await pk.ledger(session)).balance(bucket)


async def october(session):
    await budget.open_period(session, starts_on=START, month=START, user_id=None, today=TODAY)
    return (await budget.periods(session))[-1]


def actual(view: budget.MonthView, name: str, owner=None) -> Decimal | None:
    return next(r.actual for r in view.rows if r.name == name and r.owner_id == owner)


class TestBalance:
    async def test_only_money_that_arrived_counts(self, session):
        savings = await pocket(session, "Savings", opening=1000)
        await deposit(session, savings, 500)
        await deposit(session, savings, 9999, done=False)  # planned, never sent
        assert await balance(session, (savings.id, None)) == Decimal("1500.00")

    async def test_a_purchase_from_the_pocket_draws_it_down(self, session):
        trips = await pocket(session, "Kirándulás", opening=20000)
        food = await category(session, "Élelmiszer")
        await receipt(session, date(2026, 10, 5), [(3000, food)], from_pocket=trips)
        assert await balance(session, (trips.id, None)) == Decimal("17000.00")

    async def test_a_purchase_before_the_books_were_opened_is_not_drawn(self, session):
        trips = await pocket(session, "Kirándulás", opening=20000, opened_on=date(2026, 10, 10))
        await receipt(session, date(2026, 10, 5), [(3000, None)], from_pocket=trips)
        assert await balance(session, (trips.id, None)) == Decimal("20000.00")

    async def test_a_pocket_pays_only_what_it_holds(self, session):
        """The rest is ordinary spending of that month, on its category's line (D27)."""
        trips = await pocket(session, "Kirándulás", opening=1000)
        food = await category(session, "Élelmiszer")
        kaja = BudgetLine(name="Kaja", kind="valtozo", active=True)
        session.add(kaja)
        await session.flush()
        await budget.set_line_categories(session, kaja, [food.id])
        span = await october(session)
        await receipt(session, date(2026, 10, 5), [(2500, food)], from_pocket=trips)

        view = await budget.month_view(session, span, TODAY)
        assert actual(view, "Kaja") == Decimal("1500.00")
        assert await balance(session, (trips.id, None)) == Decimal("0.00")


class TestWhichPocket:
    async def test_a_receipt_all_under_a_pocket_line_is_guessed_into_it(self, session):
        balazs = await person(session, "Balázs")
        hobby = await category(session, "Hobbi")
        projects = await pocket(session, "Hobby/projektek", holder=balazs, opening=50000)
        line = await earmark(session, "Hobbi", projects, owner=balazs, categories=[hobby])
        await deposit(session, projects, 10000, line)
        span = await october(session)
        await receipt(session, date(2026, 10, 5), [(4000, hobby)], paid_by=balazs)

        assert await balance(session, (projects.id, line.id)) == Decimal("6000.00")
        view = await budget.month_view(session, span, TODAY)
        assert not any(r.type == "unplanned" for r in view.rows), "not the month's spending"

    async def test_a_pocket_line_uses_the_pockets_unassigned_money_next(self, session):
        """The pocket pays up to its whole balance; a goal would not (D34)."""
        balazs = await person(session, "Balázs")
        hobby = await category(session, "Hobbi")
        projects = await pocket(session, "Hobby/projektek", holder=balazs, opening=5000)
        line = await earmark(session, "Hobbi", projects, owner=balazs, categories=[hobby])
        await deposit(session, projects, 1000, line)
        await receipt(session, date(2026, 10, 5), [(4000, hobby)], paid_by=balazs)

        led = await pk.ledger(session)
        assert led.balance((projects.id, line.id)) == Decimal("0.00")
        assert led.balance((projects.id, None)) == Decimal("2000.00")

    async def test_a_mixed_receipt_is_not_guessed_but_flagged(self, session):
        balazs = await person(session, "Balázs")
        hobby, food = await category(session, "Hobbi"), await category(session, "Élelmiszer")
        projects = await pocket(session, "Hobby/projektek", holder=balazs, opening=50000)
        await earmark(session, "Hobbi", projects, owner=balazs, categories=[hobby])
        span = await october(session)
        mixed = await receipt(session, date(2026, 10, 5), [(4000, hobby), (900, food)],
                              paid_by=balazs)

        view = await budget.month_view(session, span, TODAY)
        assert list(view.spending.maybe_pocket) == [mixed.id]
        assert await balance(session, (projects.id, None)) == Decimal("50000.00")

    async def test_choosing_the_main_account_beats_the_guess(self, session):
        balazs = await person(session, "Balázs")
        hobby = await category(session, "Hobbi")
        projects = await pocket(session, "Hobby/projektek", holder=balazs, opening=50000)
        line = await earmark(session, "Hobbi", projects, owner=balazs, categories=[hobby])
        await deposit(session, projects, 10000, line)
        await receipt(session, date(2026, 10, 5), [(4000, hobby)], paid_by=balazs,
                      from_pocket=None)
        assert await balance(session, (projects.id, line.id)) == Decimal("10000.00")


class TestGoals:
    async def test_only_the_goals_lines_draw_from_it(self, session):
        electronics = await category(session, "Elektronika")
        savings = await pocket(session, "Savings", opening=0)
        camera = await earmark(session, "Fényképezőgép", savings, kind="celalap",
                               target=300000, by=date(2027, 3, 1))
        await deposit(session, savings, 280000, camera)
        bought = await receipt(session, date(2026, 10, 20),
                               [(270000, electronics), (9000, electronics)])
        bought.items[0].earmark_id = camera.id  # the camera, not the SD card
        await session.flush()

        assert await balance(session, (savings.id, camera.id)) == Decimal("10000.00")

    def test_the_suggestion_spreads_what_is_missing_over_the_months_left(self):
        goal = BudgetLine(name="Kanapé", target_amount=Decimal("300000"),
                          target_date=date(2027, 3, 15))
        # November to March is five months; 250 000 missing.
        assert pk.suggestion(goal, Decimal("50000"), date(2026, 11, 1)) == Decimal("50000.00")
        assert pk.suggestion(goal, Decimal("300000"), date(2026, 11, 1)) == Decimal("0.00")

    def test_the_suggestion_rounds_up_to_a_hundred(self):
        goal = BudgetLine(name="Kanapé", target_amount=Decimal("100000"),
                          target_date=date(2027, 1, 1))
        assert pk.suggestion(goal, Decimal("0"), date(2026, 11, 1)) == Decimal("33400.00")

    async def test_a_bought_goals_leftover_moves_to_another(self, session):
        savings = await pocket(session, "Savings")
        camera = await earmark(session, "Fényképezőgép", savings, kind="celalap", target=1)
        sofa = await earmark(session, "Kanapé", savings, kind="celalap", target=1)
        await deposit(session, savings, 20000, camera)

        moved = await budget.settle_goal(session, camera, today=TODAY, move_to=sofa.id)
        assert moved == Decimal("20000.00")
        assert await balance(session, (savings.id, sofa.id)) == Decimal("20000.00")
        assert camera.active is False and camera.bought_on == TODAY

    async def test_a_released_leftover_leaves_the_pocket(self, session):
        savings = await pocket(session, "Savings")
        camera = await earmark(session, "Fényképezőgép", savings, kind="celalap", target=1)
        await deposit(session, savings, 20000, camera)
        await budget.settle_goal(session, camera, today=TODAY, release=True)
        assert (await pk.ledger(session)).pocket_balance(savings.id) == Decimal("0.00")


class TestTheMeeting:
    async def test_each_person_sends_their_share_of_a_shared_goal(self, session):
        balazs, petra = await person(session, "Balázs"), await person(session, "Petra")
        hobby = await category(session, "Hobbi")
        savings = await pocket(session, "Savings", holder=balazs)
        projects = await pocket(session, "Hobby/projektek", holder=balazs)
        await earmark(session, "Kanapé", savings, kind="celalap", target=1, amount=30001)
        await earmark(session, "Hobbi", projects, owner=balazs, categories=[hobby],
                      amount=20000)

        found = await budget.proposed_transfers(session, START, [balazs.id, petra.id])
        sent = {(t.line.name, t.from_user_id): t.amount for t in found}
        assert sent[("Kanapé", balazs.id)] + sent[("Kanapé", petra.id)] == Decimal("30001.00")
        assert sent[("Hobbi", balazs.id)] == Decimal("20000.00")
        assert ("Hobbi", petra.id) not in sent

    async def test_an_unticked_transfer_waits_until_it_is_sent(self, session):
        balazs = await person(session, "Balázs")
        savings = await pocket(session, "Savings", holder=balazs)
        sofa = await earmark(session, "Kanapé", savings, kind="celalap", target=1)
        await budget.open_period(
            session, starts_on=date(2026, 11, 3), month=None, user_id=None, today=TODAY,
            transfers=[budget.TransferIn(sofa.id, balazs.id, Decimal("30000"), False)],
            checks=[(savings.id, Decimal("0"))],
        )
        assert await balance(session, (savings.id, sofa.id)) == Decimal("0.00")
        [waiting] = await budget.pending_transfers(session)

        await budget.mark_transfer_done(session, waiting, TODAY)
        assert await balance(session, (savings.id, sofa.id)) == Decimal("30000.00")
        assert await budget.pending_transfers(session) == []

    async def test_a_check_at_the_meeting_ignores_that_meetings_transfers(self, session):
        """You read Revolut before sending the money, not after."""
        balazs = await person(session, "Balázs")
        savings = await pocket(session, "Savings", holder=balazs, opening=1000)
        sofa = await earmark(session, "Kanapé", savings, kind="celalap", target=1)
        await budget.open_period(
            session, starts_on=date(2026, 11, 3), month=None, user_id=None, today=TODAY,
            transfers=[budget.TransferIn(sofa.id, balazs.id, Decimal("30000"), True)],
            checks=[(savings.id, Decimal("1000"))],
        )
        span = (await budget.periods(session))[-1]
        [view] = (await budget.month_view(session, span, TODAY)).pockets
        assert view.check.balance - view.expected_at_check == Decimal("0.00")

    async def test_a_revolut_check_shows_the_difference(self, session):
        savings = await pocket(session, "Savings", opening=1000)
        await budget.record_check(session, savings.id, Decimal("1200"), TODAY, None)
        span = await october(session)
        [view] = (await budget.month_view(session, span, TODAY)).pockets
        assert view.check.balance - view.expected_at_check == Decimal("200.00")


class TestRecurringFromAPocket:
    async def test_it_plans_nothing_and_its_bills_draw_from_the_pocket(self, session):
        tmcs = await pocket(session, "TMCS", opening=10000)
        session.add(RecurringPayment(
            name="Netflix", merchant_name="Netflix", amount=Decimal("4000"), currency="HUF",
            cadence="monthly", day_of_month=5, payment_method="card",
            starts_on=date(2026, 10, 1), active=True, pocket_id=tmcs.id,
        ))
        await session.flush()
        await materialise_due(session, today=date(2026, 10, 31))

        assert await balance(session, (tmcs.id, None)) == Decimal("6000.00")
        grid = await budget.plan_grid(session, START, 1)
        assert not any(r.type == "recurring" for r in grid.rows)


class TestOverHttp:
    async def test_a_wishlist_item_bought_without_a_receipt(self, auth_client, session):
        savings = await pocket(session, "Savings", opening=0)
        pot = await earmark(session, "Kívánságlista", savings, kind="celalap", wishlist=True)
        await deposit(session, savings, 50000, pot)
        await session.commit()

        item = (await auth_client.post("/api/wishlist", json={
            "name": "Porszívó", "priority": 1, "estimated_price": "40000",
        })).json()
        assert item["priority_label"] == "Alacsony" and item["earmark_id"] == str(pot.id)

        listed = (await auth_client.post(f"/api/wishlist/{item['id']}/to-list")).json()
        assert listed["on_list"] is True

        bought = await auth_client.post("/api/pockets/purchase", json={
            "wishlist_item_id": item["id"], "price": "38990", "on": "2026-11-10",
        })
        assert bought.status_code == 201, bought.text
        [after] = (await auth_client.get("/api/wishlist")).json()
        assert after["bought_on"] == "2026-11-10"
        assert Decimal(after["actual_price"]) == Decimal("38990")
        assert await balance(session, (savings.id, pot.id)) == Decimal("11010.00")

    async def test_choosing_a_pocket_on_the_receipt_page(self, auth_client, session):
        trips = await pocket(session, "Kirándulás", opening=10000)
        food = await category(session, "Élelmiszer")
        stored = await receipt(session, date(2026, 10, 5), [(2000, food)])
        await session.commit()

        chosen = await auth_client.put(f"/api/receipts/{stored.id}/pocket",
                                       json={"pocket_id": str(trips.id)})
        assert chosen.json()["pocket_source"] == "manual"
        assert await balance(session, (trips.id, None)) == Decimal("8000.00")

        back = await auth_client.put(f"/api/receipts/{stored.id}/pocket", json={"auto": True})
        assert back.json()["pocket_source"] is None

    async def test_linking_lines_to_a_goal(self, auth_client, session):
        electronics = await category(session, "Elektronika")
        savings = await pocket(session, "Savings")
        camera = await earmark(session, "Fényképezőgép", savings, kind="celalap", target=1)
        await deposit(session, savings, 300000, camera)
        stored = await receipt(session, date(2026, 10, 20),
                               [(270000, electronics), (9000, electronics)])
        await session.commit()

        linked = await auth_client.put(f"/api/receipts/{stored.id}/links", json={
            "item_ids": [str(stored.items[0].id)], "earmark_id": str(camera.id),
        })
        assert linked.status_code == 200, linked.text
        items = {i["raw_name"]: i["earmark_id"] for i in linked.json()["items"]}
        assert items == {"tétel 1": str(camera.id), "tétel 2": None}

    async def test_a_goal_starts_at_its_suggestion(self, auth_client, session):
        savings = await pocket(session, "Savings", opening=60000)
        await session.commit()
        created = await auth_client.post("/api/budget/lines", json={
            "name": "Kanapé", "kind": "celalap", "pocket_id": str(savings.id),
            "target_amount": "300000", "target_date": "2027-03-01",
            "saved_amount": "50000", "from_month": "2026-11-01",
        })
        assert created.status_code == 201, created.text
        line = await session.scalar(select(BudgetLine).where(BudgetLine.name == "Kanapé"))
        grid = await budget.plan_grid(session, date(2026, 11, 1), 1)
        row = next(r for r in grid.rows if r.id == line.id)
        assert row.amounts[0][0] == Decimal("50000.00")  # 250 000 over Nov-Mar
        assert await balance(session, (savings.id, line.id)) == Decimal("50000.00")
        assert await balance(session, (savings.id, None)) == Decimal("10000.00")

    async def test_a_goal_needs_a_pocket(self, auth_client):
        refused = await auth_client.post("/api/budget/lines", json={
            "name": "Kanapé", "kind": "celalap", "target_amount": "300000",
        })
        assert refused.status_code == 422

    @pytest.mark.parametrize("path", ["/api/pockets/overview", "/api/wishlist"])
    async def test_the_pages_load_empty(self, auth_client, path):
        assert (await auth_client.get(path)).status_code == 200
