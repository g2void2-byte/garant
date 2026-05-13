/**
 * Local-storage helpers for the PIN session token.
 *
 * The token is a short-lived JWT issued by the backend after the user
 * passes PIN verification. It is attached to subsequent requests via the
 * `X-Pin-Token` header so sensitive endpoints can require it without
 * forcing the user to re-enter their PIN on every call.
 */

const STORAGE_KEY = "garant.pin_token";
const EXPIRES_KEY = "garant.pin_token_expires";

export function setPinToken(token: string, expiresAt: string) {
  try {
    window.localStorage.setItem(STORAGE_KEY, token);
    window.localStorage.setItem(EXPIRES_KEY, expiresAt);
  } catch {
    /* storage unavailable */
  }
}

export function clearPinToken() {
  try {
    window.localStorage.removeItem(STORAGE_KEY);
    window.localStorage.removeItem(EXPIRES_KEY);
  } catch {
    /* noop */
  }
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
