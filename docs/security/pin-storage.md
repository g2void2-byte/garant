# PIN and TOTP Session Storage

The frontend stores two short-lived JWTs in `window.localStorage`:

- `garant.pin_token` after PIN verification;
- `garant.totp_session_token` after an admin TOTP code is accepted.

This is a deliberate Telegram Mini App tradeoff. HttpOnly cookies are a better default for normal web apps, but Telegram WebView cookie persistence is not reliable across iOS, Android, Desktop, and Web clients. The app auth model is already header-based: Telegram `initData` proves the user identity, then PIN/TOTP tokens add step-up checks through `X-Pin-Token` and `X-Totp-Session`.

The risk is XSS: any script that runs in the app origin can read localStorage. The project compensates on the server side:

- PIN JWTs have bounded TTL and are rejected when the user's PIN epoch/session state changes.
- TOTP session JWTs expire after `totp_session_ttl_seconds` and include `users.totp_session_epoch`, so disabling or rotating 2FA invalidates outstanding tokens.
- Admin status is checked on every TOTP-gated request; demoting an admin neuters an existing TOTP session.
- The initial TOTP session mint still consumes a one-time code and updates `users.totp_last_counter` to prevent replay.
- CSP forbids inline scripts/styles and limits script origins to reduce XSS probability.

Rules for changing this storage primitive:

1. Prove the replacement survives Telegram WebView reopen/reload cycles on iOS, Android, Desktop, and Web.
2. Keep server-side epoch/TTL validation; client storage must not be the only revocation control.
3. Update `frontend/src/lib/pin.ts`, `frontend/src/lib/totp.ts`, tests, and this document in the same change.
4. If cookies are introduced, document `SameSite`, `Secure`, domain/path scope, CSRF implications, and split-origin behavior.
