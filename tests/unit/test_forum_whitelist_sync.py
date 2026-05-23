"""Audit (continuation) M-1 — keep the backend + frontend forum
whitelist in lockstep.

Pre-fix the backend ``ForumOut._name_ok`` validator only enforced
non-empty / length caps, and the list of approved forum names lived
only in ``frontend/src/pages/profile/AddForumPage.tsx`` as
``FORUM_OPTIONS``. The validator now rejects names outside
``schemas.FORUM_WHITELIST`` — but as long as the two constants are
maintained by hand on opposite sides of the wire there is exactly
one regression test worth writing: "if they drift, fail loudly".

The architectural fix is a ``GET /api/forums`` endpoint that both
sides consume; once that lands this test (and ``FORUM_OPTIONS``)
should be deleted. Until then, this test is the only mechanism that
detects an out-of-band edit of either side.
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
    """Pluck ``FORUM_OPTIONS`` from ``AddForumPage.tsx``.

    The source uses the shape::

        const FORUM_OPTIONS = [
          "Darkmoney",
          "Probiv",
          ...
        ];

    We extract the string literals from inside the brackets with a
    tolerant regex that survives trailing commas, comments, or
    additional fields landing in the array later. The test asserts
    against a *set* equality, so the order doesn't matter.
    """
    text = _FRONTEND_FILE.read_text(encoding="utf-8")
    match = re.search(r"FORUM_OPTIONS\s*=\s*\[(.*?)\]", text, re.DOTALL)
    assert match, (
        "Failed to locate FORUM_OPTIONS in AddForumPage.tsx. "
        "If the source moved, update this test to follow."
    )
    # Strip line comments (//...) before plucking string literals so a
    # commented-out option doesn't accidentally show up in the set.
    body = re.sub(r"//[^\n]*", "", match.group(1))
    return set(re.findall(r'"([^"]+)"', body))


def test_forum_whitelist_matches_frontend_options() -> None:
    """Backend ``FORUM_WHITELIST`` and frontend ``FORUM_OPTIONS`` must match.

    A drift in either direction is a real bug:

    * Backend adds a name the frontend doesn't render → that forum
      is unreachable via the dropdown (only via direct API hits).
    * Frontend adds a name the backend rejects → user picks it
      from the dropdown, submits the form, hits a confusing 422
      with no actionable error message.

    Failure mode for this test: edit ``schemas.FORUM_WHITELIST`` and
    ``frontend/src/pages/profile/AddForumPage.tsx`` together in the
    same PR so both sides stay synchronised.
    """
    frontend_options = _parse_frontend_options()
    backend_options = set(FORUM_WHITELIST)
    missing_in_backend = frontend_options - backend_options
    missing_in_frontend = backend_options - frontend_options
    assert not missing_in_backend, (
        "Frontend FORUM_OPTIONS has names the backend does NOT accept; "
        "add them to backend/app/schemas.FORUM_WHITELIST: "
        f"{sorted(missing_in_backend)}"
    )
    assert not missing_in_frontend, (
        "Backend FORUM_WHITELIST has names the frontend does NOT render; "
        "add them to frontend/src/pages/profile/AddForumPage.tsx "
        f"FORUM_OPTIONS: {sorted(missing_in_frontend)}"
    )
