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
