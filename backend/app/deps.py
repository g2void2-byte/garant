from __future__ import annotations

import ipaddress
from datetime import datetime, timedelta
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .db import async_session
from .models import User
from .pin import decode_session_token
from .security import InitDataError, verify_init_data

_trusted_networks: list[ipaddress.IPv4Network | ipaddress.IPv6Network] | None = None


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
    """Check if the direct peer is in the trusted proxy list."""
    nets = _get_trusted_networks()
    if not nets:
        return True
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
    all peers are trusted for backwards compatibility.
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


async def get_current_user(
    request: Request,
    authorization: Annotated[str, Header()],
    session: AsyncSession = Depends(get_session),
) -> User:
    if not authorization.lower().startswith("tma "):
        raise HTTPException(401, "Invalid Authorization header")

    init_data = authorization[4:]
    try:
        tg_user = verify_init_data(init_data)
    except InitDataError as e:
        raise HTTPException(401, str(e))

    tg_user_id = tg_user.get("id")
    if not tg_user_id:
        raise HTTPException(401, "User ID not found in init data")

    stmt = select(User).where(User.tg_user_id == tg_user_id)
    result = await session.execute(stmt)
    user = result.scalar_one_or_none()

    ip = _client_ip(request)
    now = datetime.utcnow()

    if user is None:
        user = User(
            tg_user_id=tg_user_id,
            username=tg_user.get("username"),
            display_name=tg_user.get("first_name", ""),
            photo_url=tg_user.get("photo_url"),
            last_ip=ip,
            last_login_at=now,
            login_count=1,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
    else:
        dirty = False
        if tg_user.get("username") and user.username != tg_user["username"]:
            user.username = tg_user["username"]
            dirty = True
        if user.last_ip != ip:
            user.last_ip = ip
            dirty = True
        # "Session ping": stamp ``last_login_at`` / bump ``login_count``
        # for the admin panel's "last seen" column. Debounced to at
        # most once per ``_LAST_LOGIN_DEBOUNCE`` so we don't UPDATE the
        # row on every API call — a single active user paging the deal
        # list otherwise generates hundreds of writes/hour, drowning
        # WAL and conflicting with admin updates on the same row.
        if user.last_login_at is None or (now - user.last_login_at) >= _LAST_LOGIN_DEBOUNCE:
            user.last_login_at = now
            user.login_count = (user.login_count or 0) + 1
            dirty = True
        if dirty:
            await session.commit()
            await session.refresh(user)

    if user.is_banned:
        raise HTTPException(403, "Аккаунт заблокирован")
    if user.is_frozen:
        raise HTTPException(403, "Аккаунт заморожен")

    return user


async def require_pin_session(
    user: User = Depends(get_current_user),
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
    """
    if not user.pin_hash:
        raise HTTPException(403, "PIN не установлен")
    if not x_pin_token:
        raise HTTPException(401, "PIN-сессия отсутствует")
    decoded = decode_session_token(x_pin_token)
    if decoded is None:
        raise HTTPException(401, "PIN-сессия недействительна")
    token_user_id, token_epoch = decoded
    if token_user_id != user.id:
        raise HTTPException(401, "PIN-сессия недействительна")
    if token_epoch != (user.pin_session_epoch or 0):
        raise HTTPException(401, "PIN-сессия отозвана")
    return user


async def require_admin(
    user: User = Depends(get_current_user),
) -> User:
    """Gate an endpoint behind ``is_admin``.

    Used by every ``/api/admin/*`` route. The two privileged roles are
    ``admin`` (full access) and ``arbiter`` (only the arbitration tab,
    handled by its own dep).
    """
    if not user.is_admin:
        raise HTTPException(403, "Доступ запрещён")
    return user


async def require_admin_or_arbiter(
    user: User = Depends(get_current_user),
) -> User:
    """Gate an endpoint behind ``is_admin`` OR ``is_arbiter``.

    Used by arbitration-only endpoints in the admin panel: arbiters can
    read their own dispute queue, admins see everything.
    """
    if not (user.is_admin or user.is_arbiter):
        raise HTTPException(403, "Доступ запрещён")
    return user


SessionDep = Annotated[AsyncSession, Depends(get_session)]
CurrentUser = Annotated[User, Depends(get_current_user)]
PinUser = Annotated[User, Depends(require_pin_session)]
AdminUser = Annotated[User, Depends(require_admin)]
AdminOrArbiterUser = Annotated[User, Depends(require_admin_or_arbiter)]
