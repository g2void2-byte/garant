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

export function setPinToken(token: string, expiresAt: string) {
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
    if (new Date(expires).getTime() <= Date.now()) {
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
