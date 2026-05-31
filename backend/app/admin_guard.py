"""Unified admin authentication dependency.

R2 (audit) — collapse the trio of ``require_admin`` (read-only admin
endpoints), ``require_admin_or_arbiter`` (arbitration tab), and
``require_totp`` (admin write endpoints) into one
``AdminGuard`` callable factory. Every existing admin endpoint stays
on the same behaviour: the legacy type aliases
(:data:`AdminUser`, :data:`AdminOrArbiterUser`, :data:`TotpUser`)
just point at three pre-built ``AdminGuard`` instances.

Why a class instead of three functions?

* **Single source of truth.** All three permission checks now live in
  one ``__call__`` body. Adding a new dimension (IP allowlist,
  per-actor rate limit, audit-action propagation) is one edit
  instead of three.
* **Composable.** The common combinations below cover current admin
  endpoints, including arbiter endpoints that also need TOTP.
* **Cache-friendly.** FastAPI's dependency cache keys on the callable
  identity. The module-level singletons below give the most common
  combinations a stable identity so FastAPI can de-duplicate
  the resolution within a request even across multiple sub-deps.

What this **does not** do (intentionally):

* No ``audit_action=`` parameter. The audit log emitter
  (``log_admin_action``) needs the *before* / *after* snapshots,
  which only the handler has. Pre-emitting from the dep would either
  duplicate the handler's row or fire with empty payloads — both
  worse than the current explicit calls. The action string lives in
  ``log_admin_action(..., action="wallet.adjust", ...)`` at each
  call site and that is where it belongs.
* No IP allowlist / per-actor rate-limit. Those are cross-cutting
  concerns that already have dedicated middlewares
  (``backend.app.rate_limit``, the ``TRUSTED_PROXIES`` setting).
  Re-implementing them inside the auth dep would split the
  enforcement.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from .auth_2fa import _consume_totp, validate_totp_session
from .deps import get_current_user, get_session
from .models import User

__all__ = [
    "AdminGuard",
    "ADMIN_GUARD",
    "ADMIN_GUARD_TOTP",
    "ADMIN_GUARD_OR_ARBITER",
    "ADMIN_GUARD_TOTP_OR_ARBITER",
    "AdminUser",
    "TotpUser",
    "AdminOrArbiterUser",
    "TotpOrArbiterUser",
]


class AdminGuard:
    """Callable FastAPI dependency gating an endpoint behind admin
    access (and optionally a valid TOTP code / arbiter role).

    Usage::

        # Read-only admin endpoint (was ``AdminUser``):
        async def list_things(_admin: AdminUser, ...): ...

        # Admin write endpoint with TOTP (was ``TotpUser``):
        async def mutate_thing(admin: TotpUser, ...): ...

        # Arbiter-or-admin endpoint (was ``AdminOrArbiterUser``):
        async def list_disputes(_u: AdminOrArbiterUser, ...): ...

        # Arbiter-or-admin write endpoint with TOTP:
        async def mutate_dispute(user: TotpOrArbiterUser, ...): ...

    Both flags default to ``False`` to keep the no-argument
    constructor a faithful replacement for the previous
    ``require_admin``.
    """

    __slots__ = ("require_totp", "allow_arbiter")

    def __init__(self, *, require_totp: bool = False, allow_arbiter: bool = False):
        self.require_totp = require_totp
        self.allow_arbiter = allow_arbiter

    async def __call__(
        self,
        user: User = Depends(get_current_user),
        session: AsyncSession = Depends(get_session),
        x_totp_code: str | None = Header(default=None, alias="X-Totp-Code"),
        x_totp_session: str | None = Header(default=None, alias="X-Totp-Session"),
    ) -> User:
        # Direct ``Depends(...)`` markers (not the ``CurrentUser`` /
        # ``SessionDep`` Annotated aliases from ``deps``) because
        # FastAPI introspects ``__call__`` via ``inspect.signature`` and
        # does not chase Annotated metadata through type aliases on
        # bound methods reliably — with the aliases, the params get
        # interpreted as plain query strings and the route returns 422
        # instead of running the dep.
        # Role check first — cheap, no DB write.
        if self.allow_arbiter:
            if not (user.is_admin or user.is_arbiter):
                raise HTTPException(403, "Доступ запрещён")
        else:
            if not user.is_admin:
                raise HTTPException(403, "Доступ запрещён")
        # TOTP last — burns the counter and writes to the session, so
        # we only do it after the cheaper role gate has passed.
        if self.require_totp:
            # 24h ``X-Totp-Session`` JWT short-circuits the per-request
            # code consumption: one code valid for 24h across every
            # admin action. The session is pure (no DB write) and
            # leaves ``_consume_totp`` as the fallback for the very
            # first action of a new 24h window.
            if not validate_totp_session(user, x_totp_session):
                await _consume_totp(session, user, x_totp_code)
        return user


# Module-level singletons. Declaring them once gives FastAPI a stable
# dependency identity (handy for the per-request cache) and keeps
# the call sites short.
ADMIN_GUARD = AdminGuard()
ADMIN_GUARD_TOTP = AdminGuard(require_totp=True)
ADMIN_GUARD_OR_ARBITER = AdminGuard(allow_arbiter=True)
ADMIN_GUARD_TOTP_OR_ARBITER = AdminGuard(require_totp=True, allow_arbiter=True)


# Backwards-compatible type aliases. Every router in the codebase
# imports one of these three names today (``from ...deps import
# AdminUser`` / ``from ...auth_2fa import TotpUser`` / etc.). The
# names stay exactly the same; only the underlying implementation
# now flows through ``AdminGuard``.
AdminUser = Annotated[User, Depends(ADMIN_GUARD)]
TotpUser = Annotated[User, Depends(ADMIN_GUARD_TOTP)]
AdminOrArbiterUser = Annotated[User, Depends(ADMIN_GUARD_OR_ARBITER)]
TotpOrArbiterUser = Annotated[User, Depends(ADMIN_GUARD_TOTP_OR_ARBITER)]
