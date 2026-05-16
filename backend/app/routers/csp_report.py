"""L-2 — CSP violation collector.

Browsers POST a JSON envelope here when the active CSP policy blocks
something on the page. We log the report so it shows up in the normal
application log; nothing in this endpoint is allowed to talk back to
the client (the only response is a 204 — the spec asks user-agents to
ignore the body anyway).

Why this exists now that ``'unsafe-inline'`` has been removed from
``style-src``: telemetry guards against regressions. If a future change
re-introduces inline ``style=`` attributes in markup, the CSP report
will surface it here before users notice breakage.

V5-D-7 — categorical log dampening
----------------------------------
The browser CSP layer is famously noisy: every browser-extension that
injects a stylesheet / inline script, every Telegram-WebView shim that
patches ``window``, every machine-translation overlay, fires a report
against *our* report-uri because the violation is observed on our page.
None of that is actionable for us.

We do a best-effort JSON parse of the envelope so we can pick out the
``violated-directive`` / ``blocked-uri`` pair and bucket the report:

* **noise** — known-irrelevant sources (``chrome-extension://`` and
  siblings, Translate/Reader overlays, ``data:``/``blob:`` URLs from
  in-app screenshots, etc.). Logged at ``DEBUG`` so it stays out of
  the default-level log + Sentry stream but is still available when
  debugging a specific user report.
* **signal** — anything else. Logged at ``INFO`` exactly as before.
* **unparseable** — JSON couldn't be decoded or didn't match the
  ``application/csp-report`` / ``application/reports+json`` shape we
  expect. Logged at ``INFO`` (we err on the side of visibility for
  payloads we don't recognise — they might be a new browser envelope
  we haven't accounted for).

The body is still kept verbatim so the operator can grep the log for
the suspect URL; only the *severity* changes per category. The cap
(``_MAX_BODY``) and the anon rate-limit (30/min/IP) stay as outer
defences regardless of category.

Public + unauthenticated by design (CSP reports come from the browser
without any of our cookies), and rate-limited by client IP to keep a
single misbehaving page from flooding the log. Body size is capped via
``content-length`` so a chatty browser can't OOM the worker.
"""

from __future__ import annotations

import json
import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from ..rate_limit import rate_limit_anon

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["csp"])

# Hard cap on the JSON envelope size. The Chromium CSP report payload
# is ~1 KB; 16 KB gives Firefox / Safari headroom without giving a
# malicious page room to ship MB-sized reports.
_MAX_BODY = 16 * 1024

# Anonymous limiter — 30 reports per minute per IP is generous enough
# for a real browser (one violation per page navigation + a handful
# of in-page interactions) and tight enough to refuse a scraper.
RLCSPReport = Annotated[None, Depends(rate_limit_anon("csp-report", limit=30, window=60))]


# V5-D-7 — URL prefixes that indicate the violation came from a
# browser-extension / WebView shim / in-app overlay rather than from
# our markup.  Matched case-insensitively against ``blocked-uri`` /
# ``source-file``.  Order doesn't matter; first match wins.
_NOISE_URI_PREFIXES = (
    "chrome-extension://",
    "moz-extension://",
    "safari-extension://",
    "safari-web-extension://",
    "ms-browser-extension://",
    "webkit-masked-url://",  # Safari "hides" extension sources behind this.
    "about:",
    "data:",  # In-app pasted screenshots / inline previews.
)

# ``blocked-uri`` is sometimes a bare keyword instead of a URL.  These
# keywords land in the "noise" bucket because they're emitted by
# extension-style injections that race the page's own CSS / JS.
_NOISE_URI_KEYWORDS = frozenset(
    {
        "self",  # The browser couldn't determine the URL — usually extension noise.
        "inline",  # We removed ``'unsafe-inline'`` from ``style-src``; legitimate
        # inline-style violations belong in the "signal" bucket. We only treat
        # ``inline`` as noise when paired with an extension/Telegram source-file
        # below.
    }
)


def _classify_report(payload: dict[str, Any]) -> str:
    """Return ``"noise"`` or ``"signal"`` for a parsed CSP report.

    Accepts either the legacy ``{"csp-report": {...}}`` envelope or a
    single Reporting-API ``{"type": "csp-violation", "body": {...}}``
    record.  Unknown shapes are treated as ``"signal"`` so we never
    silently drop a genuine violation report.
    """
    if not isinstance(payload, dict):
        return "signal"

    if isinstance(payload.get("csp-report"), dict):
        report = payload["csp-report"]
    elif isinstance(payload.get("body"), dict):
        report = payload["body"]
    else:
        return "signal"

    blocked = str(report.get("blocked-uri") or report.get("blockedURL") or "").lower()
    source = str(report.get("source-file") or report.get("sourceFile") or "").lower()

    for url in (blocked, source):
        for prefix in _NOISE_URI_PREFIXES:
            if url.startswith(prefix):
                return "noise"

    # ``blocked-uri == "inline"`` only counts as noise when the
    # source-file is itself an extension URL (extension injecting an
    # inline style/script onto our page).  Bare ``inline`` from our
    # own bundle stays "signal" — that's exactly the regression
    # ``report-uri`` is meant to catch.
    if blocked in _NOISE_URI_KEYWORDS:
        for prefix in _NOISE_URI_PREFIXES:
            if source.startswith(prefix):
                return "noise"

    return "signal"


@router.post("/csp-report", status_code=status.HTTP_204_NO_CONTENT)
async def csp_report(request: Request, _rl: RLCSPReport) -> Response:
    """Accept a CSP violation report and log it.

    Returns 204 No Content unconditionally on accept; the spec lets
    user-agents ignore the response body. Refuses payloads larger than
    ``_MAX_BODY`` with 413.
    """
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            if int(content_length) > _MAX_BODY:
                raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)
        except ValueError:
            # Malformed Content-Length — treat as a misbehaving client.
            raise HTTPException(status.HTTP_400_BAD_REQUEST) from None

    raw = await request.body()
    if len(raw) > _MAX_BODY:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)

    # We don't validate the body — different browsers use slightly
    # different envelopes (``application/csp-report`` vs
    # ``application/reports+json``) and forcing a schema would just
    # drop legitimate reports.  Best-effort decode + classify so the
    # known-noise channel doesn't drown out a real regression.
    try:
        text = raw.decode("utf-8", errors="replace")
    except Exception:  # pragma: no cover — decode("replace") never raises
        text = "<undecodable>"

    category = "signal"
    try:
        parsed = json.loads(text) if text else None
    except ValueError:
        parsed = None
    if isinstance(parsed, list):
        # Reporting-API ships an array of records; classify as "noise"
        # only if *every* record is noise — a single real violation
        # in a batch still warrants visibility.
        records = [r for r in parsed if isinstance(r, dict)]
        if records and all(_classify_report(r) == "noise" for r in records):
            category = "noise"
    elif isinstance(parsed, dict):
        category = _classify_report(parsed)

    truncated = text[:_MAX_BODY]
    if category == "noise":
        logger.debug("csp violation report (noise): %s", truncated)
    else:
        logger.info("csp violation report: %s", truncated)

    return Response(status_code=status.HTTP_204_NO_CONTENT)
