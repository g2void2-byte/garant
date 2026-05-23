import ky, { type BeforeRequestHook, HTTPError, type NormalizedOptions } from "ky";
import { clearPinToken, getPinToken } from "@/lib/pin";
import {
  clearTotpSessionToken,
  getTotpSessionToken,
} from "@/lib/totp";
import { queryClient } from "@/lib/queryClient";
import { getInitData } from "@/lib/tg";
import { qk } from "./queryKeys";

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
  /** Server-supplied detail string we used to flip into the gate. */
  detail: string;
  /** HTTP method of the failed request (for retry on success). */
  method: string;
  /** Fully-qualified URL of the failed request. */
  url: string;
  /** Request body as a clone — undefined for GET / no-body requests. */
  body: BodyInit | null | undefined;
  /** Raw header bag of the failed request, for replay. */
  headers: Record<string, string>;
}

function bodyFromInit(req: Request): BodyInit | null | undefined {
  // ``Request`` consumes its body on first read; we only get one
  // shot per failed request. Clone so a successful retry inside
  // ``TotpGate`` can still send the original payload.
  const clone = req.clone();
  if (clone.body == null) return undefined;
  return clone.body as unknown as BodyInit;
}

function headersFromRequest(req: Request): Record<string, string> {
  const out: Record<string, string> = {};
  req.headers.forEach((v, k) => {
    out[k] = v;
  });
  return out;
}

const attachAuthHeaders: BeforeRequestHook = (req: Request, _opts: NormalizedOptions) => {
  const initData = getInitData();
  if (initData) req.headers.set("Authorization", `tma ${initData}`);
  const pinToken = getPinToken();
  if (pinToken) req.headers.set("X-Pin-Token", pinToken);
  const totpToken = getTotpSessionToken();
  if (totpToken) req.headers.set("X-Totp-Session", totpToken);
};

export const api = ky.create({
  prefixUrl: baseURL ? `${baseURL.replace(/\/$/, "")}/` : "/",
  // 30s accommodates slow mobile networks and the occasional cold
  // Postgres connection without prematurely cancelling legitimate
  // requests. ky still enforces a finite timeout — we don't disable
  // it — so a hung backend won't leave the UI spinning forever.
  timeout: 30_000,
  hooks: {
    beforeRequest: [attachAuthHeaders],
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
                method: err.request.method,
                url: err.request.url,
                body: bodyFromInit(err.request),
                headers: headersFromRequest(err.request),
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
