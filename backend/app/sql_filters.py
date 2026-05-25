"""Tiny SQL-level helpers shared across routers.

Kept as a separate module so individual routers don't accumulate
ad-hoc copies of the same primitives.
"""

from __future__ import annotations


def escape_like_wildcards(q: str) -> str:
    """Escape ``%`` / ``_`` / ``\\`` for ``LIKE`` / ``ILIKE`` patterns.

    User-typed search strings are interpolated into ``"%{q}%"`` patterns
    on the admin search endpoints. Without escaping, a user-supplied
    ``%`` would match every row regardless of context, ``_`` would match
    any single character, and a trailing backslash could leak the
    pattern's own escape mechanics.

    Callers must pair this with ``escape="\\\\"`` on the SQLAlchemy
    ``ilike(..., escape="\\\\")`` / ``like(..., escape="\\\\")`` call so
    Postgres interprets the escape character correctly.
    """
    # Escape the escape character first so we don't double-escape it.
    return q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
