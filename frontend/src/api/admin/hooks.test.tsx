import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import type {
  AdminBalanceSnapshotDto,
  AdminDealDetailDto,
  AdminDepositDto,
} from "../types";

/**
 * Regression tests for V5-F-5 — admin React Query cache invalidation.
 *
 * Before this fix, ``useAdminDealAction`` invalidated the deals list
 * + the deal detail but NOT the buyer/seller user-detail queries,
 * which meant an admin viewing the buyer's profile saw a stale balance
 * after force-release / force-refund. ``useAdminClaimArbitration``
 * had the same gap. The mutation response for ``useAdminDealAction``
 * is ``AdminDealDetailDto`` and exposes ``buyer.user_id`` /
 * ``seller.user_id`` (verified at frontend/src/api/types.ts:374-422),
 * so the fix reads those ids straight from the response. The claim
 * payload only carries ``{ claimed, deal_id, arbiter_id }``, so the
 * fix falls back to a prefix-only ``["admin", "user"]`` invalidation
 * (TanStack Query treats it as a prefix matcher).
 */

const apiState = vi.hoisted(() => ({
  // The next value `api.post(...).json()` resolves to. Tests overwrite
  // this before each render. Default is a minimal AdminDealDetailDto so
  // useAdminDealAction's existing return-shape contract is honoured.
  postResponse: undefined as unknown,
}));

vi.mock("../client", () => ({
  api: {
    post: (..._args: unknown[]) => ({
      json: async () => apiState.postResponse,
    }),
  },
}));

import {
  useAdminClaimArbitration,
  useAdminDepositMarkPaid,
  useAdminDepositRefund,
  useAdminForceRefund,
  useAdminForceRelease,
} from "./hooks";

function makeBalance(overrides: Partial<AdminBalanceSnapshotDto>): AdminBalanceSnapshotDto {
  return {
    user_id: 0,
    username: null,
    display_name: "user",
    currency_code: "USDT",
    amount: "0",
    locked: "0",
    total: "0",
    ...overrides,
  };
}

function makeDealDetail(overrides: Partial<AdminDealDetailDto> = {}): AdminDealDetailDto {
  return {
    id: 7,
    status: "completed",
    description: "test",
    currency_code: "USDT",
    amount: "100",
    commission_amount: "0",
    commission_paid: true,
    topup_deposit_id: null,
    buyer: makeBalance({ user_id: 42, display_name: "buyer" }),
    seller: makeBalance({ user_id: 99, display_name: "seller" }),
    created_at: "2025-01-01T00:00:00Z",
    in_progress_at: null,
    completed_at: "2025-01-02T00:00:00Z",
    cancellation_initiator: null,
    cancellation_reason: null,
    cancellation_requested_at: null,
    arbitration_initiator: null,
    arbitration_reason: null,
    arbitration_resolved_by_id: null,
    arbitration_resolved_by_username: null,
    arbitration_resolution: null,
    arbitration_resolved_at: null,
    confirm_buyer: true,
    confirm_seller: true,
    events: [],
    messages: [],
    ...overrides,
  };
}

function makeDeposit(overrides: Partial<AdminDepositDto> = {}): AdminDepositDto {
  return {
    id: 10,
    user_id: 42,
    username: "alice",
    display_name: "Alice",
    currency_code: "USDT",
    amount: "50.00",
    status: "paid",
    provider_invoice_id: "inv-10",
    pay_url: "https://pay.example/inv-10",
    created_at: "2026-01-01T00:00:00Z",
    paid_at: "2026-01-01T01:00:00Z",
    ...overrides,
  };
}

function spyInvalidate(qc: QueryClient) {
  return vi.spyOn(qc, "invalidateQueries");
}

function makeHarness() {
  const qc = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  const invalidateSpy = spyInvalidate(qc);
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
  return { qc, invalidateSpy, wrapper };
}

function invalidatedKeys(
  spy: ReturnType<typeof spyInvalidate>,
): readonly (readonly unknown[])[] {
  return spy.mock.calls
    .map((call) => {
      const arg = call[0] as { queryKey?: readonly unknown[] } | undefined;
      return arg?.queryKey;
    })
    .filter((k): k is readonly unknown[] => Array.isArray(k));
}

function hasKey(keys: readonly (readonly unknown[])[], expected: readonly unknown[]): boolean {
  return keys.some(
    (k) =>
      k.length === expected.length && k.every((part, i) => part === expected[i]),
  );
}

describe("useAdminDealAction (force-release / force-refund) — V5-F-5 invalidations", () => {
  beforeEach(() => {
    apiState.postResponse = { deal: makeDealDetail() };
  });

  it("force-release invalidates buyer + seller user-detail query keys", async () => {
    apiState.postResponse = { deal: makeDealDetail() };
    const { invalidateSpy, wrapper } = makeHarness();

    const { result } = renderHook(() => useAdminForceRelease(), { wrapper });
    await result.current.mutateAsync({ dealId: 7 });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const keys = invalidatedKeys(invalidateSpy);
    // V5-F-5 additions: buyer + seller user-detail invalidations.
    expect(hasKey(keys, ["admin", "user", 42])).toBe(true);
    expect(hasKey(keys, ["admin", "user", 99])).toBe(true);
    // Existing four invalidations must still fire (regression guard).
    expect(hasKey(keys, ["admin", "deals"])).toBe(true);
    expect(hasKey(keys, ["admin", "deal", 7])).toBe(true);
    expect(hasKey(keys, ["admin", "arbitration"])).toBe(true);
    expect(hasKey(keys, ["admin", "dashboard"])).toBe(true);
  });

  it("force-refund invalidates buyer + seller user-detail query keys", async () => {
    apiState.postResponse = {
      deal: makeDealDetail({
        buyer: makeBalance({ user_id: 42 }),
        seller: makeBalance({ user_id: 99 }),
      }),
    };
    const { invalidateSpy, wrapper } = makeHarness();

    const { result } = renderHook(() => useAdminForceRefund(), { wrapper });
    await result.current.mutateAsync({ dealId: 7 });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const keys = invalidatedKeys(invalidateSpy);
    expect(hasKey(keys, ["admin", "user", 42])).toBe(true);
    expect(hasKey(keys, ["admin", "user", 99])).toBe(true);
    expect(hasKey(keys, ["admin", "deals"])).toBe(true);
    expect(hasKey(keys, ["admin", "deal", 7])).toBe(true);
    expect(hasKey(keys, ["admin", "arbitration"])).toBe(true);
    expect(hasKey(keys, ["admin", "dashboard"])).toBe(true);
  });

  it("does NOT invalidate user keys when the response is `{ deleted: true }` (no buyer/seller)", async () => {
    // The mutationFn returns `json.deal ?? json`; when the server
    // replies with `{ deleted: true }` (no `deal` envelope), the
    // mutation data is `{ deleted: true }` and the type-guard branch
    // for buyer/seller invalidation must be skipped without crashing.
    apiState.postResponse = { deleted: true };
    const { invalidateSpy, wrapper } = makeHarness();

    const { result } = renderHook(() => useAdminForceRelease(), { wrapper });
    await result.current.mutateAsync({ dealId: 7 });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const keys = invalidatedKeys(invalidateSpy);
    // Type-guard rejected the deleted-only payload — no per-id user
    // invalidations fire.
    expect(keys.some((k) => k[0] === "admin" && k[1] === "user" && k.length === 3)).toBe(false);
    // The existing four invalidations still fire.
    expect(hasKey(keys, ["admin", "deals"])).toBe(true);
    expect(hasKey(keys, ["admin", "deal", 7])).toBe(true);
    expect(hasKey(keys, ["admin", "arbitration"])).toBe(true);
    expect(hasKey(keys, ["admin", "dashboard"])).toBe(true);
  });
});

describe("useAdminClaimArbitration — V5-F-5 prefix invalidation", () => {
  it("falls back to invalidating the ['admin', 'user'] prefix when payload has no buyer/seller", async () => {
    apiState.postResponse = { claimed: true, deal_id: 7, arbiter_id: 1 };
    const { invalidateSpy, wrapper } = makeHarness();

    const { result } = renderHook(() => useAdminClaimArbitration(), { wrapper });
    await result.current.mutateAsync(7);
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const keys = invalidatedKeys(invalidateSpy);
    // V5-F-5: prefix-only invalidation matches every cached
    // ["admin", "user", N] query without needing party ids.
    expect(hasKey(keys, ["admin", "user"])).toBe(true);
    // Existing invalidations are preserved.
    expect(hasKey(keys, ["admin", "arbitration"])).toBe(true);
    expect(hasKey(keys, ["admin", "deals"])).toBe(true);
  });
});

describe("admin deposit actions — side-effect cache invalidations", () => {
  const expectedKeys = [
    ["admin", "deposits"],
    ["admin", "wallets"],
    ["admin", "user-wallet", 42],
    ["admin", "user", 42],
    ["admin", "dashboard"],
    ["admin", "system-status"],
    ["admin", "audit"],
    ["wallet"],
    ["me"],
  ] as const;

  it("mark-paid invalidates every cache touched by the backend side effects", async () => {
    apiState.postResponse = makeDeposit({ status: "paid" });
    const { invalidateSpy, wrapper } = makeHarness();

    const { result } = renderHook(() => useAdminDepositMarkPaid(), { wrapper });
    await result.current.mutateAsync({ id: 10, reason: "manual reconcile" });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const keys = invalidatedKeys(invalidateSpy);
    for (const expected of expectedKeys) {
      expect(hasKey(keys, expected)).toBe(true);
    }
  });

  it("refund invalidates every cache touched by the backend side effects", async () => {
    apiState.postResponse = makeDeposit({ status: "refunded" });
    const { invalidateSpy, wrapper } = makeHarness();

    const { result } = renderHook(() => useAdminDepositRefund(), { wrapper });
    await result.current.mutateAsync({ id: 10, reason: "duplicate payment" });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const keys = invalidatedKeys(invalidateSpy);
    for (const expected of expectedKeys) {
      expect(hasKey(keys, expected)).toBe(true);
    }
  });
});
