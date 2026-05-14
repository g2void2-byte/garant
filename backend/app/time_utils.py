"""Tiny time helpers shared across the backend.

Replaces the deprecated ``datetime.utcnow()`` calls scattered across
``backend/app``. ``datetime.utcnow()`` was deprecated in Python 3.12 in
favour of ``datetime.now(timezone.utc)``, but the latter returns a
*tz-aware* value, while the rest of the codebase (DB columns,
in-memory comparisons) is uniformly naive-UTC.

``utcnow`` therefore returns the same naive UTC ``datetime`` the old
call did — just routed through the non-deprecated API. This keeps the
migration mechanical and zero-risk: callers that compare against, or
persist into, ``DateTime`` columns continue to see a naive value.
"""

from __future__ import annotations

from datetime import datetime, timezone


def utcnow() -> datetime:
    """Return the current UTC time as a *naive* ``datetime``.

    Equivalent to the now-deprecated ``datetime.utcnow()`` but uses the
    supported ``datetime.now(timezone.utc)`` API under the hood.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)
