import ky, { HTTPError } from "ky";
import { getPinToken } from "@/lib/pin";
import { getInitData } from "@/lib/tg";

const baseURL = import.meta.env.VITE_API_URL || "";

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
        try {
          const data: any = await err.response.clone().json();
          if (data?.detail) err.message = typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail);
        } catch {
          /* ignore */
        }
        return err;
      },
    ],
  },
});

export function apiUrl(path: string) {
  return baseURL ? `${baseURL.replace(/\/$/, "")}${path}` : path;
}
