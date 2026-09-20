"""Where a thing is.

A tree rather than a flat list of rooms, because the answer to "where is the drill?" is
"a garázs, a fém polcon, a kék dobozban" and each of those is a place you can put other
things in. Depth is not limited; the UI shows the full path.
"""

from __future__ import annotations

import enum
import uuid

from sqlalchemy import ForeignKey, Integer, String, Text, UniqueConstraint
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

    # Two rooms may not share a name under the same parent - that way "Konyha" always
    # means one place, and the seeded tree cannot be duplicated by a second startup.
    __table_args__ = (UniqueConstraint("parent_id", "name", name="uq_places_parent_name"),)
