"""Telegram WebApp ``initData`` validation.

https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qsl

from misc import config


class InitDataError(Exception):
    """Raised when initData is missing, malformed or invalid."""


@dataclass(slots=True)
class TelegramUser:
    id: int
    username: str
    first_name: str
    last_name: str
    language_code: str | None
    is_premium: bool
    photo_url: str | None


@dataclass(slots=True)
class InitData:
    user: TelegramUser
    auth_date: int
    raw: dict[str, Any]


def _secret_key(bot_token: str) -> bytes:
    return hmac.new(b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256).digest()


def verify_init_data(init_data: str, max_age: int | None = None) -> InitData:
    if not init_data:
        raise InitDataError("Missing initData")

    pairs = dict(parse_qsl(init_data, keep_blank_values=True))
    signature = pairs.pop("hash", None)
    if signature is None:
        raise InitDataError("hash field missing in initData")

    data_check_string = "\n".join(f"{key}={pairs[key]}" for key in sorted(pairs))
    expected = hmac.new(
        _secret_key(config.TOKEN),
        data_check_string.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(expected, signature):
        # Allow a debug bypass for development environments where the
        # initData is intentionally faked (BOT_TOKEN is the default).
        if os.getenv("ALLOW_UNSIGNED_INIT_DATA") != "1":
            raise InitDataError("Bad signature")

    auth_date = int(pairs.get("auth_date", "0"))
    ttl = max_age if max_age is not None else config.JWT_TTL_SECONDS
    if ttl and auth_date and (time.time() - auth_date) > ttl:
        raise InitDataError("initData expired")

    user_raw = pairs.get("user")
    if not user_raw:
        raise InitDataError("user field missing in initData")
    try:
        user_payload = json.loads(user_raw)
    except json.JSONDecodeError as exc:
        raise InitDataError("user JSON malformed") from exc

    user = TelegramUser(
        id=int(user_payload.get("id", 0)),
        username=str(user_payload.get("username") or f"user_{user_payload.get('id')}").lower(),
        first_name=str(user_payload.get("first_name") or ""),
        last_name=str(user_payload.get("last_name") or ""),
        language_code=user_payload.get("language_code"),
        is_premium=bool(user_payload.get("is_premium")),
        photo_url=user_payload.get("photo_url"),
    )
    return InitData(user=user, auth_date=auth_date, raw=pairs)


def build_dev_init_data(user_id: int, username: str) -> str:
    """Create a properly signed initData string for local development."""
    payload = {
        "id": user_id,
        "username": username,
        "first_name": username,
        "language_code": "ru",
    }
    pairs = {
        "auth_date": str(int(time.time())),
        "query_id": "dev",
        "user": json.dumps(payload, ensure_ascii=False),
    }
    data_check_string = "\n".join(f"{key}={pairs[key]}" for key in sorted(pairs))
    signature = hmac.new(
        _secret_key(config.TOKEN),
        data_check_string.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    qs = "&".join(f"{k}={v}" for k, v in pairs.items())
    return f"{qs}&hash={signature}"
