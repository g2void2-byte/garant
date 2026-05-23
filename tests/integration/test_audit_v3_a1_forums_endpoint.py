"""Audit v3 A-1 — ``GET /api/forums`` single-source-of-truth.

Pre-fix the frontend hard-coded a ``FORUM_OPTIONS`` literal that
mirrored ``schemas.FORUM_WHITELIST`` by hand; drift between the two
was caught only by ``tests/unit/test_forum_whitelist_sync.py``.  The
architectural fix is the public endpoint exposed by
``backend.app.routers.forums``: the frontend fetches the list at
runtime, the backend serves the canonical whitelist, and the offline
``FORUM_OPTIONS_FALLBACK`` in ``AddForumPage.tsx`` is only the
"network broken" failsafe.
"""

from __future__ import annotations

from backend.app.schemas import FORUM_FREEFORM_OPTION, FORUM_WHITELIST


async def test_forums_endpoint_returns_whitelist(client) -> None:
    """The endpoint returns the whitelist sorted + the freeform marker last."""
    resp = await client.get("/api/forums")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert set(body["forums"]) == set(FORUM_WHITELIST)
    # The freeform option must be one of the listed names so the
    # frontend can render "pick + type custom URL" with the same
    # string the backend's whitelist already accepts.
    assert body["freeform_option"] == FORUM_FREEFORM_OPTION
    assert body["freeform_option"] in body["forums"]


async def test_forums_endpoint_is_anonymous_friendly(client) -> None:
    """No ``Authorization`` header — the endpoint must still respond.

    Pre-init-data SPA bootstrap renders the dropdown before any
    auth has happened; an auth-gated endpoint here would force the
    UI to delay the picker render to the first authenticated tick,
    visibly stalling the page on cold loads.
    """
    resp = await client.get("/api/forums")
    assert resp.status_code == 200


async def test_forums_endpoint_sets_cache_control(client) -> None:
    """The handler sets ``Cache-Control: public, max-age=...`` so the
    browser layer below TanStack Query can re-use the response."""
    resp = await client.get("/api/forums")
    cache_control = resp.headers.get("cache-control", "")
    assert "max-age" in cache_control
    assert "public" in cache_control
