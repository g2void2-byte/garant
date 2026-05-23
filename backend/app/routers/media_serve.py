"""Auth-gated serve route for signed deal-media URLs (Audit v3 L-14).

The public ``/media`` ``StaticFiles`` mount in :mod:`backend.app.main`
serves every uploaded file unconditionally, which is fine for avatars
and service-card images (already exposed on user profiles) but
inappropriate for deal-chat attachments — those carry user-supplied
screenshots inside a private 1:1 chat.

Pre-fix the URLs lived on the same public mount and any leak (referrer
header, forwarded link, browser history) gave indefinite read access.
This module adds a sibling route at ``/media/deal/{filename:path}``
that:

1. Verifies the ``?exp=&sig=`` query pair via
   :func:`backend.app.media_signing.verify_media_signature`.  Bad /
   expired / missing signatures return ``403`` (so a stale link in a
   user's clipboard reads the same as a tampered one).
2. Resolves ``filename`` against
   ``settings.media_root / "deal"`` with
   :py:meth:`pathlib.Path.is_relative_to` so a ``..`` payload in the
   URL cannot escape the bucket.

The route is registered as a regular FastAPI ``APIRouter`` so it sits
in :data:`backend.app.routers.all_routers` and is included *before*
the ``StaticFiles`` mount in :func:`backend.app.main`; Starlette
routes are matched in insertion order, so the explicit signed-URL
handler wins over the catch-all static mount for the
``/media/deal/...`` prefix.

The handler is intentionally synchronous (``FileResponse`` does the
streaming via ``anyio.open_file``); no DB lookup happens on the hot
path — verification is pure HMAC + ``Path.resolve`` so a flood of
expired-URL hits never reaches the database.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

from ..config import settings
from ..media_signing import verify_media_signature

router = APIRouter(tags=["media"])


def _media_root() -> Path:
    return Path(settings.media_root).expanduser().resolve()


# ``settings.media_base_url`` defaults to ``/media`` but is overridable
# (some deploys mount the bucket at a different prefix); read it once
# at import time so the route path matches whatever the rest of the
# app emits as ``Media.url``.
_DEAL_SERVE_PATH = f"{settings.media_base_url.rstrip('/')}/deal/{{filename:path}}"


@router.get(_DEAL_SERVE_PATH)
async def serve_deal_media(
    filename: str,
    exp: Annotated[str | None, Query()] = None,
    sig: Annotated[str | None, Query()] = None,
) -> FileResponse:
    """Serve a signed deal-attachment file.

    The caller is the browser pulling ``MediaOut.url`` directly via
    ``<img src>`` / ``<a href>`` — there is no ``Authorization``
    header on the wire, so authentication is delegated to the HMAC
    signature embedded in the URL.  The URL is minted at
    serialisation time by ``_signed_media_url`` (see
    :mod:`backend.app.routers.media` and
    :mod:`backend.app.routers.deal_messages`); only callers that
    already passed the initData + chat-participant check can obtain a
    fresh signature.
    """
    # ``filename`` is what the SPA places after ``/media/deal/`` —
    # FastAPI's ``{filename:path}`` converter passes it through with
    # the slashes preserved, which we explicitly want to reject (no
    # nested subdirectories under ``deal/``). The same check also
    # blocks the ``..`` traversal payloads that the resolve-relative
    # check below would otherwise have to catch.
    if not filename or "\x00" in filename or "/" in filename or "\\" in filename:
        raise HTTPException(404, "Файл не найден")
    canonical = f"{settings.media_base_url.rstrip('/')}/deal/{filename}"
    if not verify_media_signature(canonical, exp=exp, sig=sig):
        # 403 (not 401) — the request *was* authenticated by the
        # signature, just with credentials that don't pass. 401 would
        # ask the client to re-auth via ``Authorization``, which is
        # not how this route works.
        raise HTTPException(403, "Ссылка истекла или подписана некорректно")
    root = _media_root() / "deal"
    candidate = (root / filename).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError:
        # Path-traversal payload (``../`` etc.) — the signature
        # check above already gates access, but this is a
        # defence-in-depth so a misconfigured signing secret can't
        # be combined with a traversal payload to leak files
        # outside the bucket.
        raise HTTPException(404, "Файл не найден") from None
    if not candidate.is_file():
        raise HTTPException(404, "Файл не найден")
    # ``FileResponse`` sets ``Content-Type`` from the extension; the
    # upload pipeline already locks the on-disk extension to the
    # validated content-type (see ``media._safe_extension``), so we
    # don't need to look up ``Media.content_type`` here.
    return FileResponse(candidate)
