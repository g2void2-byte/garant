"""FastAPI application that powers the Telegram Mini App."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from misc import config
from utils.database.db import DB
from utils.database.extras import WebDB
from utils.database.models import ALL_MODELS, db
from webapp.backend.routers import (
    categories,
    deals,
    me,
    notifications,
    payments,
    reviews,
    services,
    support,
    users,
    ws,
)

logger = logging.getLogger(__name__)

FRONTEND_DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.connect(reuse_if_open=True)
    db.create_tables(ALL_MODELS)
    try:
        db.execute_sql("PRAGMA journal_mode=WAL;")
    except Exception:
        logger.exception("Could not enable WAL journal mode")
    WebDB().seed_default_categories()
    # Ensure the legacy PercentInvoice / PercentDeal rows exist so that
    # commission lookups during deposit-credit and deal-completion don't
    # raise DoesNotExist on a fresh database.
    try:
        await DB().get_or_create_percents()
    except Exception:
        logger.exception("Could not seed percent rows")
    yield
    if not db.is_closed():
        db.close()


def create_app() -> FastAPI:
    app = FastAPI(title="Garant Mini App", version="1.0.0", lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.ALLOWED_ORIGINS or ["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    for router in (
        me.router,
        categories.router,
        services.router,
        users.router,
        deals.router,
        reviews.router,
        notifications.router,
        support.router,
        payments.router,
        ws.router,
    ):
        app.include_router(router)

    @app.get("/api/health", tags=["health"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    # Serve compiled frontend if present.
    if FRONTEND_DIST.exists():
        assets_dir = FRONTEND_DIST / "assets"
        if assets_dir.exists():
            app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

        @app.get("/{full_path:path}", include_in_schema=False)
        async def spa(full_path: str):  # pragma: no cover - simple file serving
            requested = (FRONTEND_DIST / full_path).resolve()
            try:
                requested.relative_to(FRONTEND_DIST.resolve())
            except ValueError:
                return FileResponse(FRONTEND_DIST / "index.html")
            if requested.is_file():
                return FileResponse(requested)
            return FileResponse(FRONTEND_DIST / "index.html")

    return app


app = create_app()
