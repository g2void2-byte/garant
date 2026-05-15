"""``/api/admin/system`` — service-health introspection.

Returns liveness of the major dependencies (Postgres, Redis) with
latency probes plus a snapshot of process state. Used by the admin
"System" page to colour-code the green/yellow/red lamps and surface
configuration warnings (e.g. no CryptoBot token configured).

The destructive ``POST /redis/flush`` endpoint is 2FA-gated and writes
an entry to the admin audit log — wiping Redis loses all rate-limit
counters, WS pub/sub state, and any other in-memory metadata, so we
treat it as a privileged action on par with treasury withdrawals.
"""

from __future__ import annotations

import time

from fastapi import APIRouter, Depends, Request
from sqlalchemy import text

from ... import version as app_version
from ...admin_audit import log_admin_action
from ...admin_guard import TotpUser
from ...config import settings as app_settings_env
from ...deps import AdminUser, SessionDep
from ...rate_limit import rate_limit
from ...redis_client import get_redis
from ...schemas import AdminSystemStatusOut
from ...time_utils import utcnow

router = APIRouter(
    prefix="/api/admin/system",
    tags=["admin"],
    dependencies=[Depends(rate_limit("admin", limit=600, window=60))],
)


_STARTED_AT = utcnow()


@router.get("/status", response_model=AdminSystemStatusOut)
async def status(_admin: AdminUser, session: SessionDep):
    db_ok = True
    db_latency: float | None = None
    try:
        t0 = time.perf_counter()
        await session.execute(text("SELECT 1"))
        db_latency = (time.perf_counter() - t0) * 1000.0
    except Exception:
        db_ok = False

    redis_ok = False
    redis_latency: float | None = None
    try:
        r = await get_redis()
        if r is not None:
            t0 = time.perf_counter()
            await r.ping()
            redis_latency = (time.perf_counter() - t0) * 1000.0
            redis_ok = True
    except Exception:
        redis_ok = False

    return AdminSystemStatusOut(
        db_ok=db_ok,
        db_latency_ms=db_latency,
        redis_ok=redis_ok,
        redis_latency_ms=redis_latency,
        cryptobot_configured=bool(
            app_settings_env.cryptobot_token
            and not app_settings_env.cryptobot_token.startswith("000")
        ),
        bot_configured=bool(
            app_settings_env.bot_token and not app_settings_env.bot_token.startswith("0000")
        ),
        backend_version=app_version.BACKEND_VERSION,
        started_at=_STARTED_AT,
        uptime_seconds=(utcnow() - _STARTED_AT).total_seconds(),
    )


@router.post("/redis/flush")
async def flush_redis(
    admin: TotpUser,
    request: Request,
    session: SessionDep,
):
    """Wipe the Redis database used by the backend.

    Gated behind 2FA + audit log because a flush clears every key in
    the DB — including shared rate-limit counters and WS pub/sub
    state. The action is recorded under ``system.redis_flush`` so an
    operator can always trace who triggered it.
    """
    r = await get_redis()
    redis_configured = r is not None
    if redis_configured:
        await r.flushdb()
    await log_admin_action(
        session,
        actor=admin,
        action="system.redis_flush",
        target_type="system",
        target_id=None,
        payload={"redis_configured": redis_configured},
        request=request,
    )
    await session.commit()
    if not redis_configured:
        return {"ok": False, "message": "Redis не настроен"}
    return {"ok": True}
