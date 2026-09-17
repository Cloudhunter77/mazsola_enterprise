"""A normalised fingerprint on product aliases, so a line spelled differently still matches

Revision ID: d4a91f37e2b8
Revises: c2f83a41b6d7
Create Date: 2026-09-17

`PEPSI 1,5L` and `Pepsi Cola 1.5 l` are one product. Recognising that on the way in means
comparing a normalised form, and comparing it needs it stored - otherwise every receipt
line re-normalises every alias in the table. Backfilled in Python rather than SQL because
the normalisation rules (accent folding, unit conversion, token sorting) live in
app/services/matching.py and must not be duplicated in a migration that will then drift.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d4a91f37e2b8"
down_revision: str | None = "c2f83a41b6d7"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("product_aliases", sa.Column("fingerprint", sa.String(length=320), nullable=True))
    op.create_index(
        op.f("ix_product_aliases_fingerprint"), "product_aliases", ["fingerprint"], unique=False
    )

    from app.services.matching import fingerprint

    connection = op.get_bind()
    rows = connection.execute(sa.text("SELECT id, raw_name FROM product_aliases")).fetchall()
    for alias_id, raw_name in rows:
        connection.execute(
            sa.text("UPDATE product_aliases SET fingerprint = :fp WHERE id = :id"),
            {"fp": fingerprint(raw_name)[:320], "id": alias_id},
        )


def downgrade() -> None:
    op.drop_index(op.f("ix_product_aliases_fingerprint"), table_name="product_aliases")
    op.drop_column("product_aliases", "fingerprint")
