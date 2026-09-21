"""a room cannot be added twice

Revision ID: e38304e1c415
Revises: 2d997d9dd7c9
Create Date: 2026-09-21 11:59:39.785208
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = 'e38304e1c415'
down_revision: str | None = '2d997d9dd7c9'
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


# PostgreSQL treats NULLs as distinct in a unique index, so the existing
# (parent_id, name) constraint never applied to top-level places: two rooms called
# "Garázs" with no parent were two different rows as far as the database was concerned.
# Any install that hit the form bug fixed alongside this migration will have collected a
# few, and a unique index cannot be created over them - so they are renamed first rather
# than the migration failing on somebody's NAS at start-up.
#
# The oldest keeps the name; the rest get a number, which is visible and editable on the
# Helyek page. Renaming beats merging: the app cannot know whether two rooms with one name
# were a mistake or two actual rooms somebody names the same, and merging them would move
# items somewhere their owner did not put them.
DEDUPLICATE = """
WITH ranked AS (
    SELECT id, name,
           row_number() OVER (PARTITION BY name ORDER BY created_at, id) AS position
    FROM places
    WHERE parent_id IS NULL
)
UPDATE places
   SET name = places.name || ' (' || ranked.position || ')'
  FROM ranked
 WHERE places.id = ranked.id
   AND ranked.position > 1
"""


def upgrade() -> None:
    op.execute(DEDUPLICATE)
    op.create_index('uq_places_root_name', 'places', ['name'], unique=True, postgresql_where=sa.text('parent_id IS NULL'))


def downgrade() -> None:
    # The renames are not undone: by the time anyone downgrades, the new names may be the
    # ones their items are filed under.
    op.drop_index('uq_places_root_name', table_name='places', postgresql_where=sa.text('parent_id IS NULL'))
