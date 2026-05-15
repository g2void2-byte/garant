"""L-2 — CSP violation collector.

Browsers POST a JSON envelope here when the active CSP policy blocks
something on the page. We log the report at ``INFO`` level so it shows
up in the normal application log; nothing in this endpoint is allowed
to talk back to the client (the only response is a 204 — the spec
asks user-agents to ignore the body anyway).

Why this exists now that ``'unsafe-inline'`` has been removed from
``style-src``: telemetry guards against regressions. If a future change
re-introduces inline ``style=`` attributes in markup, the CSP report
will surface it here before users notice breakage.

Public + unauthenticated by design (CSP reports come from the browser
without any of our cookies), and rate-limited by client IP to keep a
single misbehaving page from flooding the log. Body size is capped via
``content-length`` so a chatty browser can't OOM the worker.
"""

from __future__ import annotations

import logging
from typing import Annotated

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

    # We don't parse the body — different browsers use slightly
    # different envelopes (``application/csp-report`` vs
    # ``application/reports+json``) and forcing a schema would just
    # drop legitimate reports. Logging the raw text (truncated, to
    # keep one runaway page from filling the log) is enough for the
    # telemetry pass.
    try:
        text = raw.decode("utf-8", errors="replace")
    except Exception:  # pragma: no cover — decode("replace") never raises
        text = "<undecodable>"
    logger.info("csp violation report: %s", text[:_MAX_BODY])

    return Response(status_code=status.HTTP_204_NO_CONTENT)
