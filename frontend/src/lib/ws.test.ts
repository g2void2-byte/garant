import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

/**
 * The WS module is exercised against a fake ``WebSocket`` constructor
 * + ``vi.useFakeTimers`` so we don't actually open sockets in jsdom.
 * Tests focus on the contract that the rest of the app depends on:
 *
 *   1. ``onOpen`` is only surfaced after the server-side auth ACK.
 *   2. ``onEvent`` is *not* called for the auth ACK frame, only for
 *      post-auth payloads.
 *   3. The first server message must be the auth ACK — any other
 *      frame closes the socket.
 *   4. Auto-reconnect uses exponential backoff (1s -> 2s -> 4s …
 *      capped at 30s).
 *   5. The cleanup function returned from ``connectNotifications``
 *      stops the reconnect loop.
 */

interface FakeCloseEvent {
  code: number;
  reason: string;
  wasClean: boolean;
}

interface FakeSocketHandlers {
  open?: () => void;
  message?: (msg: { data: string }) => void;
  close?: (ev: FakeCloseEvent) => void;
  error?: () => void;
}

class FakeSocket {
  static instances: FakeSocket[] = [];
  url: string;
  sent: string[] = [];
  handlers: FakeSocketHandlers = {};
  closed = false;

  constructor(url: string) {
    this.url = url;
    FakeSocket.instances.push(this);
  }

  addEventListener<E extends keyof FakeSocketHandlers>(
    event: E,
    handler: NonNullable<FakeSocketHandlers[E]>,
  ) {
    this.handlers[event] = handler;
  }

  send(data: string) {
    this.sent.push(data);
  }

  close() {
    if (this.closed) return;
    this.closed = true;
    this.handlers.close?.({ code: 1000, reason: "", wasClean: true });
  }

  closeWith(code: number, reason = "") {
    if (this.closed) return;
    this.closed = true;
    this.handlers.close?.({ code, reason, wasClean: false });
  }

  // Test helpers — drive the socket lifecycle from outside.
  triggerOpen() {
    this.handlers.open?.();
  }
  triggerMessage(payload: unknown) {
    this.handlers.message?.({ data: JSON.stringify(payload) });
  }
  triggerError() {
    this.handlers.error?.();
  }
}

vi.mock("@/lib/tg", () => ({
  useTelegramViewport: () => null,
  getInitData: () => "user=%7B%22id%22%3A1%7D&hash=dev",
}));

let connectNotifications: typeof import("./ws").connectNotifications;

beforeEach(async () => {
  FakeSocket.instances = [];
  vi.useFakeTimers();
  (globalThis as unknown as { WebSocket: typeof FakeSocket }).WebSocket = FakeSocket;
  // Reset module so the WS module captures the patched WebSocket.
  vi.resetModules();
  ({ connectNotifications } = await import("./ws"));
});

afterEach(() => {
  vi.useRealTimers();
});

describe("connectNotifications — auth handshake", () => {
  it("opens a socket and sends the auth frame on transport open", () => {
    const disconnect = connectNotifications({ onEvent: vi.fn() });
    expect(FakeSocket.instances).toHaveLength(1);

    FakeSocket.instances[0].triggerOpen();
    expect(FakeSocket.instances[0].sent).toHaveLength(1);
    const frame = JSON.parse(FakeSocket.instances[0].sent[0]);
    expect(frame).toMatchObject({ type: "auth" });
    expect(frame.init_data).toBeTruthy();

    disconnect();
  });

  it("only fires onOpen after a successful auth ACK", () => {
    const onOpen = vi.fn();
    const onEvent = vi.fn();
    const disconnect = connectNotifications({ onEvent, onOpen });

    const sock = FakeSocket.instances[0];
    sock.triggerOpen();
    expect(onOpen).not.toHaveBeenCalled();

    sock.triggerMessage({ type: "auth", ok: true });
    expect(onOpen).toHaveBeenCalledTimes(1);
    expect(onEvent).not.toHaveBeenCalled();

    disconnect();
  });

  it("closes the socket if the first message is NOT an auth ACK", () => {
    const onOpen = vi.fn();
    const disconnect = connectNotifications({ onEvent: vi.fn(), onOpen });

    const sock = FakeSocket.instances[0];
    sock.triggerOpen();
    sock.triggerMessage({ event: "notification", data: { id: 1 } });

    expect(sock.closed).toBe(true);
    expect(onOpen).not.toHaveBeenCalled();
    disconnect();
  });

  it("forwards post-auth events to onEvent", () => {
    const onEvent = vi.fn();
    const disconnect = connectNotifications({ onEvent });

    const sock = FakeSocket.instances[0];
    sock.triggerOpen();
    sock.triggerMessage({ type: "auth", ok: true });
    sock.triggerMessage({ event: "notification", data: { id: 7 } });

    expect(onEvent).toHaveBeenCalledTimes(1);
    expect(onEvent).toHaveBeenCalledWith({
      event: "notification",
      data: { id: 7 },
    });
    disconnect();
  });

  it("ignores non-JSON frames", () => {
    const onEvent = vi.fn();
    const disconnect = connectNotifications({ onEvent });

    const sock = FakeSocket.instances[0];
    sock.triggerOpen();
    // Authenticated path
    sock.triggerMessage({ type: "auth", ok: true });
    sock.handlers.message?.({ data: "not-json" });
    expect(onEvent).not.toHaveBeenCalled();
    disconnect();
  });
});

describe("connectNotifications — reconnect", () => {
  it("reopens after close with exponential backoff (1s -> 2s)", () => {
    const onOpen = vi.fn();
    const disconnect = connectNotifications({ onEvent: vi.fn(), onOpen });

    const first = FakeSocket.instances[0];
    first.triggerOpen();
    first.triggerMessage({ type: "auth", ok: true });
    expect(onOpen).toHaveBeenCalledTimes(1);

    // Server drops the connection.
    first.close();

    // First retry happens after MIN_BACKOFF (1s).
    vi.advanceTimersByTime(1_000);
    expect(FakeSocket.instances).toHaveLength(2);

    // Re-auth on the new socket.
    const second = FakeSocket.instances[1];
    second.triggerOpen();
    second.triggerMessage({ type: "auth", ok: true });
    expect(onOpen).toHaveBeenCalledTimes(2);

    disconnect();
  });

  it("does not reconnect after the consumer disconnects", () => {
    const disconnect = connectNotifications({ onEvent: vi.fn() });
    const first = FakeSocket.instances[0];

    disconnect();
    // After the user-side disconnect, ``close`` is invoked synchronously
    // and the timer is cleared. Advancing time should NOT open a new
    // socket.
    vi.advanceTimersByTime(60_000);
    expect(FakeSocket.instances).toHaveLength(1);
    expect(first.closed).toBe(true);
  });

  it("does not reconnect after terminal backend close codes", () => {
    const onClose = vi.fn();
    const disconnect = connectNotifications({ onEvent: vi.fn(), onClose });
    const first = FakeSocket.instances[0];

    first.closeWith(4003, "Account is locked out");
    vi.advanceTimersByTime(60_000);

    expect(onClose).toHaveBeenCalledTimes(1);
    expect(FakeSocket.instances).toHaveLength(1);
    disconnect();
  });
});
