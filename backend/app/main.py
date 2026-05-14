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
from .db import async_session, run_migrations
from .redis_client import close_redis
from .seed import run_seed
from .ws import manager as ws_manager

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

    await run_migrations()

    async with async_session() as session:
        await run_seed(session)

    # P3.5 — when Redis is configured, subscribe to the WS broadcast
    # channel so other backend instances' notifications reach our local
    # sockets. A no-op when Redis is disabled.
    await ws_manager.start_subscriber()

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

    await ws_manager.stop_subscriber()
    await close_redis()


app = FastAPI(title="Garant TMA", lifespan=lifespan)

# CORS: the old fallback was ``origins or ["*"]`` which combines with
# ``allow_credentials=True``. Browsers refuse that pairing at runtime so
# the wildcard was inert in practice, but it kept ``ALLOWED_ORIGINS``
# misconfigurations silent and would have been a genuine
# CORS-anywhere-with-credentials vulnerability the moment somebody
# flipped ``allow_credentials`` off. We now require at least one origin
# to be configured and refuse to boot otherwise.
origins = [o.strip() for o in settings.allowed_origins.split(",") if o.strip()]
if not origins:
    raise RuntimeError(
        "ALLOWED_ORIGINS is empty — set it explicitly (e.g. "
        "ALLOWED_ORIGINS=https://your-domain.example,http://localhost:5173). "
        "Refusing to start with a wildcard CORS policy."
    )
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Security response headers. Cheap defence-in-depth on every HTTP
# response — they don't replace input validation but they shrink the
# blast radius if something goes wrong elsewhere (MIME-confusion, leaky
# referrers across third-party redirects, etc.). Set as a middleware
# rather than per-route so static + media + SPA fallback responses are
# covered too.
@app.middleware("http")
async def _security_headers(request, call_next):
    response = await call_next(request)
    # Stop browsers from second-guessing our Content-Type — relevant
    # for the /media/ mount, where a confused sniffer used to be how
    # uploaded HTML got executed.
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    # Don't leak Garant URLs (which encode user IDs in paths) to
    # third-party origins users navigate to from inside the TMA.
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    # Stop other origins from framing the app. Telegram embeds via its
    # native WebView, not an iframe, so ``DENY`` is safe.
    response.headers.setdefault("X-Frame-Options", "DENY")
    return response


# Admin PR-CDE — global maintenance switch. Reads ``AppSettings`` once
# per request and short-circuits state-changing calls when on.
from .maintenance import maintenance_middleware  # noqa: E402

app.middleware("http")(maintenance_middleware)

from .routers import (  # noqa: E402
    account,
    arbitration,
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
from .routers.admin import routers as admin_routers  # noqa: E402

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
    arbitration,
    media,
    ws,
):
    app.include_router(r.router)

app.include_router(services.admin_router)

# Admin panel routers (PR-A: dashboard + users management). All routes
# under /api/admin/* require an authenticated admin.
for r in admin_routers:
    app.include_router(r)

# Serve uploaded media files from disk.
_media_root = _Path(settings.media_root).expanduser().resolve()
_media_root.mkdir(parents=True, exist_ok=True)
app.mount(
    settings.media_base_url,
    StaticFiles(directory=str(_media_root)),
    name="media",
)

FRONTEND_DIST = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"


@app.get("/api/settings/maintenance")
async def public_maintenance_status():
    """Public read-only probe of the maintenance flag.

    Returned to the TMA on every poll so the banner overlay can show
    even for un-logged-in users. Returns ``{"enabled": false,
    "message": ""}`` if the row is missing.
    """
    from sqlalchemy import select as _select

    from .models import AppSettings

    async with async_session() as session:
        row = (
            await session.execute(_select(AppSettings).order_by(AppSettings.id).limit(1))
        ).scalar_one_or_none()
    if row is None:
        return {"enabled": False, "message": ""}
    return {
        "enabled": bool(row.maintenance_enabled),
        "message": row.maintenance_message,
    }


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
