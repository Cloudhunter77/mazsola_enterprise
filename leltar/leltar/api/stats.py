"""What is in the house, where it is, and what reading it has cost."""

from __future__ import annotations

from fastapi import APIRouter

from leltar.api.deps import AuthDep, SessionDep
from leltar.schemas.api import AccuracyStat, CategoryStat, CostSummary, PlaceStat, StatsSummary
from leltar.services import stats as service

router = APIRouter(prefix="/api/stats", tags=["stats"])


@router.get("/summary", response_model=StatsSummary)
async def summary(_: AuthDep, session: SessionDep) -> StatsSummary:
    return StatsSummary(**await service.summary(session))


@router.get("/by-place", response_model=list[PlaceStat])
async def by_place(_: AuthDep, session: SessionDep) -> list[PlaceStat]:
    return [PlaceStat(**row) for row in await service.by_place(session)]


@router.get("/by-category", response_model=list[CategoryStat])
async def by_category(_: AuthDep, session: SessionDep) -> list[CategoryStat]:
    return [CategoryStat(**row) for row in await service.by_category(session)]


@router.get("/accuracy", response_model=AccuracyStat)
async def accuracy(_: AuthDep, session: SessionDep) -> AccuracyStat:
    return AccuracyStat(**await service.accuracy(session))


@router.get("/costs", response_model=CostSummary)
async def costs(_: AuthDep, session: SessionDep) -> CostSummary:
    return CostSummary(**await service.costs(session))
