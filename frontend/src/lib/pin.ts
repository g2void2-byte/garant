/**
 * Local-storage helpers for the PIN session token.
 *
 * The token is a short-lived JWT issued by the backend after the user
 * passes PIN verification. It is attached to subsequent requests via the
 * `X-Pin-Token` header so sensitive endpoints can require it without
 * forcing the user to re-enter their PIN on every call.
 *
 * A custom ``garant:pin-token-changed`` event is dispatched on every
 * mutation so React components (notably ``PinGate``) can react to the
 * token being revoked from outside their tree — for example by the
 * ky 401 interceptor in ``api/client.ts`` clearing the token after the
 * server returned "PIN-сессия отозвана".
 *
 * Audit N-2 — the threat-model rationale for using ``localStorage``
 * instead of an HttpOnly cookie (Telegram WebView cookie quirks,
 * compensating server-side controls) used to live as a 30-line block
 * here. It now sits in ``docs/security/pin-storage.md`` so the source
 * file stays focused on storage mechanics; do read the doc before
 * migrating the token to ``document.cookie`` or moving the TOTP token
 * (``frontend/src/lib/totp.ts``) into a different storage primitive.
 */

const STORAGE_KEY = "garant.pin_token";
const EXPIRES_KEY = "garant.pin_token_expires";

export const PIN_TOKEN_CHANGED_EVENT = "garant:pin-token-changed";

function notifyTokenChanged() {
  try {
    window.dispatchEvent(new Event(PIN_TOKEN_CHANGED_EVENT));
  } catch {
    /* DOM unavailable (e.g. during SSR/tests) */
  }
}

function parseExpiryTime(expiresAt: string): number | null {
  const ts = new Date(expiresAt).getTime();
  return Number.isFinite(ts) ? ts : null;
}

export function setPinToken(token: string, expiresAt: string) {
  // Comment 42: reject garbage expiry values that would write a
  // non-expiring (NaN / Infinity) token into localStorage.
  if (parseExpiryTime(expiresAt) === null) return;
  try {
    window.localStorage.setItem(STORAGE_KEY, token);
    window.localStorage.setItem(EXPIRES_KEY, expiresAt);
  } catch {
    /* storage unavailable */
  }
  notifyTokenChanged();
}

export function clearPinToken() {
  try {
    window.localStorage.removeItem(STORAGE_KEY);
    window.localStorage.removeItem(EXPIRES_KEY);
  } catch {
    /* noop */
  }
  notifyTokenChanged();
}

export function getPinToken(): string | null {
  try {
    const token = window.localStorage.getItem(STORAGE_KEY);
    const expires = window.localStorage.getItem(EXPIRES_KEY);
    if (!token || !expires) return null;
    const expiresTs = parseExpiryTime(expires);
    if (expiresTs === null || expiresTs <= Date.now()) {
      clearPinToken();
      return null;
    }
    return token;
  } catch {
    return null;
  }
}

export function hasValidPinToken(): boolean {
  return !!getPinToken();
}
