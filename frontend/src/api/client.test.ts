import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { HTTPError } from "ky";
import type { TotpRequiredDetail } from "./client";

/**
 * Tests for the project-wide ``api`` ky instance.
 *
 * We don't hit any real network — instead we mock global ``fetch`` so
 * we can introspect the outgoing ``Request`` headers (auth + PIN
 * forwarding) and feed canned error responses back into ky's
 * ``beforeError`` hook (PIN-session-invalid -> ``clearPinToken`` +
 * cache invalidation).
 */

const tgState = vi.hoisted(() => ({ initData: "" }));
const pinState = vi.hoisted(() => ({
  token: null as string | null,
  cleared: false,
}));

vi.mock("@/lib/tg", () => ({
  useTelegramViewport: () => null,
  getInitData: () => tgState.initData,
}));

vi.mock("@/lib/pin", () => ({
  getPinToken: () => pinState.token,
  clearPinToken: () => {
    pinState.cleared = true;
    pinState.token = null;
  },
}));

const queryClientSpy = vi.hoisted(() => ({
  invalidateQueries: vi.fn(),
}));

vi.mock("@/lib/queryClient", () => ({
  queryClient: queryClientSpy,
}));

let fetchSpy: ReturnType<typeof vi.fn>;

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

beforeEach(() => {
  tgState.initData = "";
  pinState.token = null;
  pinState.cleared = false;
  queryClientSpy.invalidateQueries.mockClear();
  fetchSpy = vi.fn();
  vi.stubGlobal("fetch", fetchSpy);
  // ky needs an absolute base URL — without a configured backend host
  // it tries ``new URL("/api/foo")`` and throws. Pin a synthetic base
  // so the headers + error-hook contract can be tested in isolation.
  vi.stubEnv("VITE_API_URL", "http://api.test");
  vi.resetModules();
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

describe("api ky client — headers", () => {
  it("attaches Authorization: tma when initData is set", async () => {
    tgState.initData = "user=%7B%22id%22%3A1%7D&hash=dev";
    fetchSpy.mockResolvedValue(jsonResponse(200, { ok: true }));

    const { api } = await import("./client");
    await api.get("api/me").json();

    const req = fetchSpy.mock.calls[0][0] as Request;
    expect(req.headers.get("authorization")).toBe(
      "tma user=%7B%22id%22%3A1%7D&hash=dev",
    );
    expect(req.headers.get("x-pin-token")).toBeNull();
  });

  it("attaches X-Pin-Token when getPinToken returns a value", async () => {
    tgState.initData = "user=abc&hash=dev";
    pinState.token = "secret-pin-token";
    fetchSpy.mockResolvedValue(jsonResponse(200, { ok: true }));

    const { api } = await import("./client");
    await api.get("api/wallet/balances").json();

    const req = fetchSpy.mock.calls[0][0] as Request;
    expect(req.headers.get("x-pin-token")).toBe("secret-pin-token");
  });

  it("does NOT attach Authorization when initData is empty", async () => {
    tgState.initData = "";
    fetchSpy.mockResolvedValue(jsonResponse(200, { ok: true }));

    const { api } = await import("./client");
    await api.get("api/categories").json();

    const req = fetchSpy.mock.calls[0][0] as Request;
    expect(req.headers.get("authorization")).toBeNull();
  });
});

describe("api ky client — beforeError", () => {
  it("rewrites err.message from JSON detail (string)", async () => {
    fetchSpy.mockResolvedValue(
      jsonResponse(400, { detail: "Минимальная сумма — 5 USDT" }),
    );

    const { api } = await import("./client");
    await expect(api.get("api/wallet/withdrawals").json()).rejects.toMatchObject({
      message: "Минимальная сумма — 5 USDT",
    });
    expect(pinState.cleared).toBe(false);
  });

  it("rewrites err.message from JSON detail (object) as stringified payload", async () => {
    fetchSpy.mockResolvedValue(
      jsonResponse(422, { detail: [{ loc: ["body", "amount"], msg: "required" }] }),
    );

    const { api } = await import("./client");
    let caught: HTTPError | null = null;
    try {
      await api.get("api/foo").json();
    } catch (e) {
      caught = e as HTTPError;
    }
    expect(caught).toBeInstanceOf(HTTPError);
    expect(caught!.message).toContain("required");
  });

  it("stringifies malformed structured detail and ignores non-string codes", async () => {
    pinState.token = "still-good";
    fetchSpy.mockResolvedValue(
      jsonResponse(401, { detail: { code: 123, detail: { message: "bad shape" } } }),
    );

    const { api, TOTP_REQUIRED_EVENT } = await import("./client");
    const events: TotpRequiredDetail[] = [];
    const onRequired = (event: Event) => {
      events.push((event as CustomEvent<TotpRequiredDetail>).detail);
    };
    window.addEventListener(TOTP_REQUIRED_EVENT, onRequired);

    try {
      await expect(api.get("api/me").json()).rejects.toThrow("bad shape");
    } finally {
      window.removeEventListener(TOTP_REQUIRED_EVENT, onRequired);
    }

    expect(pinState.cleared).toBe(false);
    expect(queryClientSpy.invalidateQueries).not.toHaveBeenCalled();
    expect(events).toEqual([]);
  });

  it("clears the PIN token + invalidates PIN status on 401 with PIN-session detail", async () => {
    pinState.token = "stale-token";
    fetchSpy.mockResolvedValue(
      jsonResponse(401, { detail: { code: "pin_session_invalid", detail: "PIN-сессия недействительна" } }),
    );

    const { api } = await import("./client");
    await expect(api.get("api/wallet/withdrawals").json()).rejects.toBeTruthy();

    expect(pinState.cleared).toBe(true);
    expect(queryClientSpy.invalidateQueries).toHaveBeenCalledWith({
      queryKey: ["pin", "status"],
    });
  });

  it("dispatches TOTP event without replaying the failed mutation", async () => {
    fetchSpy.mockImplementation(async (input: RequestInfo | URL) => {
      if (input instanceof Request && input.body !== null) {
        await input.text();
      }
      return jsonResponse(401, {
        detail: { code: "totp_required", detail: "Введите код 2FA" },
      });
    });

    const { api, TOTP_REQUIRED_EVENT } = await import("./client");
    const events: TotpRequiredDetail[] = [];
    const onRequired = (event: Event) => {
      events.push((event as CustomEvent<TotpRequiredDetail>).detail);
    };
    window.addEventListener(TOTP_REQUIRED_EVENT, onRequired);

    try {
      await expect(
        api
          .post("api/admin/settings", { json: { support_username: "support" } })
          .json(),
      ).rejects.toThrow("Введите код 2FA");
    } finally {
      window.removeEventListener(TOTP_REQUIRED_EVENT, onRequired);
    }

    expect(events).toHaveLength(1);
    expect(events[0]).toEqual({ detail: "Введите код 2FA" });
  });

  it("does NOT clear PIN on 401 with an unrelated detail string", async () => {
    pinState.token = "still-good";
    fetchSpy.mockResolvedValue(
      jsonResponse(401, { detail: "Unauthorized" }),
    );

    const { api } = await import("./client");
    await expect(api.get("api/me").json()).rejects.toBeTruthy();

    expect(pinState.cleared).toBe(false);
    expect(queryClientSpy.invalidateQueries).not.toHaveBeenCalled();
  });

  it("survives a non-JSON error body without throwing in the hook", async () => {
    fetchSpy.mockResolvedValue(
      new Response("oops", { status: 500, headers: { "content-type": "text/plain" } }),
    );

    const { api } = await import("./client");
    await expect(api.get("api/me").json()).rejects.toBeInstanceOf(HTTPError);
    expect(pinState.cleared).toBe(false);
  });

  it("does not parse malformed Retry-After prefixes as seconds", async () => {
    fetchSpy.mockResolvedValue(
      new Response(JSON.stringify({ detail: "limited" }), {
        status: 429,
        headers: { "content-type": "application/json", "Retry-After": "1abc" },
      }),
    );
    const toasts: Array<{ title: string }> = [];
    const onToast = (event: Event) => {
      toasts.push((event as CustomEvent<{ title: string }>).detail);
    };
    window.addEventListener("garant:toast", onToast);

    try {
      const { api } = await import("./client");
      await expect(api.get("api/limited").json()).rejects.toBeInstanceOf(HTTPError);
    } finally {
      window.removeEventListener("garant:toast", onToast);
    }

    expect(toasts[0]?.title).toMatch(/5/);
  });
});

describe("apiUrl", () => {
  it("prepends the configured baseURL to absolute paths", async () => {
    const { apiUrl } = await import("./client");
    expect(apiUrl("/api/foo")).toBe("http://api.test/api/foo");
  });

  it("returns the path as-is when VITE_API_URL is empty", async () => {
    vi.stubEnv("VITE_API_URL", "");
    vi.resetModules();
    const { apiUrl } = await import("./client");
    expect(apiUrl("/api/foo")).toBe("/api/foo");
  });
});
