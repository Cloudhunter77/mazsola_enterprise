"""Shelf labels: photograph a price without buying the thing.

Every route here reads and writes `price_label_photos` and `price_observations` and
nothing else. There is deliberately no way to turn an observation into a receipt: the two
answer different questions, and a price you saw is not money you spent.
"""

from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, Query, Response, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import delete, func, select
from sqlalchemy.orm import selectinload

from app.api.deps import AuthDep, SessionDep, SettingsDep
from app.models import (
    LabelStatus,
    Merchant,
    PriceLabelPhoto,
    PriceObservation,
    Product,
)
from app.schemas.labels import (
    LabelPhotoDetail,
    LabelPhotoSummary,
    LabelUploadResponse,
    ObservationOut,
    ObservationPatch,
    ScannedPrice,
)
from app.services.ingest import IngestError
from app.services.labels import ingest_label_photo

router = APIRouter(prefix="/api/labels", tags=["price labels"])


@router.post("", response_model=LabelUploadResponse, status_code=status.HTTP_202_ACCEPTED)
async def upload_label_photo(
    _: AuthDep,
    session: SessionDep,
    settings: SettingsDep,
    response: Response,
    file: UploadFile = File(..., description="One photo of a shelf label or a shelf strip."),
    shop: str | None = Query(
        None,
        description=(
            "The shop you are standing in. Most shelf labels do not name it, so the app "
            "says so once per visit and sends the same answer with every photo."
        ),
    ),
) -> LabelUploadResponse:
    """Queue one shelf photograph. Returns immediately; the worker reads it in the background."""
    data = await file.read()
    try:
        # No `observed_at`: passing the clock here would override the photograph's own
        # timestamp, which is the whole point of being able to upload one taken earlier.
        photo, created = await ingest_label_photo(
            session, data, settings, merchant_name=shop
        )
    except IngestError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    await session.commit()
    if not created:
        response.status_code = status.HTTP_200_OK
    return LabelUploadResponse(id=photo.id, status=photo.status, duplicate=not created)


@router.get("", response_model=list[LabelPhotoSummary])
async def list_label_photos(
    _: AuthDep,
    session: SessionDep,
    status_filter: str | None = Query(None, alias="status"),
    limit: int = Query(100, le=500),
) -> list[LabelPhotoSummary]:
    counts = (
        select(PriceObservation.photo_id, func.count().label("n"))
        .group_by(PriceObservation.photo_id)
        .subquery()
    )
    stmt = (
        select(PriceLabelPhoto, Merchant.name, func.coalesce(counts.c.n, 0))
        .outerjoin(Merchant, PriceLabelPhoto.merchant_id == Merchant.id)
        .outerjoin(counts, counts.c.photo_id == PriceLabelPhoto.id)
        .order_by(PriceLabelPhoto.observed_at.desc())
        .limit(limit)
    )
    if status_filter:
        stmt = stmt.where(PriceLabelPhoto.status == status_filter)

    return [
        LabelPhotoSummary(
            id=photo.id,
            status=photo.status,
            observed_at=photo.observed_at,
            merchant_name=merchant_name,
            observation_count=count,
            review_reasons=photo.review_reasons or [],
            error=photo.error,
        )
        for photo, merchant_name, count in (await session.execute(stmt)).all()
    ]


@router.get("/prices", response_model=list[ScannedPrice])
async def scanned_prices(
    _: AuthDep,
    session: SessionDep,
    shop: str | None = Query(None, description="Only this shop."),
    limit: int = Query(200, le=1000),
) -> list[ScannedPrice]:
    """Every price read off a shelf label, newest first.

    A photograph is how the price got here; the price is the thing you want to look at. The
    photo list answers "did that scan work", this answers "what did it cost".
    """
    stmt = (
        select(
            PriceObservation,
            PriceLabelPhoto.observed_at,
            PriceLabelPhoto.id,
            Merchant.name,
            Product.canonical_name,
        )
        .join(PriceLabelPhoto, PriceObservation.photo_id == PriceLabelPhoto.id)
        .outerjoin(Merchant, PriceLabelPhoto.merchant_id == Merchant.id)
        .outerjoin(Product, PriceObservation.product_id == Product.id)
        .order_by(PriceLabelPhoto.observed_at.desc(), PriceObservation.line_no)
        .limit(limit)
    )
    if shop:
        stmt = stmt.where(Merchant.name == shop)

    return [
        ScannedPrice(
            id=observation.id,
            photo_id=photo_id,
            observed_at=observed_at,
            merchant_name=merchant_name,
            raw_name=observation.raw_name,
            product_id=observation.product_id,
            product_name=product_name,
            price=observation.price,
            unit_price=observation.unit_price,
            unit=observation.unit,
            is_promotion=observation.is_promotion,
            regular_price=observation.regular_price,
            confidence=observation.confidence,
        )
        for observation, observed_at, photo_id, merchant_name, product_name in (
            await session.execute(stmt)
        ).all()
    ]


@router.get("/{photo_id}", response_model=LabelPhotoDetail)
async def get_label_photo(
    _: AuthDep, session: SessionDep, photo_id: uuid.UUID
) -> LabelPhotoDetail:
    photo = await session.scalar(
        select(PriceLabelPhoto)
        .options(selectinload(PriceLabelPhoto.observations))
        .where(PriceLabelPhoto.id == photo_id)
    )
    if photo is None:
        raise HTTPException(status_code=404, detail="No such photo.")

    merchant_name = None
    if photo.merchant_id:
        merchant = await session.get(Merchant, photo.merchant_id)
        merchant_name = merchant.name if merchant else None

    names = {
        product.id: product.canonical_name
        for product in (await session.scalars(select(Product))).all()
    }

    return LabelPhotoDetail(
        id=photo.id,
        status=photo.status,
        observed_at=photo.observed_at,
        merchant_name=merchant_name,
        review_reasons=photo.review_reasons or [],
        error=photo.error,
        notes=photo.notes,
        confidence=photo.confidence,
        observations=[
            ObservationOut(
                id=observation.id,
                line_no=observation.line_no,
                raw_name=observation.raw_name,
                product_id=observation.product_id,
                product_name=names.get(observation.product_id),
                price=observation.price,
                unit_price=observation.unit_price,
                unit=observation.unit,
                package_size=observation.package_size,
                package_unit=observation.package_unit,
                is_promotion=observation.is_promotion,
                regular_price=observation.regular_price,
                promotion_until=observation.promotion_until,
                confidence=observation.confidence,
            )
            for observation in photo.observations
        ],
    )


@router.get("/{photo_id}/image")
async def get_label_image(
    _: AuthDep, session: SessionDep, photo_id: uuid.UUID
) -> FileResponse:
    photo = await session.get(PriceLabelPhoto, photo_id)
    if photo is None:
        raise HTTPException(status_code=404, detail="No such photo.")
    path = Path(photo.image_path)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="The photo file is missing.")
    return FileResponse(path, media_type=photo.image_mime)


@router.patch("/observations/{observation_id}", response_model=ObservationOut)
async def update_observation(
    _: AuthDep, session: SessionDep, observation_id: uuid.UUID, body: ObservationPatch
) -> ObservationOut:
    """Correct one label by hand. Anything left unset keeps its current value."""
    observation = await session.get(PriceObservation, observation_id)
    if observation is None:
        raise HTTPException(status_code=404, detail="No such observation.")

    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(observation, field, value)

    await session.commit()
    await session.refresh(observation)

    product_name = None
    if observation.product_id:
        product = await session.get(Product, observation.product_id)
        product_name = product.canonical_name if product else None

    return ObservationOut(
        id=observation.id,
        line_no=observation.line_no,
        raw_name=observation.raw_name,
        product_id=observation.product_id,
        product_name=product_name,
        price=observation.price,
        unit_price=observation.unit_price,
        unit=observation.unit,
        package_size=observation.package_size,
        package_unit=observation.package_unit,
        is_promotion=observation.is_promotion,
        regular_price=observation.regular_price,
        promotion_until=observation.promotion_until,
        confidence=observation.confidence,
    )


@router.post("/{photo_id}/confirm", response_model=LabelPhotoDetail)
async def confirm_label_photo(
    _: AuthDep, session: SessionDep, photo_id: uuid.UUID
) -> LabelPhotoDetail:
    photo = await session.get(PriceLabelPhoto, photo_id)
    if photo is None:
        raise HTTPException(status_code=404, detail="No such photo.")
    photo.status = LabelStatus.CONFIRMED.value
    photo.review_reasons = None
    await session.commit()
    return await get_label_photo(_, session, photo_id)


@router.delete("/observations/{observation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_observation(
    _: AuthDep, session: SessionDep, observation_id: uuid.UUID
) -> None:
    """Drop one misread label without discarding the rest of the shelf."""
    await session.execute(
        delete(PriceObservation).where(PriceObservation.id == observation_id)
    )
    await session.commit()


@router.delete("/{photo_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_label_photo(
    _: AuthDep, session: SessionDep, photo_id: uuid.UUID
) -> None:
    photo = await session.get(PriceLabelPhoto, photo_id)
    if photo is None:
        raise HTTPException(status_code=404, detail="No such photo.")

    path = Path(photo.image_path)
    await session.delete(photo)
    await session.commit()
    path.unlink(missing_ok=True)
