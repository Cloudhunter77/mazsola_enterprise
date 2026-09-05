"""Multi-part receipts: a receipt_images table, backfilled from the existing columns

Revision ID: b17c4e29d8f1
Revises: a96705bc6f65
Create Date: 2026-09-05

A receipt longer than a phone frame can hold legibly is now captured as several
overlapping photographs and read as one document. Part 0 stays mirrored in the
`receipts.image_*` columns, so nothing that already reads them needs to change and every
existing receipt is a valid one-part receipt after the backfill below.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b17c4e29d8f1"
down_revision: str | None = "a96705bc6f65"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "receipt_images",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("receipt_id", sa.Uuid(), nullable=False),
        sa.Column("part_no", sa.Integer(), nullable=False),
        sa.Column("path", sa.String(length=500), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("bytes", sa.Integer(), nullable=True),
        sa.Column("mime", sa.String(length=60), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["receipt_id"], ["receipts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("receipt_id", "part_no", name="uq_receipt_images_part"),
    )
    op.create_index(
        op.f("ix_receipt_images_receipt_id"), "receipt_images", ["receipt_id"], unique=False
    )
    op.create_index(op.f("ix_receipt_images_sha256"), "receipt_images", ["sha256"], unique=True)

    # Every receipt that already exists is a one-part receipt. Without this backfill the
    # worker would find no images for them and reprocessing an old receipt would fail.
    op.execute(
        sa.text(
            """
            INSERT INTO receipt_images
                (id, receipt_id, part_no, path, sha256, bytes, mime, created_at, updated_at)
            SELECT gen_random_uuid(), id, 0, image_path, image_sha256, image_bytes,
                   image_mime, created_at, updated_at
            FROM receipts
            """
        )
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_receipt_images_sha256"), table_name="receipt_images")
    op.drop_index(op.f("ix_receipt_images_receipt_id"), table_name="receipt_images")
    op.drop_table("receipt_images")
