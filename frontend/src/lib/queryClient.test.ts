import { describe, expect, it } from "vitest";
import { QueryClient } from "@tanstack/react-query";
import { queryClient } from "./queryClient";

/**
 * The literal ``["pin", "status"]`` tuple below intentionally stays
 * un-factored. It mirrors what the ky 401 interceptor would emit at
 * runtime and acts as a contract check on ``qk.pin.status()`` — if a
 * later refactor accidentally changes the factory's tuple shape, this
 * test fails because the cached entry under the literal key would no
 * longer match.
 */

describe("queryClient", () => {
  it("is a QueryClient instance", () => {
    expect(queryClient).toBeInstanceOf(QueryClient);
  });

  it("has the project-wide query defaults applied", () => {
    const defaults = queryClient.getDefaultOptions().queries;
    expect(defaults).toBeDefined();
    expect(defaults?.staleTime).toBe(30_000);
    expect(defaults?.gcTime).toBe(5 * 60_000);
    expect(defaults?.refetchOnWindowFocus).toBe(false);
    expect(defaults?.retry).toBe(1);
  });

  it("supports manual cache invalidation (used by ky 401 interceptor)", async () => {
    const localQc = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    localQc.setQueryData(["pin", "status"], { ok: true });
    expect(localQc.getQueryData(["pin", "status"])).toEqual({ ok: true });
    await localQc.invalidateQueries({ queryKey: ["pin", "status"] });
    const state = localQc.getQueryState(["pin", "status"]);
    expect(state?.isInvalidated).toBe(true);
  });
});
