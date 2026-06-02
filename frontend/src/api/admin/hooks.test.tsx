import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import type {
  AdminBalanceSnapshotDto,
  AdminCategoryDto,
  AdminCommentItemDto,
  AdminCurrencyDto,
  AdminDealDetailDto,
  AdminDepositDto,
  AdminReviewItemDto,
  AdminServiceItemDto,
  AdminWithdrawalDto,
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
  patchResponse: undefined as unknown,
  putResponse: undefined as unknown,
  deleteResponse: undefined as unknown,
}));

vi.mock("../client", () => ({
  api: {
    post: (..._args: unknown[]) => ({
      json: async () => apiState.postResponse,
    }),
    patch: (..._args: unknown[]) => ({
      json: async () => apiState.patchResponse,
    }),
    put: (..._args: unknown[]) => ({
      json: async () => apiState.putResponse,
    }),
    delete: (..._args: unknown[]) => ({
      json: async () => apiState.deleteResponse,
    }),
  },
}));

import {
  useAdminClaimArbitration,
  useAdminCreateBroadcast,
  useAdminCreateReview,
  useAdminDeleteBroadcast,
  useAdminDeleteComment,
  useAdminDeleteCategory,
  useAdminDeleteCurrency,
  useAdminDeleteReview,
  useAdminDeleteService,
  useAdminDecideWithdrawal,
  useAdminDepositMarkPaid,
  useAdminDepositRefund,
  useAdminForceRefund,
  useAdminForceRelease,
  useAdminFlushRedis,
  useAdminUpdateSettings,
  useAdminUpsertCategory,
  useAdminUpsertCurrency,
  useAdminUpdateComment,
  useAdminUpdateReview,
  useAdminUpdateService,
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

function makeWithdrawal(overrides: Partial<AdminWithdrawalDto> = {}): AdminWithdrawalDto {
  return {
    id: 11,
    user_id: 42,
    username: "alice",
    display_name: "Alice",
    currency_code: "USDT",
    amount: "25.00",
    address: null,
    status: "sent",
    admin_note: "",
    created_at: "2026-01-01T00:00:00Z",
    processed_at: "2026-01-01T02:00:00Z",
    ...overrides,
  };
}

function makeReview(overrides: Partial<AdminReviewItemDto> = {}): AdminReviewItemDto {
  return {
    id: 12,
    deal_id: 7,
    author_id: 99,
    author_username: "seller",
    target_id: 42,
    target_username: "buyer",
    rating: 5,
    text: "ok",
    created_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

function makeService(overrides: Partial<AdminServiceItemDto> = {}): AdminServiceItemDto {
  return {
    id: 55,
    owner_id: 42,
    category_id: 3,
    category_slug: "dev",
    title: "Build API",
    description: "Backend work",
    price: 100,
    status: "active",
    ban_reason: null,
    views: 10,
    deals_count: 2,
    deposit: 0,
    rating_manual: null,
    created_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

function makeComment(overrides: Partial<AdminCommentItemDto> = {}): AdminCommentItemDto {
  return {
    id: 77,
    service_id: 55,
    author_id: 42,
    author_username: "alice",
    text: "good",
    rating: 5,
    created_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

function makeCategory(overrides: Partial<AdminCategoryDto> = {}): AdminCategoryDto {
  return {
    id: 3,
    slug: "dev",
    name: "Development",
    icon: "code",
    ...overrides,
  };
}

function makeCurrency(overrides: Partial<AdminCurrencyDto> = {}): AdminCurrencyDto {
  return {
    id: 4,
    code: "USD",
    name: "US Dollar",
    network: "fiat",
    icon_url: "",
    decimals: 2,
    min_deposit: 1,
    min_withdraw: 1,
    is_active: true,
    sort_order: 1,
    address_regex: "",
    kind: "fiat",
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

describe("admin service/comment mutations - public cache invalidations", () => {
  it("service update invalidates admin content, public catalog, detail, comments and audit caches", async () => {
    apiState.postResponse = makeService({ title: "Updated API" });
    const { invalidateSpy, wrapper } = makeHarness();

    const { result } = renderHook(() => useAdminUpdateService(42), { wrapper });
    await result.current.mutateAsync({ serviceId: 55, body: { title: "Updated API" } });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const keys = invalidatedKeys(invalidateSpy);
    for (const expected of [
      ["admin", "user-services", 42],
      ["admin", "user", 42],
      ["admin", "audit"],
      ["services"],
      ["categories"],
      ["service", 55],
      ["service", 55, "comments"],
    ] as const) {
      expect(hasKey(keys, expected)).toBe(true);
    }
  });

  it("service delete invalidates public catalog/detail/comment caches", async () => {
    apiState.postResponse = { deleted: true, service_id: 55 };
    const { invalidateSpy, wrapper } = makeHarness();

    const { result } = renderHook(() => useAdminDeleteService(42), { wrapper });
    await result.current.mutateAsync(55);
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const keys = invalidatedKeys(invalidateSpy);
    for (const expected of [
      ["admin", "user-services", 42],
      ["admin", "user", 42],
      ["admin", "audit"],
      ["services"],
      ["categories"],
      ["service", 55],
      ["service", 55, "comments"],
    ] as const) {
      expect(hasKey(keys, expected)).toBe(true);
    }
  });

  it("comment update invalidates public service comments/detail and audit caches", async () => {
    apiState.postResponse = makeComment({ rating: 1, text: "edited" });
    const { invalidateSpy, wrapper } = makeHarness();

    const { result } = renderHook(() => useAdminUpdateComment(42), { wrapper });
    await result.current.mutateAsync({ commentId: 77, body: { text: "edited", rating: 1 } });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const keys = invalidatedKeys(invalidateSpy);
    for (const expected of [
      ["admin", "user-comments", 42],
      ["admin", "audit"],
      ["service", 55, "comments"],
      ["service", 55],
    ] as const) {
      expect(hasKey(keys, expected)).toBe(true);
    }
  });

  it("comment delete uses backend side-effect ids for precise invalidation", async () => {
    apiState.postResponse = { deleted: true, comment_id: 77, service_id: 55, author_id: 42 };
    const { invalidateSpy, wrapper } = makeHarness();

    const { result } = renderHook(() => useAdminDeleteComment(), { wrapper });
    await result.current.mutateAsync(77);
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const keys = invalidatedKeys(invalidateSpy);
    for (const expected of [
      ["admin", "user-comments", 42],
      ["admin", "audit"],
      ["service", 55, "comments"],
      ["service", 55],
    ] as const) {
      expect(hasKey(keys, expected)).toBe(true);
    }
  });
});

describe("admin broadcast mutations - audit cache invalidations", () => {
  it("create invalidates broadcast history and audit log caches", async () => {
    apiState.postResponse = { id: 21 };
    const { invalidateSpy, wrapper } = makeHarness();

    const { result } = renderHook(() => useAdminCreateBroadcast(), { wrapper });
    await result.current.mutateAsync({ body: "Maintenance window", dispatch_inapp: true });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const keys = invalidatedKeys(invalidateSpy);
    expect(hasKey(keys, ["admin", "broadcasts"])).toBe(true);
    expect(hasKey(keys, ["admin", "audit"])).toBe(true);
  });

  it("delete invalidates broadcast history and audit log caches", async () => {
    apiState.deleteResponse = { ok: true };
    const { invalidateSpy, wrapper } = makeHarness();

    const { result } = renderHook(() => useAdminDeleteBroadcast(), { wrapper });
    await result.current.mutateAsync(21);
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const keys = invalidatedKeys(invalidateSpy);
    expect(hasKey(keys, ["admin", "broadcasts"])).toBe(true);
    expect(hasKey(keys, ["admin", "audit"])).toBe(true);
  });
});

describe("admin settings/system mutations - side-effect cache invalidations", () => {
  it("settings update invalidates public projections, maintenance, system status and audit", async () => {
    apiState.patchResponse = { maintenance_enabled: true };
    const { invalidateSpy, wrapper } = makeHarness();

    const { result } = renderHook(() => useAdminUpdateSettings(), { wrapper });
    await result.current.mutateAsync({
      maintenance_enabled: true,
      pending_topup_expiry_hours: 12,
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const keys = invalidatedKeys(invalidateSpy);
    for (const expected of [
      ["admin", "settings"],
      ["public-settings"],
      ["public-stats"],
      ["maintenance"],
      ["admin", "system-status"],
      ["admin", "audit"],
    ] as const) {
      expect(hasKey(keys, expected)).toBe(true);
    }
  });

  it("redis flush invalidates system status and audit log caches", async () => {
    apiState.postResponse = { ok: true, deleted_by_prefix: { "rl:": 2 } };
    const { invalidateSpy, wrapper } = makeHarness();

    const { result } = renderHook(() => useAdminFlushRedis(), { wrapper });
    await result.current.mutateAsync();
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const keys = invalidatedKeys(invalidateSpy);
    expect(hasKey(keys, ["admin", "system-status"])).toBe(true);
    expect(hasKey(keys, ["admin", "audit"])).toBe(true);
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
    ["admin", "analytics-series"],
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

describe("admin withdrawal decisions — side-effect cache invalidations", () => {
  it("invalidates admin analytics and user-facing wallet caches", async () => {
    apiState.postResponse = makeWithdrawal({ status: "sent" });
    const { invalidateSpy, wrapper } = makeHarness();

    const { result } = renderHook(() => useAdminDecideWithdrawal(), { wrapper });
    await result.current.mutateAsync({ id: 11, body: { action: "mark_sent" } });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const keys = invalidatedKeys(invalidateSpy);
    for (const expected of [
      ["admin", "withdrawals"],
      ["admin", "wallets"],
      ["admin", "user-wallet", 42],
      ["admin", "user", 42],
      ["admin", "analytics-kpi"],
      ["admin", "analytics-series"],
      ["admin", "system-status"],
      ["admin", "audit"],
      ["wallet"],
    ] as const) {
      expect(hasKey(keys, expected)).toBe(true);
    }
  });

  it("invalidates broad caches when the backend reports an error after a partial commit", async () => {
    apiState.postResponse = Promise.reject(new Error("CryptoBot failed"));
    const { invalidateSpy, wrapper } = makeHarness();

    const { result } = renderHook(() => useAdminDecideWithdrawal(), { wrapper });
    await expect(
      result.current.mutateAsync({ id: 11, body: { action: "approve" } }),
    ).rejects.toThrow("CryptoBot failed");
    await waitFor(() => expect(result.current.isError).toBe(true));

    const keys = invalidatedKeys(invalidateSpy);
    for (const expected of [
      ["admin", "withdrawals"],
      ["admin", "wallets"],
      ["admin", "user-wallet"],
      ["admin", "user"],
      ["admin", "analytics-kpi"],
      ["admin", "analytics-series"],
      ["admin", "system-status"],
      ["admin", "audit"],
      ["wallet"],
    ] as const) {
      expect(hasKey(keys, expected)).toBe(true);
    }
  });
});

describe("admin review mutations — rating side-effect cache invalidations", () => {
  const expectedReviewKeys = [
    ["admin", "user-reviews"],
    ["admin", "users"],
    ["admin", "user", 42],
    ["admin", "user", 99],
    ["admin", "audit"],
    ["reviews"],
    ["users"],
    ["user"],
  ] as const;

  it("create invalidates target rating, review lists, public users and audit caches", async () => {
    apiState.postResponse = makeReview();
    const { invalidateSpy, wrapper } = makeHarness();

    const { result } = renderHook(() => useAdminCreateReview(42), { wrapper });
    await result.current.mutateAsync({ author_id: 99, target_id: 42, rating: 5, text: "ok" });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const keys = invalidatedKeys(invalidateSpy);
    for (const expected of expectedReviewKeys) {
      expect(hasKey(keys, expected)).toBe(true);
    }
  });

  it("update invalidates target rating, review lists, public users and audit caches", async () => {
    apiState.postResponse = makeReview({ rating: 2 });
    const { invalidateSpy, wrapper } = makeHarness();

    const { result } = renderHook(() => useAdminUpdateReview(42), { wrapper });
    await result.current.mutateAsync({ reviewId: 12, body: { rating: 2, text: "bad" } });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const keys = invalidatedKeys(invalidateSpy);
    for (const expected of expectedReviewKeys) {
      expect(hasKey(keys, expected)).toBe(true);
    }
  });

  it("delete falls back to broad user invalidations because the response has no target id", async () => {
    apiState.postResponse = { deleted: true };
    const { invalidateSpy, wrapper } = makeHarness();

    const { result } = renderHook(() => useAdminDeleteReview(99), { wrapper });
    await result.current.mutateAsync(12);
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const keys = invalidatedKeys(invalidateSpy);
    for (const expected of [
      ["admin", "user-reviews"],
      ["admin", "users"],
      ["admin", "user"],
      ["admin", "audit"],
      ["reviews"],
      ["users"],
      ["user"],
    ] as const) {
      expect(hasKey(keys, expected)).toBe(true);
    }
  });
});

describe("admin taxonomy mutations - public cache invalidations", () => {
  const expectedCategoryKeys = [
    ["admin", "categories"],
    ["admin", "audit"],
    ["categories"],
    ["services"],
    ["service"],
  ] as const;

  const expectedCurrencyKeys = [
    ["admin", "currencies"],
    ["admin", "wallets"],
    ["admin", "user-wallet"],
    ["admin", "deals"],
    ["admin", "deal"],
    ["admin", "deposits"],
    ["admin", "withdrawals"],
    ["admin", "analytics-kpi"],
    ["admin", "analytics-series"],
    ["admin", "analytics-top"],
    ["admin", "system-status"],
    ["admin", "audit"],
    ["wallet"],
  ] as const;

  it("category upsert invalidates public category/service projections and audit", async () => {
    apiState.putResponse = makeCategory({ name: "Updated" });
    const { invalidateSpy, wrapper } = makeHarness();

    const { result } = renderHook(() => useAdminUpsertCategory(), { wrapper });
    await result.current.mutateAsync({ slug: "dev", name: "Updated" });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const keys = invalidatedKeys(invalidateSpy);
    for (const expected of expectedCategoryKeys) {
      expect(hasKey(keys, expected)).toBe(true);
    }
  });

  it("category delete invalidates public category/service projections and audit", async () => {
    apiState.deleteResponse = { ok: true };
    const { invalidateSpy, wrapper } = makeHarness();

    const { result } = renderHook(() => useAdminDeleteCategory(), { wrapper });
    await result.current.mutateAsync(3);
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const keys = invalidatedKeys(invalidateSpy);
    for (const expected of expectedCategoryKeys) {
      expect(hasKey(keys, expected)).toBe(true);
    }
  });

  it("currency upsert invalidates wallet/admin projections and audit", async () => {
    apiState.putResponse = makeCurrency({ min_deposit: 2 });
    const { invalidateSpy, wrapper } = makeHarness();

    const { result } = renderHook(() => useAdminUpsertCurrency(), { wrapper });
    await result.current.mutateAsync({ code: "USD", min_deposit: 2 });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const keys = invalidatedKeys(invalidateSpy);
    for (const expected of expectedCurrencyKeys) {
      expect(hasKey(keys, expected)).toBe(true);
    }
  });

  it("currency delete uses the backend DELETE route and invalidates wallet/admin projections", async () => {
    apiState.deleteResponse = { ok: true };
    const { invalidateSpy, wrapper } = makeHarness();

    const { result } = renderHook(() => useAdminDeleteCurrency(), { wrapper });
    await result.current.mutateAsync(4);
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const keys = invalidatedKeys(invalidateSpy);
    for (const expected of expectedCurrencyKeys) {
      expect(hasKey(keys, expected)).toBe(true);
    }
  });
});
