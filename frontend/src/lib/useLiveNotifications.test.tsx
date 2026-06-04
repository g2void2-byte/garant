import { describe, expect, it, vi, beforeEach } from "vitest";
import { renderHook } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import type { DealMessageDto, NotificationCountersDto, NotificationDto } from "@/api/types";

/**
 * Verifies the React Query cache & toast side-effects of the live
 * notifications hook. The real WS module is replaced by a mock that
 * captures the handlers object so each test can drive arbitrary
 * events through ``onEvent`` and assert the side-effects.
 */

const wsState = vi.hoisted(() => ({
  capturedHandlers: null as
    | null
    | { onEvent: (e: { event: string; data?: unknown }) => void; onOpen?: () => void; onClose?: () => void },
  disconnect: vi.fn(),
}));

vi.mock("@/lib/ws", () => ({
  connectNotifications: (handlers: {
    onEvent: (e: { event: string; data?: unknown }) => void;
    onOpen?: () => void;
    onClose?: () => void;
  }) => {
    wsState.capturedHandlers = handlers;
    return wsState.disconnect;
  },
}));

const hapticSpy = vi.hoisted(() => vi.fn());
vi.mock("@/lib/tg", () => ({
  useTelegramViewport: () => null,
  haptic: hapticSpy,
}));

const toastSpy = vi.hoisted(() => vi.fn());
vi.mock("@/components/ui/Toast", () => ({
  useToast: () => ({ show: toastSpy }),
}));

const clearPinTokenSpy = vi.hoisted(() => vi.fn());
vi.mock("@/lib/pin", () => ({
  clearPinToken: clearPinTokenSpy,
}));

import { useLiveNotifications } from "./useLiveNotifications";

function makeWrapper(client: QueryClient) {
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
}

function makeDealMessage(overrides: Partial<DealMessageDto> = {}): DealMessageDto {
  return {
    id: 1,
    deal_id: 42,
    sender_id: 100,
    sender_username: "alice",
    text: "hi",
    attachments: [],
    created_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

function makeNotification(overrides: Partial<NotificationDto> = {}): NotificationDto {
  return {
    id: 1,
    type: "deals",
    title: "New deal",
    body: "Pay attention",
    payload: {},
    is_read: false,
    created_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

function makeCounters(overrides: Partial<NotificationCountersDto> = {}): NotificationCountersDto {
  return {
    all: 2,
    deals: 1,
    deposits: 1,
    system: 0,
    unread: 2,
    ...overrides,
  };
}

beforeEach(() => {
  wsState.capturedHandlers = null;
  wsState.disconnect.mockClear();
  hapticSpy.mockClear();
  toastSpy.mockClear();
  clearPinTokenSpy.mockClear();
});

describe("useLiveNotifications", () => {
  it("subscribes on mount and unsubscribes on unmount", () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const { unmount } = renderHook(() => useLiveNotifications(), {
      wrapper: makeWrapper(qc),
    });
    expect(wsState.capturedHandlers).not.toBeNull();
    expect(wsState.disconnect).not.toHaveBeenCalled();
    unmount();
    expect(wsState.disconnect).toHaveBeenCalled();
  });

  it("appends incoming deal_message to the cached deal thread", () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const first = makeDealMessage({ id: 1, text: "hi" });
    const second = makeDealMessage({ id: 2, text: "yo" });
    qc.setQueryData(["deal", 42, "messages"], [first]);

    renderHook(() => useLiveNotifications(), { wrapper: makeWrapper(qc) });

    wsState.capturedHandlers!.onEvent({
      event: "deal_message",
      data: second,
    });

    expect(qc.getQueryData(["deal", 42, "messages"])).toEqual([
      first,
      second,
    ]);
    expect(hapticSpy).toHaveBeenCalledWith("light");
    expect(toastSpy).not.toHaveBeenCalled();
  });

  it("de-dupes deal_message by id (no duplicates on reconnect replay)", () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const first = makeDealMessage({ id: 7, deal_id: 5, text: "hi" });
    qc.setQueryData(["deal", 5, "messages"], [first]);

    renderHook(() => useLiveNotifications(), { wrapper: makeWrapper(qc) });

    wsState.capturedHandlers!.onEvent({
      event: "deal_message",
      data: makeDealMessage({ id: 7, deal_id: 5, text: "duplicate" }),
    });

    expect(qc.getQueryData(["deal", 5, "messages"])).toEqual([first]);
  });

  it("seeds the deal thread when no messages were cached yet", () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    renderHook(() => useLiveNotifications(), { wrapper: makeWrapper(qc) });

    const first = makeDealMessage({ id: 1, deal_id: 99, text: "first!" });

    wsState.capturedHandlers!.onEvent({
      event: "deal_message",
      data: first,
    });
    expect(qc.getQueryData(["deal", 99, "messages"])).toEqual([first]);
  });

  it("ignores malformed deal_message frames instead of poisoning message caches", () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const first = makeDealMessage({ id: 1, deal_id: 42, text: "hi" });
    qc.setQueryData(["deal", 42, "messages"], [first]);

    renderHook(() => useLiveNotifications(), { wrapper: makeWrapper(qc) });

    wsState.capturedHandlers!.onEvent({
      event: "deal_message",
      data: { id: 2, text: "missing fields" },
    });
    wsState.capturedHandlers!.onEvent({
      event: "deal_message",
      data: { ...makeDealMessage({ id: 3 }), deal_id: "0x2" },
    });
    wsState.capturedHandlers!.onEvent({
      event: "deal_message",
      data: {
        ...makeDealMessage({ id: 4 }),
        attachments: [{ id: 1, url: "/media/a.png" }],
      },
    });
    wsState.capturedHandlers!.onEvent({
      event: "deal_message",
      data: {
        ...makeDealMessage({ id: 5 }),
        attachments: [
          {
            id: 1,
            kind: "deal",
            url: "/media/a.png",
            name: "a.png",
            size: 1,
            content_type: "image/png",
          },
        ],
      },
    });
    wsState.capturedHandlers!.onEvent({
      event: "deal_message",
      data: {
        ...makeDealMessage({ id: 6 }),
        attachments: [
          {
            id: 1,
            kind: "deal",
            url: "javascript:alert(1)",
            name: "a.png",
            size: 1,
            content_type: "image/png",
            created_at: null,
          },
        ],
      },
    });

    expect(qc.getQueryData(["deal", 42, "messages"])).toEqual([first]);
    expect(qc.getQueryData(["deal", undefined, "messages"])).toBeUndefined();
    expect(hapticSpy).not.toHaveBeenCalled();
  });

  it("inserts a notification, fires haptic+toast, and invalidates counters", () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    qc.setQueryData(["notifications"], [makeNotification({ id: 1, title: "Old", body: "" })]);
    const invalidate = vi.spyOn(qc, "invalidateQueries");

    renderHook(() => useLiveNotifications(), { wrapper: makeWrapper(qc) });

    const incoming = makeNotification({
      id: 2,
      type: "deals",
      title: "New deal",
      body: "Pay attention",
      payload: { deal_id: 42 },
    });

    wsState.capturedHandlers!.onEvent({
      event: "notification",
      data: incoming,
    });

    const list = qc.getQueryData(["notifications"]) as { id: number }[];
    expect(list).toHaveLength(2);
    expect(list[0].id).toBe(2);
    expect(hapticSpy).toHaveBeenCalledWith("light");
    expect(toastSpy).toHaveBeenCalledWith(
      expect.objectContaining({ kind: "info", title: "New deal" }),
    );
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["notifications", "counters"] });
    // deals-typed notification also invalidates deals + deal caches.
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["deals"] });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["deal"] });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["wallet"] });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["users"] });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["user"] });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["me"] });
  });

  it("uses 'success' kind for deposit notifications and invalidates me/wallet", () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const invalidate = vi.spyOn(qc, "invalidateQueries");

    renderHook(() => useLiveNotifications(), { wrapper: makeWrapper(qc) });

    wsState.capturedHandlers!.onEvent({
      event: "notification",
      data: makeNotification({
        id: 9,
        type: "deposits",
        title: "Зачислено",
        body: "+50 USDT",
        payload: null,
      }),
    });
    expect(toastSpy).toHaveBeenCalledWith(
      expect.objectContaining({ kind: "success", title: "Зачислено" }),
    );
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["me"] });
    // H-1 — legacy ``qk.payments`` was retired; wallet deposits are
    // surfaced through ``qk.wallet.*`` now.
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["wallet"] });
  });

  it("ignores malformed notification frames instead of showing forged toasts", () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const first = makeNotification({ id: 1, title: "Old", body: "" });
    qc.setQueryData(["notifications"], [first]);
    const invalidate = vi.spyOn(qc, "invalidateQueries");

    renderHook(() => useLiveNotifications(), { wrapper: makeWrapper(qc) });

    wsState.capturedHandlers!.onEvent({
      event: "notification",
      data: { id: 2, type: "deals", title: "Missing fields", body: "" },
    });
    wsState.capturedHandlers!.onEvent({
      event: "notification",
      data: { ...makeNotification({ id: 3 }), id: "3" },
    });

    expect(qc.getQueryData(["notifications"])).toEqual([first]);
    expect(toastSpy).not.toHaveBeenCalled();
    expect(hapticSpy).not.toHaveBeenCalled();
    expect(invalidate).not.toHaveBeenCalledWith({ queryKey: ["notifications", "counters"] });
  });

  it("ignores events without ``data`` or with unknown event names", () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    renderHook(() => useLiveNotifications(), { wrapper: makeWrapper(qc) });

    wsState.capturedHandlers!.onEvent({ event: "notification" });
    wsState.capturedHandlers!.onEvent({ event: "unknown_event", data: { foo: 1 } });

    expect(toastSpy).not.toHaveBeenCalled();
    expect(hapticSpy).not.toHaveBeenCalled();
  });

  it("invalidates the deal + deals caches on deal.updated (item 22)", () => {
    // The backend emits ``deal.updated`` to every participant after a
    // state-changing op so the initiator's React Query cache is busted
    // even though they never received a stored ``notification`` row.
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const invalidate = vi.spyOn(qc, "invalidateQueries");
    renderHook(() => useLiveNotifications(), { wrapper: makeWrapper(qc) });

    wsState.capturedHandlers!.onEvent({
      event: "deal.updated",
      data: { deal_id: 77, status: "completed" },
    });

    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["deal", 77] });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["deals"] });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["deal"] });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["wallet"] });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["users"] });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["user"] });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["me"] });
    // No toast / haptic — this is a silent cache-bust, not a user
    // event. The companion ``notification`` event (when the user is
    // also a recipient of a stored notification row) is what fires
    // the toast.
    expect(toastSpy).not.toHaveBeenCalled();
    expect(hapticSpy).not.toHaveBeenCalled();
  });

  it("invalidates list caches even when deal.updated lacks a deal_id", () => {
    // Defensive — a malformed frame still busts the list cache so the
    // next render eventually catches the new status.
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const invalidate = vi.spyOn(qc, "invalidateQueries");
    renderHook(() => useLiveNotifications(), { wrapper: makeWrapper(qc) });

    wsState.capturedHandlers!.onEvent({ event: "deal.updated", data: {} });
    wsState.capturedHandlers!.onEvent({
      event: "deal.updated",
      data: { deal_id: "77", status: "completed" },
    });

    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["deals"] });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["deal"] });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["wallet"] });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["users"] });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["user"] });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["me"] });
    expect(invalidate).not.toHaveBeenCalledWith({ queryKey: ["deal", undefined] });
    expect(invalidate).not.toHaveBeenCalledWith({ queryKey: ["deal", "77"] });
    expect(invalidate).not.toHaveBeenCalledWith({ queryKey: ["deal", 77] });
  });

  it("mirrors valid notification.read payloads into local caches", () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    qc.setQueryData(["notifications"], [
      makeNotification({ id: 1, type: "deals" }),
      makeNotification({ id: 2, type: "deposits" }),
    ]);
    qc.setQueryData(["notifications", "counters"], makeCounters());

    renderHook(() => useLiveNotifications(), { wrapper: makeWrapper(qc) });

    wsState.capturedHandlers!.onEvent({
      event: "notification.read",
      data: { ids: [1], all: false },
    });

    expect(qc.getQueryData(["notifications"])).toEqual([
      makeNotification({ id: 1, type: "deals", is_read: true }),
      makeNotification({ id: 2, type: "deposits" }),
    ]);
    expect(qc.getQueryData(["notifications", "counters"])).toEqual(
      makeCounters({ deals: 0, unread: 1 }),
    );
  });

  it("does not coerce malformed cached counters while mirroring reads", () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const counters = makeCounters({
      deals: "1e2" as unknown as number,
      unread: "0x10" as unknown as number,
    });
    qc.setQueryData(["notifications"], [makeNotification({ id: 1, type: "deals" })]);
    qc.setQueryData(["notifications", "counters"], counters);

    renderHook(() => useLiveNotifications(), { wrapper: makeWrapper(qc) });

    wsState.capturedHandlers!.onEvent({
      event: "notification.read",
      data: { ids: [1], all: false },
    });

    expect(qc.getQueryData(["notifications", "counters"])).toEqual(counters);
  });

  it("ignores malformed notification.read payloads instead of mutating counters", () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const notifications = [
      makeNotification({ id: 1, type: "deals" }),
      makeNotification({ id: 2, type: "deposits" }),
    ];
    const counters = makeCounters();
    qc.setQueryData(["notifications"], notifications);
    qc.setQueryData(["notifications", "counters"], counters);

    renderHook(() => useLiveNotifications(), { wrapper: makeWrapper(qc) });

    wsState.capturedHandlers!.onEvent({
      event: "notification.read",
      data: { ids: ["1"], all: false },
    });
    wsState.capturedHandlers!.onEvent({
      event: "notification.read",
      data: { ids: [0], all: false },
    });
    wsState.capturedHandlers!.onEvent({
      event: "notification.read",
      data: { all: "true" },
    });

    expect(qc.getQueryData(["notifications"])).toEqual(notifications);
    expect(qc.getQueryData(["notifications", "counters"])).toEqual(counters);
  });

  it("drops the local PIN token and invalidates pin status on pin.reset (item 8)", () => {
    // Admin pressed ``reset-pin`` on this user. The backend publishes
    // ``{event: 'pin.reset'}`` over the WS channel; the hook must:
    // 1) call ``clearPinToken()`` (which dispatches the
    //    ``garant:pin-token-changed`` event the PinGate listens for);
    // 2) invalidate ``qk.pin.*`` so the next ``usePinStatus`` refetch
    //    sees ``has_pin=false``.
    // Without (1) the locally cached JWT TTL keeps PinGate in the
    // authenticated tree until the user manually reloads.
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const invalidate = vi.spyOn(qc, "invalidateQueries");
    renderHook(() => useLiveNotifications(), { wrapper: makeWrapper(qc) });

    wsState.capturedHandlers!.onEvent({ event: "pin.reset", data: {} });

    expect(clearPinTokenSpy).toHaveBeenCalledTimes(1);
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["pin"] });
    // Toast/haptic intentionally NOT fired on pin.reset — the user
    // is about to be bounced to the new-PIN setup screen, no need
    // for an additional in-app surface that they'd dismiss anyway.
    expect(toastSpy).not.toHaveBeenCalled();
    expect(hapticSpy).not.toHaveBeenCalled();
  });
});
