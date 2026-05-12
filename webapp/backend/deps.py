"""FastAPI dependencies."""

from __future__ import annotations

import logging

from fastapi import Depends, Header, HTTPException, status
from fastapi.concurrency import run_in_threadpool

from utils.database.extras import WebDB
from utils.database.models import Users
from webapp.backend.security import InitData, InitDataError, verify_init_data

logger = logging.getLogger(__name__)


async def get_init_data(
    authorization: str | None = Header(default=None, alias="Authorization"),
    x_init_data: str | None = Header(default=None, alias="X-Init-Data"),
) -> InitData:
    raw: str | None = None
    if authorization:
        if authorization.lower().startswith("tma "):
            raw = authorization[4:].strip()
        elif authorization.lower().startswith("bearer "):
            raw = authorization[7:].strip()
        else:
            raw = authorization.strip()
    raw = raw or x_init_data
    if not raw:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing initData")
    try:
        return verify_init_data(raw)
    except InitDataError as exc:
        logger.warning("initData verification failed: %s", exc)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc))


def _sync_user(init_data: InitData) -> Users:
    """Ensure the bot's ``Users`` row exists for the caller."""
    tg = init_data.user
    user = Users.get_or_none(Users.user_id == tg.id)
    if user is None:
        user = Users.create(user_id=tg.id, username=tg.username)
    else:
        if tg.username and user.username != tg.username:
            user.username = tg.username
            user.save()
    return user


async def get_current_user(init_data: InitData = Depends(get_init_data)) -> Users:
    user = await run_in_threadpool(_sync_user, init_data)
    await run_in_threadpool(WebDB().touch_online, user.username)
    if user.ban:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Banned")
    return user


async def get_web_db() -> WebDB:  # pragma: no cover - trivial
    return WebDB()
