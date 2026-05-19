"""``/api/admin/2fa`` — TOTP enrolment & verification.

Flow:

1. ``GET  /api/admin/2fa/status``       — whether the caller has 2FA on.
2. ``POST /api/admin/2fa/setup``        — server returns a fresh secret +
   ``otpauth://`` URL. The secret is *not* persisted yet.
3. ``POST /api/admin/2fa/enable``       — admin sends the secret back
   together with a TOTP code; on success we persist
   ``users.totp_secret`` and set ``totp_enabled=True``.
4. ``POST /api/admin/2fa/disable``      — turn it off (still requires
   a valid code so a stolen session cannot silently disable 2FA).

The treasury withdrawal endpoint depends on ``auth_2fa.require_totp``
which reads the ``X-Totp-Code`` header.

Replay protection: every accepted code's counter is recorded on
``users.totp_last_counter`` so the same 6-digit value can't be reused
inside its 30-second window (RFC 6238 §5.2). Rotation of an
already-enabled 2FA secret additionally requires a valid ``current_code``
to prove ownership of the existing secret — otherwise a stolen session
could silently swap the secret to one the attacker controls.
"""

from __future__ import annotations

import logging
import time

from fastapi import APIRouter, Depends, HTTPException, Request

from ...admin_audit import log_admin_action
from ...auth_2fa import (
    _consume_totp,
    generate_secret,
    issue_totp_session_token,
    otpauth_url,
    verify_totp_and_counter,
)
from ...deps import AdminUser, SessionDep
from ...rate_limit import rate_limit
from ...redis_client import get_redis
from ...schemas import (
    Admin2faConfirmIn,
    Admin2faSessionOut,
    Admin2faSetupOut,
    Admin2faStatusOut,
    Admin2faVerifyIn,
)

logger = logging.getLogger(__name__)

# Comment 49: pending TOTP secret TTL (10 minutes).
_PENDING_TTL = 10 * 60
# In-process fallback when Redis is unavailable.
#
# Audit section 8 — ``_pending_secrets`` is keyed off the local
# process's memory. With ``REDIS_URL`` set (the production path) the
# fallback is never touched and ``/setup`` -> ``/enable`` works across
# any number of backend replicas because the pending secret lives in
# Redis. Without Redis the fallback works for *single-replica* dev /
# test deployments but breaks transparently on scale-out: a request
# landing on the replica that did NOT serve ``/setup`` will not see
# the secret and will fail enrolment with "TOTP секрет не найден".
# We surface this explicitly with a structured log line at every
# fallback write/read (see ``_store_pending`` / ``_pop_pending``
# below) so operators can detect the misconfiguration before users
# do.
_pending_secrets: dict[int, tuple[str, float]] = {}

router = APIRouter(
    prefix="/api/admin/2fa",
    tags=["admin"],
    dependencies=[Depends(rate_limit("admin", limit=600, window=60))],
)


@router.get("/status", response_model=Admin2faStatusOut)
async def status(admin: AdminUser):
    return Admin2faStatusOut(enabled=bool(admin.totp_enabled and admin.totp_secret))


# Audit section 8 — one-shot guard for the fallback warning. We log
# at WARNING the first time the process writes to the in-process
# fallback (so a scale-out deployment without Redis emits a visible
# signal in the very first 2FA setup attempt) and at DEBUG for
# subsequent occurrences so steady-state logs don't drown in repeats.
_fallback_warned: bool = False


def _warn_fallback_once(event: str, user_id: int) -> None:
    """Emit a one-shot WARNING when we fall back to in-process storage.

    Operators on scale-out deployments without ``REDIS_URL`` will see
    this on the very first 2FA enrolment and can configure Redis
    before users hit "TOTP секрет не найден". Single-replica
    dev / test runs still get one line of visibility too.
    """
    global _fallback_warned
    level = logging.WARNING if not _fallback_warned else logging.DEBUG
    logger.log(
        level,
        "admin 2fa: Redis unavailable, using in-process pending-secret store. "
        "This breaks /setup -> /enable handoff on scale-out (multiple replicas) "
        "because the secret is per-process. Set REDIS_URL to fix.",
        extra={
            "event": event,
            "user_id": user_id,
            "first_observation": not _fallback_warned,
        },
    )
    _fallback_warned = True


async def _store_pending(user_id: int, secret: str) -> None:
    """Store a pending TOTP secret in Redis (or in-process fallback)."""
    r = await get_redis()
    if r is not None:
        try:
            await r.setex(f"totp:pending:{user_id}", _PENDING_TTL, secret)
            return
        except Exception:  # noqa: BLE001
            # V11-L-15 — ``logger.exception`` (and structured ``event``)
            # so the redis-fallback transition is traceable in JSON
            # logs. Pre-fix the warning was a bare message which made
            # it impossible to correlate a 2FA enrolment failure with
            # the underlying redis hiccup.
            logger.exception(
                "Redis setex failed for pending TOTP; using fallback",
                extra={"event": "totp.pending.redis_setex_failed", "user_id": user_id},
            )
    _warn_fallback_once("totp.pending.fallback_write", user_id)
    _pending_secrets[user_id] = (secret, time.monotonic() + _PENDING_TTL)


async def _pop_pending(user_id: int) -> str | None:
    """Retrieve and delete the pending secret."""
    r = await get_redis()
    if r is not None:
        try:
            val = await r.getdel(f"totp:pending:{user_id}")
            if val is not None:
                return val if isinstance(val, str) else val.decode()
        except Exception:  # noqa: BLE001
            logger.exception(
                "Redis getdel failed for pending TOTP; using fallback",
                extra={"event": "totp.pending.redis_getdel_failed", "user_id": user_id},
            )
    entry = _pending_secrets.pop(user_id, None)
    if entry is None:
        return None
    secret, expires = entry
    if time.monotonic() > expires:
        return None
    _warn_fallback_once("totp.pending.fallback_read", user_id)
    return secret


def _reset_fallback_warn_for_tests() -> None:
    """Reset the one-shot fallback guard. Test-only hook."""
    global _fallback_warned
    _fallback_warned = False


@router.post("/setup", response_model=Admin2faSetupOut)
async def setup(admin: AdminUser):
    secret = generate_secret()
    await _store_pending(admin.id, secret)
    account = admin.username or f"id{admin.id}"
    return Admin2faSetupOut(secret=secret, otpauth_url=otpauth_url(secret, account=account))


@router.post("/enable", response_model=Admin2faStatusOut)
async def enable(
    body: Admin2faConfirmIn,
    admin: AdminUser,
    session: SessionDep,
    request: Request,
):
    # Rotation guard: if 2FA is already on, the caller must prove they
    # hold the *current* secret before we accept a new one. Without this
    # a stolen admin session could silently replace the secret.
    #
    # 6.2 — don't touch ``admin.totp_last_counter`` until the new code
    # also verifies. Pre-fix we assigned ``current_counter`` straight
    # onto the row right after the rotation check, then later raised
    # 401 if the *new* code was invalid. The DB rollback from
    # ``AsyncSession.__aexit__`` undid the row write, but the
    # *in-memory* ``admin`` object kept the bumped counter — a latent
    # foot-gun for any future retry/refresh wrapper that re-uses the
    # same instance without ``session.refresh(admin)``. The rotation
    # guard's ``current_counter`` is therefore only used for the
    # threshold check here; the canonical counter post-rotation is
    # ``new_counter`` for the new secret (see the assignment block
    # right before ``session.add(admin)`` below).
    rotated = False
    if admin.totp_enabled and admin.totp_secret:
        if not body.current_code:
            raise HTTPException(401, "Введите текущий код 2FA для ротации")
        current_counter = verify_totp_and_counter(admin.totp_secret, body.current_code)
        if current_counter is None or current_counter <= (admin.totp_last_counter or -1):
            raise HTTPException(401, "Неверный текущий код 2FA")
        rotated = True

    # 11.3.1 — on first enrolment the secret enabled for the user
    # MUST come from ``/setup``'s server-side pending cache; we never
    # accept a client-supplied secret as authoritative. Pre-fix this
    # branch used ``body.secret`` verbatim when provided, which meant
    # an attacker who hijacked an admin session BEFORE 2FA was
    # configured could call ``/enable`` directly with a secret they
    # control — the server would happily persist it, locking the
    # legitimate admin out of their own account on the next login.
    # During a rotation (``admin.totp_enabled`` was already true) the
    # ``current_code`` check above already proves the caller holds the
    # current secret — the session-swap attack is impossible there —
    # so we keep the legacy "trust ``body.secret``" path for rotation
    # to avoid forcing the frontend into a ``/setup`` round-trip on
    # every rotation.
    pending = await _pop_pending(admin.id)
    if rotated:
        # Rotation already gated by ``current_code``; accept the
        # caller-supplied secret. ``pending`` is popped above only so
        # a stale entry from an aborted ``/setup`` doesn't linger past
        # the rotation.
        secret = body.secret or pending
        if not secret:
            raise HTTPException(400, "TOTP секрет не найден. Повторите /setup.")
    else:
        # First enrolment — the secret MUST equal the one ``/setup``
        # stashed; an attacker without a valid ``/setup`` round-trip
        # has nothing to send.
        if pending is None:
            raise HTTPException(400, "TOTP секрет не найден. Повторите /setup.")
        if body.secret and body.secret != pending:
            # Caller-supplied secret diverges from the one ``/setup``
            # stored — reject loudly. The log line is structured so
            # the JSON-logger downstream can alert on repeated
            # secret-mismatch attempts (a strong signal of an active
            # session-hijack secret-swap attempt).
            logger.warning(
                "admin 2fa.enable: client-supplied secret diverges from pending",
                extra={
                    "event": "admin.2fa.enable.secret_mismatch",
                    "actor_id": admin.id,
                },
            )
            raise HTTPException(400, "Секрет не соответствует /setup. Повторите /setup.")
        secret = pending

    new_counter = verify_totp_and_counter(secret, body.code)
    if new_counter is None:
        raise HTTPException(401, "Неверный код")

    # Both codes verified — write the row. ``new_counter`` is the
    # counter of the *new* secret, which is what gates future replay
    # checks (the old secret is being replaced on rotation).
    admin.totp_secret = secret
    admin.totp_enabled = True
    admin.totp_last_counter = new_counter
    # Bump the TOTP session epoch so every 24h session minted before
    # this enable / rotation is invalidated immediately. Without
    # this, an attacker who somehow got a session token before the
    # admin rotated their secret could keep using it for up to 24h.
    admin.totp_session_epoch = int(admin.totp_session_epoch or 0) + 1
    session.add(admin)
    await log_admin_action(
        session,
        actor=admin,
        action="2fa.rotate" if rotated else "2fa.enable",
        target_type="user",
        target_id=admin.id,
        payload={"enabled": True, "rotated": rotated},
        request=request,
    )
    await session.commit()
    return Admin2faStatusOut(enabled=True)


@router.post("/disable", response_model=Admin2faStatusOut)
async def disable(
    body: Admin2faVerifyIn,
    admin: AdminUser,
    session: SessionDep,
    request: Request,
):
    if not admin.totp_enabled or not admin.totp_secret:
        return Admin2faStatusOut(enabled=False)
    matched = verify_totp_and_counter(admin.totp_secret, body.code)
    if matched is None or matched <= (admin.totp_last_counter or -1):
        raise HTTPException(401, "Неверный код")
    # Burn the counter before clearing so a concurrent disable can't
    # reuse the same 6-digit value to disable a re-enabled secret.
    admin.totp_last_counter = matched
    admin.totp_enabled = False
    admin.totp_secret = None
    # Disabling 2FA invalidates every outstanding session immediately.
    admin.totp_session_epoch = int(admin.totp_session_epoch or 0) + 1
    session.add(admin)
    await log_admin_action(
        session,
        actor=admin,
        action="2fa.disable",
        target_type="user",
        target_id=admin.id,
        payload={"enabled": False},
        request=request,
    )
    await session.commit()
    return Admin2faStatusOut(enabled=False)


@router.post("/session", response_model=Admin2faSessionOut)
async def open_session(
    body: Admin2faVerifyIn,
    admin: AdminUser,
    session: SessionDep,
    request: Request,
):
    """Mint a 24h ``X-Totp-Session`` JWT after one valid TOTP code.

    The frontend calls this once when the global 2FA gate is opened
    (either explicitly by the admin via the "Открыть сессию 2FA"
    affordance on ``/admin/2fa``, or implicitly when a TOTP-gated
    action 401s with "Введите код 2FA"). The token is cached in
    ``localStorage`` and replayed on every admin request for the
    next 24h, so the operator only types a code once per workday.

    Replay protection mirrors :func:`auth_2fa._consume_totp` — the
    code's counter is burned in Redis + the DB so the same 6-digit
    value cannot be reused inside its 30s window.
    """
    if not admin.totp_enabled or not admin.totp_secret:
        raise HTTPException(403, "2FA не настроен — пройдите настройку 2FA")
    await _consume_totp(session, admin, body.code)
    # ``_consume_totp`` mutates ``admin`` and adds it to the session
    # but does NOT commit; we have to commit before issuing the JWT
    # so the new ``totp_last_counter`` is durable (otherwise a crash
    # between mint and commit would let the same code be replayed
    # within its 30s window).
    await session.commit()
    token, expires = issue_totp_session_token(admin.id, int(admin.totp_session_epoch or 0))
    await log_admin_action(
        session,
        actor=admin,
        action="2fa.session.open",
        target_type="user",
        target_id=admin.id,
        payload={"expires_at": expires.isoformat()},
        request=request,
    )
    await session.commit()
    return Admin2faSessionOut(token=token, expires_at=expires)
