"""Several people in one household: logins, who paid, and how a bill is split

Revision ID: e2b7c9d41f06
Revises: d8e2f4a61b93
Create Date: 2026-10-03

Purely additive. Existing receipts get no payer and no shares, which is the truthful state
- nobody recorded who paid them - and a receipt without shares takes no part in anyone's
balance, so nothing already stored changes meaning. The first login is created from
APP_PASSWORD_HASH when the app starts, not here: the hash lives in the environment, and a
migration should not read secrets.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e2b7c9d41f06"
down_revision: str | None = "d8e2f4a61b93"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("username", sa.String(length=60), nullable=False, unique=True),
        sa.Column("display_name", sa.String(length=80), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("is_admin", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                  nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                  nullable=False),
    )

    op.create_table(
        "receipt_shares",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("receipt_id", sa.Uuid(),
                  sa.ForeignKey("receipts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Uuid(),
                  sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("percent", sa.Numeric(5, 2), nullable=False),
        sa.UniqueConstraint("receipt_id", "user_id", name="uq_receipt_shares_receipt_user"),
        sa.CheckConstraint("percent >= 0 AND percent <= 100", name="ck_receipt_shares_percent"),
    )
    op.create_index("ix_receipt_shares_receipt_id", "receipt_shares", ["receipt_id"])
    op.create_index("ix_receipt_shares_user_id", "receipt_shares", ["user_id"])

    op.create_table(
        "settlements",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("from_user_id", sa.Uuid(),
                  sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("to_user_id", sa.Uuid(),
                  sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("settled_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                  nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                  nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                  nullable=False),
        sa.CheckConstraint("amount > 0", name="ck_settlements_positive"),
        sa.CheckConstraint("from_user_id <> to_user_id", name="ck_settlements_two_people"),
    )
    op.create_index("ix_settlements_from_user_id", "settlements", ["from_user_id"])
    op.create_index("ix_settlements_to_user_id", "settlements", ["to_user_id"])

    op.add_column("receipts", sa.Column("paid_by_id", sa.Uuid(), nullable=True))
    op.add_column("receipts", sa.Column("uploaded_by_id", sa.Uuid(), nullable=True))
    op.create_index("ix_receipts_paid_by_id", "receipts", ["paid_by_id"])
    op.create_foreign_key("fk_receipts_paid_by", "receipts", "users",
                          ["paid_by_id"], ["id"], ondelete="SET NULL")
    op.create_foreign_key("fk_receipts_uploaded_by", "receipts", "users",
                          ["uploaded_by_id"], ["id"], ondelete="SET NULL")


def downgrade() -> None:
    op.drop_constraint("fk_receipts_uploaded_by", "receipts", type_="foreignkey")
    op.drop_constraint("fk_receipts_paid_by", "receipts", type_="foreignkey")
    op.drop_index("ix_receipts_paid_by_id", table_name="receipts")
    op.drop_column("receipts", "uploaded_by_id")
    op.drop_column("receipts", "paid_by_id")
    op.drop_table("settlements")
    op.drop_table("receipt_shares")
    op.drop_table("users")
