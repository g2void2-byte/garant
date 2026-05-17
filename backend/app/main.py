from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from .config import settings
from .db import async_session, run_migrations, verify_migrations_at_head
from .redis_client import close_redis
from .seed import run_seed
from .ws import manager as ws_manager

logger = logging.getLogger(__name__)
# V11-M-13 — only install the default root handler when no other
# handler is configured yet. Pre-fix the unconditional
# ``basicConfig(...)`` call meant that if an embedder (gunicorn,
# uvicorn ``--log-config``, a test harness) had already wired up
# structured / JSON logging at import time, our naive
# ``"%(levelname)s: %(name)s: %(message)s"`` format silently replaced
# theirs — because ``basicConfig`` was a no-op on the first call
# (theirs), then theirs ran ours and ours installed an *additional*
# stream handler. Guarding on ``root.handlers`` is the documented way
# to opt in to the default config only when the embedder hasn't said
# otherwise; tests / production logging frameworks now keep their
# handlers intact.
if not logging.getLogger().handlers:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(name)s: %(message)s")

_bot_task: asyncio.Task | None = None
_inactivity_task: asyncio.Task | None = None
_deposit_expiry_task: asyncio.Task | None = None
_invoice_expiry_task: asyncio.Task | None = None
_last_ip_purge_task: asyncio.Task | None = None

# V11-L-17 — exponential backoff ceiling for sweep loop error retries.
# Without a ceiling a database that stays down would accelerate the
# back-off arbitrarily; capping at 5 min means even a multi-hour
# outage produces at most ~12 retries / hour per loop. The base unit
# is the loop's own configured ``interval_seconds`` so a sweep that
# normally runs every 30 s caps its retries way earlier than one that
# runs every 10 min.
_SWEEP_BACKOFF_MAX_SECONDS = 300.0


def _make_sweep_loop(
    name: str,
    work: Callable[[], Awaitable[int | None]],
    success_message: str,
) -> Callable[[int], Awaitable[None]]:
    """Build a background sweep loop with logging + exponential backoff.

    V11-L-8 / V11-L-17 — pre-fix every sweep (inactivity, deposit
    expiry, invoice expiry, last-IP purge) had its own near-identical
    while-True body. Four duplicated try/except/sleep blocks meant
    four places to forget to update the next time we add a retry
    semantic. This factory centralises:

    1. The error try/except (cancellation passes through, anything
       else is logged with traceback rather than crashing the loop).
    2. The success log line — only emitted when ``work()`` returned
       a truthy affected-count, so silent sweeps stay silent.
    3. Exponential backoff on errors. The first failure waits the
       full ``interval``, the second waits ``2 × interval``, capped
       at :data:`_SWEEP_BACKOFF_MAX_SECONDS`. A successful iteration
       resets the backoff. This protects the DB from getting pinned
       by tight-loop reconnect storms during an outage; pre-fix every
       sweep would hammer the broken connection every ``interval_seconds``
       indefinitely.

    ``work`` is an ``async`` zero-arg callable that returns the
    affected-row count (or ``None`` for a no-op).
    """

    async def loop(interval_seconds: int) -> None:
        backoff_multiplier = 1
        while True:
            try:
                affected = await work()
                if affected:
                    logger.info(success_message, affected)
                backoff_multiplier = 1
                await asyncio.sleep(interval_seconds)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                logger.exception("%s sweep failed", name)
                sleep_for = min(
                    interval_seconds * backoff_multiplier,
                    _SWEEP_BACKOFF_MAX_SECONDS,
                )
                backoff_multiplier = min(backoff_multiplier * 2, 64)
                await asyncio.sleep(sleep_for)

    loop.__name__ = f"_sweep_loop_{name}"
    return loop


async def _inactivity_work() -> int | None:
    from .services_deals import sweep_inactivity

    async with async_session() as session:
        return await sweep_inactivity(session)


async def _deposit_expiry_work() -> int | None:
    from .services_wallet import sweep_expired_deposits

    async with async_session() as session:
        return await sweep_expired_deposits(session)


async def _invoice_expiry_work() -> int | None:
    from .services import sweep_expired_invoices

    async with async_session() as session:
        return await sweep_expired_invoices(session)


async def _last_ip_purge_work() -> int | None:
    from .services import sweep_user_last_ip

    async with async_session() as session:
        return await sweep_user_last_ip(session)


# Concrete loops are produced via the factory. Names kept identical
# to the legacy hand-rolled functions so external imports / tests that
# monkey-patch by module attribute keep working.
_inactivity_loop = _make_sweep_loop(
    "inactivity",
    _inactivity_work,
    "inactivity sweep: cancelled %d deal(s)",
)
_deposit_expiry_loop = _make_sweep_loop(
    "deposit-expiry",
    _deposit_expiry_work,
    "deposit-expiry sweep: marked %d deposit(s) expired",
)
_invoice_expiry_loop = _make_sweep_loop(
    "invoice-expiry",
    _invoice_expiry_work,
    "invoice-expiry sweep: marked %d invoice(s) expired",
)
_last_ip_purge_loop = _make_sweep_loop(
    "last-ip-purge",
    _last_ip_purge_work,
    "last-ip purge: scrubbed %d user(s)",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global \
        _bot_task, \
        _inactivity_task, \
        _deposit_expiry_task, \
        _invoice_expiry_task, \
        _last_ip_purge_task

    # M-8 — Redis-backed rate limit is the only way to share counters
    # across uvicorn workers / replicas. With ``REDIS_URL`` empty the
    # limiter silently falls back to per-process buckets, so the
    # effective limit becomes ``N × configured`` for ``N`` workers.
    # Refuse to boot in production/staging; loud WARNING in dev/test so
    # local runs aren't blocked.
    if not settings.redis_url:
        if settings.environment in ("production", "staging"):
            raise RuntimeError(
                "REDIS_URL must be set when ENVIRONMENT is "
                f"'{settings.environment}'; in-memory rate-limit "
                "counters are per-process and unsafe with multiple workers."
            )
        logger.warning(
            "REDIS_URL is empty — rate-limit counters are per-process; "
            "this is OK for development only.",
        )

    # ``ALLOW_UNSIGNED_INIT_DATA`` skips Telegram HMAC verification so the
    # TMA can run outside Telegram during local development. Allowing it
    # in production/staging would let any caller forge an init-data
    # payload and authenticate as an arbitrary user, so refuse to boot
    # before we open the listener.
    if settings.allow_unsigned_init_data and settings.environment in ("production", "staging"):
        raise RuntimeError(
            "ALLOW_UNSIGNED_INIT_DATA must not be enabled when ENVIRONMENT is "
            f"'{settings.environment}'; it disables Telegram HMAC verification "
            "and is dev-only."
        )

    # V12-H3 — by default run migrations in-process so single-node
    # deploys (manual ``uvicorn``, the test suite) keep working. With
    # ``RUN_MIGRATIONS_ON_STARTUP=false`` (the compose default — see
    # the dedicated ``migrate`` init-service in ``docker-compose.yml``)
    # we only assert the DB is already at the head revision this
    # build expects. The two paths share an advisory lock at the
    # alembic level so a misconfigured deploy with both paths
    # enabled still serialises rather than racing.
    if settings.run_migrations_on_startup:
        await run_migrations()
    else:
        await verify_migrations_at_head()

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

    if settings.wallet_deposit_sweep_seconds > 0:
        _deposit_expiry_task = asyncio.create_task(
            _deposit_expiry_loop(settings.wallet_deposit_sweep_seconds)
        )

    if settings.invoice_sweep_seconds > 0:
        _invoice_expiry_task = asyncio.create_task(
            _invoice_expiry_loop(settings.invoice_sweep_seconds)
        )

    if settings.last_ip_purge_sweep_seconds > 0:
        _last_ip_purge_task = asyncio.create_task(
            _last_ip_purge_loop(settings.last_ip_purge_sweep_seconds)
        )

    yield

    for task in (
        _bot_task,
        _inactivity_task,
        _deposit_expiry_task,
        _invoice_expiry_task,
        _last_ip_purge_task,
    ):
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
# V11-M-17 — replaced wildcard ``allow_methods=["*"]`` /
# ``allow_headers=["*"]`` with explicit allowlists. With
# ``allow_credentials=True`` browsers already refuse to honour ``*``,
# so the wildcards were functionally inert — but they made it easy
# to miss a CORS misconfig in code review. The explicit lists below
# cover every method and header that ``frontend/src/api/client.ts``
# actually sends; anything outside this set is now refused at the
# preflight stage rather than silently working in some browsers and
# failing in others.
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
    allow_headers=[
        "Accept",
        "Accept-Language",
        "Authorization",
        "Content-Type",
        "X-Pin-Token",
        "X-Requested-With",
    ],
)


# Security response headers. Cheap defence-in-depth on every HTTP
# response — they don't replace input validation but they shrink the
# blast radius if something goes wrong elsewhere (MIME-confusion, leaky
# referrers across third-party redirects, etc.). Set as a middleware
# rather than per-route so static + media + SPA fallback responses are
# covered too.
#
# CSP rationale — the TMA loads exactly one cross-origin script
# (``telegram-web-app.js`` from ``telegram.org``), talks to its own
# backend only (REST + WebSocket on the same origin), and renders
# user-uploaded avatars/screenshots from ``/media/`` (same origin).
# Everything else collapses to ``'self'``. ``frame-ancestors 'none'``
# duplicates the legacy ``X-Frame-Options: DENY`` for modern browsers
# that prefer the CSP3 directive.
#
# L-2 — ``style-src`` is now ``'self'`` only. Framer Motion was the
# sole source of dynamic inline ``style=`` attributes, and the full
# migration to CSS class-based animations (PR «CSP nonce migration»)
# eliminated that dependency. React CSR (client-side rendering via
# ``createRoot``) sets element styles through the CSSOM
# (``element.style.prop = value``), which is NOT blocked by CSP
# ``style-src`` — only HTML ``style=`` attributes in source markup
# are restricted. Since the app is a Vite SPA with no SSR, the
# remaining dynamic ``style`` props (layout positioning, scroll
# parallax) go through React DOM's CSSOM path and are safe.
#
# The CSP report endpoint is kept as telemetry for regressions:
# ``report-uri``/``report-to`` so we can SEE what would actually break
# if we tightened the policy, before flipping the switch. That's what
# the trailing ``report-uri`` directive does: violations get POSTed to
# ``/api/csp-report`` (defined below), where we rate-limit them and
# log at INFO level. Browsers also accept ``report-to`` but it needs a
# matching ``Report-To`` header naming an endpoint group — sticking
# with the legacy ``report-uri`` is enough for the telemetry pass and
# avoids the extra header.
_CSP_DIRECTIVES = (
    "default-src 'self'; "
    "script-src 'self' https://telegram.org; "
    "style-src 'self'; "
    "img-src 'self' data: blob:; "
    "font-src 'self' data:; "
    "connect-src 'self'; "
    "worker-src 'self' blob:; "
    "frame-ancestors 'none'; "
    "base-uri 'self'; "
    "form-action 'self'; "
    "object-src 'none'; "
    "report-uri /api/csp-report"
)


@app.middleware("http")
async def _security_headers(request, call_next):
    response = await call_next(request)
    # V11-M-16 — direct assignment, NOT ``setdefault``. Security
    # headers are policy from this middleware; a downstream handler
    # that happens to set ``X-Content-Type-Options`` (or, worse,
    # ``Content-Security-Policy: ""``) must not be able to weaken
    # the global policy by accident. If a specific route ever needs
    # a different CSP (e.g. an embed page) it has to be whitelisted
    # by ``request.url.path`` here, never by overriding a header in
    # the route body.
    # Stop browsers from second-guessing our Content-Type — relevant
    # for the /media/ mount, where a confused sniffer used to be how
    # uploaded HTML got executed.
    response.headers["X-Content-Type-Options"] = "nosniff"
    # Don't leak Garant URLs (which encode user IDs in paths) to
    # third-party origins users navigate to from inside the TMA.
    response.headers["Referrer-Policy"] = "no-referrer"
    # Stop other origins from framing the app. Telegram embeds via its
    # native WebView, not an iframe, so ``DENY`` is safe.
    response.headers["X-Frame-Options"] = "DENY"
    # Full CSP — closes the gap flagged as Info in the security audit.
    response.headers["Content-Security-Policy"] = _CSP_DIRECTIVES
    return response


# Admin PR-CDE — global maintenance switch. Reads ``AppSettings`` once
# per request and short-circuits state-changing calls when on.
from .maintenance import maintenance_middleware  # noqa: E402

app.middleware("http")(maintenance_middleware)

from .routers import (  # noqa: E402
    account,
    arbitration,
    categories,
    csp_report,
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
    csp_report,
):
    app.include_router(r.router)

app.include_router(services.admin_router)

# Admin panel routers (PR-A: dashboard + users management). All routes
# under /api/admin/* require an authenticated admin.
for r in admin_routers:
    app.include_router(r)

# Serve uploaded media files from disk.
_media_root = Path(settings.media_root).expanduser().resolve()
_media_root.mkdir(parents=True, exist_ok=True)
app.mount(
    settings.media_base_url,
    StaticFiles(directory=str(_media_root)),
    name="media",
)

# V11-M-15 — frontend dist directory is overridable via
# ``settings.frontend_dist_dir``. Pre-fix the path was hard-coded to
# the monorepo layout (``<repo>/frontend/dist``), which is fine for a
# Docker build but broken for deploys where the SPA is served by a
# CDN / S3 and the backend container has no ``frontend/`` directory
# at all. Empty (default) preserves the legacy resolution so existing
# monorepo deploys are unaffected.
if settings.frontend_dist_dir:
    FRONTEND_DIST = Path(settings.frontend_dist_dir).expanduser().resolve()
else:
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


def resolve_spa_path(full_path: str, dist: Path) -> Path:
    """Map a SPA fallback request path to a file inside ``dist``.

    Returns the resolved absolute path. If the request's path attempts
    to escape ``dist`` (via ``..`` segments, an embedded absolute path,
    or any other trick that ``Path.resolve`` normalises), the function
    returns ``dist / "index.html"`` — the SPA shell — instead. The
    same fallback applies when the resolved target points inside the
    dist but doesn't actually exist on disk (e.g. a client-side route
    like ``/deals/123``).

    R1/C-3 — extracted from the route handler so the traversal
    semantics can be unit-tested without spinning up a real built
    frontend bundle on disk.
    """
    dist_resolved = dist.resolve()
    candidate = (dist / full_path).resolve()
    if not candidate.is_relative_to(dist_resolved):
        return dist / "index.html"
    if candidate.is_file():
        return candidate
    return dist / "index.html"


if FRONTEND_DIST.is_dir():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

    @app.get("/{full_path:path}")
    async def spa_fallback(full_path: str):
        # V11-H-5 — ``index.html`` MUST NOT be cached by browsers or
        # intermediary CDNs/proxies. ``/assets/*`` filenames are
        # content-hashed by Vite so long TTLs on those are safe and
        # desirable; but the SPA shell itself references hashed asset
        # paths inline, and any cached copy of ``index.html`` will
        # keep pointing at asset bundles that have since been deleted
        # on the server. The symptom is "stale users see a blank
        # screen for days after a deploy". ``no-store`` is the
        # strongest CDN signal — stricter than ``no-cache`` (which
        # only forces revalidation, not eviction) — and is the right
        # choice for an SPA shell whose response body changes on
        # every deploy.
        response = FileResponse(resolve_spa_path(full_path, FRONTEND_DIST))
        response.headers["Cache-Control"] = "no-store"
        return response
