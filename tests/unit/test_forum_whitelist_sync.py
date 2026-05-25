"""Audit v3 A-1 — verify the ``AddForumPage`` offline-fallback list
stays a subset of the backend whitelist.

Pre-fix this test guarded a hand-maintained ``FORUM_OPTIONS`` literal
that mirrored :data:`backend.app.schemas.FORUM_WHITELIST`. The
architectural fix landed: ``GET /api/forums`` is now the single
source of truth, the frontend fetches it at runtime, and the
hard-coded ``FORUM_OPTIONS_FALLBACK`` in ``AddForumPage.tsx`` is
only used when the network request fails (offline cold start) so
the dropdown still renders something usable.

The fallback is intentionally allowed to be a *subset* of the
backend whitelist — dropping a name from it just hides one offline
choice without breaking the write boundary — but it must never
contain a name the backend would reject, because picking that name
would surface a confusing 422 after the user clicked Add.
"""

from __future__ import annotations

import re
from pathlib import Path

from backend.app.schemas import FORUM_WHITELIST

_FRONTEND_FILE = (
    Path(__file__).resolve().parent.parent.parent
    / "frontend"
    / "src"
    / "pages"
    / "profile"
    / "AddForumPage.tsx"
)


def _parse_frontend_options() -> set[str]:
    """Pluck ``FORUM_OPTIONS_FALLBACK`` from ``AddForumPage.tsx``.

    The source uses the shape::

        const FORUM_OPTIONS_FALLBACK = [
          "Darkmoney",
          "Probiv",
          ...
        ];

    We extract the string literals from inside the brackets with a
    tolerant regex that survives trailing commas, comments, or
    additional fields landing in the array later. The test asserts
    against a subset relationship, so the order doesn't matter.
    """
    text = _FRONTEND_FILE.read_text(encoding="utf-8")
    match = re.search(r"FORUM_OPTIONS_FALLBACK\s*=\s*\[(.*?)\]", text, re.DOTALL)
    assert match, (
        "Failed to locate FORUM_OPTIONS_FALLBACK in AddForumPage.tsx. "
        "If the source moved, update this test to follow."
    )
    # Strip line comments (//...) before plucking string literals so a
    # commented-out option doesn't accidentally show up in the set.
    body = re.sub(r"//[^\n]*", "", match.group(1))
    return set(re.findall(r'"([^"]+)"', body))


def test_forum_offline_fallback_is_subset_of_backend_whitelist() -> None:
    """The offline-fallback dropdown must not surface unknown names.

    The runtime path (``useForums`` → ``GET /api/forums``) is the
    single source of truth; the fallback only kicks in when that
    request fails. A drift where the fallback picks up a name the
    backend rejects would land the user on a confusing 422 after
    submit — keep them in sync (subset) so the offline UX still
    matches the write boundary.
    """
    fallback = _parse_frontend_options()
    backend_options = set(FORUM_WHITELIST)
    surplus = fallback - backend_options
    assert not surplus, (
        "FORUM_OPTIONS_FALLBACK in AddForumPage.tsx has names the backend "
        "does NOT accept; either add them to "
        "backend/app/schemas.FORUM_WHITELIST or remove from the fallback: "
        f"{sorted(surplus)}"
    )
