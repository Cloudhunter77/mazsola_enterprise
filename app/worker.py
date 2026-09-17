"""The extraction worker.

An asyncio loop inside the API process rather than a separate queue service. Job state lives
in the `receipts` table, so a container restart resumes work instead of losing it, and the
whole stack stays at two containers - which is the right amount of machinery for a household
that produces a few receipts a day.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db import SessionLocal
from app.extraction.base import ExtractionError, ReceiptExtractor
from app.extraction.factory import build_extractor
from app.models import Receipt, ReceiptImage, ReceiptStatus
from app.services.autolink import autolink_stored
from app.services.persist import persist_extraction, record_attempt
from app.services.recurring import materialise_due

log = logging.getLogger(__name__)

# Subscriptions come due once a month and product mappings change when you sit down and map
# them; checking hourly is already far more often than either needs, and both checks are
# no-ops the rest of the time.
HOUSEKEEPING_INTERVAL_SECONDS = 3600


class ExtractionWorker:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self._extractor: ReceiptExtractor | None = None
        self._task: asyncio.Task | None = None
        self._stopping = asyncio.Event()
        # None means never checked, so the first loop iteration does it. That first pass
        # is the one that matters after an update: it is what brings receipts stored by the
        # previous version up to date with the current matching rules.
        self._housekept_at: float | None = None

    @property
    def extractor(self) -> ReceiptExtractor:
        # Built lazily so a missing API key surfaces as a failed receipt with a readable
        # message, rather than a container that will not start.
        if self._extractor is None:
            self._extractor = build_extractor(self.settings)
        return self._extractor

    # --- lifecycle -----------------------------------------------------------
    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self.run_forever(), name="receipt-tracker-worker")
            log.info("extraction worker started (engine=%s)", self.settings.extractor)

    async def stop(self) -> None:
        self._stopping.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def run_forever(self) -> None:
        while not self._stopping.is_set():
            try:
                await self.housekeeping()
            except Exception:  # housekeeping must never stop extraction
                log.exception("housekeeping pass failed")

            try:
                did_work = await self.process_next()
            except Exception:  # never let one bad receipt kill the loop
                log.exception("worker iteration failed")
                did_work = False

            if not did_work:
                try:
                    await asyncio.wait_for(
                        self._stopping.wait(), timeout=self.settings.worker_poll_seconds
                    )
                except TimeoutError:
                    pass

    # --- periodic housekeeping -----------------------------------------------
    async def housekeeping(self) -> dict[str, int]:
        """The once-an-hour jobs: subscriptions coming due, and stored lines to link.

        Rate-limited because both are whole-table scans that almost always find nothing -
        the queue loop runs every few seconds and neither needs that. Repeating one early
        would still be harmless: `recurring_charges` has a unique key on (rule, period) so
        a second pass over the same period is a no-op rather than a double charge, and
        auto-linking only ever fills in a NULL.

        The two are run in separate sessions so a failure in one cannot roll back the
        other's work.
        """
        now = time.monotonic()
        if self._housekept_at is not None and (
            now - self._housekept_at < HOUSEKEEPING_INTERVAL_SECONDS
        ):
            return {}

        done: dict[str, int] = {}
        for name, job in (("charges", self.materialise_recurring), ("linked", self.autolink)):
            try:
                done[name] = await job()
            except Exception:  # one broken rule must not stop the other job
                log.exception("%s pass failed", name)

        self._housekept_at = now
        return done

    async def materialise_recurring(self) -> int:
        """Generate any subscription charge that has come due. Cheap and idempotent."""
        async with SessionLocal() as session:
            created = await materialise_due(session)
            await session.commit()
        return len(created)

    async def autolink(self) -> int:
        """Link stored receipt lines to products they letter-for-letter match.

        Without this, recognising a product across tills would only ever apply to receipts
        scanned after the mapping existed, and everything already in the database would
        stay unmapped for good.
        """
        async with SessionLocal() as session:
            linked = await autolink_stored(session)
            await session.commit()
        return linked

    # --- work ----------------------------------------------------------------
    async def _claim(self, session: AsyncSession) -> Receipt | None:
        """Take the oldest waiting receipt and mark it in flight.

        "Waiting" includes receipts stranded in `processing` by a worker that died - a
        container restart mid-extraction would otherwise leave them stuck in that state
        forever, showing as permanently in-progress with no retry. The staleness window
        is long enough that a live extraction is never stolen from a running worker.

        SKIP LOCKED means a second app replica would pick a different row rather than
        duplicate the work (and the API spend).
        """
        stale_before = datetime.now(UTC) - timedelta(seconds=self.settings.worker_stale_seconds)
        stmt = (
            select(Receipt)
            .where(
                or_(
                    and_(
                        Receipt.status == ReceiptStatus.PENDING.value,
                        Receipt.attempts < self.settings.worker_max_attempts,
                    ),
                    # A stranded receipt is reclaimed whatever its attempt count. Applying
                    # the attempts filter here too would leave one that crashed on its
                    # final attempt showing as in-progress forever - the exact state this
                    # is meant to clear. If it has no attempts left it is marked failed
                    # below rather than retried.
                    and_(
                        Receipt.status == ReceiptStatus.PROCESSING.value,
                        Receipt.updated_at < stale_before,
                    ),
                )
            )
            .order_by(Receipt.created_at)
            .limit(1)
        )
        if session.bind.dialect.name == "postgresql":
            stmt = stmt.with_for_update(skip_locked=True)

        receipt = await session.scalar(stmt)
        if receipt is None:
            return None

        if receipt.status == ReceiptStatus.PROCESSING.value:
            log.warning(
                "reclaiming receipt %s, stranded in processing since %s",
                receipt.id, receipt.updated_at,
            )
            if receipt.attempts >= self.settings.worker_max_attempts:
                receipt.status = ReceiptStatus.FAILED.value
                receipt.error = (
                    "Extraction was interrupted and no attempts remain. "
                    "Use reprocess to try again."
                )
                await session.commit()
                log.warning("receipt %s had no attempts left; marked failed", receipt.id)
                return None

        receipt.status = ReceiptStatus.PROCESSING.value
        receipt.attempts += 1
        await session.commit()
        return receipt

    async def process_next(self) -> bool:
        """Process one receipt. Returns False when the queue is empty."""
        async with SessionLocal() as session:
            receipt = await self._claim(session)
            if receipt is None:
                return False

            paths = await self._image_paths(session, receipt)
            images = await asyncio.to_thread(self._read_images, paths)
            if images is None:
                await self._fail(
                    session, receipt, f"An image file is missing: {', '.join(paths)}", terminal=True
                )
                return True

            try:
                result = await self.extractor.extract(images, receipt.image_mime)
            except ExtractionError as exc:
                await self._fail(session, receipt, str(exc))
                return True
            except Exception as exc:  # noqa: BLE001 - surface anything unexpected on the receipt
                log.exception("unexpected extraction failure for %s", receipt.id)
                await self._fail(session, receipt, f"{type(exc).__name__}: {exc}")
                return True

            verdict = await persist_extraction(session, receipt, result)
            await record_attempt(
                session, receipt, extractor=self.extractor.name, result=result
            )
            await session.commit()

            log.info(
                "receipt %s -> %s%s",
                receipt.id,
                receipt.status,
                f" ({', '.join(verdict.reasons)})" if verdict.reasons else "",
            )
            return True

    @staticmethod
    async def _image_paths(session: AsyncSession, receipt: Receipt) -> list[str]:
        """Every photograph of this receipt, in reading order.

        Falls back to the mirrored `image_path` column so a receipt whose parts row is
        somehow missing still gets read rather than failing outright.
        """
        paths = list(
            (
                await session.scalars(
                    select(ReceiptImage.path)
                    .where(ReceiptImage.receipt_id == receipt.id)
                    .order_by(ReceiptImage.part_no)
                )
            ).all()
        )
        return paths or [receipt.image_path]

    @staticmethod
    def _read_images(paths: list[str]) -> list[bytes] | None:
        """All parts, or None if any one of them is gone - a partial receipt is worse than none."""
        from pathlib import Path

        images = []
        for path in paths:
            file = Path(path)
            if not file.is_file():
                return None
            images.append(file.read_bytes())
        return images

    async def _fail(
        self, session: AsyncSession, receipt: Receipt, message: str, *, terminal: bool = False
    ) -> None:
        """Record a failure, and decide whether it is worth another try."""
        exhausted = terminal or receipt.attempts >= self.settings.worker_max_attempts
        receipt.status = (
            ReceiptStatus.FAILED.value if exhausted else ReceiptStatus.PENDING.value
        )
        receipt.error = message
        await record_attempt(
            session,
            receipt,
            extractor=self.settings.extractor,
            model=self.settings.extractor_model,
            error=message,
        )
        await session.commit()
        log.warning(
            "receipt %s failed (attempt %d/%d): %s",
            receipt.id, receipt.attempts, self.settings.worker_max_attempts, message,
        )
