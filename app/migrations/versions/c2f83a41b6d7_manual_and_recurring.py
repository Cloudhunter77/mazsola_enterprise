"""Typed-in receipts and recurring payments

Revision ID: c2f83a41b6d7
Revises: b17c4e29d8f1
Create Date: 2026-09-06

Two things that are spending but never produced a photograph: a receipt you lost but still
remember, and a subscription that never printed one. Both become ordinary `receipts` rows
so the dashboard, price history and basket comparison need no special case - which is why
the image columns have to become nullable rather than a new table appearing beside them.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c2f83a41b6d7"
down_revision: str | None = "b17c4e29d8f1"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    # Postgres permits any number of NULLs under a unique index, so receipts with no image
    # do not collide on image_sha256.
    op.alter_column("receipts", "image_path", existing_type=sa.String(500), nullable=True)
    op.alter_column("receipts", "image_sha256", existing_type=sa.String(64), nullable=True)

    op.create_table(
        "recurring_payments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("merchant_name", sa.String(length=300), nullable=False),
        sa.Column("merchant_id", sa.Uuid(), nullable=True),
        sa.Column("category_id", sa.Uuid(), nullable=True),
        sa.Column("amount", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("cadence", sa.String(length=10), nullable=False),
        sa.Column("day_of_month", sa.Integer(), nullable=False),
        sa.Column("month_of_year", sa.Integer(), nullable=True),
        sa.Column("payment_method", sa.String(length=10), nullable=False),
        sa.Column("starts_on", sa.Date(), nullable=False),
        sa.Column("ends_on", sa.Date(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False,
        ),
        sa.ForeignKeyConstraint(["merchant_id"], ["merchants.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["category_id"], ["categories.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "recurring_charges",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("recurring_id", sa.Uuid(), nullable=False),
        sa.Column("period", sa.Date(), nullable=False),
        sa.Column("receipt_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False,
        ),
        sa.ForeignKeyConstraint(["recurring_id"], ["recurring_payments.id"], ondelete="CASCADE"),
        # SET NULL, not CASCADE: deleting a generated receipt must not make the period look
        # unbilled, or the next pass would recreate exactly what was just deleted.
        sa.ForeignKeyConstraint(["receipt_id"], ["receipts.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("recurring_id", "period", name="uq_recurring_charge"),
    )
    op.create_index(
        op.f("ix_recurring_charges_recurring_id"), "recurring_charges", ["recurring_id"]
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_recurring_charges_recurring_id"), table_name="recurring_charges")
    op.drop_table("recurring_charges")
    op.drop_table("recurring_payments")

    # Only reversible while no typed-in receipt exists; those rows have no image to restore.
    op.execute(sa.text("DELETE FROM receipts WHERE image_path IS NULL"))
    op.alter_column("receipts", "image_sha256", existing_type=sa.String(64), nullable=False)
    op.alter_column("receipts", "image_path", existing_type=sa.String(500), nullable=False)
