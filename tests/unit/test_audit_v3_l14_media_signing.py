"""Audit v3 L-14 — HMAC-signed deal-media URLs.

Pre-fix deal-chat attachments were served from the public
``/media`` ``StaticFiles`` mount, so any leak (referrer header,
forwarded screenshot link) gave indefinite read access.  This PR
introduces :mod:`backend.app.media_signing` which appends
``?exp=&sig=`` to URLs returned for kinds listed in
``settings.media_signed_kinds`` (``deal`` by default) and a sibling
serve route that verifies the pair before streaming the file.

The signature scheme is intentionally minimal (HMAC-SHA256 over
``"<canonical-path>|<exp>"``), so these unit tests pin the
round-trip + the three rejection paths that protect the bucket:
expired ``exp``, tampered ``sig``, and tampered ``path``.
"""

from __future__ import annotations

import time

import pytest

from backend.app.media_signing import (
    sign_media_path,
    signed_media_url,
    verify_media_signature,
)


def _split_signed(url: str) -> tuple[str, str, str]:
    """Split a signed ``/media/deal/<file>?exp=...&sig=...`` URL."""
    path, _, query = url.partition("?")
    parts = dict(item.split("=", 1) for item in query.split("&"))
    return path, parts["exp"], parts["sig"]


def test_sign_media_path_round_trips() -> None:
    """A freshly-signed path verifies back via ``verify_media_signature``."""
    signed = sign_media_path("/media/deal/abc.png", ttl=60)
    path, exp, sig = _split_signed(signed)
    assert path == "/media/deal/abc.png"
    assert verify_media_signature(path, exp=exp, sig=sig) is True


def test_signed_media_url_signs_deal_kind() -> None:
    """``signed_media_url`` decorates deal URLs with ``?exp=&sig=``."""
    url = signed_media_url(url="/media/deal/x.png", kind="deal", ttl=60)
    assert url.startswith("/media/deal/x.png?exp=")
    assert "&sig=" in url


def test_signed_media_url_leaves_public_kinds_unchanged() -> None:
    """Avatar / banner / service buckets keep the unsigned URL."""
    for kind in ("avatar", "banner", "service"):
        url = signed_media_url(url=f"/media/{kind}/x.png", kind=kind, ttl=60)
        assert url == f"/media/{kind}/x.png"


def test_verify_rejects_expired_signature() -> None:
    """An ``exp`` in the past fails verification even with a valid signature."""
    signed = sign_media_path("/media/deal/abc.png", ttl=1)
    path, _, sig = _split_signed(signed)
    # Hand-roll an expired ``exp`` and re-sign so the ``sig`` matches
    # — this is the strongest test: a leaked, perfectly-signed URL
    # whose only flaw is the time stamp must still be rejected.
    from backend.app.media_signing import _sign

    past = int(time.time()) - 1
    sig = _sign(path, past)
    assert verify_media_signature(path, exp=str(past), sig=sig) is False


def test_verify_rejects_tampered_signature() -> None:
    signed = sign_media_path("/media/deal/abc.png", ttl=60)
    path, exp, _sig = _split_signed(signed)
    assert verify_media_signature(path, exp=exp, sig="deadbeef") is False


def test_verify_rejects_tampered_path() -> None:
    """A signature minted for path A must not verify against path B."""
    signed = sign_media_path("/media/deal/abc.png", ttl=60)
    _, exp, sig = _split_signed(signed)
    assert verify_media_signature("/media/deal/other.png", exp=exp, sig=sig) is False


@pytest.mark.parametrize(
    "exp,sig",
    [(None, "abc"), ("123", None), ("", ""), (None, None), ("notanint", "abc")],
)
def test_verify_rejects_missing_or_malformed_query(exp, sig) -> None:
    assert verify_media_signature("/media/deal/abc.png", exp=exp, sig=sig) is False
