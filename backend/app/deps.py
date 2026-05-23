from __future__ import annotations

import ipaddress
import logging
from datetime import timedelta
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .auth_helpers import ensure_user_row
from .config import settings
from .db import async_session
from .models import User
from .pin import decode_session_token
from .security import InitDataError, verify_init_data
from .time_utils import utcnow

logger = logging.getLogger(__name__)

_trusted_networks: list[ipaddress.IPv4Network | ipaddress.IPv6Network] | None = None

# A-6 — width of ``users.language_code`` in the schema. Kept slightly
# wider than the IETF "primary tag - region" shape (``pt-BR`` etc.) so
# Telegram's occasional ``zh-hans``-style payloads still fit, but
# bounded so a hostile client can't push 1 MiB of garbage into the
# broadcast filter.
_LANGUAGE_CODE_MAX_LEN = 16


def _normalise_language_code(raw: str | None) -> str | None:
    """Normalise the Telegram ``language_code`` field for storage.

    Returns ``None`` for missing / empty / non-string inputs so the
    column stays NULL — broadcast filters then treat the user as
    "language unknown" (the filter requires an exact match and skips
    NULL rows).
    """
    if not isinstance(raw, str):
        return None
    code = raw.strip().lower()
    if not code:
        return None
    # Audit L-6 — log a single line when truncation actually drops
    # characters so broadcast-filter triage (e.g. "why does ``zh-hans``
    # match but ``zh-hans-cn`` not?") doesn't require reproducing the
    # input. Structured fields keep the message body fixed-cardinality
    # so the JSON-logger downstream can pivot without regex parsing.
    if len(code) > _LANGUAGE_CODE_MAX_LEN:
        truncated = code[:_LANGUAGE_CODE_MAX_LEN]
        logger.warning(
            "language_code truncated to %d chars",
            _LANGUAGE_CODE_MAX_LEN,
            extra={
                "event": "deps.language_code.truncated",
                "original_len": len(code),
                "stored_value": truncated,
            },
        )
        return truncated
    return code


def _get_trusted_networks() -> list[ipaddress.IPv4Network | ipaddress.IPv6Network]:
    global _trusted_networks
    if _trusted_networks is None:
        nets: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = []
        for part in settings.trusted_proxies.split(","):
            part = part.strip()
            if part:
                nets.append(ipaddress.ip_network(part, strict=False))
        _trusted_networks = nets
    return _trusted_networks


def _is_trusted_peer(request: Request) -> bool:
    """Check if the direct peer is in the trusted proxy list.

    H-3: when ``TRUSTED_PROXIES`` is empty (the default) we now return
    ``False`` — i.e. do NOT trust ``X-Forwarded-For`` from arbitrary
    callers. Previously the empty-list case returned ``True`` which
    let any client spoof their IP.
    """
    nets = _get_trusted_networks()
    if not nets:
        return False
    peer = request.client.host if request.client else None
    if not peer:
        return False
    try:
        addr = ipaddress.ip_address(peer)
    except ValueError:
        return False
    return any(addr in net for net in nets)


def _client_ip(request: Request) -> str | None:
    """Best-effort extraction of the originating IP.

    Only honours ``X-Forwarded-For`` / ``X-Real-IP`` when the direct
    peer is in ``TRUSTED_PROXIES``. When that list is empty (default),
    no peers are trusted (H-3) — returns the direct socket peer.
    """
    if _is_trusted_peer(request):
        fwd = request.headers.get("x-forwarded-for")
        if fwd:
            return fwd.split(",")[0].strip()
        real = request.headers.get("x-real-ip")
        if real:
            return real.strip()
    return request.client.host if request.client else None


async def get_session():
    async with async_session() as session:
        yield session


# Minimum gap between two ``last_login_at`` updates for the same user.
# 5 min is short enough that the admin "last seen" column stays fresh
# (the panel auto-refreshes on a similar cadence) but long enough that
# a user pulling-to-refresh in the deals list doesn't generate a
# write per call. Module-level so tests can patch it.
_LAST_LOGIN_DEBOUNCE = timedelta(minutes=5)

# Audit v3 A-3 — minimum gap of inactivity before we treat the next
# request as the start of a new "session" for analytics purposes.  Any
# gap shorter than this is the same continuous session (user idle on
# the deal list, app suspended in background, fast-pull-to-refresh).
# 30 min is the industry-standard idle timeout (matches GA4's default
# session timeout) and is long enough that a normal "switched apps for
# a coffee" doesn't double-count, short enough that "came back after
# lunch" does.  Module-level so tests can patch it.
_SESSION_GAP = timedelta(minutes=30)


# Item 24 — backwards-compatible structured lockout payload. Pre-fix
# the 403 carried only a Russian string ("Аккаунт заблокирован"); the
# frontend had no way to distinguish ban-vs-frozen, no reason text and
# no admin contact, so the TMA just showed a generic error and the
# user had no path to appeal. Now the payload carries:
#
# * ``code`` — ``"banned"`` / ``"frozen"`` so the frontend can route to
#   the right gate screen.
# * ``reason`` — admin-supplied ``ban_reason`` / ``freeze_reason``.
# * ``admin_username`` — first available admin's Telegram username,
#   used by the gate's "Связаться с админом" button to deep-link to
#   ``https://t.me/<admin>``. ``None`` if the admins haven't set a
#   username yet (rare; the gate falls back to a plain text message).
#
# The ``message`` field keeps the legacy Russian string so any older
# client that still treats ``detail`` as a plain string degrades to
# the same toast it used to show.
async def _first_admin_username(session: AsyncSession) -> str | None:
    """Resolve the first admin Telegram ``username`` for ban-gate deep-links.

    Picks the lowest-id admin with a non-NULL username so the choice is
    deterministic across sessions. Returns ``None`` if no admin has a
    username configured.
    """

    stmt = (
        select(User.username)
        .where(User.is_admin.is_(True), User.username.isnot(None))
        .order_by(User.id.asc())
        .limit(1)
    )
    row = (await session.execute(stmt)).scalar_one_or_none()
    return row


async def _build_lockout_exception(session: AsyncSession, user: User) -> HTTPException:
    admin = await _first_admin_username(session)
    if user.is_banned:
        code = "banned"
        message = "Аккаунт заблокирован"
        reason = user.ban_reason
    else:
        code = "frozen"
        message = "Аккаунт заморожен"
        reason = user.freeze_reason
    return HTTPException(
        status_code=403,
        detail={
            "code": code,
            "message": message,
            "reason": reason,
            "admin_username": admin,
        },
    )


async def get_current_user(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
    session: AsyncSession = Depends(get_session),
) -> User:
    # Audit (continuation) H-3 — pre-fix ``authorization`` was a
    # *required* ``Header()`` parameter, so a client that omitted the
    # header entirely got a 422 from FastAPI's Pydantic validation
    # layer with body ``{"detail":[{"type":"missing","loc":["header",
    # "authorization"]...}]}``. Two problems with that:
    #   1. The 422 leaks the internal field name + Pydantic error
    #      machinery to anonymous callers (defence-in-depth issue).
    #   2. The frontend ``ky.beforeError`` hook is wired to re-auth
    #      on 401/403 — 422 falls through to a generic error toast
    #      so an expired initData blob shows a confusing "Не удалось"
    #      instead of triggering a fresh re-auth handshake.
    # Marking the header optional lets us emit a clean 401 with the
    # same shape as the other auth failures below.
    if not authorization:
        raise HTTPException(401, "Authorization header missing")
    if not authorization.lower().startswith("tma "):
        raise HTTPException(401, "Invalid Authorization header")

    init_data = authorization[4:]
    try:
        tg_user = verify_init_data(init_data)
    except InitDataError as e:
        raise HTTPException(401, str(e)) from e

    tg_user_id = tg_user.get("id")
    if not tg_user_id:
        raise HTTPException(401, "User ID not found in init data")

    ip = _client_ip(request)
    now = utcnow()

    stmt = select(User).where(User.tg_user_id == tg_user_id)
    result = await session.execute(stmt)
    user = result.scalar_one_or_none()

    if user is None:
        # Audit H-2 / L-1 — both REST (``get_current_user``) and WS
        # (``routers/ws._authenticate``) routes go through the same
        # ``ensure_user_row`` helper so two parallel first-touch
        # deliveries from a brand-new client always converge on a
        # single row via ``INSERT ... ON CONFLICT`` instead of crashing
        # the loser with an ``IntegrityError`` on ``users.tg_user_id``.
        #
        # A-6 — Telegram populates ``user.language_code`` (a two-letter
        # IETF tag like ``ru`` or ``en``, occasionally a region-tagged
        # variant like ``pt-br``) in the initData blob. Normalise to
        # lowercase + clip to the column width so a misbehaving client
        # can't OOM the admin broadcast filter, and tolerate clients
        # that omit the field entirely (legacy Telegram desktop builds).
        language_code = _normalise_language_code(tg_user.get("language_code"))
        # ``bump_login=True`` is REST-only: the helper bumps
        # ``login_count`` and refreshes ``last_login_at`` / ``last_ip``
        # for both the winning insert AND the loser of the race,
        # mirroring what the existing-user branch below does on every
        # post-debounce session ping (audit L-1). WS does not count as
        # a "session ping" — see ``routers/ws._authenticate`` for the
        # ``DO NOTHING`` variant.
        try:
            user = await ensure_user_row(
                session,
                tg_user_id=tg_user_id,
                username=tg_user.get("username"),
                display_name=tg_user.get("first_name", ""),
                photo_url=tg_user.get("photo_url"),
                language_code=language_code,
                bump_login=True,
                last_ip=ip,
                now=now,
            )
        except RuntimeError as exc:  # pragma: no cover — see helper
            raise HTTPException(500, "Failed to create user account") from exc
    else:
        # Comment 50 (M) — refuse banned / frozen accounts BEFORE
        # writing anything to their row. Pre-fix the access check
        # lived after the ``last_login_at`` / ``login_count`` /
        # ``last_ip`` bump, so every request from a banned user
        # still landed an UPDATE on ``users`` — wasting WAL and
        # silently extending the admin panel's "last seen" column
        # to show that a *blocked* user was just active. Cheap
        # role gate first; the DB-write side effects only run for
        # callers who would actually get past the 403.
        if user.is_banned or user.is_frozen:
            raise await _build_lockout_exception(session, user)

        dirty = False
        # Audit (continuation) L-8 — defensive ``.strip()`` so a
        # malformed/empty ``username`` field from Telegram never
        # overwrites a previously-set value with whitespace. Telegram
        # itself never sends ``username=""`` (it omits the key when
        # there's no username), but a future client-side
        # transformation that calls ``trim()`` *and* keeps the field
        # would otherwise pass this gate and blank out
        # ``user.username``. Truthiness alone wouldn't catch that.
        observed_username = (tg_user.get("username") or "").strip()
        if observed_username and user.username != observed_username:
            user.username = observed_username
            dirty = True
        # A-6 — refresh ``language_code`` on the same dirty-track as
        # ``username`` so an admin broadcast targeting the ``ru`` cohort
        # picks up users who switched their Telegram client locale
        # since their last visit. Comparing to ``user.language_code``
        # avoids touching the row when nothing changed.
        observed_lang = _normalise_language_code(tg_user.get("language_code"))
        if observed_lang is not None and user.language_code != observed_lang:
            user.language_code = observed_lang
            dirty = True
        # "Session ping": stamp ``last_login_at`` / bump ``login_count``
        # for the admin panel's "last seen" column. Debounced to at
        # most once per ``_LAST_LOGIN_DEBOUNCE`` so we don't UPDATE the
        # row on every API call — a single active user paging the deal
        # list otherwise generates hundreds of writes/hour, drowning
        # WAL and conflicting with admin updates on the same row.
        #
        # V11-M-4 — ``last_ip`` is now debounced into the same window.
        # Pre-fix, ``user.last_ip != ip`` ran every request, so a
        # mobile user whose CGN address bounces between cells (or any
        # Wi-Fi ↔ LTE handoff) generated a write per API call. The new
        # rule: if we're inside the debounce window, leave ``last_ip``
        # alone; the next session-ping refresh will stamp the freshest
        # observed IP. This collapses the worst case to one UPDATE per
        # 5 min instead of one per HTTP request.
        should_ping = (
            user.last_login_at is None or (now - user.last_login_at) >= _LAST_LOGIN_DEBOUNCE
        )
        if should_ping:
            # Audit v3 A-3 — only treat this as a fresh *session* if
            # the gap since the last ping crossed ``_SESSION_GAP``;
            # within that window the user is still inside the same
            # session.  ``last_login_at is None`` is the brand-new
            # row case (no prior pings) and trivially counts as a
            # new session.  We evaluate this BEFORE the
            # ``last_login_at = now`` assignment below so the gap
            # measurement is taken against the *previous* ping.
            is_new_session = (
                user.last_login_at is None or (now - user.last_login_at) >= _SESSION_GAP
            )
            user.last_login_at = now
            user.login_count = (user.login_count or 0) + 1
            if is_new_session:
                user.sessions_count = (user.sessions_count or 0) + 1
            if user.last_ip != ip:
                user.last_ip = ip
            dirty = True
        if dirty:
            await session.commit()

    # New-user path drops here directly: the row we just inserted
    # has the model defaults (``is_banned=False`` / ``is_frozen=False``),
    # so the gate above is a no-op for first-touch callers — but we
    # still keep a belt-and-braces check here in case a future
    # migration starts seeding banned rows.
    if user.is_banned or user.is_frozen:
        raise await _build_lockout_exception(session, user)

    return user


async def require_pin_session(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    x_pin_token: Annotated[str | None, Header(alias="X-Pin-Token")] = None,
) -> User:
    """Require a valid PIN session token in addition to the Telegram initData.

    Used to gate sensitive endpoints (wallet, deal payments, account
    transfer). Endpoints that only need user identity stay on
    `get_current_user`.

    The token embeds the user's ``pin_session_epoch`` at issue time; if
    an admin has since bumped that column (``invalidate-sessions``), the
    token's epoch no longer matches and the session is rejected without
    waiting for the JWT TTL.

    Idle window enforcement: a token whose JWT exp is still in the
    future but whose ``user.pin_last_activity_at`` is older than
    ``settings.pin_session_ttl_seconds`` is rejected with the same
    "session expired" detail the client uses to wipe the local token
    and re-prompt for the PIN. ``pin_last_activity_at`` is bumped on
    every successful gate-pass (debounced via
    ``settings.pin_activity_debounce_seconds`` to avoid one write per
    request on busy users).
    """
    if not user.pin_hash:
        raise HTTPException(
            403,
            {"code": "pin_not_set", "detail": "PIN не установлен"},
        )
    if not x_pin_token:
        raise HTTPException(
            401,
            {"code": "pin_session_missing", "detail": "PIN-сессия отсутствует"},
        )
    decoded = decode_session_token(x_pin_token)
    if decoded is None:
        raise HTTPException(
            401,
            {"code": "pin_session_invalid", "detail": "PIN-сессия недействительна"},
        )
    token_user_id, token_epoch = decoded
    if token_user_id != user.id:
        raise HTTPException(
            401,
            {"code": "pin_session_invalid", "detail": "PIN-сессия недействительна"},
        )
    if token_epoch != (user.pin_session_epoch or 0):
        raise HTTPException(
            401,
            {"code": "pin_session_revoked", "detail": "PIN-сессия отозвана"},
        )

    now = utcnow()
    idle_window = timedelta(seconds=settings.pin_session_ttl_seconds)
    last = user.pin_last_activity_at
    if last is not None and (now - last) > idle_window:
        raise HTTPException(
            401,
            {"code": "pin_session_idle", "detail": "PIN-сессия истекла из-за неактивности"},
        )
    # Debounce the activity write so back-to-back protected calls don't
    # generate a write per request. NULL → first write unconditionally.
    debounce = timedelta(seconds=settings.pin_activity_debounce_seconds)
    if last is None or (now - last) >= debounce:
        user.pin_last_activity_at = now
        await session.commit()
    return user


SessionDep = Annotated[AsyncSession, Depends(get_session)]
CurrentUser = Annotated[User, Depends(get_current_user)]
PinUser = Annotated[User, Depends(require_pin_session)]


# Admin gating moved to :mod:`backend.app.admin_guard` (R2 — unified
# admin dependency). The legacy type aliases are re-exported here so
# existing ``from .deps import AdminUser`` imports keep working.
#
# Lazy re-export via :pep:`562` module-level ``__getattr__``: a direct
# top-level ``from .admin_guard import ...`` would deadlock because
# ``admin_guard`` itself imports ``CurrentUser`` / ``SessionDep`` from
# this module. ``__getattr__`` only fires when an attribute is looked
# up *after* both modules have finished loading, so the cycle is
# avoided at import time. Once resolved, the value is cached in the
# module's ``__dict__`` so subsequent lookups are direct.
def __getattr__(name: str):
    if name in ("AdminUser", "AdminOrArbiterUser"):
        from . import admin_guard

        value = getattr(admin_guard, name)
        globals()[name] = value
        return value
    raise AttributeError(name)
