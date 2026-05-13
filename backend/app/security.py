from __future__ import annotations

import hashlib
import hmac
import json
import time
from urllib.parse import parse_qs, urlencode

from .config import settings


class InitDataError(Exception):
    pass


def verify_init_data(init_data: str) -> dict:
    """Validate Telegram WebApp init data and return the parsed user dict."""
    if settings.allow_unsigned_init_data:
        return _parse_unsigned(init_data)

    if not settings.bot_token:
        raise InitDataError("BOT_TOKEN is not configured")

    parsed = parse_qs(init_data, keep_blank_values=True)

    received_hash = parsed.pop("hash", [None])[0]
    if not received_hash:
        raise InitDataError("hash is missing from init data")

    items = sorted((k, v[0]) for k, v in parsed.items())
    data_check_string = "\n".join(f"{k}={v}" for k, v in items)

    secret_key = hmac.new(b"WebAppData", settings.bot_token.encode(), hashlib.sha256).digest()
    computed = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()

    if not hmac.compare_digest(computed, received_hash):
        raise InitDataError("init data signature mismatch")

    auth_date_str = parsed.get("auth_date", [None])[0]
    if auth_date_str:
        auth_date = int(auth_date_str)
        if time.time() - auth_date > 86400:
            raise InitDataError("init data expired")

    user_json = parsed.get("user", [None])[0]
    if not user_json:
        raise InitDataError("user field missing from init data")

    return json.loads(user_json)


def _parse_unsigned(init_data: str) -> dict:
    """Accept unsigned init data for local dev."""
    try:
        parsed = parse_qs(init_data, keep_blank_values=True)
        user_json = parsed.get("user", [None])[0]
        if user_json:
            return json.loads(user_json)
    except Exception:
        pass
    try:
        return json.loads(init_data)
    except Exception:
        raise InitDataError("Cannot parse unsigned init data")


def build_dev_init_data(user_id: int, username: str = "dev_user") -> str:
    """Build fake init data for local development testing."""
    user = json.dumps(
        {"id": user_id, "first_name": username, "username": username},
        separators=(",", ":"),
    )
    params = {
        "user": user,
        "auth_date": str(int(time.time())),
        "hash": "dev",
    }
    return urlencode(params)
