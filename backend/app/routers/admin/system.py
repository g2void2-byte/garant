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
from collections.abc import Awaitable
from datetime import timedelta
from typing import cast

from fastapi import APIRouter, Depends, Request
from redis.exceptions import RedisError
from sqlalchemy import func, or_, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from ... import version as app_version
from ...admin_audit import log_admin_action
from ...admin_guard import TotpUser
from ...config import settings as app_settings_env
from ...deps import AdminUser, SessionDep
from ...models import (
    AdminApprovalRequest,
    AppSettings,
    CurrencyUsdRate,
    Deal,
    DealStatus,
    ProviderWebhookEvent,
    ProviderWebhookOutbox,
    UserBalance,
)
from ...rate_limit import rate_limit
from ...redis_client import get_redis
from ...schemas import AdminSystemStatusOut, OperationalAlertOut
from ...services_wallet import is_cryptopay_configured
from ...time_utils import utcnow

router = APIRouter(
    prefix="/api/admin/system",
    tags=["admin"],
    dependencies=[Depends(rate_limit("admin:system", limit=600, window=60))],
)


_STARTED_AT = utcnow()


async def _count(session: AsyncSession, stmt) -> int:
    return int((await session.execute(stmt)).scalar_one() or 0)


async def _operational_alerts(session: AsyncSession) -> list[OperationalAlertOut]:
    now = utcnow()
    webhook_grace = now - timedelta(minutes=15)
    settings_row = (
        await session.execute(select(AppSettings).order_by(AppSettings.id).limit(1))
    ).scalar_one_or_none()
    pending_topup_hours = int(
        (settings_row.pending_topup_expiry_hours if settings_row is not None else None) or 24
    )
    pending_topup_cutoff = now - timedelta(hours=pending_topup_hours)

    pending_approvals = await _count(
        session,
        select(func.count())
        .select_from(AdminApprovalRequest)
        .where(AdminApprovalRequest.status == "pending"),
    )
    stale_topups = await _count(
        session,
        select(func.count())
        .select_from(Deal)
        .where(
            Deal.status == DealStatus.pending_topup,
            Deal.created_at < pending_topup_cutoff,
        ),
    )
    stuck_webhooks = await _count(
        session,
        select(func.count())
        .select_from(ProviderWebhookEvent)
        .where(
            or_(
                ProviderWebhookEvent.status == "failed",
                ProviderWebhookEvent.status.in_(("received", "processing"))
                & (ProviderWebhookEvent.created_at < webhook_grace),
            )
        ),
    )
    outbox_backlog = await _count(
        session,
        select(func.count())
        .select_from(ProviderWebhookOutbox)
        .where(
            or_(
                ProviderWebhookOutbox.status == "failed",
                (ProviderWebhookOutbox.status == "ready")
                & or_(
                    ProviderWebhookOutbox.next_attempt_at.is_(None),
                    ProviderWebhookOutbox.next_attempt_at <= now,
                ),
            )
        ),
    )
    missing_rate_currencies = await _count(
        session,
        select(func.count(func.distinct(UserBalance.currency_id)))
        .select_from(UserBalance)
        .outerjoin(CurrencyUsdRate, CurrencyUsdRate.currency_id == UserBalance.currency_id)
        .where(
            (UserBalance.amount + UserBalance.locked) > 0,
            CurrencyUsdRate.id.is_(None),
        ),
    )

    alerts: list[OperationalAlertOut] = []
    if pending_approvals:
        alerts.append(
            OperationalAlertOut(
                name="admin_approvals_pending",
                severity="warning",
                count=pending_approvals,
                detail="High-risk admin deal actions are waiting for a second admin.",
            )
        )
    if stale_topups:
        alerts.append(
            OperationalAlertOut(
                name="pending_topup_stale",
                severity="warning",
                count=stale_topups,
                detail=f"Deals stayed pending_topup for more than {pending_topup_hours} hours.",
            )
        )
    if stuck_webhooks:
        alerts.append(
            OperationalAlertOut(
                name="webhook_inbox_attention",
                severity="critical",
                count=stuck_webhooks,
                detail="Webhook inbox rows are failed or stuck in processing.",
            )
        )
    if outbox_backlog:
        alerts.append(
            OperationalAlertOut(
                name="webhook_outbox_backlog",
                severity="warning",
                count=outbox_backlog,
                detail="Webhook outbox rows are ready or failed and need reconciliation.",
            )
        )
    if missing_rate_currencies:
        alerts.append(
            OperationalAlertOut(
                name="usd_rates_missing",
                severity="info",
                count=missing_rate_currencies,
                detail="Currencies with non-zero balances are missing USD rates.",
            )
        )
    return alerts


@router.get("/status", response_model=AdminSystemStatusOut)
async def status(_admin: AdminUser, session: SessionDep):
    db_ok = True
    db_latency: float | None = None
    try:
        t0 = time.perf_counter()
        await session.execute(text("SELECT 1"))
        db_latency = (time.perf_counter() - t0) * 1000.0
    except (SQLAlchemyError, OSError, TimeoutError):
        # Health probe deliberately narrows the catch so it keeps
        # surfacing fatal interpreter errors (``KeyboardInterrupt``,
        # ``MemoryError`` etc.) instead of hiding them behind a
        # green/red lamp.
        db_ok = False

    redis_ok = False
    redis_latency: float | None = None
    try:
        r = await get_redis()
        if r is not None:
            t0 = time.perf_counter()
            # redis-py types ``Redis.ping()`` as
            # ``Union[Awaitable[bool], bool]`` (one method body serves
            # both sync and async clients); pyright picks the ``bool``
            # branch arbitrarily and warns on ``await``. The async
            # client always returns the awaitable at runtime, so cast
            # to narrow it for the type-checker. Mirrors the wrapper
            # in ``redis_client.get_redis``.
            await cast("Awaitable[bool]", r.ping())
            redis_latency = (time.perf_counter() - t0) * 1000.0
            redis_ok = True
    except (RedisError, OSError, TimeoutError):
        # Same narrowing rationale as the DB probe above: ``redis-py``
        # raises ``ConnectionError`` / ``TimeoutError`` (both subclasses
        # of ``RedisError``) on network failure; ``OSError`` covers
        # socket-level failures before the redis layer wraps them.
        # Anything else is a bug we want to bubble up.
        redis_ok = False

    return AdminSystemStatusOut(
        db_ok=db_ok,
        db_latency_ms=db_latency,
        redis_ok=redis_ok,
        redis_latency_ms=redis_latency,
        cryptobot_configured=is_cryptopay_configured(app_settings_env.cryptobot_token),
        bot_configured=bool(
            app_settings_env.bot_token and not app_settings_env.bot_token.startswith("0000")
        ),
        backend_version=app_version.BACKEND_VERSION,
        started_at=_STARTED_AT,
        uptime_seconds=(utcnow() - _STARTED_AT).total_seconds(),
        alerts=await _operational_alerts(session),
    )


# Audit L-12 — closed set of Redis key prefixes the backend itself
# writes. The admin "flush Redis" button now scans for exactly these
# prefixes and deletes only matching keys, instead of calling
# ``FLUSHDB`` which would wipe every key in the DB — including keys
# written by neighbouring services if the Redis instance is shared
# (a common production setup). Adding a new prefix? Add it here too,
# otherwise the flush button won't clear it.
#
# Each entry is paired with a short human description so a follow-up
# audit can grep the codebase for the prefix and find the owning
# module. The descriptions are not exposed in the API response.
_KNOWN_REDIS_PREFIXES: tuple[tuple[str, str], ...] = (
    # rate_limit.py: sliding-window counters keyed
    # ``rl:{scope}:{user|ip}:...``.
    ("rl:", "rate-limit counters"),
    # auth_2fa.py: TOTP single-use claim (``totp-claim:{uid}:{step}``).
    ("totp-claim:", "TOTP single-use claim"),
    # routers/admin/twofa.py: TOTP enrolment pending secret
    # (``totp:pending:{uid}``).
    ("totp:pending:", "TOTP enrolment pending"),
    # ws.py: pub/sub channels for cross-process WS fan-out.
    ("ws:", "WS pub/sub channels"),
)


async def _flush_known_prefixes(r) -> dict[str, int]:
    """Delete every key matching one of :data:`_KNOWN_REDIS_PREFIXES`.

    Uses ``SCAN`` (not ``KEYS``) so the loop is co-operative under a
    big keyspace — ``KEYS`` blocks the Redis event loop for the
    duration of the iteration, while ``SCAN`` returns cursor-paged
    batches that other clients can interleave their commands
    against. Deletes are batched into ``UNLINK`` calls (lazy
    background free in Redis 4+), falling back to ``DEL`` if the
    server is older.

    Returns a ``{prefix: deleted_count}`` map for the audit log so
    operators can see exactly what got wiped.
    """
    counts: dict[str, int] = {}
    for prefix, _desc in _KNOWN_REDIS_PREFIXES:
        match = f"{prefix}*"
        deleted = 0
        # ``scan_iter`` is the async-iterator wrapper around
        # ``SCAN`` provided by redis-py. ``count=500`` is a hint to
        # Redis for the per-batch upper bound (Redis may return
        # fewer); 500 is small enough to avoid long-tail latency
        # spikes and large enough to keep round-trip overhead low.
        batch: list[str] = []
        async for key in r.scan_iter(match=match, count=500):
            batch.append(key)
            if len(batch) >= 500:
                try:
                    deleted += await r.unlink(*batch)
                except Exception:
                    # ``UNLINK`` was added in Redis 4.0 — fall back
                    # to synchronous ``DEL`` on older servers.
                    deleted += await r.delete(*batch)
                batch.clear()
        if batch:
            try:
                deleted += await r.unlink(*batch)
            except Exception:
                deleted += await r.delete(*batch)
        counts[prefix] = deleted
    return counts


@router.post("/redis/flush")
async def flush_redis(
    admin: TotpUser,
    request: Request,
    session: SessionDep,
):
    """Selectively wipe Redis keys this backend wrote.

    Gated behind 2FA + audit log because a flush clears all
    rate-limit counters, TOTP claims and WS pub/sub state. The
    action is recorded under ``system.redis_flush`` so an operator
    can always trace who triggered it.

    Audit L-12 — pre-fix this endpoint called ``FLUSHDB``, which
    wipes EVERY key in the configured Redis DB regardless of which
    service wrote it. In a shared-Redis production deployment the
    button would silently knock out neighbouring services. We now
    iterate the closed set of prefixes the backend itself owns
    (see :data:`_KNOWN_REDIS_PREFIXES`) via ``SCAN`` + ``UNLINK``
    and delete only those keys. Foreign keys are left untouched.
    """
    r = await get_redis()
    redis_configured = r is not None
    deleted_by_prefix: dict[str, int] = {}
    if redis_configured:
        deleted_by_prefix = await _flush_known_prefixes(r)
    await log_admin_action(
        session,
        actor=admin,
        action="system.redis_flush",
        target_type="system",
        target_id=None,
        payload={
            "redis_configured": redis_configured,
            # Mirror the per-prefix delete counts into the audit log
            # so a follow-up incident review can see exactly what
            # was wiped without re-running the flush.
            "deleted_by_prefix": deleted_by_prefix,
        },
        request=request,
    )
    await session.commit()
    if not redis_configured:
        return {"ok": False, "message": "Redis не настроен"}
    return {"ok": True, "deleted_by_prefix": deleted_by_prefix}
