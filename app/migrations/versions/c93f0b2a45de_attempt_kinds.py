"""Record what each engine call was reading, not just that it was a receipt

Revision ID: c93f0b2a45de
Revises: a7d4e1f90c38
Create Date: 2026-09-23

Shelf labels and shopping-list photographs have been calling the model and recording
nothing, because an attempt could only belong to a receipt. So the Costs page has been
answering a narrower question than it appeared to - the receipt bill, presented as the bill.

`receipt_id` becomes nullable and two more subject columns join it. Existing rows are all
receipts, which is exactly what they were, so the backfill is the honest one.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c93f0b2a45de"
down_revision: str | None = "a7d4e1f90c38"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "extraction_attempts",
        sa.Column("kind", sa.String(length=16), nullable=False, server_default="receipt"),
    )
    op.create_index(op.f("ix_extraction_attempts_kind"), "extraction_attempts", ["kind"])

    op.add_column(
        "extraction_attempts", sa.Column("price_label_photo_id", sa.Uuid(), nullable=True)
    )
    op.add_column(
        "extraction_attempts", sa.Column("shopping_item_id", sa.Uuid(), nullable=True)
    )
    op.create_index(
        op.f("ix_extraction_attempts_price_label_photo_id"),
        "extraction_attempts", ["price_label_photo_id"],
    )
    op.create_index(
        op.f("ix_extraction_attempts_shopping_item_id"),
        "extraction_attempts", ["shopping_item_id"],
    )
    op.create_foreign_key(
        "fk_extraction_attempts_price_label_photo",
        "extraction_attempts", "price_label_photos",
        ["price_label_photo_id"], ["id"], ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_extraction_attempts_shopping_item",
        "extraction_attempts", "shopping_items",
        ["shopping_item_id"], ["id"], ondelete="CASCADE",
    )

    # An attempt used to require a receipt; now one of three subjects carries it.
    op.alter_column(
        "extraction_attempts", "receipt_id", existing_type=sa.Uuid(), nullable=True
    )


def downgrade() -> None:
    # Only reversible while nothing but receipts has been read; anything else has no
    # receipt to point at and cannot be represented in the old shape.
    op.execute(sa.text("DELETE FROM extraction_attempts WHERE receipt_id IS NULL"))
    op.alter_column(
        "extraction_attempts", "receipt_id", existing_type=sa.Uuid(), nullable=False
    )
    op.drop_constraint(
        "fk_extraction_attempts_shopping_item", "extraction_attempts", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_extraction_attempts_price_label_photo", "extraction_attempts", type_="foreignkey"
    )
    op.drop_index(
        op.f("ix_extraction_attempts_shopping_item_id"), table_name="extraction_attempts"
    )
    op.drop_index(
        op.f("ix_extraction_attempts_price_label_photo_id"), table_name="extraction_attempts"
    )
    op.drop_column("extraction_attempts", "shopping_item_id")
    op.drop_column("extraction_attempts", "price_label_photo_id")
    op.drop_index(op.f("ix_extraction_attempts_kind"), table_name="extraction_attempts")
    op.drop_column("extraction_attempts", "kind")
