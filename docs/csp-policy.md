# Content Security Policy

> **Status:** enforced on every HTTP response, snapshot-tested,
> lint-gated.
> **Owner:** backend security middleware (`backend/app/main.py`).
> **Telemetry:** `POST /api/csp-report` (rate-limited, structured-logged).

This document is the contract for what Garant's CSP allows and why,
plus the rules a reviewer applies when a change wants to relax it.
It exists so the policy doesn't quietly drift through copy-paste or
through a new dependency that ships inline styles or scripts.

---

## TL;DR

* No inline `<style>` blocks, no `style=` HTML attributes in markup,
  no inline `<script>` blocks, no `onclick=`-style HTML event
  handlers. Tailwind utility classes and React's CSSOM
  (`element.style.prop = value`) are fine — CSP scopes the
  inline-style ban to *markup*, not to runtime DOM mutation.
* No `'unsafe-inline'`, no `'unsafe-eval'`, no `*` wildcard origin.
* External scripts: exactly one — `https://telegram.org` for the
  Telegram WebApp SDK. Adding a second one requires a sibling
  policy change documented in this file.
* `dangerouslySetInnerHTML` is forbidden at the lint stage.
* Violations from real browsers POST to `/api/csp-report` and show
  up as `csp.report.signal` / `csp.report.noise` events in the
  structured log.

---

## The directive string

The exact policy served on every response. Snapshot-tested in
`tests/test_csp_policy.py::test_csp_directives_match_expected_snapshot`;
mirrored verbatim in `backend/app/main.py::_CSP_DIRECTIVES`.

```
default-src 'self';
script-src 'self' https://telegram.org;
script-src-attr 'none';
style-src 'self';
style-src-elem 'self';
style-src-attr 'none';
img-src 'self' data: blob:;
font-src 'self' data:;
connect-src 'self';
worker-src 'self' blob:;
frame-ancestors 'none';
base-uri 'self';
form-action 'self';
object-src 'none';
report-uri /api/csp-report
```

### Why each directive looks like this

| Directive | Value | Rationale |
|---|---|---|
| `default-src` | `'self'` | Anything not explicitly listed below falls back to same-origin. Catch-all for future CSP directives we don't yet name. |
| `script-src` | `'self' https://telegram.org` | Vite emits same-origin module bundles; the Telegram WebApp SDK is the only external script. We accept the supply-chain risk of `telegram.org` because the alternative is shipping no integration. |
| `script-src-attr` | `'none'` | Refuses HTML `onclick=""` event-handler attributes. React attaches all listeners via `addEventListener`. |
| `style-src` | `'self'` | Legacy fallback for browsers that don't honour the CSP3 `-elem` / `-attr` split. |
| `style-src-elem` | `'self'` | Refuses cross-origin `<style>` blocks and `<link rel="stylesheet">`. Tailwind compiles to `/assets/*.css` served from the same origin. |
| `style-src-attr` | `'none'` | Refuses HTML `style=` attributes in source markup. React's CSSOM path (`element.style.prop = value` in JSX `style={{...}}`) is *unaffected* — the CSP spec scopes this directive to markup attributes, not to runtime DOM properties. |
| `img-src` | `'self' data: blob:` | `/media/` uploads, plus inline data URIs and blob URIs the UI generates for screenshot previews. |
| `font-src` | `'self' data:` | Tailwind / system fonts plus data-URI font shims. |
| `connect-src` | `'self'` | REST + WebSocket on the same origin. The bot talks to Telegram from the backend, not from the browser. |
| `worker-src` | `'self' blob:` | Future-proof for service workers / web workers. `blob:` covers Vite's worker chunking. |
| `frame-ancestors` | `'none'` | The TMA renders inside Telegram's native WebView (not an `<iframe>`); blocking framing closes click-jacking. Duplicates the legacy `X-Frame-Options: DENY` for browsers that honour both. |
| `base-uri` | `'self'` | Stops a hostile DOM from changing the document base URL and pivoting relative paths. |
| `form-action` | `'self'` | We don't have HTML form submissions, but if a 3rd-party widget tries to POST credentials cross-origin this is the safety net. |
| `object-src` | `'none'` | No `<object>` / `<embed>` / `<applet>`. |
| `report-uri` | `/api/csp-report` | Telemetry collector — see `backend/app/routers/csp_report.py`. |

### Why no nonces?

The TMA is a Vite SPA with no SSR — `frontend/index.html` is a
static file served by the backend's SPA-fallback handler. A real
nonce-based CSP requires:

1. A placeholder token in `index.html` that survives the Vite build.
2. A backend middleware that reads `index.html` on every SPA-fallback
   request, generates a per-request nonce, substitutes it into the
   markup, and sets the matching `'nonce-{value}'` source on the
   response CSP header.
3. Cache-control gymnastics to keep nonced HTML out of the CDN.

The previous architectural decision (PR «CSP nonce migration») was
to migrate *away* from libraries that need inline styles —
specifically Framer Motion's dynamic `style=` attributes — rather
than pay the per-request HTML-rewrite cost. The current policy
encodes that decision: same-origin assets only, no nonces, no
inline anything.

If a future change genuinely needs inline content (e.g. inlining a
critical-CSS chunk to fix LCP), the nonce middleware can be added
*then* with a focused diff that touches `_CSP_DIRECTIVES`, the SPA
fallback handler, `tests/test_csp_policy.py`, and this doc.

---

## What contributors must follow

### Frontend dependencies

Before adding a new dep to `frontend/package.json`, check whether it
injects inline styles or scripts at runtime:

```bash
# 1. Read the README / docs.
# 2. Grep the published source for inline injection patterns.
npm view <package> dist.tarball
# Then inspect the tarball:
#   - <style> tags built into the JS source
#   - document.head.appendChild(style) calls
#   - elt.innerHTML = '...' with <style>/<script> content
#   - elt.setAttribute('style', '...') with computed values
```

Known compatible patterns (no inline content):

* React, React DOM (uses CSSOM, not markup styles).
* TailwindCSS (compiles to a same-origin CSS file).
* TanStack Query / Zustand / React Router (state libs; no DOM).
* Lucide React (SVG components, no inline `<style>`).

Known incompatible patterns (rejected at this policy):

* Framer Motion (sets `style=` attributes — removed in a prior PR).
* CSS-in-JS libraries that inject runtime `<style>` blocks
  (emotion, styled-components default mode, JSS).
* Analytics tags that load external scripts.

### Frontend code

ESLint blocks the four ways a contributor can re-introduce inline
content from JSX (`frontend/eslint.config.js::no-restricted-syntax`):

| Pattern | Why it's blocked |
|---|---|
| `<style>...</style>` JSX element | `style-src-elem 'self'` refuses inline blocks. |
| `<script>...</script>` JSX element | `script-src 'self'` is origin-allowlisted, not inline-allowing. |
| `<link rel="stylesheet" href="https://...">` JSX | `style-src-elem 'self'` refuses cross-origin stylesheets. |
| `dangerouslySetInnerHTML={...}` | Injected HTML can contain inline `<style>`/`<script>` that CSP blocks at first paint. |

Inline JSX `style={{...}}` props are *fine* — they go through React's
CSSOM path and CSP doesn't see them. 14 such call sites exist today
(positioning, scroll parallax, dynamic sizing). The contract test
`tests/test_csp_policy.py::test_index_html_has_no_inline_style_tags`
covers the `index.html` shell separately.

### Backend changes

The directive string is owned by `_CSP_DIRECTIVES` in
`backend/app/main.py`. Changing it requires:

1. Update `_CSP_DIRECTIVES`.
2. Update the snapshot in
   `tests/test_csp_policy.py::test_csp_directives_match_expected_snapshot`.
3. Update the table above and the rationale section.
4. PR-review explicitly approving the policy change.

This file is the single source of truth; everything else (the test
snapshot, the lint rule, the middleware code) is enforced *from* it.

---

## Telemetry

Real browsers POST a JSON envelope to `/api/csp-report` whenever the
policy blocks something. The collector (`backend/app/routers/csp_report.py`)
classifies each report:

* `csp.report.signal` — anything our markup did. Acts on at INFO,
  visible in the default-level log + Sentry.
* `csp.report.noise` — known-irrelevant sources (browser extensions,
  Translate overlays, in-app screenshot data-URIs). Logged at DEBUG
  so it doesn't drown the signal channel.

The collector is rate-limited (30 reports/min/IP) and capped at 16 KB
body size to keep a misbehaving page from flooding the log. The full
classification rules live next to the code in `csp_report.py`.

If you tighten the policy and start seeing `csp.report.signal`
entries, fix the markup — don't re-loosen the policy.

---

## Related audit items

* **M-5** — original audit item. *This document.*
* **L-7** — Subresource Integrity (SRI) on the Telegram script tag.
  Deferred because Telegram rotates its CDN without preannouncement;
  a hash pin would break the TMA on every Telegram-side update.
* **H-1 / H-2** — money-precision unification (orthogonal; not CSP).

---

## See also

* `backend/app/main.py::_CSP_DIRECTIVES` — the live policy string.
* `backend/app/main.py::_security_headers` — the middleware that
  attaches it to every response.
* `backend/app/routers/csp_report.py` — the telemetry collector.
* `tests/test_csp_policy.py` — snapshot + invariant tests.
* `tests/test_csp_report.py` — collector-endpoint tests.
* `frontend/eslint.config.js` — JSX-side enforcement.
