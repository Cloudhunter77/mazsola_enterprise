"""Record which rule gave a line its category

Revision ID: f1a83c25d7b6
Revises: e5c2b07d9a13
Create Date: 2026-09-19

One nullable column. Existing lines get NULL, which reads correctly as "nothing has
categorised this yet" - and a line you categorised by hand before this column existed keeps
its category, because nothing here touches `category_id`.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f1a83c25d7b6"
down_revision: str | None = "e5c2b07d9a13"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "receipt_items", sa.Column("category_source", sa.String(length=12), nullable=True)
    )
    op.create_index(
        op.f("ix_receipt_items_category_source"), "receipt_items", ["category_source"]
    )
    # A line that already has a category got it from a person, one way or another: either
    # typed in, or set on the review screen, or copied from a product that a person named.
    # Marking those `manual` is what stops any automatic rule from ever overwriting them.
    op.execute(
        sa.text(
            "UPDATE receipt_items SET category_source = 'manual' WHERE category_id IS NOT NULL"
        )
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_receipt_items_category_source"), table_name="receipt_items")
    op.drop_column("receipt_items", "category_source")
