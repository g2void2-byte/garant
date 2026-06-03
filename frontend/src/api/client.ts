import ky, { type BeforeRequestHook, HTTPError } from "ky";
import { clearPinToken, getPinToken } from "@/lib/pin";
import {
  clearTotpSessionToken,
  getTotpSessionToken,
} from "@/lib/totp";
import { queryClient } from "@/lib/queryClient";
import { getInitData } from "@/lib/tg";
import { emitGlobalToast } from "@/components/ui/Toast";
import { qk } from "./queryKeys";

// Bug-12 — coalesce 429 toasts so a runaway component / scraper
// doesn't stack 50 identical "Слишком часто" cards on top of each
// other while the rate-limit window resets. We track the last toast
// timestamp per ``URL.pathname`` bucket so distinct endpoints can
// each surface their own message but rapid repeats from the same
// endpoint are throttled to one toast every 5 s.
const _RATE_LIMIT_TOAST_WINDOW_MS = 5000;
const _rateLimitToastLast: Map<string, number> = new Map();

function _rateLimitBucket(url: string): string {
  try {
    return new URL(url).pathname || url;
  } catch {
    return url;
  }
}

function _maybeShowRateLimitToast(url: string, retryAfter: number) {
  const bucket = _rateLimitBucket(url);
  const now = Date.now();
  const last = _rateLimitToastLast.get(bucket) ?? 0;
  if (now - last < _RATE_LIMIT_TOAST_WINDOW_MS) {
    return;
  }
  _rateLimitToastLast.set(bucket, now);
  const seconds = Number.isFinite(retryAfter) && retryAfter > 0
    ? Math.max(1, Math.round(retryAfter))
    : 5;
  emitGlobalToast({
    kind: "error",
    title: `Слишком часто, попробуйте через ${seconds} сек.`,
  });
}

function _parseRetryAfter(value: string | null): number {
  const trimmed = value?.trim();
  if (!trimmed) return Number.NaN;
  if (/^\d+$/.test(trimmed)) {
    const seconds = Number(trimmed);
    return Number.isSafeInteger(seconds) ? seconds : Number.NaN;
  }
  const dateMs = Date.parse(trimmed);
  if (!Number.isFinite(dateMs)) return Number.NaN;
  return Math.max(0, (dateMs - Date.now()) / 1000);
}

const baseURL = import.meta.env.VITE_API_URL || "";

// Audit v3 A-4 — match on structured ``code`` fields instead of
// hardcoded Russian detail strings. The backend now returns
// ``{"code": "...", "detail": "..."}`` for PIN / TOTP errors.
// The ``code`` is locale-independent and forms a stable API contract.
const PIN_SESSION_INVALID_CODES = new Set([
  "pin_session_missing",
  "pin_session_invalid",
  "pin_session_revoked",
  "pin_session_idle",
]);

const TOTP_REQUIRED_CODES = new Set([
  "totp_required",
  "totp_invalid",
  "totp_replay",
]);

const TOTP_NOT_CONFIGURED_CODE = "totp_not_configured";

export const TOTP_REQUIRED_EVENT = "garant:totp-required";
export const TOTP_NOT_CONFIGURED_EVENT = "garant:totp-not-configured";

// Item 24 — global lockout event. The backend now responds with a
// structured 403 payload (``code = "banned" | "frozen"``) for any
// authenticated endpoint when the user's account is locked. The TMA
// listens for this on the root ``App`` shell and replaces the whole
// app with the dedicated ``BannedPage`` so the user can't keep
// hitting (and being rejected by) downstream endpoints.
export const LOCKOUT_EVENT = "garant:lockout";

export interface LockoutDetail {
  code: "banned" | "frozen";
  message: string;
  reason: string | null;
  admin_username: string | null;
}

function isLockoutDetail(value: unknown): value is LockoutDetail {
  if (!value || typeof value !== "object") return false;
  const v = value as Record<string, unknown>;
  return v.code === "banned" || v.code === "frozen";
}

export interface TotpRequiredDetail {
  detail: string;
}

function attachAuthHeaders(req: Request) {
  const initData = getInitData();
  if (initData) req.headers.set("Authorization", `tma ${initData}`);
  const pinToken = getPinToken();
  if (pinToken) req.headers.set("X-Pin-Token", pinToken);
  const totpToken = getTotpSessionToken();
  if (totpToken) req.headers.set("X-Totp-Session", totpToken);
}

export const api = ky.create({
  prefixUrl: baseURL ? `${baseURL.replace(/\/$/, "")}/` : "/",
  // 30s accommodates slow mobile networks and the occasional cold
  // Postgres connection without prematurely cancelling legitimate
  // requests. ky still enforces a finite timeout — we don't disable
  // it — so a hung backend won't leave the UI spinning forever.
  timeout: 30_000,
  // Bug-12 — silently retrying a 429 is what kept the UI "stuck"
  // looking like it was loading when the user was actually being
  // rate-limited. Drop 429 from the retry list and let the
  // ``beforeError`` hook below surface a user-visible toast instead.
  // 408/500/502/503/504 stay on the default ky retry list (set via
  // ``methods``/``statusCodes`` defaults).
  retry: {
    limit: 2,
    statusCodes: [408, 500, 502, 503, 504],
  },
  hooks: {
    beforeRequest: [attachAuthHeaders as BeforeRequestHook],
    beforeError: [
      async (err: HTTPError) => {
        let detail: unknown;
        let code: string | undefined;
        try {
          const data: unknown = await err.response.clone().json();
          if (data && typeof data === "object" && "detail" in data) {
            detail = (data as { detail?: unknown }).detail;
            // Audit v3 A-4 — structured errors return
            // ``{"detail": {"code": "...", "detail": "..."}}``
            if (detail && typeof detail === "object" && "code" in detail) {
              const structured = detail as { code: string; detail: string };
              code = structured.code;
              err.message = structured.detail;
            } else if (detail) {
              err.message = typeof detail === "string" ? detail : JSON.stringify(detail);
            }
          }
        } catch {
          /* ignore */
        }
        if (
          err.response.status === 401 &&
          code !== undefined &&
          PIN_SESSION_INVALID_CODES.has(code)
        ) {
          clearPinToken();
          queryClient.invalidateQueries({ queryKey: qk.pin.status() });
        }
        // 2FA failure — drop any cached session token (it's stale or
        // already invalidated server-side) and dispatch the event the
        // global ``TotpGate`` listens on.
        if (
          err.response.status === 401 &&
          code !== undefined &&
          TOTP_REQUIRED_CODES.has(code)
        ) {
          clearTotpSessionToken();
          try {
            const evt = new CustomEvent<TotpRequiredDetail>(TOTP_REQUIRED_EVENT, {
              detail: {
                detail: typeof detail === "object" && detail !== null && "detail" in detail
                  ? (detail as { detail: string }).detail
                  : String(detail),
              },
            });
            window.dispatchEvent(evt);
          } catch {
            /* DOM unavailable */
          }
        }
        if (err.response.status === 403 && code === TOTP_NOT_CONFIGURED_CODE) {
          try {
            window.dispatchEvent(new Event(TOTP_NOT_CONFIGURED_EVENT));
          } catch {
            /* noop */
          }
        }
        // Bug-12 — surface a single throttled "Слишком часто" toast
        // when the backend rate-limits us. The retry list above
        // already excludes 429, so the failing request just bubbles
        // up to the calling component — no silent retry loop, no
        // wedged spinner.
        if (err.response.status === 429) {
          const retryAfter = _parseRetryAfter(err.response.headers.get("Retry-After"));
          _maybeShowRateLimitToast(err.request.url, retryAfter);
        }
        // Item 24 — fan out a lockout event so the root app can swap
        // to the dedicated ban gate. We dispatch regardless of which
        // endpoint tripped the 403; the gate listens once and the
        // event is idempotent.
        if (err.response.status === 403 && isLockoutDetail(detail)) {
          try {
            const evt = new CustomEvent<LockoutDetail>(LOCKOUT_EVENT, {
              detail,
            });
            window.dispatchEvent(evt);
          } catch {
            /* DOM unavailable */
          }
        }
        return err;
      },
    ],
  },
});

export function apiUrl(path: string) {
  return baseURL ? `${baseURL.replace(/\/$/, "")}${path}` : path;
}
