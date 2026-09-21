"""Photographs, and the things found in them.

One photograph yields any number of items: point the camera at a shelf and eight things
are on it. So a photo is the unit of work for the model, and an item is the unit you
approve - which is also why an item keeps both the name the model suggested and the name
you settled on. Those two columns are the whole record of whether this app is any good.
"""

from __future__ import annotations

import enum
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    event,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from leltar.models.base import Base, TimestampMixin, money, pk
from leltar.text import searchable

if TYPE_CHECKING:
    from leltar.models.catalog import Category
    from leltar.models.place import Place


class PhotoMode(enum.StrEnum):
    """What the photographer meant by this picture.

    A shelf and a single object are different jobs: one wants everything nameable in the
    frame, the other wants the subject and nothing else - not the table it stands on, not
    the wall behind it. The person knows which they took, so they say, rather than the
    model having to infer intent from composition.
    """

    SCENE = "scene"
    SINGLE = "single"


class PhotoStatus(enum.StrEnum):
    PENDING = "pending"            # uploaded, waiting for the worker
    PROCESSING = "processing"      # identification in flight
    IDENTIFIED = "identified"      # the model named something; nothing looked wrong
    NEEDS_REVIEW = "needs_review"  # named, but a rule flagged it
    FAILED = "failed"              # identification errored out past max attempts
    REVIEWED = "reviewed"          # you have been through its items


class ItemStatus(enum.StrEnum):
    """A draft is a guess. Only you can turn one into an entry in the inventory."""

    DRAFT = "draft"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"  # not a thing worth listing; kept so it is not guessed again


class Condition(enum.StrEnum):
    NEW = "new"
    GOOD = "good"
    USED = "used"
    WORN = "worn"
    BROKEN = "broken"
    UNKNOWN = "unknown"


class Photo(Base, TimestampMixin):
    __tablename__ = "photos"

    id: Mapped[uuid.UUID] = pk()

    path: Mapped[str] = mapped_column(String(500), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    mime: Mapped[str] = mapped_column(String(60), default="image/jpeg", nullable=False)
    source: Mapped[str] = mapped_column(String(20), default="web", nullable=False)

    # Where the camera was pointed, chosen before the upload. It is the one thing a
    # photograph cannot tell you and you always know, so items inherit it rather than the
    # model being asked to guess which room this is.
    place_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("places.id", ondelete="SET NULL"), nullable=True, index=True
    )
    taken_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    mode: Mapped[str] = mapped_column(
        String(10), default=PhotoMode.SCENE.value, nullable=False
    )

    # --- pipeline state ------------------------------------------------------
    status: Mapped[str] = mapped_column(
        String(20), default=PhotoStatus.PENDING.value, nullable=False, index=True
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    review_reasons: Mapped[list | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # The model's one-line description of what it is looking at ("konyhai polc edényekkel").
    # Useful when a photo's items read oddly: it says whether the picture was understood.
    scene: Mapped[str | None] = mapped_column(String(300), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    identified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    items: Mapped[list[Item]] = relationship(
        back_populates="photo",
        cascade="all, delete-orphan",
        order_by="Item.created_at",
    )
    place: Mapped[Place | None] = relationship()  # noqa: F821


class Item(Base, TimestampMixin):
    __tablename__ = "items"

    id: Mapped[uuid.UUID] = pk()
    # Null for something typed in rather than photographed.
    photo_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("photos.id", ondelete="CASCADE"), nullable=True, index=True
    )
    place_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("places.id", ondelete="SET NULL"), nullable=True, index=True
    )
    category_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("categories.id", ondelete="SET NULL"), nullable=True, index=True
    )

    # --- what it is ----------------------------------------------------------
    name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    # Never overwritten by an edit. Keeping the original guess next to the name you chose
    # is what lets the Pontosság page answer "is the model actually saving me typing?" -
    # and it is the only honest way to answer it, because a corrected name looks exactly
    # like a right one once it is saved.
    suggested_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    brand: Mapped[str | None] = mapped_column(String(120), nullable=True)
    product_model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    colour: Mapped[str | None] = mapped_column(String(60), nullable=True)
    material: Mapped[str | None] = mapped_column(String(60), nullable=True)
    condition: Mapped[str] = mapped_column(
        String(10), default=Condition.UNKNOWN.value, nullable=False
    )
    quantity: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    serial_number: Mapped[str | None] = mapped_column(String(120), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # --- what you know about it that no photograph shows ----------------------
    # One optional figure, typed in, for the handful of things where it matters - the
    # bicycle, the laptop. The model is never asked what anything is worth: this is a
    # catalogue of what is in the house, and a column of guessed prices would be a column
    # of numbers nobody can act on, bought with output tokens on every photograph.
    value: Mapped[Decimal | None] = money()
    currency: Mapped[str] = mapped_column(String(3), default="HUF", nullable=False)
    acquired_on: Mapped[date | None] = mapped_column(Date, nullable=True)

    # Every field worth finding the item by, lowercased and stripped of accents. Kept as a
    # column rather than computed per query: nobody types "bögre" with the umlaut on a
    # phone, ILIKE over the original text cannot match what they do type, and a folded
    # expression over four columns cannot use an index. Maintained by the listener at the
    # bottom of this module, so no write path can forget it.
    search_text: Mapped[str] = mapped_column(Text, default="", nullable=False, index=True)

    # --- state ---------------------------------------------------------------
    status: Mapped[str] = mapped_column(
        String(10), default=ItemStatus.DRAFT.value, nullable=False, index=True
    )
    # photo (the model named it) | manual (you typed it)
    source: Mapped[str] = mapped_column(String(10), default="photo", nullable=False)
    edited: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    review_reasons: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # Other names the model thought plausible. Shown as one-tap alternatives on review,
    # which is faster than typing a correction and is the app's whole promise.
    alternatives: Mapped[list | None] = mapped_column(JSON, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    photo: Mapped[Photo | None] = relationship(back_populates="items")
    place: Mapped[Place | None] = relationship()  # noqa: F821
    category: Mapped[Category | None] = relationship()  # noqa: F821
    images: Mapped[list[ItemImage]] = relationship(
        back_populates="item",
        cascade="all, delete-orphan",
        order_by="ItemImage.created_at",
    )


class ItemImage(Base, TimestampMixin):
    """A picture of one thing.

    Three ways one arrives, and the app treats them alike once stored:

    * a **crop** of the photograph the item was identified in, taken at the box the model
      drew - which is what gives eight things photographed together eight pictures;
    * the **whole photograph**, when there was no usable box - still a picture of the item,
      just a wider one;
    * an **upload**, attached to an item afterwards: the serial plate, the damage, the
      thing inside its case. This is the one that makes the inventory worth keeping after
      the first pass.

    Every row owns a file. A crop could in principle be recomputed from its photograph and
    its box, but making that the only copy would mean a deleted photograph silently
    emptying the inventory's pictures - and the photograph is the thing most likely to be
    tidied away.
    """

    __tablename__ = "item_images"

    id: Mapped[uuid.UUID] = pk()
    item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("items.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # crop | photo (the whole frame) | upload
    kind: Mapped[str] = mapped_column(String(10), default="upload", nullable=False)
    # Which photograph it came out of, when it came out of one. SET NULL rather than
    # CASCADE: deleting a scene photograph must not take the item pictures with it.
    source_photo_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("photos.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # The box it was cut from, in thousandths, kept so a crop can be explained and redone.
    box: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    path: Mapped[str] = mapped_column(String(500), nullable=False)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    mime: Mapped[str] = mapped_column(String(60), default="image/jpeg", nullable=False)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # The one shown in the list. A partial unique index enforces "at most one per item",
    # because two primaries is a state no screen can render and every screen would have to
    # guess its way out of.
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    item: Mapped[Item] = relationship(back_populates="images")

    __table_args__ = (
        Index(
            "uq_item_images_primary",
            "item_id",
            unique=True,
            postgresql_where=text("is_primary"),
        ),
    )


@event.listens_for(Item, "before_insert")
@event.listens_for(Item, "before_update")
def _refresh_search_text(_mapper, _connection, item: Item) -> None:
    """Keep the search column in step with the fields it is built from.

    A listener rather than a call in each write path: there are five of those already
    (identification, manual entry, the patch endpoint, confirming, the demo seeder) and an
    item that is invisible to search because one of them forgot is a bug nobody reports -
    they just conclude the search is unreliable and stop using it.
    """
    item.search_text = searchable(
        item.name,
        item.suggested_name,
        item.brand,
        item.product_model,
        item.description,
        item.serial_number,
        item.notes,
    )
