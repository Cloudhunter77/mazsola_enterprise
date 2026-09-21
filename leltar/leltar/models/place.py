"""Where a thing is.

A tree rather than a flat list of rooms, because the answer to "where is the drill?" is
"a garázs, a fém polcon, a kék dobozban" and each of those is a place you can put other
things in. Depth is not limited; the UI shows the full path.
"""

from __future__ import annotations

import enum
import uuid

from sqlalchemy import ForeignKey, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from leltar.models.base import Base, TimestampMixin, pk


class PlaceKind(enum.StrEnum):
    BUILDING = "building"    # ház, garázs, nyaraló
    ROOM = "room"            # konyha, nappali, padlás
    STORAGE = "storage"      # szekrény, polc, fiók, doboz


class Place(Base, TimestampMixin):
    __tablename__ = "places"

    id: Mapped[uuid.UUID] = pk()
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("places.id", ondelete="SET NULL"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    kind: Mapped[str] = mapped_column(String(12), default=PlaceKind.ROOM.value, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    parent: Mapped[Place | None] = relationship(remote_side="Place.id")

    # Two places may not share a name under the same parent - that way "Konyha" always
    # means one place, and the seeded tree cannot be duplicated by a second startup.
    #
    # The second index is not redundant. PostgreSQL treats NULLs as distinct in a unique
    # index, so the constraint above never applied to top-level places at all: "Garázs"
    # and "Garázs" with no parent were two different rows as far as the database was
    # concerned. A partial index over the rows where `parent_id IS NULL` is what closes
    # that, and closing it matters because a duplicate room silently splits a catalogue
    # in two - half your things in one "Garázs" and half in the other.
    __table_args__ = (
        UniqueConstraint("parent_id", "name", name="uq_places_parent_name"),
        Index(
            "uq_places_root_name",
            "name",
            unique=True,
            postgresql_where=text("parent_id IS NULL"),
        ),
    )
