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
 * Audit 5.3 (MED) — threat model
 * -------------------------------
 * The PIN session token lives in `window.localStorage` (NOT an HttpOnly
 * cookie). This is a deliberate choice driven by the Telegram Mini App
 * platform:
 *
 *   - The TMA frontend runs *inside* Telegram's WebView, not a
 *     traditional browser tab. Cookies set by the FastAPI backend are
 *     NOT reliably attached to the next request because the TMA's
 *     origin handling differs per Telegram client (desktop / mobile /
 *     web) and may strip third-party cookies entirely.
 *   - The Auth model is `initData` HMAC verification per request, NOT
 *     cookie-based sessions. The PIN token is a short-lived JWT that
 *     piggybacks on the `X-Pin-Token` header alongside `X-Init-Data`.
 *     An HttpOnly cookie would be inert because nothing else uses
 *     cookies and the frontend cannot tell whether the cookie is
 *     present (it can only observe failed requests, which is too
 *     late).
 *   - Compensating controls on the *server* side mitigate the XSS
 *     exposure surface: (1) the token is bound to `pin_session_epoch`
 *     so a single click on "выйти" or any password change revokes ALL
 *     outstanding tokens server-side regardless of where they were
 *     stored; (2) the TTL is short (`pin_session_ttl_seconds`, default
 *     30 min) — a stolen token expires before the attacker can do much
 *     damage; (3) the backend enforces an idle-timeout via
 *     `pin_last_activity_at`, so an inactive session is killed even
 *     within its TTL window.
 *
 * Anyone reading this: do NOT migrate the token to `document.cookie`
 * without first proving that cookies survive the Telegram WebView round
 * trip on iOS, Android, and Desktop clients. The same applies to the
 * TOTP session token in `frontend/src/lib/totp.ts`.
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
  // Comment 42: reject garbage expiry values that would write a
  // non-expiring (NaN / Infinity) token into localStorage.
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
