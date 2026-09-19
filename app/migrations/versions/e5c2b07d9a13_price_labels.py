"""Shelf labels: prices observed without buying

Revision ID: e5c2b07d9a13
Revises: d4a91f37e2b8
Create Date: 2026-09-19

Two new tables and nothing else - no column on `receipts`, no change to anything that
feeds the spending statistics. That separation is the point of the feature: a price seen
on a shelf must never be able to reach a month's total, and the cheapest way to guarantee
that is for the spending queries to have nothing to join to.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e5c2b07d9a13"
down_revision: str | None = "d4a91f37e2b8"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "price_label_photos",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("image_path", sa.String(length=500), nullable=False),
        sa.Column("image_sha256", sa.String(length=64), nullable=False),
        sa.Column("image_bytes", sa.Integer(), nullable=True),
        sa.Column("image_mime", sa.String(length=60), nullable=False),
        sa.Column("merchant_id", sa.Uuid(), nullable=True),
        sa.Column("merchant_raw_name", sa.String(length=300), nullable=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("review_reasons", sa.JSON(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("parsed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False,
        ),
        sa.ForeignKeyConstraint(["merchant_id"], ["merchants.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_price_label_photos_image_sha256"),
        "price_label_photos", ["image_sha256"], unique=True,
    )
    op.create_index(
        op.f("ix_price_label_photos_merchant_id"), "price_label_photos", ["merchant_id"]
    )
    op.create_index(
        op.f("ix_price_label_photos_observed_at"), "price_label_photos", ["observed_at"]
    )
    op.create_index(op.f("ix_price_label_photos_status"), "price_label_photos", ["status"])

    op.create_table(
        "price_observations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("photo_id", sa.Uuid(), nullable=False),
        sa.Column("line_no", sa.Integer(), nullable=False),
        sa.Column("raw_name", sa.String(length=300), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=True),
        sa.Column("price", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("unit_price", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("unit", sa.String(length=10), nullable=True),
        sa.Column("package_size", sa.Float(), nullable=True),
        sa.Column("package_unit", sa.String(length=10), nullable=True),
        sa.Column("is_promotion", sa.Boolean(), nullable=False),
        sa.Column("regular_price", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("promotion_until", sa.Date(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False,
        ),
        sa.ForeignKeyConstraint(["photo_id"], ["price_label_photos.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_price_observations_photo_id"), "price_observations", ["photo_id"]
    )
    op.create_index(
        op.f("ix_price_observations_product_id"), "price_observations", ["product_id"]
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_price_observations_product_id"), table_name="price_observations")
    op.drop_index(op.f("ix_price_observations_photo_id"), table_name="price_observations")
    op.drop_table("price_observations")

    for index in (
        "ix_price_label_photos_status",
        "ix_price_label_photos_observed_at",
        "ix_price_label_photos_merchant_id",
        "ix_price_label_photos_image_sha256",
    ):
        op.drop_index(op.f(index), table_name="price_label_photos")
    op.drop_table("price_label_photos")
