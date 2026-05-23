"""HMAC-signed media URLs (Audit v3 L-14).

Deal-chat attachments are stored under ``settings.media_root`` and the
on-disk path is mirrored 1:1 into ``Media.url`` (e.g.
``/media/deal/<owner-id>-<ts>-<rand>.png``).  Pre-fix the static-file
mount served those files to anyone who happened to know the URL —
random filenames made enumeration infeasible, but an attacker who got
a single URL (referrer leak, shoulder-surf, forwarded screenshot link)
could fetch the attachment forever.

The signing scheme used here is intentionally minimal: an HMAC-SHA256
over ``"<canonical-path>|<exp>"`` and the unix-timestamp expiry are
appended as ``?exp=&sig=`` query parameters.  Verification re-derives
the HMAC and ``hmac.compare_digest``-checks it against the supplied
value, and refuses anything past ``exp``.

The signing secret falls back to :func:`backend.app.config.pin_secret`
when ``settings.media_url_signing_secret`` is empty so dev/test setups
work out of the box; production deploys should set it explicitly so
rotating the PIN secret does not invalidate every outstanding deal
attachment link.

Public buckets (``avatar``, ``banner``, ``service``) keep the unsigned
``StaticFiles`` mount — they're already exposed on profile and service
cards.  Only the kinds listed in ``settings.media_signed_kinds`` go
through the signing layer.
"""

from __future__ import annotations

import hashlib
import hmac
import time
from typing import Final
from urllib.parse import quote

from .config import pin_secret, settings


def _signing_secret() -> bytes:
    """Return the HMAC key as bytes.

    ``settings.media_url_signing_secret`` takes precedence so a deploy
    can rotate the media-URL key independently of the PIN-session JWT.
    The fall-back to :func:`pin_secret` keeps test / dev setups working
    without extra wiring (they already have a deterministic PIN
    secret derived from ``BOT_TOKEN``).
    """
    explicit = settings.media_url_signing_secret
    if explicit:
        return explicit.encode("utf-8")
    return pin_secret().encode("utf-8")


def _signed_kinds() -> set[str]:
    return {k.strip() for k in settings.media_signed_kinds.split(",") if k.strip()}


def _sign(path: str, exp: int) -> str:
    """HMAC-SHA256 over ``<path>|<exp>`` returned as lowercase hex."""
    msg = f"{path}|{exp}".encode()
    return hmac.new(_signing_secret(), msg, hashlib.sha256).hexdigest()


# ``_QUERY_SAFE`` mirrors the RFC-3986 ``unreserved`` set so the signed
# URL stays a valid relative path when the caller hands it back to the
# browser via ``MediaOut.url``.  In particular we do *not* encode ``/``
# because the canonical path includes the ``/media/<kind>/<file>``
# prefix that has to land verbatim on the wire.
_QUERY_SAFE: Final[str] = "/-_."


def sign_media_path(path: str, *, ttl: int | None = None) -> str:
    """Append ``?exp=&sig=`` to a canonical media path.

    ``path`` is what is stored on ``Media.url`` — for deal media this
    looks like ``/media/deal/<file>``.  The returned string is safe to
    use directly as an ``<img src>`` / ``<a href>`` because the query
    component only contains ASCII digits and lowercase hex.
    """
    if ttl is None:
        ttl = settings.media_signed_url_ttl_seconds
    exp = int(time.time()) + max(1, int(ttl))
    sig = _sign(path, exp)
    return f"{quote(path, safe=_QUERY_SAFE)}?exp={exp}&sig={sig}"


def signed_media_url(*, url: str, kind: str, ttl: int | None = None) -> str:
    """Return the signed URL for a ``Media`` row.

    Buckets outside ``settings.media_signed_kinds`` (``avatar``,
    ``banner``, ``service`` by default) return ``url`` unchanged so the
    public ``StaticFiles`` mount continues to serve them.
    """
    if kind not in _signed_kinds():
        return url
    return sign_media_path(url, ttl=ttl)


def verify_media_signature(path: str, *, exp: str | None, sig: str | None) -> bool:
    """Validate the ``?exp=&sig=`` pair the serve route saw.

    Returns ``False`` on any of: missing parameters, non-integer
    ``exp``, expired ``exp``, or HMAC mismatch.  The comparison uses
    ``hmac.compare_digest`` so a timing-side-channel does not leak the
    expected signature byte-by-byte.
    """
    if not exp or not sig:
        return False
    try:
        exp_ts = int(exp)
    except ValueError:
        return False
    if exp_ts < int(time.time()):
        return False
    expected = _sign(path, exp_ts)
    return hmac.compare_digest(expected, sig)
