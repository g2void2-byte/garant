"""Public list of approved forum names (Audit v3 A-1).

Pre-fix the dropdown in ``AddForumPage.tsx`` carried its own
``FORUM_OPTIONS`` literal that mirrored
:data:`backend.app.schemas.FORUM_WHITELIST` by hand.  Drift between
the two was caught only by ``tests/test_forum_whitelist_sync.py``
(see ``test_forum_whitelist_sync.py``).  The architectural fix is to
expose the backend list via ``GET /api/forums`` and have the frontend
fetch it instead of duplicating the constant.

The endpoint is intentionally anonymous-friendly (no ``CurrentUser``)
so the SPA can render the dropdown options even before initData has
been verified, and to keep the response cacheable.  The whitelist is
small (≤32 names) and changes only on a backend deploy; we return
``Cache-Control: max-age=300`` so the SPA can re-use the response
across page navigations within the same session.
"""

from __future__ import annotations

from fastapi import APIRouter, Response

from ..schemas import FORUM_FREEFORM_OPTION, FORUM_WHITELIST, ForumListOut

router = APIRouter(prefix="/api", tags=["forums"])


@router.get("/forums", response_model=ForumListOut)
async def list_forums(response: Response) -> ForumListOut:
    """Approved forum names + the free-form ``"Другое"`` option.

    Order is lexicographic over the backend whitelist with the
    ``Другое`` catch-all appended last (mirrors the historical
    frontend ordering so the migration is visually a no-op).
    """
    response.headers["Cache-Control"] = "public, max-age=300"
    names = sorted(FORUM_WHITELIST) + [FORUM_FREEFORM_OPTION]
    return ForumListOut(forums=names, freeform_option=FORUM_FREEFORM_OPTION)
