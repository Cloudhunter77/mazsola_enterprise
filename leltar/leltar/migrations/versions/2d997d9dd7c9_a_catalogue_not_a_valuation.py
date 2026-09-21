"""a catalogue, not a valuation

Revision ID: 2d997d9dd7c9
Revises: 5f7e41134fe9
Create Date: 2026-09-21 01:17:15.815103
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = '2d997d9dd7c9'
down_revision: str | None = '5f7e41134fe9'
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


# What `leltar.text.fold` does, in SQL, so existing rows are searchable the moment this
# runs rather than only after they are next edited. `lower()` first, so the uppercase
# accented letters are covered by the nine lowercase ones listed here.
BACKFILL_SEARCH_TEXT = """
UPDATE items SET search_text = trim(regexp_replace(
    translate(
        lower(concat_ws(' ', name, suggested_name, brand, product_model,
                        description, serial_number, notes)),
        'áéíóöőúüű',
        'aeiooouuu'
    ),
    '[^a-z0-9]+', ' ', 'g'
))
"""


def upgrade() -> None:
    # The app no longer asks the model what anything is worth - it is a catalogue of what
    # is in the house, not a valuation of it. One optional, typed-in figure replaces the
    # guessed range, and whatever a row already had is carried into it rather than
    # dropped: a number somebody entered by hand is the one kind here worth keeping.
    op.add_column('items', sa.Column('value', sa.Numeric(precision=12, scale=2), nullable=True))
    op.execute(
        "UPDATE items SET value = COALESCE(estimated_value, value_low, value_high)"
    )

    # Autogenerate wrote this as a bare NOT NULL, which cannot be added to a table that
    # already has rows. Default, backfill, then drop the default so the column matches
    # what the model describes and the application supplies it from here on.
    op.add_column(
        'items',
        sa.Column('search_text', sa.Text(), nullable=False, server_default=''),
    )
    op.execute(BACKFILL_SEARCH_TEXT)
    op.alter_column('items', 'search_text', server_default=None)
    op.create_index(op.f('ix_items_search_text'), 'items', ['search_text'], unique=False)

    op.drop_column('items', 'estimated_value')
    op.drop_column('items', 'value_high')
    op.drop_column('items', 'value_low')


def downgrade() -> None:
    op.add_column('items', sa.Column('value_low', sa.NUMERIC(precision=12, scale=2), autoincrement=False, nullable=True))
    op.add_column('items', sa.Column('value_high', sa.NUMERIC(precision=12, scale=2), autoincrement=False, nullable=True))
    op.add_column('items', sa.Column('estimated_value', sa.NUMERIC(precision=12, scale=2), autoincrement=False, nullable=True))
    # Going back, the single figure returns to the column the statistics used to read.
    op.execute("UPDATE items SET estimated_value = value")
    op.drop_index(op.f('ix_items_search_text'), table_name='items')
    op.drop_column('items', 'search_text')
    op.drop_column('items', 'value')
