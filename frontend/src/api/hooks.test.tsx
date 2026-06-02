import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";

const apiState = vi.hoisted(() => ({
  postResponse: undefined as unknown,
}));

vi.mock("./client", () => ({
  api: {
    post: (..._args: unknown[]) => ({
      json: async () => apiState.postResponse,
    }),
  },
}));

import { useCreateReview, useDealAction } from "./hooks";

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
  return { invalidateSpy, wrapper };
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
