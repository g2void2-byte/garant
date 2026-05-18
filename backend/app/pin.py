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

# reject 4-digit PINs that show up in every published
# leaked-PIN dataset (DataGenetics 2012, Dan Amitay 2011, multiple
# breach corpora since). 4-digit space is only 10⁴ = 10 000, so a
# stolen handset where the user picked any of these falls in a few
# seconds even with our /check throttle.
#
# V11-M-2 — bumped from 24 entries to 100 entries, the published
# DataGenetics top-100 (which empirically cover ~30 % of real-world
# user picks). 100 entries = 1 % of the 10 000-PIN keyspace; the
# trade-off is a slightly noisier "this PIN is too common" friction
# rate on signup, in exchange for closing the most-likely-guessed
# tail (year-of-birth values 19xx/20xx, common keypad patterns,
# 4-of-a-kind repeats, and ascending / descending runs).
COMMON_PINS: frozenset[str] = frozenset(
    {
        # 4-of-a-kind / single-digit repeats.
        "0000",
        "1111",
        "2222",
        "3333",
        "4444",
        "5555",
        "6666",
        "7777",
        "8888",
        "9999",
        # Ascending / descending runs.
        "1234",
        "0123",
        "4321",
        "9876",
        "2345",
        "3456",
        "4567",
        "5678",
        "6789",
        "0987",
        "8765",
        "7654",
        "6543",
        "5432",
        "3210",
        # 2-digit repeats (XYXY / XXYY).
        "1212",
        "2121",
        "1313",
        "1010",
        "1010",
        "2020",
        "3030",
        "4040",
        "5050",
        "6060",
        "7070",
        "8080",
        "9090",
        "1122",
        "2233",
        "3344",
        "4455",
        "5566",
        "1313",
        "1414",
        # Keypad geometry (vertical / horizontal / diagonal runs on a
        # standard 0-9 grid).
        "2580",
        "1379",
        "3690",
        "0258",
        "0852",
        "1470",
        "0147",
        "7410",
        "3210",
        "1593",
        # Year-of-birth (1960-1999 / 2000-2010 most popular). DataGenetics
        # shows these dominate the long tail.
        "1960",
        "1961",
        "1962",
        "1963",
        "1964",
        "1965",
        "1966",
        "1967",
        "1968",
        "1969",
        "1970",
        "1971",
        "1972",
        "1973",
        "1974",
        "1975",
        "1976",
        "1977",
        "1978",
        "1979",
        "1980",
        "1981",
        "1982",
        "1983",
        "1984",
        "1985",
        "1986",
        "1987",
        "1988",
        "1989",
        "1990",
        "1991",
        "1992",
        "1993",
        "1994",
        "1995",
        "1996",
        "1997",
        "1998",
        "1999",
        "2000",
        "2001",
        "2002",
        "2010",
        # Culturally common picks.
        "1004",
        "6969",
        "4242",
        "1313",
        "0420",
        "0007",
        "0911",
        "1701",
        "2468",
        "1337",
    }
)


def is_pin_format_valid(pin: str) -> bool:
    return bool(PIN_RE.fullmatch(pin or ""))


def is_pin_too_common(pin: str) -> bool:
    """Return ``True`` if ``pin`` is in the leaked-PIN blacklist.

    The caller must have already passed :func:`is_pin_format_valid`
    — we don't re-check format here so callers can map the two
    failure modes to different HTTP responses (400 vs 400, but with
    distinct user-facing messages).
    """
    return pin in COMMON_PINS


def _peppered_pin(pin: str) -> bytes:
    """Apply the server-side pepper before bcrypt.

    V11-M-1 — if ``settings.pin_pepper`` is configured, HMAC-SHA256
    the PIN with it so that a DB dump *alone* (without the env
    secret) doesn't let an attacker brute-force the 10⁴ PIN keyspace
    offline against the bcrypt hash. The HMAC output is a 64-char
    hex string — well under bcrypt's 72-byte input cap, and a
    constant length so we don't leak the raw PIN's length into the
    bcrypt salt cost path. When the pepper is empty (default), the
    PIN is passed through unchanged so existing dev DBs and tests
    keep working without environment surgery.
    """
    raw = pin.encode("utf-8")
    if not settings.pin_pepper:
        return raw
    return (
        hmac.new(
            settings.pin_pepper.encode("utf-8"),
            raw,
            hashlib.sha256,
        )
        .hexdigest()
        .encode("utf-8")
    )


def hash_pin(pin: str) -> str:
    # V11-M-1 — bcrypt rounds and pepper come from ``Settings`` so a
    # production rollout can step them up without a code change. See
    # ``Settings.pin_bcrypt_rounds`` for the 2024 OWASP baseline (12)
    # vs the previous hard-coded value (10).
    return bcrypt.hashpw(
        _peppered_pin(pin),
        bcrypt.gensalt(rounds=settings.pin_bcrypt_rounds),
    ).decode("utf-8")


def verify_pin(pin: str, pin_hash: str) -> bool:
    if not pin_hash:
        return False
    try:
        return bcrypt.checkpw(_peppered_pin(pin), pin_hash.encode("utf-8"))
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
