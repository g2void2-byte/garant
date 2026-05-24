import { describe, expect, it, vi, beforeEach } from "vitest";
import { renderHook } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";

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
    qc.setQueryData(["deal", 42, "messages"], [{ id: 1, body: "hi" }]);

    renderHook(() => useLiveNotifications(), { wrapper: makeWrapper(qc) });

    wsState.capturedHandlers!.onEvent({
      event: "deal_message",
      data: { id: 2, deal_id: 42, body: "yo" },
    });

    expect(qc.getQueryData(["deal", 42, "messages"])).toEqual([
      { id: 1, body: "hi" },
      { id: 2, deal_id: 42, body: "yo" },
    ]);
    expect(hapticSpy).toHaveBeenCalledWith("light");
    expect(toastSpy).not.toHaveBeenCalled();
  });

  it("de-dupes deal_message by id (no duplicates on reconnect replay)", () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    qc.setQueryData(["deal", 5, "messages"], [{ id: 7, body: "hi" }]);

    renderHook(() => useLiveNotifications(), { wrapper: makeWrapper(qc) });

    wsState.capturedHandlers!.onEvent({
      event: "deal_message",
      data: { id: 7, deal_id: 5, body: "duplicate" },
    });

    expect(qc.getQueryData(["deal", 5, "messages"])).toEqual([
      { id: 7, body: "hi" },
    ]);
  });

  it("seeds the deal thread when no messages were cached yet", () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    renderHook(() => useLiveNotifications(), { wrapper: makeWrapper(qc) });

    wsState.capturedHandlers!.onEvent({
      event: "deal_message",
      data: { id: 1, deal_id: 99, body: "first!" },
    });
    expect(qc.getQueryData(["deal", 99, "messages"])).toEqual([
      { id: 1, deal_id: 99, body: "first!" },
    ]);
  });

  it("inserts a notification, fires haptic+toast, and invalidates counters", () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    qc.setQueryData(["notifications"], [{ id: 1, type: "deals", title: "Old", body: "" }]);
    const invalidate = vi.spyOn(qc, "invalidateQueries");

    renderHook(() => useLiveNotifications(), { wrapper: makeWrapper(qc) });

    wsState.capturedHandlers!.onEvent({
      event: "notification",
      data: { id: 2, type: "deals", title: "New deal", body: "Pay attention" },
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
  });

  it("uses 'success' kind for deposit notifications and invalidates me/wallet", () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const invalidate = vi.spyOn(qc, "invalidateQueries");

    renderHook(() => useLiveNotifications(), { wrapper: makeWrapper(qc) });

    wsState.capturedHandlers!.onEvent({
      event: "notification",
      data: { id: 9, type: "deposits", title: "Зачислено", body: "+50 USDT" },
    });
    expect(toastSpy).toHaveBeenCalledWith(
      expect.objectContaining({ kind: "success", title: "Зачислено" }),
    );
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["me"] });
    // H-1 — legacy ``qk.payments`` was retired; wallet deposits are
    // surfaced through ``qk.wallet.*`` now.
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["wallet"] });
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

    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["deals"] });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["deal"] });
    expect(invalidate).not.toHaveBeenCalledWith({ queryKey: ["deal", undefined] });
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
