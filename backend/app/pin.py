"""PIN-code authentication helpers.

* Hashing — bcrypt.
* Session — short-lived JWT bound to user_id + issued_at.
* Lockout — N failed attempts → cool-down period.
* Reset — 6-digit code delivered to the user via the Telegram bot.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from .config import pin_secret, settings

PIN_RE = re.compile(r"^\d{4}$")
RESET_CODE_LEN = 6
JWT_ALGORITHM = "HS256"
JWT_ISSUER = "garant-pin"


def is_pin_format_valid(pin: str) -> bool:
    return bool(PIN_RE.fullmatch(pin or ""))


def hash_pin(pin: str) -> str:
    return bcrypt.hashpw(pin.encode("utf-8"), bcrypt.gensalt(rounds=10)).decode("utf-8")


def verify_pin(pin: str, pin_hash: str) -> bool:
    if not pin_hash:
        return False
    try:
        return bcrypt.checkpw(pin.encode("utf-8"), pin_hash.encode("utf-8"))
    except ValueError:
        return False


def generate_reset_code() -> str:
    return "".join(secrets.choice("0123456789") for _ in range(RESET_CODE_LEN))


def hash_reset_code(code: str) -> str:
    """Plain SHA-256 — reset codes are short-lived (10 minutes) and single-use."""
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def verify_reset_code(code: str, code_hash: str) -> bool:
    if not code_hash:
        return False
    return hmac.compare_digest(hash_reset_code(code), code_hash)


def issue_session_token(user_id: int, epoch: int = 0) -> tuple[str, datetime]:
    """Issue a PIN session JWT bound to ``(user_id, epoch)``.

    The ``epoch`` claim mirrors ``users.pin_session_epoch`` at issue
    time. An admin can bump that column via ``invalidate-sessions`` and
    every previously-issued token will fail the equality check in
    :func:`decode_session_token` / ``require_pin_session`` instantly,
    without waiting for the JWT ``exp`` to expire.
    """
    now = datetime.now(timezone.utc)
    expires = now + timedelta(seconds=settings.pin_session_ttl_seconds)
    payload = {
        "sub": str(user_id),
        "iss": JWT_ISSUER,
        "iat": int(now.timestamp()),
        "exp": int(expires.timestamp()),
        "jti": secrets.token_hex(8),
        "epoch": int(epoch),
    }
    token = jwt.encode(payload, pin_secret(), algorithm=JWT_ALGORITHM)
    return token, expires


def decode_session_token(token: str) -> tuple[int, int] | None:
    """Return ``(user_id, epoch)`` for a valid token, or ``None``.

    The caller compares ``epoch`` against the user's current
    ``pin_session_epoch`` to enforce admin-initiated invalidation.
    Tokens minted before the epoch claim was introduced default to
    ``epoch=0`` (matching the column's server default), so they keep
    working until natural TTL expiry on existing deployments.
    """
    try:
        payload = jwt.decode(
            token,
            pin_secret(),
            algorithms=[JWT_ALGORITHM],
            issuer=JWT_ISSUER,
        )
    except jwt.PyJWTError:
        return None
    sub = payload.get("sub")
    if not sub:
        return None
    try:
        user_id = int(sub)
    except (TypeError, ValueError):
        return None
    raw_epoch = payload.get("epoch", 0)
    try:
        epoch = int(raw_epoch)
    except (TypeError, ValueError):
        return None
    return user_id, epoch
