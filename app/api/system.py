"""What is running, so an update can be verified without a shell.

The awkward part of updating this app was never pulling the image - the TrueNAS Apps
screen does that. It was proving the pull took: comparing digests and reading container
logs over SSH. Everything needed for that is here instead, and the Rendszer page shows it.
"""

from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import func, select, text

from app.api.deps import AuthDep, SessionDep, SettingsDep
from app.models import Receipt, ReceiptStatus
from app.version import app_version, build_info, schema_revision

router = APIRouter(prefix="/api/system", tags=["ops"])


@router.get("")
async def system(_: AuthDep, session: SessionDep, settings: SettingsDep) -> dict:
    """Version, schema state and queue depth, in one call."""
    applied = await _applied_revision(session)
    expected = schema_revision()

    counts = dict(
        (
            await session.execute(
                select(Receipt.status, func.count(Receipt.id)).group_by(Receipt.status)
            )
        ).all()
    )

    return {
        "version": app_version(),
        "build": build_info(),
        "schema": {
            "expected": expected,
            "applied": applied,
            # False means migrations did not finish - the one thing worth an alarm here.
            "up_to_date": bool(expected and applied and expected == applied),
        },
        "extractor": settings.extractor,
        "model": settings.active_model,
        "worker_enabled": settings.worker_enabled,
        "max_image_edge": settings.max_image_edge,
        "min_image_width": settings.min_image_width,
        "receipts": {
            "total": sum(counts.values()),
            "pending": counts.get(ReceiptStatus.PENDING.value, 0),
            "needs_review": counts.get(ReceiptStatus.NEEDS_REVIEW.value, 0),
            "failed": counts.get(ReceiptStatus.FAILED.value, 0),
        },
    }


async def _applied_revision(session: SessionDep) -> str | None:
    """The revision Alembic actually recorded in this database, or None if it never has.

    Inside a savepoint, because a failing statement aborts the whole transaction in
    PostgreSQL: catching the error without rolling back leaves the session poisoned and
    every later query in the request fails too. A missing `alembic_version` table is an
    ordinary answer here - a database built by `create_all` has no such table - so it must
    not take the rest of the page down with it.
    """
    try:
        async with session.begin_nested():
            return await session.scalar(text("SELECT version_num FROM alembic_version LIMIT 1"))
    except Exception:  # noqa: BLE001 - "never migrated" is an answer, not a crash
        return None
