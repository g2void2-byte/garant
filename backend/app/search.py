"""Helpers for full-text search (P3.4).

We convert user-typed queries into Postgres ``to_tsquery`` expressions so
the catalog and user-search endpoints can leverage the GIN-indexed
``search_vector`` columns introduced in revision ``b8adfad43818``.

Behaviour:

* Each whitespace-separated token is sanitised (only word chars + Cyrillic
  remain), then suffixed with ``:*`` for prefix matching — this preserves
  the substring-feel of the previous ILIKE-based search.
* Multiple tokens are combined with ``&`` (boolean AND).
* If sanitisation removes every token (e.g. the input was only punctuation),
  the helper returns ``None`` so callers can skip the filter entirely.
"""

from __future__ import annotations

import re

# Word chars (\w) include digits + underscore + most unicode word chars
# already, but we add an explicit Cyrillic range for clarity in PG terms.
_TOKEN_RE = re.compile(r"[^\w\u0400-\u04FF]+", re.UNICODE)


def build_prefix_tsquery(query: str) -> str | None:
    """Turn ``"foo bar"`` into ``"foo:* & bar:*"`` for ``to_tsquery``.

    Returns ``None`` for empty / non-word input.
    """
    if not query:
        return None
    tokens: list[str] = []
    for raw in query.split():
        cleaned = _TOKEN_RE.sub("", raw)
        if cleaned:
            tokens.append(f"{cleaned}:*")
    if not tokens:
        return None
    return " & ".join(tokens)
