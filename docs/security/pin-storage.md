# PIN session token — storage threat model

> Source code reference: `frontend/src/lib/pin.ts` /
> `frontend/src/lib/totp.ts`

This note captures the threat-model rationale for keeping the PIN session
token (and the parallel TOTP session token) in `window.localStorage`
rather than an HttpOnly cookie. It used to live inline in `pin.ts`; the
audit (`N-2`) flagged the 30-line block as deserving its own doc.

## Why `localStorage`, not `document.cookie`

The PIN session token is a short-lived JWT issued by the backend after
the user passes PIN verification. It is attached to subsequent requests
via the `X-Pin-Token` header so sensitive endpoints can require it
without forcing the user to re-enter their PIN on every call.

The token lives in `window.localStorage` (NOT an HttpOnly cookie). This
is a deliberate choice driven by the Telegram Mini App platform:

- The TMA frontend runs *inside* Telegram's WebView, not a traditional
  browser tab. Cookies set by the FastAPI backend are NOT reliably
  attached to the next request because the TMA's origin handling
  differs per Telegram client (desktop / mobile / web) and may strip
  third-party cookies entirely.
- The auth model is `initData` HMAC verification per request, NOT
  cookie-based sessions. The PIN token is a short-lived JWT that
  piggybacks on the `X-Pin-Token` header alongside `X-Init-Data`. An
  HttpOnly cookie would be inert because nothing else uses cookies and
  the frontend cannot tell whether the cookie is present (it can only
  observe failed requests, which is too late).

## Compensating server-side controls

Compensating controls on the *server* side mitigate the XSS exposure
surface:

1. The token is bound to `pin_session_epoch` so a single click on
   "выйти" or any password change revokes ALL outstanding tokens
   server-side regardless of where they were stored.
2. The TTL is short (`pin_session_ttl_seconds`, default 30 min) —
   a stolen token expires before the attacker can do much damage.
3. The backend enforces an idle-timeout via `pin_last_activity_at`,
   so an inactive session is killed even within its TTL window.

## Migration warning

Anyone reading this: do NOT migrate the token to `document.cookie`
without first proving that cookies survive the Telegram WebView round
trip on **iOS, Android, and Desktop** clients. The same applies to the
TOTP session token in `frontend/src/lib/totp.ts`.

## Custom event surface

A `garant:pin-token-changed` event is dispatched on every mutation so
React components (notably `PinGate`) can react to the token being
revoked from outside their tree — for example by the ky 401
interceptor in `frontend/src/api/client.ts` clearing the token after
the server returned "PIN-сессия отозвана".
