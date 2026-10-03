"""Who paid, who carries which part, and who owes whom.

A split receipt has a payer and a set of shares that add up to 100%. The payer handed
over the whole total; every other share is money owed to them. The balance is computed
fresh from the receipts and settlements every time - never stored - so correcting a total
or re-splitting a bill months later simply changes the answer, rather than leaving a
running figure that quietly disagrees with the receipts it came from.

A receipt with no shares is not split and takes no part in any balance, whoever paid it.
That is every receipt from before there were several people, which is right: nobody
agreed to share those.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Merchant, Receipt, ReceiptShare, ReceiptStatus, Settlement, User

HUNDRED = Decimal("100")
CENT = Decimal("0.01")

# Receipts that count towards spending count towards the balance too, so the two never
# disagree about whether a bill happened.
COUNTED = (
    ReceiptStatus.PARSED.value,
    ReceiptStatus.NEEDS_REVIEW.value,
    ReceiptStatus.CONFIRMED.value,
)


class SplitError(ValueError):
    """A split that cannot be stored as asked; the message says why, for the screen."""


async def set_split(
    session: AsyncSession,
    receipt: Receipt,
    paid_by_id: uuid.UUID | None,
    shares: list[tuple[uuid.UUID, Decimal]],
) -> None:
    """Record who paid and how the bill is divided. An empty `shares` means not split."""
    users = {
        user.id: user for user in (await session.scalars(select(User))).all()
    }
    if paid_by_id is not None and paid_by_id not in users:
        raise SplitError("Nincs ilyen felhasználó.")

    cleaned: dict[uuid.UUID, Decimal] = {}
    for user_id, percent in shares:
        if user_id not in users:
            raise SplitError("Nincs ilyen felhasználó.")
        percent = Decimal(percent).quantize(CENT)
        if percent < 0 or percent > HUNDRED:
            raise SplitError("Egy rész 0 és 100% között lehet.")
        cleaned[user_id] = cleaned.get(user_id, Decimal(0)) + percent

    if cleaned:
        if paid_by_id is None:
            raise SplitError("Megosztáshoz tudni kell, ki fizetett.")
        if sum(cleaned.values()) != HUNDRED:
            raise SplitError("A részeknek együtt 100%-ot kell kiadniuk.")
        # A split where the payer carries everything is no split; store it as none, so it
        # does not show up among the shared bills with nothing to settle.
        if cleaned.get(paid_by_id) == HUNDRED:
            cleaned = {}

    receipt.paid_by_id = paid_by_id
    await session.execute(delete(ReceiptShare).where(ReceiptShare.receipt_id == receipt.id))
    for user_id, percent in cleaned.items():
        if percent > 0:
            session.add(ReceiptShare(receipt_id=receipt.id, user_id=user_id, percent=percent))


async def shares_of(session: AsyncSession, receipt_id: uuid.UUID) -> list[ReceiptShare]:
    return list(
        (
            await session.scalars(
                select(ReceiptShare).where(ReceiptShare.receipt_id == receipt_id)
            )
        ).all()
    )


def owed(total: Decimal, percent: Decimal) -> Decimal:
    return (total * percent / HUNDRED).quantize(CENT, rounding=ROUND_HALF_UP)


@dataclass(slots=True)
class Transfer:
    from_user_id: uuid.UUID
    to_user_id: uuid.UUID
    amount: Decimal


@dataclass(slots=True)
class Balance:
    # Positive: the household owes this person. Negative: they owe the household.
    net: dict[uuid.UUID, Decimal] = field(default_factory=dict)
    # The fewest payments that would even everything out.
    transfers: list[Transfer] = field(default_factory=list)


async def balance(session: AsyncSession) -> Balance:
    net: dict[uuid.UUID, Decimal] = {}

    rows = (
        await session.execute(
            select(Receipt.paid_by_id, Receipt.total_gross, ReceiptShare.user_id,
                   ReceiptShare.percent)
            .join(ReceiptShare, ReceiptShare.receipt_id == Receipt.id)
            .where(Receipt.status.in_(COUNTED))
            .where(Receipt.paid_by_id.is_not(None))
            .where(Receipt.total_gross.is_not(None))
        )
    ).all()
    for paid_by, total, user_id, percent in rows:
        if user_id == paid_by:
            continue  # your own share of what you paid is not owed to anyone
        amount = owed(Decimal(total), Decimal(percent))
        net[paid_by] = net.get(paid_by, Decimal(0)) + amount
        net[user_id] = net.get(user_id, Decimal(0)) - amount

    for from_id, to_id, amount in (
        await session.execute(
            select(Settlement.from_user_id, Settlement.to_user_id, Settlement.amount)
        )
    ).all():
        net[from_id] = net.get(from_id, Decimal(0)) + Decimal(amount)
        net[to_id] = net.get(to_id, Decimal(0)) - Decimal(amount)

    return Balance(net=net, transfers=_transfers(net))


def _transfers(net: dict[uuid.UUID, Decimal]) -> list[Transfer]:
    """Pair whoever owes most with whoever is owed most, until everyone is even.

    With two people this is simply "A pays B the difference"; with more it keeps the number
    of payments small. Amounts under one forint are left alone - a cash transfer cannot
    carry them, and showing "tartozol 0,40 Ft" would be noise.
    """
    # [amount still to pay or receive, who], largest first.
    debts = sorted(([-v, k] for k, v in net.items() if v < -CENT), reverse=True)
    credits = sorted(([v, k] for k, v in net.items() if v > CENT), reverse=True)
    transfers: list[Transfer] = []
    d = c = 0
    while d < len(debts) and c < len(credits):
        amount = min(debts[d][0], credits[c][0])
        if amount >= 1:
            transfers.append(Transfer(debts[d][1], credits[c][1], amount.quantize(CENT)))
        debts[d][0] -= amount
        credits[c][0] -= amount
        if debts[d][0] <= CENT:
            d += 1
        if credits[c][0] <= CENT:
            c += 1
    return transfers


async def split_receipts(session: AsyncSession, limit: int = 100) -> list[dict]:
    """The shared bills, newest first, each with its shares in forints as well as percent."""
    receipts = (
        await session.execute(
            select(Receipt, Merchant.name)
            .outerjoin(Merchant, Merchant.id == Receipt.merchant_id)
            .where(Receipt.id.in_(select(ReceiptShare.receipt_id)))
            .where(Receipt.status.in_(COUNTED))
            .order_by(Receipt.purchased_at.desc().nulls_last())
            .limit(limit)
        )
    ).all()
    ids = [receipt.id for receipt, _ in receipts]
    shares: dict[uuid.UUID, list[ReceiptShare]] = {}
    for share in (
        await session.scalars(select(ReceiptShare).where(ReceiptShare.receipt_id.in_(ids)))
    ).all():
        shares.setdefault(share.receipt_id, []).append(share)

    return [
        {
            "receipt_id": receipt.id,
            "purchased_at": receipt.purchased_at,
            "merchant_name": merchant_name or receipt.merchant_raw_name,
            "total_gross": receipt.total_gross,
            "paid_by_id": receipt.paid_by_id,
            "shares": [
                {
                    "user_id": share.user_id,
                    "percent": share.percent,
                    "amount": owed(Decimal(receipt.total_gross or 0), Decimal(share.percent)),
                }
                for share in shares.get(receipt.id, [])
            ],
        }
        for receipt, merchant_name in receipts
    ]
