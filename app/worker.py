"""The extraction worker.

An asyncio loop inside the API process rather than a separate queue service. Job state lives
in the `receipts` table, so a container restart resumes work instead of losing it, and the
whole stack stays at two containers - which is the right amount of machinery for a household
that produces a few receipts a day.
"""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db import SessionLocal
from app.extraction.base import ExtractionError, ReceiptExtractor
from app.extraction.factory import build_extractor
from app.models import Receipt, ReceiptStatus
from app.services.persist import persist_extraction, record_attempt

log = logging.getLogger(__name__)


class ExtractionWorker:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self._extractor: ReceiptExtractor | None = None
        self._task: asyncio.Task | None = None
        self._stopping = asyncio.Event()

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
            self._task = asyncio.create_task(self.run_forever(), name="mazsola-worker")
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

    # --- work ----------------------------------------------------------------
    async def _claim(self, session: AsyncSession) -> Receipt | None:
        """Take the oldest pending receipt and mark it in flight.

        SKIP LOCKED means a second app replica would pick a different row rather than
        duplicate the work (and the API spend).
        """
        stmt = (
            select(Receipt)
            .where(Receipt.status == ReceiptStatus.PENDING.value)
            .where(Receipt.attempts < self.settings.worker_max_attempts)
            .order_by(Receipt.created_at)
            .limit(1)
        )
        if session.bind.dialect.name == "postgresql":
            stmt = stmt.with_for_update(skip_locked=True)

        receipt = await session.scalar(stmt)
        if receipt is None:
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

            image = await asyncio.to_thread(self._read_image, receipt.image_path)
            if image is None:
                await self._fail(
                    session, receipt, f"Image file is missing: {receipt.image_path}", terminal=True
                )
                return True

            try:
                result = await self.extractor.extract(image, receipt.image_mime)
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
    def _read_image(path: str) -> bytes | None:
        from pathlib import Path

        file = Path(path)
        return file.read_bytes() if file.is_file() else None

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
