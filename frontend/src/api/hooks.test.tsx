import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import type { DealMessageDto } from "./types";

const apiState = vi.hoisted(() => ({
  getResponse: undefined as unknown,
  postResponse: undefined as unknown,
  patchResponse: undefined as unknown,
  deleteResponse: undefined as unknown,
}));

vi.mock("./client", () => ({
  api: {
    get: (..._args: unknown[]) => ({
      json: async () => apiState.getResponse,
    }),
    post: (..._args: unknown[]) => ({
      json: async () => apiState.postResponse,
    }),
    patch: (..._args: unknown[]) => ({
      json: async () => apiState.patchResponse,
    }),
    delete: (..._args: unknown[]) => ({
      json: async () => apiState.deleteResponse,
    }),
  },
}));

import {
  buildWalletHistorySearchParams,
  useCreateReview,
  useDealAction,
  useDeleteService,
  useLoadOlderDealMessages,
  useSendDealMessage,
  useUpdateMe,
  useUpdateService,
} from "./hooks";

describe("buildWalletHistorySearchParams", () => {
  it("normalizes valid currency codes and bounded pagination", () => {
    expect(buildWalletHistorySearchParams({ currency: " usd ", limit: 50, offset: 10 })).toEqual({
      currency: "USD",
      limit: "50",
      offset: "10",
    });
  });

  it("drops malformed currency and backend-invalid pagination params", () => {
    expect(
      buildWalletHistorySearchParams({
        currency: "USD/../admin",
        limit: 101,
        offset: -1,
      }),
    ).toEqual({});
  });
});

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

describe("useUpdateMe", () => {
  beforeEach(() => {
    apiState.patchResponse = {
      id: 1,
      username: "alice",
      is_hidden_profile: true,
    };
  });

  it("invalidates public profile, service and review projections", async () => {
    const { invalidateSpy, wrapper } = makeHarness();

    const { result } = renderHook(() => useUpdateMe(), { wrapper });
    await result.current.mutateAsync({ is_hidden_profile: true });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const keys = invalidatedKeys(invalidateSpy);
    for (const expected of [
      ["user", "alice"],
      ["reviews", "alice"],
      ["users"],
      ["services"],
      ["service"],
      ["categories"],
    ] as const) {
      expect(hasKey(keys, expected)).toBe(true);
    }
  });
});

describe("useCreateReview", () => {
  beforeEach(() => {
    apiState.postResponse = {
      id: 1,
      deal_id: 7,
      author_username: "bob",
      target_username: "alice",
      rating: 5,
      text: "ok",
      created_at: "2026-01-01T00:00:00Z",
    };
  });

  it("invalidates review, target profile and public user list caches", async () => {
    const { invalidateSpy, wrapper } = makeHarness();

    const { result } = renderHook(() => useCreateReview(), { wrapper });
    await result.current.mutateAsync({
      target_username: "alice",
      rating: 5,
      text: "ok",
      deal_id: 7,
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const keys = invalidatedKeys(invalidateSpy);
    expect(hasKey(keys, ["reviews", "alice"])).toBe(true);
    expect(hasKey(keys, ["user", "alice"])).toBe(true);
    expect(hasKey(keys, ["users"])).toBe(true);
  });
});

describe("useDealAction", () => {
  beforeEach(() => {
    apiState.postResponse = { id: 7, status: "completed" };
  });

  it("invalidates deal, wallet and user projection caches after state changes", async () => {
    const { invalidateSpy, wrapper } = makeHarness();

    const { result } = renderHook(() => useDealAction("finish"), { wrapper });
    await result.current.mutateAsync({ id: 7 });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const keys = invalidatedKeys(invalidateSpy);
    for (const expected of [
      ["deals"],
      ["deal"],
      ["wallet"],
      ["users"],
      ["user"],
      ["me"],
    ] as const) {
      expect(hasKey(keys, expected)).toBe(true);
    }
  });
});

describe("deal message cache merges", () => {
  it("de-dupes loaded history against cached numeric-string message ids", async () => {
    const { qc, wrapper } = makeHarness();
    const cached = makeDealMessage({ id: "7" as unknown as number, text: "cached" });
    const duplicate = makeDealMessage({ id: 7, text: "duplicate" });
    const older = makeDealMessage({ id: 6, text: "older" });
    qc.setQueryData(["deal", 42, "messages"], [cached]);
    apiState.getResponse = [duplicate, older];

    const { result } = renderHook(() => useLoadOlderDealMessages(42), { wrapper });
    await result.current.mutateAsync({ beforeId: 7 });

    expect(qc.getQueryData(["deal", 42, "messages"])).toEqual([older, cached]);
  });

  it("de-dupes sent messages against cached numeric-string message ids", async () => {
    const { qc, wrapper } = makeHarness();
    const cached = makeDealMessage({ id: "7" as unknown as number, text: "cached" });
    const echo = makeDealMessage({ id: 7, text: "echo" });
    qc.setQueryData(["deal", 42, "messages"], [cached]);
    apiState.postResponse = echo;

    const { result } = renderHook(() => useSendDealMessage(42), { wrapper });
    await result.current.mutateAsync({ text: "echo", attachments: [] });

    expect(qc.getQueryData(["deal", 42, "messages"])).toEqual([cached]);
  });
});

describe("service mutations", () => {
  it("service update invalidates catalog, category and detail caches", async () => {
    apiState.patchResponse = { id: 55, status: "paused" };
    const { invalidateSpy, wrapper } = makeHarness();

    const { result } = renderHook(() => useUpdateService(), { wrapper });
    await result.current.mutateAsync({ id: 55, body: { status: "paused" } });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const keys = invalidatedKeys(invalidateSpy);
    expect(hasKey(keys, ["services"])).toBe(true);
    expect(hasKey(keys, ["categories"])).toBe(true);
    expect(hasKey(keys, ["service", 55])).toBe(true);
  });

  it("service delete invalidates catalog, category, detail and comments caches", async () => {
    apiState.deleteResponse = { ok: true };
    const { invalidateSpy, wrapper } = makeHarness();

    const { result } = renderHook(() => useDeleteService(), { wrapper });
    await result.current.mutateAsync(55);
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const keys = invalidatedKeys(invalidateSpy);
    expect(hasKey(keys, ["services"])).toBe(true);
    expect(hasKey(keys, ["categories"])).toBe(true);
    expect(hasKey(keys, ["service", 55])).toBe(true);
    expect(hasKey(keys, ["service", 55, "comments"])).toBe(true);
  });
});
