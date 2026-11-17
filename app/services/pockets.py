"""Where the money in each Revolut pocket came from and went.

Everything here is derived, never stored. A pocket's balance is its opening balance, plus
the transfers that actually happened, minus the purchases paid from it - so re-filing a
receipt months later moves its forints to the right pocket, and nothing can drift out of
step with the receipts it came from.

The money inside a pocket is held in *buckets*: one per earmark (a goal, a pocket-funded
line, the wishlist's savings) and one for whatever no earmark claims. A purchase is drawn
from a bucket in date order, and only up to what the bucket holds at that moment (D27): a
sofa that costs more than was saved for it takes the whole goal, and the rest is ordinary
spending of that month, matched to the budget like any other receipt.

Which bucket pays for a receipt line:

1. a line linked to a goal or wishlist item (D30) - that earmark, in its own pocket;
2. otherwise, if the receipt was paid from a pocket - chosen on its page, or guessed because
   every line falls under one pocket line of its owner (D29) - the pocket line in that
   pocket whose categories cover the line, or else the pocket's unassigned money;
3. otherwise no pocket at all: it is everyday spending.

A purchase dated before the app started keeping a pocket's books is not drawn from it: the
opening balance already reflects it.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import (
    BudgetLine,
    Category,
    LineKind,
    Pocket,
    PocketTransfer,
    Receipt,
    ReceiptShare,
)
from app.services.stats import COUNTED_STATUSES, LOCAL_TZ, local_day_start

ZERO = Decimal("0.00")
CENT = Decimal("0.01")
UNCATEGORISED_SLUG = "besorolatlan"
# Lines of a receipt that are things paid for. Discounts and rounding are not lines of their
# own here: they are spread over these in proportion, so the lines add up to the total.
PAID_LINE_KINDS = (LineKind.ITEM.value, LineKind.FEE.value, LineKind.DEPOSIT.value)

Bucket = tuple[uuid.UUID, uuid.UUID | None]  # (pocket, earmark line or None = unassigned)


def _q(value: Decimal | int | float | None) -> Decimal:
    return (Decimal(value) if value is not None else ZERO).quantize(CENT, rounding=ROUND_HALF_UP)


# --- one receipt, split into what each line actually cost ----------------------------


@dataclass(slots=True)
class Part:
    """What one receipt line cost, its share of discounts and rounding included."""

    item_id: uuid.UUID | None
    category_id: uuid.UUID | None
    amount: Decimal
    earmark_id: uuid.UUID | None = None


def receipt_parts(receipt: Receipt, blank: set[uuid.UUID]) -> list[Part]:
    """Spread a receipt's total over its paid lines in proportion to what each cost.

    The parts are rounded to the fillér and the last one takes the remainder, so they always
    add up to exactly the total. A receipt with no paid line at all is one uncategorised part.
    """
    lines = [
        item for item in receipt.items
        if item.kind in PAID_LINE_KINDS and Decimal(item.gross_amount or 0) > 0
    ]
    paid = sum((Decimal(item.gross_amount) for item in lines), ZERO)
    total = _q(receipt.total_gross) if receipt.total_gross is not None else _q(paid)
    if paid <= 0:
        return [Part(None, None, total)]
    out: list[Part] = []
    running = ZERO
    for index, item in enumerate(lines):
        if index == len(lines) - 1:
            amount = total - running
        else:
            amount = _q(total * Decimal(item.gross_amount) / paid)
            running += amount
        out.append(Part(
            item.id,
            None if item.category_id in blank else item.category_id,
            amount,
            item.earmark_id,
        ))
    return out


# --- what the routing needs to know ----------------------------------------------------


@dataclass(slots=True)
class Context:
    parent: dict[uuid.UUID, uuid.UUID | None]
    blank: set[uuid.UUID]
    pockets: dict[uuid.UUID, Pocket]
    earmarks: dict[uuid.UUID, BudgetLine]
    # (owner, category) -> the active pocket line of that owner covering the category.
    pocket_lines: dict[tuple[uuid.UUID | None, uuid.UUID], BudgetLine]
    # (pocket, category) -> the pocket line inside that pocket covering the category.
    in_pocket: dict[tuple[uuid.UUID, uuid.UUID], BudgetLine]

    def _climb(self, table: dict, key, category: uuid.UUID | None):
        while category is not None:
            found = table.get((key, category))
            if found is not None:
                return found
            category = self.parent.get(category)
        return None

    def pocket_line_for(self, owner: uuid.UUID | None, category: uuid.UUID | None):
        return self._climb(self.pocket_lines, owner, category)

    def line_in_pocket(self, pocket_id: uuid.UUID, category: uuid.UUID | None):
        return self._climb(self.in_pocket, pocket_id, category)


async def context(session: AsyncSession) -> Context:
    categories = (await session.scalars(select(Category))).all()
    lines = (await session.scalars(select(BudgetLine))).all()
    pocket_lines: dict[tuple[uuid.UUID | None, uuid.UUID], BudgetLine] = {}
    in_pocket: dict[tuple[uuid.UUID, uuid.UUID], BudgetLine] = {}
    for line in lines:
        if line.pocket_id is None or not line.active:
            continue
        for category_id in line.category_ids:
            pocket_lines[(line.owner_id, category_id)] = line
            in_pocket[(line.pocket_id, category_id)] = line
    return Context(
        parent={c.id: c.parent_id for c in categories},
        blank={c.id for c in categories if c.slug == UNCATEGORISED_SLUG},
        pockets={p.id: p for p in (await session.scalars(select(Pocket))).all()},
        earmarks={line.id: line for line in lines if line.pocket_id is not None},
        pocket_lines=pocket_lines,
        in_pocket=in_pocket,
    )


def guessed_pocket(
    parts: list[Part], owner: uuid.UUID | None, ctx: Context
) -> uuid.UUID | None:
    """The pocket a receipt was probably paid from: when every line not already linked to a
    goal falls under a pocket line of its owner, and all of those are in the same pocket."""
    pockets = set()
    for part in parts:
        if part.earmark_id is not None:
            continue
        line = ctx.pocket_line_for(owner, part.category_id)
        if line is None:
            return None
        pockets.add(line.pocket_id)
    return pockets.pop() if len(pockets) == 1 else None


def paying_pocket(
    receipt: Receipt, parts: list[Part], owner: uuid.UUID | None, ctx: Context
) -> tuple[uuid.UUID | None, bool]:
    """The pocket a receipt was paid from, and whether that is only a guess."""
    if receipt.pocket_source == "manual":
        return receipt.pocket_id, False
    guess = guessed_pocket(parts, owner, ctx)
    return guess, guess is not None


def route(
    receipt: Receipt, parts: list[Part], owner: uuid.UUID | None, day: date, ctx: Context
) -> dict[int, tuple[Bucket, bool]]:
    """Which bucket pays for each part (by its index), for the parts a pocket pays for, and
    whether the pocket's unassigned money may cover what that bucket cannot."""
    pocket_id, _ = paying_pocket(receipt, parts, owner, ctx)
    out: dict[int, tuple[Bucket, bool]] = {}
    for index, part in enumerate(parts):
        bucket: Bucket | None = None
        fallback = False
        earmark = ctx.earmarks.get(part.earmark_id) if part.earmark_id else None
        if earmark is not None and earmark.pocket_id is not None:
            bucket = (earmark.pocket_id, earmark.id)
        elif pocket_id is not None and pocket_id in ctx.pockets:
            line = ctx.line_in_pocket(pocket_id, part.category_id)
            bucket = (pocket_id, line.id if line is not None else None)
            fallback = line is not None
        if bucket is None:
            continue
        pocket = ctx.pockets.get(bucket[0])
        if pocket is None or day < pocket.opened_on:
            continue
        out[index] = (bucket, fallback)
    return out


# --- the ledger ---------------------------------------------------------------------------


@dataclass(slots=True)
class Event:
    day: date
    bucket: Bucket
    amount: Decimal         # signed: what the bucket's balance changed by
    kind: str               # opening | transfer | draw
    receipt_id: uuid.UUID | None = None
    item_id: uuid.UUID | None = None
    merchant: str | None = None
    # For a transfer: the meeting that planned it.
    period_id: uuid.UUID | None = None
    # A purchase on a pocket line may use the pocket's unassigned money once the line's own
    # runs out; one linked to a goal may not (D34).
    fallback: bool = False


@dataclass(slots=True)
class Ledger:
    ctx: Context
    events: list[Event] = field(default_factory=list)
    # (receipt, part index) -> ([(bucket, drawn from it)], overflow back to the month)
    draws: dict[tuple[uuid.UUID, int], tuple[list[tuple[Bucket, Decimal]], Decimal]] = field(
        default_factory=dict
    )

    def balance(self, bucket: Bucket, before: date | None = None) -> Decimal:
        """A bucket's balance at the start of `before`, or now."""
        return sum(
            (e.amount for e in self.events
             if e.bucket == bucket and (before is None or e.day < before)),
            ZERO,
        )

    def pocket_balance(
        self,
        pocket_id: uuid.UUID,
        through: date | None = None,
        without_period: uuid.UUID | None = None,
    ) -> Decimal:
        """A pocket's whole balance at the end of `through`, or now - optionally without the
        transfers one meeting planned, to compare with a balance read before sending them."""
        return sum(
            (e.amount for e in self.events
             if e.bucket[0] == pocket_id and (through is None or e.day <= through)
             and (without_period is None or e.period_id != without_period)),
            ZERO,
        )

    def buckets_of(self, pocket_id: uuid.UUID) -> set[Bucket]:
        found = {e.bucket for e in self.events if e.bucket[0] == pocket_id}
        found.add((pocket_id, None))
        found.update(
            (pocket_id, line.id)
            for line in self.ctx.earmarks.values() if line.pocket_id == pocket_id
        )
        return found

    def movement(
        self, bucket: Bucket, start: date, end: date | None
    ) -> tuple[Decimal, Decimal, Decimal, list[Event]]:
        """(opening, money in, money out, the purchases) of a bucket over [start, end)."""
        opening = self.balance(bucket, start)
        inside = [
            e for e in self.events
            if e.bucket == bucket and e.day >= start and (end is None or e.day < end)
        ]
        money_in = sum((e.amount for e in inside if e.amount > 0), ZERO)
        money_out = -sum((e.amount for e in inside if e.amount < 0), ZERO)
        return opening, money_in, money_out, [e for e in inside if e.kind == "draw" and e.amount]


def _owner_of(receipt: Receipt, split_ids: set[uuid.UUID]) -> uuid.UUID | None:
    return None if receipt.id in split_ids else receipt.paid_by_id


async def ledger(session: AsyncSession, ctx: Context | None = None) -> Ledger:
    """Replay every pocket's history in date order: openings, transfers, purchases."""
    ctx = ctx or await context(session)
    out = Ledger(ctx=ctx)
    if not ctx.pockets:
        return out

    pending: list[Event] = []
    for pocket in ctx.pockets.values():
        pending.append(Event(pocket.opened_on, (pocket.id, None), _q(pocket.opening_balance),
                             "opening"))
    for transfer in (
        await session.scalars(select(PocketTransfer).where(PocketTransfer.done.is_(True)))
    ).all():
        if transfer.pocket_id in ctx.pockets:
            pending.append(Event(transfer.on, (transfer.pocket_id, transfer.line_id),
                                 _q(transfer.amount), "transfer",
                                 period_id=transfer.period_id))

    first_day = min(p.opened_on for p in ctx.pockets.values())
    receipts = (
        await session.scalars(
            select(Receipt)
            .where(Receipt.status.in_(COUNTED_STATUSES))
            .where(Receipt.purchased_at >= local_day_start(first_day))
            .options(selectinload(Receipt.items), selectinload(Receipt.merchant))
        )
    ).all()
    ids = [r.id for r in receipts]
    split_ids = set(
        (await session.scalars(
            select(ReceiptShare.receipt_id).where(ReceiptShare.receipt_id.in_(ids)).distinct()
        )).all()
    ) if ids else set()

    draws: list[tuple[Event, int]] = []
    for receipt in receipts:
        day = receipt.purchased_at.astimezone(LOCAL_TZ).date()
        parts = receipt_parts(receipt, ctx.blank)
        routed = route(receipt, parts, _owner_of(receipt, split_ids), day, ctx)
        merchant = receipt.merchant.name if receipt.merchant else receipt.merchant_raw_name
        for index, (bucket, fallback) in routed.items():
            event = Event(day, bucket, -parts[index].amount, "draw", receipt_id=receipt.id,
                          item_id=parts[index].item_id, merchant=merchant, fallback=fallback)
            draws.append((event, index))

    order = {"opening": 0, "transfer": 1, "draw": 2}
    pending.extend(event for event, _ in draws)
    index_of = {id(event): index for event, index in draws}
    running: dict[Bucket, Decimal] = defaultdict(lambda: ZERO)
    for event in sorted(pending, key=lambda e: (e.day, order[e.kind])):
        if event.kind != "draw":
            running[event.bucket] += event.amount
            out.events.append(event)
            continue
        wanted = -event.amount
        taken: list[tuple[Bucket, Decimal]] = []
        buckets = [event.bucket]
        if event.fallback:
            buckets.append((event.bucket[0], None))
        for bucket in buckets:
            drawn = min(wanted, max(running[bucket], ZERO))
            if drawn <= 0 and bucket != event.bucket:
                continue
            running[bucket] -= drawn
            wanted -= drawn
            taken.append((bucket, drawn))
            out.events.append(Event(event.day, bucket, -drawn, "draw",
                                    receipt_id=event.receipt_id, item_id=event.item_id,
                                    merchant=event.merchant))
        out.draws[(event.receipt_id, index_of[id(event)])] = (taken, wanted)
    return out


# --- planning the month's transfers -----------------------------------------------------


def months_between(start: date, end: date) -> int:
    return (end.year - start.year) * 12 + end.month - start.month


def suggestion(line: BudgetLine, balance: Decimal, month: date) -> Decimal | None:
    """What a goal needs per month from `month` on to reach its target by its date (D26)."""
    if line.target_amount is None:
        return None
    missing = Decimal(line.target_amount) - balance
    if missing <= 0:
        return ZERO
    if line.target_date is None:
        return None
    months = max(1, months_between(month, line.target_date.replace(day=1)) + 1)
    # Rounded up to a whole hundred forints: nobody transfers 8 333,33 Ft.
    hundreds = (missing / months / 100).to_integral_value(rounding="ROUND_CEILING")
    return Decimal(hundreds * 100).quantize(CENT)

