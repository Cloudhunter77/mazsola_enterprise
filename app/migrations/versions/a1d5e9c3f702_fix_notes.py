"""Notes about what to change in the app, with an optional screenshot

Revision ID: a1d5e9c3f702
Revises: f4c1a8e27b50
Create Date: 2026-11-01

A new table and nothing else.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a1d5e9c3f702"
down_revision: str | None = "f4c1a8e27b50"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "fix_notes",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("text", sa.Text(), nullable=False, server_default=""),
        sa.Column("image_path", sa.String(length=500), nullable=True),
        sa.Column("image_mime", sa.String(length=60), nullable=True),
        sa.Column("created_by_id", sa.Uuid(),
                  sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("done", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("done_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                  nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                  nullable=False),
    )
    op.create_index("ix_fix_notes_done", "fix_notes", ["done"])


def downgrade() -> None:
    op.drop_table("fix_notes")
