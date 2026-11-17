"""Revolut pockets, goals, transfers, and the wishlist

Revision ID: c5f2a8d1e3b9
Revises: b3e8f1c2d4a7
Create Date: 2026-11-17

Purely additive. Four new tables, and nullable columns elsewhere: a budget line can now live
in a pocket and be a goal, a receipt can be paid from a pocket, a receipt line can be the
thing a goal or a wishlist item was for, and a recurring item can be paid from a pocket.
Nothing already stored changes meaning: every existing row gets NULL, which is "the main
account" and "not linked to anything".
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c5f2a8d1e3b9"
down_revision: str | None = "b3e8f1c2d4a7"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                  nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                  nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "pockets",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("holder_id", sa.Uuid(),
                  sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("opening_balance", sa.Numeric(precision=12, scale=2), nullable=False,
                  server_default="0"),
        sa.Column("opened_on", sa.Date(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("notes", sa.Text(), nullable=True),
        *_timestamps(),
    )
    op.create_index("ix_pockets_holder_id", "pockets", ["holder_id"])

    op.add_column("budget_lines", sa.Column(
        "pocket_id", sa.Uuid(), sa.ForeignKey("pockets.id", ondelete="SET NULL"),
        nullable=True))
    op.create_index("ix_budget_lines_pocket_id", "budget_lines", ["pocket_id"])
    op.add_column("budget_lines", sa.Column(
        "target_amount", sa.Numeric(precision=12, scale=2), nullable=True))
    op.add_column("budget_lines", sa.Column("target_date", sa.Date(), nullable=True))
    op.add_column("budget_lines", sa.Column(
        "is_wishlist", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("budget_lines", sa.Column("bought_on", sa.Date(), nullable=True))

    op.create_table(
        "pocket_transfers",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("pocket_id", sa.Uuid(),
                  sa.ForeignKey("pockets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("line_id", sa.Uuid(),
                  sa.ForeignKey("budget_lines.id", ondelete="SET NULL"), nullable=True),
        sa.Column("amount", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("on", sa.Date(), nullable=False),
        sa.Column("kind", sa.String(length=10), nullable=False, server_default="manual"),
        sa.Column("done", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("done_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("from_user_id", sa.Uuid(),
                  sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("period_id", sa.Uuid(),
                  sa.ForeignKey("budget_periods.id", ondelete="SET NULL"), nullable=True),
        sa.Column("group_id", sa.Uuid(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        *_timestamps(),
    )
    for column in ("pocket_id", "line_id", "on", "done", "period_id"):
        op.create_index(f"ix_pocket_transfers_{column}", "pocket_transfers", [column])

    op.create_table(
        "pocket_checks",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("pocket_id", sa.Uuid(),
                  sa.ForeignKey("pockets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("checked_on", sa.Date(), nullable=False),
        sa.Column("balance", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("period_id", sa.Uuid(),
                  sa.ForeignKey("budget_periods.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_by_id", sa.Uuid(),
                  sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        *_timestamps(),
    )
    op.create_index("ix_pocket_checks_pocket_id", "pocket_checks", ["pocket_id"])

    op.create_table(
        "wishlist_items",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("owner_id", sa.Uuid(),
                  sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("estimated_price", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("link", sa.String(length=500), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("product_id", sa.Uuid(),
                  sa.ForeignKey("products.id", ondelete="SET NULL"), nullable=True),
        sa.Column("shopping_item_id", sa.Uuid(),
                  sa.ForeignKey("shopping_items.id", ondelete="SET NULL"), nullable=True),
        sa.Column("bought_on", sa.Date(), nullable=True),
        *_timestamps(),
    )
    op.create_index("ix_wishlist_items_owner_id", "wishlist_items", ["owner_id"])

    op.add_column("receipts", sa.Column(
        "pocket_id", sa.Uuid(), sa.ForeignKey("pockets.id", ondelete="SET NULL"),
        nullable=True))
    op.create_index("ix_receipts_pocket_id", "receipts", ["pocket_id"])
    op.add_column("receipts", sa.Column("pocket_source", sa.String(length=10), nullable=True))

    op.add_column("receipt_items", sa.Column(
        "earmark_id", sa.Uuid(), sa.ForeignKey("budget_lines.id", ondelete="SET NULL"),
        nullable=True))
    op.create_index("ix_receipt_items_earmark_id", "receipt_items", ["earmark_id"])
    op.add_column("receipt_items", sa.Column(
        "wishlist_item_id", sa.Uuid(), sa.ForeignKey("wishlist_items.id", ondelete="SET NULL"),
        nullable=True))
    op.create_index("ix_receipt_items_wishlist_item_id", "receipt_items", ["wishlist_item_id"])

    op.add_column("recurring_payments", sa.Column(
        "pocket_id", sa.Uuid(), sa.ForeignKey("pockets.id", ondelete="SET NULL"),
        nullable=True))


def downgrade() -> None:
    op.drop_column("recurring_payments", "pocket_id")
    op.drop_column("receipt_items", "wishlist_item_id")
    op.drop_column("receipt_items", "earmark_id")
    op.drop_column("receipts", "pocket_source")
    op.drop_column("receipts", "pocket_id")
    op.drop_table("wishlist_items")
    op.drop_table("pocket_checks")
    op.drop_table("pocket_transfers")
    for column in ("bought_on", "is_wishlist", "target_date", "target_amount", "pocket_id"):
        op.drop_column("budget_lines", column)
    op.drop_table("pockets")
