import { test, type Page } from "@playwright/test";
import { expect, mockApi, seedSession } from "./fixtures";

/**
 * V12-M5 — WebSocket reconnect e2e.
 *
 * ``connectNotifications`` in ``src/lib/ws.ts`` opens a WebSocket
 * against ``/ws/notifications`` and, on every ``close`` event,
 * schedules a reconnect with exponential backoff (``MIN_BACKOFF``
 * 1s → ``MAX_BACKOFF`` 30s, doubled each retry). The unit suite
 * (``src/lib/ws.test.ts``) covers the JS state machine, but no
 * Playwright spec walked the real Vite build through:
 *
 *   * the ``useEffect`` mount in ``App.tsx`` opening a socket,
 *   * a forced ``close`` event,
 *   * the backoff timer firing and a *second* ``WebSocket(...)``
 *     constructor running.
 *
 * This is the V12-M5 ``WS reconnect`` bullet.
 *
 * Implementation note: we can't drive a real backend in this suite,
 * so we install a tracked WebSocket stub via ``addInitScript`` that
 * (a) records every constructor invocation, (b) exposes a helper to
 * fire ``close`` deterministically from the test, and (c) collapses
 * ``send`` to a no-op so the auth handshake doesn't bail. The stub
 * runs before any app code, so React's ``useLiveNotifications``
 * effect picks it up transparently.
 */

interface WsStubHandle {
  /** Number of WebSocket constructor invocations so far. */
  count: number;
  /** URL passed to the most recent constructor. */
  lastUrl: string | null;
}

async function installWsStub(page: Page) {
  await page.addInitScript(() => {
    interface StubSocket {
      url: string;
      readyState: number;
      _open: () => void;
      _close: () => void;
      _message: (data: unknown) => void;
      send: (data: string) => void;
      close: () => void;
      addEventListener: (event: string, fn: (ev: unknown) => void) => void;
      onopen: ((ev: unknown) => void) | null;
      onmessage: ((ev: unknown) => void) | null;
      onclose: ((ev: unknown) => void) | null;
      onerror: ((ev: unknown) => void) | null;
    }
    const instances: StubSocket[] = [];
    function StubWebSocket(this: StubSocket, url: string) {
      const self = this;
      self.url = url;
      self.readyState = 0;
      const listeners: Record<string, Array<(ev: unknown) => void>> = {
        open: [],
        message: [],
        close: [],
        error: [],
      };
      self.addEventListener = (event, fn) => {
        listeners[event] = listeners[event] || [];
        listeners[event].push(fn);
      };
      self.onopen = null;
      self.onmessage = null;
      self.onclose = null;
      self.onerror = null;
      self.send = () => {
        /* noop — accept the auth frame without forwarding */
      };
      self.close = () => {
        self.readyState = 3;
        listeners.close.forEach((fn) => fn(new Event("close")));
        if (self.onclose) self.onclose(new Event("close"));
      };
      self._open = () => {
        self.readyState = 1;
        listeners.open.forEach((fn) => fn(new Event("open")));
        if (self.onopen) self.onopen(new Event("open"));
      };
      self._close = () => {
        self.readyState = 3;
        const ev = new Event("close");
        listeners.close.forEach((fn) => fn(ev));
        if (self.onclose) self.onclose(ev);
      };
      self._message = (data) => {
        const ev = { data: typeof data === "string" ? data : JSON.stringify(data) };
        listeners.message.forEach((fn) => fn(ev));
        if (self.onmessage) self.onmessage(ev);
      };
      instances.push(self);
    }
    (StubWebSocket as unknown as { CONNECTING: number }).CONNECTING = 0;
    (StubWebSocket as unknown as { OPEN: number }).OPEN = 1;
    (StubWebSocket as unknown as { CLOSING: number }).CLOSING = 2;
    (StubWebSocket as unknown as { CLOSED: number }).CLOSED = 3;
    (window as unknown as { WebSocket: unknown }).WebSocket = StubWebSocket;
    (window as unknown as { __wsInstances: StubSocket[] }).__wsInstances = instances;
  });
}

async function readWs(page: Page): Promise<WsStubHandle> {
  return page.evaluate<WsStubHandle>(() => {
    const w = window as unknown as {
      __wsInstances?: Array<{ url: string }>;
    };
    // Vite's dev server opens its own HMR WebSocket on the same
    // origin (e.g. ``ws://127.0.0.1:5174/?token=...``). Filter the
    // stub's instance list down to *only* the notifications socket
    // so this spec doesn't trip on the HMR connection.
    const all = (w.__wsInstances ?? []).filter((s) =>
      /\/ws\/notifications(?:\?|$)/.test(s.url),
    );
    return {
      count: all.length,
      lastUrl: all.length ? all[all.length - 1].url : null,
    };
  });
}

test.describe("WebSocket reconnect", () => {
  test.beforeEach(async ({ page }) => {
    await installWsStub(page);
    await seedSession(page);
  });

  test("opens a notifications socket on mount and reconnects after a forced close", async ({
    page,
  }) => {
    await mockApi(page);

    await page.goto("/search");

    // First connection — surfaces after ``useLiveNotifications``
    // effect runs.
    await expect.poll(async () => (await readWs(page)).count).toBeGreaterThan(0);
    const first = await readWs(page);
    expect(first.lastUrl).toMatch(/\/ws\/notifications$/);

    // Force the socket closed from the page side. ``connectNotifications``
    // schedules a reconnect after MIN_BACKOFF (1s) — wait up to ~5s
    // so the test isn't flaky on slower CI runners.
    await page.evaluate(() => {
      const w = window as unknown as {
        __wsInstances: Array<{ _close: () => void }>;
      };
      w.__wsInstances[w.__wsInstances.length - 1]._close();
    });

    await expect
      .poll(async () => (await readWs(page)).count, { timeout: 5_000 })
      .toBeGreaterThan(1);

    const second = await readWs(page);
    expect(second.count).toBeGreaterThanOrEqual(2);
    expect(second.lastUrl).toMatch(/\/ws\/notifications$/);
  });
});
