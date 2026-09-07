"""Receipt Tracker - a receipt scanner and expense database for a home NAS.

One process serves the API, the built single-page app, and the extraction worker. On start
it brings the schema up to date and seeds the category tree, so deploying is 'pull the image
and set the environment variables' with no migration step to remember.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from app.api import auth, catalog, costs, receipts, recurring, stats, system
from app.config import get_settings
from app.db import SessionLocal, engine
from app.security import check_configuration
from app.services.seed import seed_if_empty
from app.version import app_version, build_info
from app.worker import ExtractionWorker

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
)
log = logging.getLogger("receipt-tracker")

STATIC_DIR = Path(__file__).resolve().parent.parent / "web" / "dist"


async def _run_migrations() -> None:
    """Apply Alembic migrations against the configured database."""
    from alembic import command
    from alembic.config import Config

    root = Path(__file__).resolve().parent.parent
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "app" / "migrations"))
    config.attributes["configure_logger"] = False

    import asyncio

    await asyncio.to_thread(command.upgrade, config, "head")
    log.info("database schema is up to date")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    # Before anything else: a misconfigured deployment should fail loudly at start
    # rather than quietly serve an app whose sessions can be forged.
    check_configuration(settings)

    settings.image_dir.mkdir(parents=True, exist_ok=True)

    await _run_migrations()

    async with SessionLocal() as session:
        await seed_if_empty(session)

    worker = ExtractionWorker(settings)
    app.state.worker = worker
    if settings.worker_enabled:
        worker.start()
    else:
        log.warning("worker disabled (WORKER_ENABLED=false); uploads will stay pending")

    if settings.auth_disabled:
        log.warning("AUTH_DISABLED is set - the API is open to anyone who can reach it")

    try:
        yield
    finally:
        await worker.stop()
        await engine.dispose()


def create_app() -> FastAPI:
    app = FastAPI(
        title="Receipt Tracker",
        description="Photograph a receipt, get a queryable expense database.",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.include_router(auth.router)
    app.include_router(receipts.router)
    app.include_router(catalog.router)
    app.include_router(stats.router)
    app.include_router(costs.router)
    app.include_router(recurring.router)
    app.include_router(system.router)

    @app.get("/health", tags=["ops"])
    async def health() -> JSONResponse:
        """Liveness plus a real database round-trip, for the compose healthcheck."""
        settings = get_settings()
        try:
            async with SessionLocal() as session:
                await session.execute(text("SELECT 1"))
            database_ok = True
        except Exception as exc:  # noqa: BLE001 - the point is to report, not raise
            log.warning("health check could not reach the database: %s", exc)
            database_ok = False

        payload = {
            "status": "ok" if database_ok else "degraded",
            "version": app_version(),
            "commit": build_info()["commit"],
            "database": database_ok,
            "extractor": settings.extractor,
            "model": _active_model(settings),
            "worker": settings.worker_enabled,
        }
        return JSONResponse(payload, status_code=200 if database_ok else 503)

    _mount_frontend(app)
    return app


def _active_model(settings) -> str | None:
    """Whichever model the configured engine will actually use."""
    return {
        "claude": settings.extractor_model,
        "openrouter": settings.openrouter_model,
    }.get(settings.extractor)


def _mount_frontend(app: FastAPI) -> None:
    """Serve the built SPA, with unknown paths falling back to index.html for client routing."""
    if not STATIC_DIR.is_dir():
        log.warning("no built frontend at %s - API only", STATIC_DIR)
        return

    root = STATIC_DIR.resolve()
    app.mount("/assets", StaticFiles(directory=root / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa(full_path: str) -> FileResponse:
        # This route is deliberately unauthenticated - it serves the app shell - so the
        # requested path must be confined to the build directory. Resolving first and
        # then checking containment is what makes `../../` traversal impossible; a
        # string check on the raw path would miss symlinks and encoded variants.
        try:
            candidate = (root / full_path).resolve()
        except (ValueError, OSError):
            # A null byte or an over-long path makes resolve() raise; that is just a
            # request for something that cannot exist, not a server error.
            return FileResponse(root / "index.html")

        if full_path and candidate.is_file() and candidate.is_relative_to(root):
            return FileResponse(candidate)
        return FileResponse(root / "index.html")


app = create_app()
