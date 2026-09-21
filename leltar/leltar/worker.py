"""The identification worker.

An asyncio loop inside the API process rather than a separate queue service. Job state
lives in the `photos` table, so a container restart resumes work instead of losing it, and
the whole stack stays at two containers - the right amount of machinery for a household
cataloguing its own cupboards.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from leltar.config import Settings, get_settings
from leltar.db import SessionLocal
from leltar.extraction.base import IdentificationError, ObjectIdentifier
from leltar.extraction.factory import build_identifier
from leltar.models import Photo, PhotoMode, PhotoStatus
from leltar.services.persist import persist_identification, record_attempt
from leltar.services.places import path_of

log = logging.getLogger(__name__)


class IdentificationWorker:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self._identifier: ObjectIdentifier | None = None
        self._tasks: list[asyncio.Task] = []
        self._stopping = asyncio.Event()

    @property
    def identifier(self) -> ObjectIdentifier:
        # Built lazily so a missing API key surfaces as a failed photo with a readable
        # message, rather than a container that will not start.
        if self._identifier is None:
            self._identifier = build_identifier(self.settings)
        return self._identifier

    # --- lifecycle -----------------------------------------------------------
    def start(self) -> None:
        """Run several claim loops side by side.

        They share nothing but the queue, and the claim below takes a row with
        `FOR UPDATE SKIP LOCKED`, so two loops can never take the same photograph - the
        same mechanism that already stopped an old and a new container paying to read one
        photo twice during an update.
        """
        if self._tasks:
            return
        for index in range(self.settings.worker_concurrency):
            self._tasks.append(
                asyncio.create_task(self.run_forever(), name=f"home-inventory-worker-{index}")
            )
        log.info(
            "identification worker started (engine=%s, %d in parallel)",
            self.settings.identifier, len(self._tasks),
        )

    async def stop(self) -> None:
        self._stopping.set()
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._tasks = []

    async def run_forever(self) -> None:
        while not self._stopping.is_set():
            try:
                did_work = await self.process_next()
            except Exception:  # never let one bad photo kill the loop
                log.exception("worker iteration failed")
                did_work = False

            if not did_work:
                try:
                    await asyncio.wait_for(
                        self._stopping.wait(), timeout=self.settings.worker_poll_seconds
                    )
                except TimeoutError:
                    pass

    # --- one photograph ------------------------------------------------------
    async def process_next(self) -> bool:
        """Identify one queued photograph. Returns False when the queue is empty."""
        async with SessionLocal() as session:
            photo = await self._claim_next(session)
            if photo is None:
                return False

            place_path = await path_of(session, photo.place_id)
            photo_id = photo.id
            image_path = photo.path
            single = photo.mode == PhotoMode.SINGLE.value
            await session.commit()

        try:
            data = await asyncio.to_thread(_read_bytes, image_path)
        except OSError as exc:
            await self._fail(photo_id, f"A fénykép nem olvasható: {exc}", terminal=True)
            return True

        try:
            result = await self.identifier.identify(
                data, place_path=place_path, single=single
            )
        except IdentificationError as exc:
            await self._fail(photo_id, str(exc))
            return True
        except Exception as exc:  # noqa: BLE001 - an engine bug must not stop the queue
            log.exception("identification raised for photo %s", photo_id)
            await self._fail(photo_id, f"Váratlan hiba: {exc}")
            return True

        async with SessionLocal() as session:
            photo = await session.get(Photo, photo_id)
            if photo is None:
                # Deleted while we were reading it. The call was still billed, so the
                # attempt is recorded against no photo rather than dropped.
                await record_attempt(
                    session,
                    None,
                    engine=result.engine,
                    model=result.model,
                    ok=True,
                    result=result,
                    items_found=len(result.photo.objects),
                )
                await session.commit()
                return True

            items = await persist_identification(session, photo, result, self.settings)
            await record_attempt(
                session,
                photo.id,
                engine=result.engine,
                model=result.model,
                ok=True,
                result=result,
                items_found=len(items),
            )
            await session.commit()
        return True

    async def _claim_next(self, session: AsyncSession) -> Photo | None:
        """Take the oldest queued photo, or one abandoned by a worker that died.

        `SKIP LOCKED` rather than a status flag alone: two workers (an old container and a
        new one during an update) must never pay to read the same photograph twice.
        """
        stale_before = datetime.now(UTC) - timedelta(seconds=self.settings.worker_stale_seconds)
        stmt = (
            select(Photo)
            .where(
                or_(
                    Photo.status == PhotoStatus.PENDING.value,
                    and_(
                        Photo.status == PhotoStatus.PROCESSING.value,
                        Photo.updated_at < stale_before,
                    ),
                ),
                Photo.attempts < self.settings.worker_max_attempts,
            )
            .order_by(Photo.created_at)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        photo = await session.scalar(stmt)
        if photo is None:
            return None
        photo.status = PhotoStatus.PROCESSING.value
        photo.attempts += 1
        await session.flush()
        return photo

    async def _fail(self, photo_id, message: str, *, terminal: bool = False) -> None:
        """Record a failure, and decide whether it is worth another attempt.

        Back to `pending` while attempts remain: a timeout or a 529 usually succeeds on the
        next pass. `terminal` is for the failures that will never succeed - a missing file
        does not become readable by asking again.
        """
        async with SessionLocal() as session:
            photo = await session.get(Photo, photo_id)
            if photo is None:
                return
            exhausted = terminal or photo.attempts >= self.settings.worker_max_attempts
            photo.status = (
                PhotoStatus.FAILED.value if exhausted else PhotoStatus.PENDING.value
            )
            photo.error = message
            await record_attempt(
                session,
                photo.id,
                engine=self.settings.identifier,
                # The configured engine's own model, not the Anthropic one: recording
                # `identifier_model` while OpenRouter was running is how the sister app
                # ended up attributing every failure to the wrong model.
                model=self.settings.active_model,
                ok=False,
                error=message,
            )
            await session.commit()
        log.warning("photo %s failed: %s", photo_id, message)


def _read_bytes(path: str) -> bytes:
    from pathlib import Path

    return Path(path).read_bytes()
