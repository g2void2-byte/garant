"""Telegram WebApp `initData` validation + simple auth helpers."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any
from urllib.parse import parse_qsl

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .database import get_session
from .models import User


def _build_data_check_string(parsed: list[tuple[str, str]]) -> str:
    pairs = [f"{k}={v}" for k, v in parsed if k != "hash"]
    pairs.sort()
    return "\n".join(pairs)


def validate_init_data(init_data: str, *, max_age_seconds: int = 86400) -> dict[str, Any]:
    """Validate Telegram WebApp `initData` per Telegram docs.

    Returns the parsed payload (with `user` decoded as a dict).
    Raises HTTPException(401) on failure.

    In dev mode (no BOT_TOKEN configured) we still parse the data
    so the Mini App can be opened in a regular browser for testing.
    """
    if not init_data:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing Telegram initData")

    parsed = parse_qsl(init_data, keep_blank_values=True)
    data = dict(parsed)
    received_hash = data.get("hash", "")

    if settings.bot_token:
        secret = hmac.new(b"WebAppData", settings.bot_token.encode(), hashlib.sha256).digest()
        check_string = _build_data_check_string(parsed)
        calc_hash = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(calc_hash, received_hash):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid Telegram signature")

        auth_date = int(data.get("auth_date", "0") or 0)
        if auth_date and time.time() - auth_date > max_age_seconds:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "initData expired")

    user_raw = data.get("user")
    if not user_raw:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "No user in initData")

    try:
        data["user"] = json.loads(user_raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Bad user payload") from exc

    return data


async def get_or_create_user(session: AsyncSession, tg_user: dict[str, Any]) -> User:
    """Lookup a user by Telegram ID, creating it on first contact."""
    tg_id = int(tg_user["id"])
    res = await session.execute(select(User).where(User.tg_id == tg_id))
    user = res.scalar_one_or_none()
    if user is None:
        user = User(
            tg_id=tg_id,
            username=tg_user.get("username"),
            first_name=tg_user.get("first_name"),
            last_name=tg_user.get("last_name"),
            photo_url=tg_user.get("photo_url"),
            is_admin=tg_id in settings.admin_id_list,
        )
        session.add(user)
        await session.flush()
    else:
        # Refresh easily-changing fields
        user.username = tg_user.get("username") or user.username
        user.first_name = tg_user.get("first_name") or user.first_name
        user.last_name = tg_user.get("last_name") or user.last_name
        user.photo_url = tg_user.get("photo_url") or user.photo_url
        if tg_id in settings.admin_id_list and not user.is_admin:
            user.is_admin = True
    return user


async def current_user(
    init_data: str = Header(alias="X-Telegram-Init-Data", default=""),
    session: AsyncSession = Depends(get_session),
) -> User:
    """FastAPI dependency: validate initData and return the active user."""
    payload = validate_init_data(init_data)
    user = await get_or_create_user(session, payload["user"])
    if user.is_banned:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "User is banned")
    await session.commit()
    return user


async def admin_user(user: User = Depends(current_user)) -> User:
    """Restrict an endpoint to admins."""
    if not user.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admin only")
    return user
