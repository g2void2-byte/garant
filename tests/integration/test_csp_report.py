"""L-2 — CSP violation collector smoke tests.

The endpoint deliberately accepts un-validated JSON because browsers
ship slightly different shapes (``application/csp-report`` vs
``application/reports+json``); we just need to confirm the endpoint is
reachable, 204s on success, rejects oversized payloads, and the
``Content-Security-Policy`` header now advertises ``report-uri``
pointing at it.
"""

from __future__ import annotations

from backend.app.main import _CSP_DIRECTIVES


def test_csp_directives_include_report_uri():
    assert "report-uri /api/csp-report" in _CSP_DIRECTIVES


async def test_csp_report_endpoint_accepts_valid_payload(client):
    payload = {
        "csp-report": {
            "document-uri": "https://example.com/",
            "violated-directive": "style-src",
            "effective-directive": "style-src",
            "blocked-uri": "inline",
            "source-file": "https://example.com/app.js",
            "line-number": 42,
        }
    }
    resp = await client.post(
        "/api/csp-report",
        json=payload,
        headers={"Content-Type": "application/csp-report"},
    )
    assert resp.status_code == 204
    assert resp.content == b""


async def test_csp_report_rejects_oversized_payload(client):
    """The collector caps the body at 16 KB to keep a chatty browser
    from filling the log; sending a ``Content-Length`` over the cap
    short-circuits to 413 before we read the body."""
    huge_body = b"x" * (32 * 1024)
    resp = await client.post(
        "/api/csp-report",
        content=huge_body,
        headers={
            "Content-Type": "application/csp-report",
            "Content-Length": str(len(huge_body)),
        },
    )
    assert resp.status_code == 413


async def test_csp_report_is_anonymous(client):
    """Browsers post these without any of our cookies — calling the
    endpoint with zero auth headers must still succeed."""
    resp = await client.post("/api/csp-report", content=b"{}")
    assert resp.status_code == 204
