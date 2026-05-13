from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from pathlib import Path as _Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from .config import settings
from .db import async_session, create_tables
from .seed import run_seed

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(name)s: %(message)s")

_bot_task: asyncio.Task | None = None
_inactivity_task: asyncio.Task | None = None


async def _inactivity_loop(interval_seconds: int) -> None:
    """Periodically sweep stale deals.

    Runs forever; cancelled cleanly during shutdown. Uses a fresh
    session per iteration so a transient SQLite write lock doesn't
    poison subsequent runs.
    """
    from .services_deals import sweep_inactivity

    while True:
        try:
            async with async_session() as session:
                affected = await sweep_inactivity(session)
            if affected:
                logger.info("inactivity sweep: cancelled %d deal(s)", affected)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("inactivity sweep failed")
        await asyncio.sleep(interval_seconds)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _bot_task, _inactivity_task

    await create_tables()

    async with async_session() as session:
        await run_seed(session)

    if settings.run_bot:
        from .bot.runner import start_polling

        _bot_task = asyncio.create_task(start_polling())

    if settings.inactivity_sweep_seconds > 0:
        _inactivity_task = asyncio.create_task(_inactivity_loop(settings.inactivity_sweep_seconds))

    yield

    for task in (_bot_task, _inactivity_task):
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass


app = FastAPI(title="Garant TMA", lifespan=lifespan)

origins = [o.strip() for o in settings.allowed_origins.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from .routers import (  # noqa: E402
    account,
    categories,
    deal_messages,
    deals,
    me,
    media,
    notifications,
    payments,
    pin,
    reviews,
    services,
    support,
    users,
    wallet,
    ws,
)

for r in (
    me,
    pin,
    account,
    categories,
    services,
    users,
    deals,
    deal_messages,
    reviews,
    notifications,
    payments,
    wallet,
    support,
    media,
    ws,
):
    app.include_router(r.router)

app.include_router(services.admin_router)

# Serve uploaded media files from disk.
_media_root = _Path(settings.media_root).expanduser().resolve()
_media_root.mkdir(parents=True, exist_ok=True)
app.mount(
    settings.media_base_url,
    StaticFiles(directory=str(_media_root)),
    name="media",
)

FRONTEND_DIST = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"


@app.get("/health")
async def health():
    """Liveness + DB readiness check.

    Returns 200 with ``{"status": "ok", "db": "ok"}`` when the database
    responds to ``SELECT 1``. Returns 503 with ``{"status": "degraded",
    "db": "down"}`` if the DB round-trip fails — useful for container
    health checks and front-proxy readiness gates.
    """
    from fastapi.responses import JSONResponse

    try:
        async with async_session() as session:
            await session.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001
        logger.exception("health check: DB ping failed")
        return JSONResponse(
            status_code=503,
            content={"status": "degraded", "db": "down"},
        )
    return {"status": "ok", "db": "ok"}


if FRONTEND_DIST.is_dir():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

    @app.get("/{full_path:path}")
    async def spa_fallback(full_path: str):
        file = FRONTEND_DIST / full_path
        if file.is_file():
            return FileResponse(file)
        return FileResponse(FRONTEND_DIST / "index.html")
