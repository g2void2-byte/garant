/**
 * Local-storage helpers for the admin TOTP-session token.
 *
 * The token is a 24h JWT minted by ``POST /api/admin/2fa/session``
 * after a single valid TOTP code is consumed. It is attached to
 * every admin request via the ``X-Totp-Session`` header so the
 * operator does not have to retype the 6-digit code on each
 * TOTP-gated action for the rest of the day.
 *
 * Mirror of ``frontend/src/lib/pin.ts`` so both surfaces have the
 * same storage / expiry / event semantics. A
 * ``garant:totp-token-changed`` event is dispatched on every
 * mutation so the global ``TotpGate`` modal can re-render and the
 * 2FA status pill in the admin nav stays in sync.
 *
 * Audit 5.3 (MED) — threat model
 * -------------------------------
 * The TOTP session token lives in `window.localStorage` (NOT an HttpOnly
 * cookie) for the same reasons documented at length in
 * `frontend/src/lib/pin.ts` — the Telegram Mini App platform does not
 * reliably persist cookies across WebView lifecycles, and the auth model
 * is header-based (`initData` HMAC + JWT) rather than cookie-based.
 *
 * Compensating controls on the *server* side mitigate the XSS exposure
 * surface for admin sessions: (1) the token is bound to
 * `users.totp_session_epoch`, so any 2FA disable / rotation / forced
 * logout invalidates ALL outstanding tokens server-side regardless of
 * where they were stored; (2) the TTL is bounded to 24h server-side
 * (`totp_session_ttl_seconds`) and the token claim is validated against
 * `users.is_admin` on every request, so demoting an admin instantly
 * neuters every issued token; (3) the backend enforces TOTP-code replay
 * prevention via `users.totp_last_counter`, so the *initial* mint of the
 * token still requires a never-before-used 6-digit code.
 *
 * Anyone reading this: do NOT migrate the token to `document.cookie`
 * without first proving that cookies survive the Telegram WebView round
 * trip on iOS, Android, and Desktop clients. See `pin.ts` for the full
 * context.
 */

const STORAGE_KEY = "garant.totp_session_token";
const EXPIRES_KEY = "garant.totp_session_token_expires";

export const TOTP_TOKEN_CHANGED_EVENT = "garant:totp-token-changed";

function notifyTokenChanged() {
  try {
    window.dispatchEvent(new Event(TOTP_TOKEN_CHANGED_EVENT));
  } catch {
    /* DOM unavailable (e.g. during SSR/tests) */
  }
}

export function setTotpSessionToken(token: string, expiresAt: string) {
  const ts = new Date(expiresAt).getTime();
  if (!Number.isFinite(ts)) return;
  try {
    window.localStorage.setItem(STORAGE_KEY, token);
    window.localStorage.setItem(EXPIRES_KEY, expiresAt);
  } catch {
    /* storage unavailable */
  }
  notifyTokenChanged();
}

export function clearTotpSessionToken() {
  try {
    window.localStorage.removeItem(STORAGE_KEY);
    window.localStorage.removeItem(EXPIRES_KEY);
  } catch {
    /* noop */
  }
  notifyTokenChanged();
}

export function getTotpSessionToken(): string | null {
  try {
    const token = window.localStorage.getItem(STORAGE_KEY);
    const expires = window.localStorage.getItem(EXPIRES_KEY);
    if (!token || !expires) return null;
    if (new Date(expires).getTime() <= Date.now()) {
      clearTotpSessionToken();
      return null;
    }
    return token;
  } catch {
    return null;
  }
}

export function hasValidTotpSessionToken(): boolean {
  return !!getTotpSessionToken();
}
