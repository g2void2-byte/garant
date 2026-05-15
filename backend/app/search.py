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

Why not ``websearch_to_tsquery``? It would let Postgres parse the query
directly, but it drops the prefix-match (``:*``) behaviour the TMA UX
relies on. Instead we strip every tsquery meta-character at the regex
layer (``_TOKEN_RE`` rejects everything outside ``\\w`` + Cyrillic) and
``_assert_safe`` asserts the invariant before the string ever hits
``to_tsquery``.
"""

from __future__ import annotations

import re

# Word chars (\w) include digits + underscore + most unicode word chars
# already, but we add an explicit Cyrillic range for clarity in PG terms.
_TOKEN_RE = re.compile(r"[^\w\u0400-\u04FF]+", re.UNICODE)

# Meta-characters that ``to_tsquery`` would interpret as operators or
# weights. ``_TOKEN_RE`` already strips them — this set is an explicit
# tripwire so a future regex change can't silently re-introduce one.
_TSQUERY_META = frozenset("!|&():*<>'\"\\")


def _assert_safe(token: str) -> None:
    bad = _TSQUERY_META.intersection(token)
    if bad:
        # The regex should have stripped these; if it didn't we'd rather
        # crash loudly than splice operator-meaningful chars into the
        # tsquery expression.
        raise AssertionError(f"tsquery token contains meta chars: {sorted(bad)!r}")


def build_prefix_tsquery(query: str) -> str | None:
    """Turn ``"foo bar"`` into ``"foo:* & bar:*"`` for ``to_tsquery``.

    Returns ``None`` for empty / non-word input. Tokens are sanitised so
    user-supplied tsquery operators (``!|&():*<>``) cannot reach
    Postgres — see :data:`_TOKEN_RE` and :func:`_assert_safe`.

    V5-D-8 (M) — caps tsquery complexity to the first 10 tokens. A
    paste-heavy or pathological input (e.g. a one-line wall of 5 000
    words) would otherwise produce a 5 000-clause ``& foo:* & bar:* …``
    expression that explodes the GIN-index scan cost for no useful
    extra precision. Ten prefix-tokens is more than enough to narrow
    any catalog / user search; the rest of the query is discarded.
    """
    if not query:
        return None
    tokens: list[str] = []
    for raw in query.split():
        cleaned = _TOKEN_RE.sub("", raw)
        if cleaned:
            _assert_safe(cleaned)
            tokens.append(f"{cleaned}:*")
    if not tokens:
        return None
    return " & ".join(tokens[:10])
