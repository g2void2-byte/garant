"""``/api/admin/system`` \u2014 service-health introspection.

Returns liveness of the major dependencies (Postgres, Redis) with
latency probes plus a snapshot of process state. Used by the admin
"System" page to colour-code the green/yellow/red lamps and surface
configuration warnings (e.g. no CryptoBot token configured).
"""

from __future__ import annotations

import time
from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy import text

from ...config import settings as app_settings_env
from ...deps import AdminUser, SessionDep
from ...rate_limit import rate_limit
from ...redis_client import get_redis
from ...schemas import AdminSystemStatusOut

router = APIRouter(
    prefix="/api/admin/system",
    tags=["admin"],
    dependencies=[Depends(rate_limit("admin", limit=600, window=60))],
)


_STARTED_AT = datetime.utcnow()


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
        backend_version=getattr(app_settings_env, "version", "dev"),
        started_at=_STARTED_AT,
        uptime_seconds=(datetime.utcnow() - _STARTED_AT).total_seconds(),
    )


@router.post("/redis/flush")
async def flush_redis(_admin: AdminUser):
    r = await get_redis()
    if r is None:
        return {"ok": False, "message": "Redis не настроен"}
    await r.flushdb()
    return {"ok": True}
