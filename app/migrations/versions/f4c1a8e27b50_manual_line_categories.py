"""Mark the categories you set line by line as yours

Revision ID: f4c1a8e27b50
Revises: e2b7c9d41f06
Create Date: 2026-10-04

Choosing a category for one line on the receipt page changed the category but not
`category_source`, so the line kept the label of whatever guess it replaced, or none. The
learning rule only learns from lines marked `manual`, so it never saw those choices, and
filing a whole receipt would have treated them as guesses it was free to replace. The
endpoint is fixed; this restores the label on lines already edited.

Every such edit is in `corrections`, written only by that endpoint. A line is marked
`manual` only when its current category is exactly the last one you chose for it, so a
line you later cleared, or that changed since, is left alone. No category changes here,
only the record of who chose it.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f4c1a8e27b50"
down_revision: str | None = "e2b7c9d41f06"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE receipt_items AS item
               SET category_source = 'manual'
              FROM (
                    SELECT DISTINCT ON (item_id) item_id, new_value
                      FROM corrections
                     WHERE field = 'category_id' AND item_id IS NOT NULL
                  ORDER BY item_id, created_at DESC, id DESC
                   ) AS latest
             WHERE latest.item_id = item.id
               AND item.category_id IS NOT NULL
               AND latest.new_value = item.category_id::text
               AND item.category_source IS DISTINCT FROM 'manual'
            """
        )
    )


def downgrade() -> None:
    # Nothing to undo: the label was missing because of a bug, and putting the wrong one
    # back would only hide your choices from the learning rule again.
    pass
