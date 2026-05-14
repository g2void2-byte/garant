import ky, { HTTPError } from "ky";
import { clearPinToken, getPinToken } from "@/lib/pin";
import { queryClient } from "@/lib/queryClient";
import { getInitData } from "@/lib/tg";

const baseURL = import.meta.env.VITE_API_URL || "";

// Server-side strings that mean "your PIN session is no longer valid".
// On a 401 with one of these we drop the local token and force the
// PinGate to re-render so the user lands back on the PIN screen
// instead of sitting in an authenticated UI whose every request 401s.
const PIN_SESSION_INVALID_DETAILS = new Set([
  "PIN-сессия отсутствует",
  "PIN-сессия недействительна",
  "PIN-сессия отозвана",
]);

export const api = ky.create({
  prefixUrl: baseURL ? `${baseURL.replace(/\/$/, "")}/` : "/",
  timeout: 15_000,
  hooks: {
    beforeRequest: [
      (req) => {
        const initData = getInitData();
        if (initData) req.headers.set("Authorization", `tma ${initData}`);
        const pinToken = getPinToken();
        if (pinToken) req.headers.set("X-Pin-Token", pinToken);
      },
    ],
    beforeError: [
      async (err: HTTPError) => {
        let detail: unknown;
        try {
          const data: any = await err.response.clone().json();
          detail = data?.detail;
          if (detail) err.message = typeof detail === "string" ? detail : JSON.stringify(detail);
        } catch {
          /* ignore */
        }
        if (
          err.response.status === 401 &&
          typeof detail === "string" &&
          PIN_SESSION_INVALID_DETAILS.has(detail)
        ) {
          clearPinToken();
          // Invalidate the cached PIN status so PinGate (and every
          // other consumer of ``["pin", "status"]``) refetches and
          // re-renders the lock screen.
          queryClient.invalidateQueries({ queryKey: ["pin", "status"] });
        }
        return err;
      },
    ],
  },
});

export function apiUrl(path: string) {
  return baseURL ? `${baseURL.replace(/\/$/, "")}${path}` : path;
}
