"""M-5 — Content Security Policy regression tests.

The CSP header is the load-bearing defence-in-depth for the Telegram
Mini App: a hostile dependency that ships ``innerHTML = '<script>...'``
or ``innerHTML = '<style>...'`` is silently neutralised because the
matching directive doesn't permit either inline form. The directive
string lives in ``backend/app/main.py::_CSP_DIRECTIVES`` and is set on
every HTTP response by the ``_security_headers`` middleware.

This file is the snapshot test for that string. Any drift — a stray
``'unsafe-inline'`` slipped in by a copy-paste, a removed
``style-src-attr 'none'``, a missing ``report-uri`` — fails one of the
assertions below so the change-author is forced to make a deliberate
policy decision in review.

Why a snapshot and not "soft" tests:

* CSP is policy, not a defaulted toggle. A regression that weakens
  the policy without anyone noticing is exactly the failure mode
  M-5 documents in ``docs/csp-policy.md``.
* The snapshot is the policy contract. Adding a new directive (or
  loosening an existing one) requires updating the expected string
  here — code review has to look at the diff and approve it.
* ``test_csp_directives_include_report_uri`` in ``test_csp_report.py``
  predates this file and only covered the ``report-uri`` directive;
  we keep that test for its narrow purpose and add the full snapshot
  here so failures point at the policy change rather than at one
  specific directive.

The ``index.html`` static-analysis tests at the bottom of the file
guard the *other* side of the contract: the SPA shell must not
re-introduce inline ``<style>`` / ``<script>`` markup, otherwise the
policy would block its own page on first paint.
"""

from __future__ import annotations

import re
from pathlib import Path

from backend.app.main import _CSP_DIRECTIVES

# Repo-relative path to the SPA shell. Anchored at this file's parent
# so the test works in CI (where the repo is checked out at a stable
# path) and locally regardless of the user's working directory.
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_INDEX_HTML = _REPO_ROOT / "frontend" / "index.html"


def _parse_directives(policy: str) -> dict[str, tuple[str, ...]]:
    """Split a CSP header value into ``{name: (tokens, ...)}``.

    Whitespace-tolerant; mirrors how user agents parse the header per
    CSP3 §3.1. Empty / malformed directives are skipped so the
    assertions below don't crash on accidentally-stripped pieces of
    the string — the snapshot test catches those separately.
    """
    out: dict[str, tuple[str, ...]] = {}
    for chunk in policy.split(";"):
        parts = chunk.split()
        if not parts:
            continue
        name, *tokens = parts
        out[name] = tuple(tokens)
    return out


# ── 1. Snapshot — the directive string itself ────────────────────────────


def test_csp_directives_match_expected_snapshot() -> None:
    """The exact directive string. Drift = explicit policy review."""
    expected = (
        "default-src 'self'; "
        "script-src 'self' https://telegram.org; "
        "script-src-attr 'none'; "
        "style-src 'self'; "
        "style-src-elem 'self'; "
        "style-src-attr 'none'; "
        "img-src 'self' data: blob: https:; "
        "font-src 'self' data:; "
        "connect-src 'self'; "
        "worker-src 'self' blob:; "
        "frame-ancestors 'self' https://web.telegram.org https://*.telegram.org; "
        "base-uri 'self'; "
        "form-action 'self'; "
        "object-src 'none'; "
        "report-uri /api/csp-report"
    )
    assert _CSP_DIRECTIVES == expected


# ── 2. Negative invariants — what the policy may NEVER contain ───────────


def test_csp_has_no_unsafe_inline_anywhere() -> None:
    """No directive may permit ``'unsafe-inline'``.

    ``'unsafe-inline'`` re-opens the exact attack surface M-5 was
    written to close (inline ``<style>`` injection silently rendering,
    inline ``<script>`` running cross-origin payload). Per CSP3 it is
    illegal to mix ``'unsafe-inline'`` with a nonce/hash on the same
    directive in any browser that supports nonces — so we don't need
    to allow it conditionally; if a future change really needs it,
    the diff has to remove this test and explain why.
    """
    parsed = _parse_directives(_CSP_DIRECTIVES)
    for name, tokens in parsed.items():
        assert "'unsafe-inline'" not in tokens, (
            f"'unsafe-inline' must never appear in CSP — found in {name!r}"
        )


def test_csp_has_no_unsafe_eval_anywhere() -> None:
    """No directive may permit ``'unsafe-eval'``.

    ``'unsafe-eval'`` lets ``eval``/``new Function``/``setTimeout(str)``
    parse strings as code. We don't use ``eval`` in the bundle and
    Vite's production output doesn't need it either; allowing it
    would defeat the script-src origin allowlist on any browser.
    """
    parsed = _parse_directives(_CSP_DIRECTIVES)
    for name, tokens in parsed.items():
        assert "'unsafe-eval'" not in tokens, (
            f"'unsafe-eval' must never appear in CSP — found in {name!r}"
        )


def test_csp_has_no_wildcard_sources() -> None:
    """No directive may use a bare ``*`` source.

    Per CSP3 a bare ``*`` matches every URL except ``data:`` /
    ``blob:`` / ``filesystem:`` — equivalent to "disable this
    directive". We never want that, even on directives that ship
    intentionally permissive values like ``img-src`` (which is
    ``'self' data: blob:`` — the explicit schemes are fine).
    """
    parsed = _parse_directives(_CSP_DIRECTIVES)
    for name, tokens in parsed.items():
        assert "*" not in tokens, f"Wildcard ``*`` must not appear in CSP — found in {name!r}"


# ── 3. Positive invariants — the CSP3 split that M-5 introduces ─────────


def test_csp_style_src_layers_lock_inline_styles() -> None:
    """``style-src`` must be ``'self'``, ``-elem`` ``'self'``,
    ``-attr`` ``'none'``.

    The split is what makes M-5 enforceable:

    * ``style-src-elem 'self'`` — only same-origin ``<style>`` and
      ``<link rel="stylesheet">``. A 3rd-party dep that injects an
      inline ``<style>`` is blocked.
    * ``style-src-attr 'none'`` — refuses HTML ``style=`` attributes
      in source markup. React's CSSOM path
      (``element.style.prop = value``) is unaffected because the CSP
      spec scopes ``style-src-attr`` to the markup attribute, not the
      DOM property.
    * Legacy ``style-src 'self'`` is the fallback for browsers that
      pre-date the ``-elem`` / ``-attr`` split; in modern browsers
      the more specific directives override it (stricter), and in
      older browsers ``'self'`` is at least as strict as the previous
      contract.
    """
    parsed = _parse_directives(_CSP_DIRECTIVES)
    assert parsed.get("style-src") == ("'self'",)
    assert parsed.get("style-src-elem") == ("'self'",)
    assert parsed.get("style-src-attr") == ("'none'",)


def test_csp_script_src_layers_lock_inline_handlers() -> None:
    """``script-src`` lists the two allowed origins; ``-attr`` is
    locked to ``'none'``.

    React attaches DOM event handlers via ``addEventListener`` so the
    bundle never emits HTML ``onclick=""``-style markup. ``-attr
    'none'`` makes that an explicit invariant — a regression test
    rather than a code-review preference.
    """
    parsed = _parse_directives(_CSP_DIRECTIVES)
    assert parsed.get("script-src") == ("'self'", "https://telegram.org")
    assert parsed.get("script-src-attr") == ("'none'",)


def test_csp_report_uri_points_at_local_collector() -> None:
    """``report-uri`` must point at our in-app endpoint so violations
    flow into our log instead of vanishing.

    The collector itself is exercised by ``test_csp_report.py``;
    here we only check that the policy is wired to it.
    """
    parsed = _parse_directives(_CSP_DIRECTIVES)
    assert parsed.get("report-uri") == ("/api/csp-report",)


# ── 4. Runtime — the header is actually attached to responses ────────────


async def test_csp_header_attached_to_health(client) -> None:
    """The middleware emits the policy on every response — the
    health endpoint is unauthenticated and stable, so it's a safe
    probe for the middleware path.
    """
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.headers.get("Content-Security-Policy") == _CSP_DIRECTIVES


async def test_csp_header_attached_to_csp_report_endpoint(client) -> None:
    """Even on the collector itself — so a misconfigured browser
    that POSTs a malformed report still gets the policy back and
    won't downgrade its own enforcement.
    """
    resp = await client.post("/api/csp-report", content=b"{}")
    assert resp.status_code == 204
    assert resp.headers.get("Content-Security-Policy") == _CSP_DIRECTIVES


async def test_csp_header_attached_to_404(client) -> None:
    """The policy attaches even when the route is unknown — a 404
    from a malicious URL must still carry the lock-down so the
    error page itself can't be turned into an XSS vector.
    """
    resp = await client.get("/this-route-does-not-exist-csp-probe")
    # The SPA fallback only mounts when ``frontend/dist`` exists; in
    # CI it doesn't, so the response is a plain 404. Either way the
    # security middleware sits in front of the router and must
    # decorate the response.
    assert resp.status_code in (200, 404)
    assert resp.headers.get("Content-Security-Policy") == _CSP_DIRECTIVES


# ── 5. SPA shell — index.html mirrors the CSP contract ───────────────────


def test_index_html_has_no_inline_style_tags() -> None:
    """The SPA shell must not contain ``<style>...</style>`` blocks.

    Tailwind classes compile to ``/assets/*.css`` files served from
    the same origin; any inline ``<style>`` in ``index.html`` would
    be blocked by ``style-src-elem 'self'`` on first paint, breaking
    the page before React mounts.
    """
    html = _INDEX_HTML.read_text(encoding="utf-8")
    # ``<style attr=>`` and ``<style>`` both match — the regex covers
    # both the bare-open and the attributed-open form.
    assert not re.search(r"<style[\s>]", html, flags=re.IGNORECASE), (
        "frontend/index.html must not contain inline <style> tags"
    )


def test_index_html_has_no_inline_script_bodies() -> None:
    """``<script>...</script>`` blocks with a non-empty body are
    forbidden — ``script-src`` is origin-allowlisted, not nonce-aware,
    so any inline JavaScript in the SPA shell would be refused on
    first paint.

    ``<script src="...">`` tags are fine and tested separately.
    """
    html = _INDEX_HTML.read_text(encoding="utf-8")
    for body in re.findall(
        r"<script[^>]*>([\s\S]*?)</script>",
        html,
        flags=re.IGNORECASE,
    ):
        assert not body.strip(), (
            f"frontend/index.html contains an inline <script> body: {body.strip()[:200]!r}"
        )


def test_index_html_script_origins_match_script_src() -> None:
    """Every ``<script src=...>`` in the SPA shell must be reachable
    under the ``script-src`` allowlist.

    Same-origin sources (``/...``, ``./...``, bare paths) are covered
    by ``'self'``; absolute URLs must match one of the explicit
    origins in ``script-src`` exactly (scheme + host, no path).
    """
    parsed = _parse_directives(_CSP_DIRECTIVES)
    allowed = set(parsed.get("script-src", ()))
    html = _INDEX_HTML.read_text(encoding="utf-8")
    for src in re.findall(
        r'<script[^>]+src=["\']([^"\']+)["\']',
        html,
        flags=re.IGNORECASE,
    ):
        if "://" in src:
            scheme, rest = src.split("://", 1)
            host = rest.split("/", 1)[0]
            origin = f"{scheme}://{host}"
            assert origin in allowed, (
                f"<script src={src!r}> in index.html — origin {origin!r} "
                f"is not in CSP script-src {sorted(allowed)!r}"
            )
        else:
            assert "'self'" in allowed, (
                f"<script src={src!r}> requires script-src 'self' but "
                f"the directive is {sorted(allowed)!r}"
            )
