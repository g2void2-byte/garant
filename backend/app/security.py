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

    # ``hash`` is the only proof Telegram's WebApp made
    # this initData (HMAC-SHA256 of the sorted data-check string keyed
    # with the bot-token-derived secret). ``parse_qs(keep_blank_values=True)``
    # would yield ``[""]`` for ``...&hash=`` and ``[None]`` is the
    # default we hand it for a missing key, so ``if not received_hash``
    # covers both branches: any falsy value (``None``, ``""``) is
    # functionally indistinguishable from "unsigned" and must be
    # rejected before we run ``hmac.compare_digest`` — which would
    # otherwise compare against ``hexdigest()`` (always non-empty) and
    # never short-circuit, but that's a defence-in-depth invariant we
    # don't want to silently rely on. NEVER accept an empty hash.
    received_hash = parsed.pop("hash", [None])[0]
    if not received_hash:
        raise InitDataError("hash is missing from init data")

    items = sorted((k, v[0]) for k, v in parsed.items())
    data_check_string = "\n".join(f"{k}={v}" for k, v in items)

    secret_key = hmac.new(b"WebAppData", settings.bot_token.encode(), hashlib.sha256).digest()
    computed = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()

    if not hmac.compare_digest(computed, received_hash):
        raise InitDataError("init data signature mismatch")

    # 3.4 — ``auth_date`` MUST be present. Pre-fix the
    # ``if auth_date_str:`` branch silently skipped the age-check when
    # the field was absent, so a (current or future) client that
    # forgot to include it would produce a token we treat as
    # "timeless" — defeating the ``init_data_max_age_seconds`` cap.
    # Telegram WebApp has always sent ``auth_date``; making the
    # presence check explicit prevents the silent-bypass mode if a
    # future client / proxy strips the field.
    auth_date_str = parsed.get("auth_date", [None])[0]
    if not auth_date_str:
        raise InitDataError("auth_date is missing from init data")
    # ``int()`` on a non-numeric ``auth_date`` would raise
    # ``ValueError`` and surface as HTTP 500 to the caller. A
    # malformed ``auth_date`` is functionally the same as a forged
    # token from our point of view: we cannot decide whether it's
    # recent. Treat it as a normal auth failure so deps.py maps it
    # to 401, not 500.
    try:
        auth_date = int(auth_date_str)
    except (TypeError, ValueError):
        raise InitDataError("init data auth_date is not numeric")
    now = time.time()
    # Reject ``auth_date`` that's far in the future too. HMAC
    # makes a forgery impossible from a malicious actor, but a
    # legitimate-but-misconfigured client (clock badly skewed
    # ahead, or a Telegram-side bug stamping the wrong epoch)
    # would otherwise produce a token that's "valid forever" by
    # our own ``time.time() - auth_date`` arithmetic. 5 minutes
    # of forward drift is enough to absorb NTP wobble without
    # admitting tokens that are de-facto un-aged.
    if auth_date - now > 300:
        raise InitDataError("init data auth_date is in the future")
    if now - auth_date > settings.init_data_max_age_seconds:
        raise InitDataError("init data expired")

    user_json = parsed.get("user", [None])[0]
    if not user_json:
        raise InitDataError("user field missing from init data")

    return json.loads(user_json)


def _parse_unsigned(init_data: str) -> dict:
    """Accept unsigned init data for local dev.

    defence-in-depth check: even though
    :mod:`backend.app.main` refuses to boot when
    ``ALLOW_UNSIGNED_INIT_DATA`` is set in production/staging, the
    runtime setting could in theory be toggled inside a test fixture
    or via a misconfiguration that bypasses startup (e.g. an
    embedded ASGI runner, or a tool that imports ``app`` directly
    without running ``lifespan``). Re-check the environment here so
    a forged unsigned token can never authenticate against a
    production-like deployment, regardless of how the server
    process was launched.
    """
    if settings.environment in ("production", "staging"):
        # The startup guard should have prevented this. If we reach
        # here, treat it as a forged token.
        raise InitDataError("unsigned init data is rejected outside development")
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
    """Build fake init data for local development testing.

    V11-L-5 — refuse to run outside dev/test even if a caller imports
    the helper directly. The pair of unsigned-init-data guards in
    :func:`_parse_unsigned` and the lifespan startup already prevent
    a forged token from authenticating in production, but the helper
    itself was previously importable from anywhere — including from a
    dev script accidentally shipped into a production container. Hard
    failing at the entry point removes that whole class of foot-gun.
    """
    if settings.environment in ("production", "staging"):
        raise RuntimeError(
            "build_dev_init_data is a development-only helper; refusing "
            f"to run with ENVIRONMENT='{settings.environment}'"
        )
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
