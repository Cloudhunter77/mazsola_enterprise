"""The shopping list

Revision ID: a7d4e1f90c38
Revises: f1a83c25d7b6
Create Date: 2026-09-23

One new table. Nothing existing is touched: a shopping list is about what you are going to
buy, and must not be able to reach anything that records what you did buy.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a7d4e1f90c38"
down_revision: str | None = "f1a83c25d7b6"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "shopping_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=True),
        sa.Column("raw_name", sa.String(length=300), nullable=True),
        sa.Column("image_path", sa.String(length=500), nullable=True),
        sa.Column("image_bytes", sa.Integer(), nullable=True),
        sa.Column("image_mime", sa.String(length=60), nullable=True),
        sa.Column("quantity", sa.String(length=60), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("source", sa.String(length=10), nullable=False),
        sa.Column("status", sa.String(length=12), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("done", sa.Boolean(), nullable=False),
        sa.Column("done_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False,
        ),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_shopping_items_product_id"), "shopping_items", ["product_id"])
    op.create_index(op.f("ix_shopping_items_status"), "shopping_items", ["status"])
    op.create_index(op.f("ix_shopping_items_done"), "shopping_items", ["done"])


def downgrade() -> None:
    for index in ("ix_shopping_items_done", "ix_shopping_items_status",
                  "ix_shopping_items_product_id"):
        op.drop_index(op.f(index), table_name="shopping_items")
    op.drop_table("shopping_items")
