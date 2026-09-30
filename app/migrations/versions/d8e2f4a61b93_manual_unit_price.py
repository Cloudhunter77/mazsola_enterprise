"""Correct the unit price of hand-typed lines that were bought more than once

Revision ID: d8e2f4a61b93
Revises: c93f0b2a45de
Create Date: 2026-09-30

Manual entry used to store a line's whole total as the price of one whenever a quantity
was typed without a unit price, so "4 tej, 1516 Ft" went into price history as milk at
1516. The entry code is fixed; this corrects the lines already stored that way.

Deliberately narrow, because this is the one migration here that changes values rather
than adding structure. A line is corrected only when every sign of the bug is present:
entered by hand (`source = 'manual'`), a quantity other than one, and a stored unit price
exactly equal to the line total - which a correctly entered line with a real quantity
cannot have. Photographed receipts, subscriptions and any unit price you typed yourself
are not touched. The gross amounts, which are what your spending totals are made of, are
not touched at all.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d8e2f4a61b93"
down_revision: str | None = "c93f0b2a45de"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE receipt_items AS item
               SET unit_price = ROUND(item.gross_amount / item.quantity, 2)
              FROM receipts AS receipt
             WHERE receipt.id = item.receipt_id
               AND receipt.source = 'manual'
               AND item.quantity IS NOT NULL
               AND item.quantity NOT IN (0, 1)
               AND item.unit_price = item.gross_amount
            """
        )
    )


def downgrade() -> None:
    # Nothing to undo: the old value was the bug, and once corrected a line cannot be told
    # apart from one entered correctly - so "restoring" would corrupt those too.
    pass
