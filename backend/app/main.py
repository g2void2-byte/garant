"""FastAPI app entrypoint — wires routers + launches the aiogram bot."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .bot import run_bot
from .config import settings
from .database import init_db
from .routers import admin, deals, users

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("autogarant")


@asynccontextmanager
async def lifespan(_: FastAPI):
    await init_db()
    bot_task = asyncio.create_task(run_bot(), name="autogarant-bot")
    log.info(
        "AutoGarant API ready (bot_username=%s, webapp_url=%s, admins=%s)",
        settings.bot_username,
        settings.webapp_url,
        settings.admin_id_list,
    )
    try:
        yield
    finally:
        bot_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await bot_task


app = FastAPI(
    title="AutoGarant API",
    version="0.1.0",
    description="REST API powering the AutoGarant Telegram Mini App",
    lifespan=lifespan,
)

# CORS is intentionally permissive — Telegram WebApps run inside Telegram's
# WebView which sends a `tgWebAppData` query param and a custom origin.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

api = FastAPI(title="AutoGarant Internal API")
api.include_router(users.router, tags=["users"])
api.include_router(deals.router)
api.include_router(admin.router)


@api.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


app.mount("/api", api)


@app.get("/healthz")
async def root_healthz() -> dict[str, str]:
    return {"status": "ok"}


# Optionally serve the built Mini App from `frontend/dist`.  Useful for
# single-process deployments (Fly.io, Docker, etc.).
_FRONTEND_DIST = Path(
    os.environ.get(
        "FRONTEND_DIST",
        Path(__file__).resolve().parent.parent.parent / "frontend" / "dist",
    )
).resolve()


if _FRONTEND_DIST.is_dir():
    log.info("Serving Mini App static assets from %s", _FRONTEND_DIST)
    assets_dir = _FRONTEND_DIST / "assets"
    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str) -> FileResponse:
        target = _FRONTEND_DIST / full_path
        if full_path and target.is_file():
            return FileResponse(target)
        return FileResponse(_FRONTEND_DIST / "index.html")
