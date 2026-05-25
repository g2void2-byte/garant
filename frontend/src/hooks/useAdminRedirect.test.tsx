import { describe, expect, it, vi } from "vitest";
import { renderHook } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import type { ReactNode } from "react";

/**
 * ``useAdminRedirect`` reads ``me`` from ``useMe`` and calls
 * ``useNavigate`` from react-router. We mock both so the hook can be
 * exercised against arbitrary user shapes without spinning up the
 * full QueryClient + router stack.
 */
const meState = vi.hoisted(() => ({
  data: undefined as { is_admin?: boolean; is_arbiter?: boolean } | undefined,
}));

vi.mock("@/api/hooks", () => ({
  useMe: () => meState,
}));

const navigateSpy = vi.hoisted(() => vi.fn());

vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual<typeof import("react-router-dom")>(
    "react-router-dom",
  );
  return {
    ...actual,
    useNavigate: () => navigateSpy,
  };
});

import { useAdminRedirect } from "./useAdminRedirect";

const wrapper = ({ children }: { children: ReactNode }) => (
  <MemoryRouter>{children}</MemoryRouter>
);

describe("useAdminRedirect", () => {
  beforeEach(() => {
    meState.data = undefined;
    navigateSpy.mockClear();
  });

  it("returns shouldRender=false while ``me`` is still loading", () => {
    // Audit M-6 — closing the "flash before me arrives" window means
    // the hook reports ``false`` until ``me`` resolves. The redirect
    // still doesn't fire on the loading branch (the effect's ``if``
    // requires ``me`` to be truthy), so callers must render nothing
    // until the role check has actually run.
    meState.data = undefined;
    const { result } = renderHook(() => useAdminRedirect(), { wrapper });
    expect(result.current.shouldRender).toBe(false);
    expect(navigateSpy).not.toHaveBeenCalled();
  });

  it("allows admins through and never navigates", () => {
    meState.data = { is_admin: true, is_arbiter: false };
    const { result } = renderHook(() => useAdminRedirect(), { wrapper });
    expect(result.current.shouldRender).toBe(true);
    expect(navigateSpy).not.toHaveBeenCalled();
  });

  it("blocks non-admins and navigates to /search by default", () => {
    meState.data = { is_admin: false, is_arbiter: false };
    const { result } = renderHook(() => useAdminRedirect(), { wrapper });
    expect(result.current.shouldRender).toBe(false);
    expect(navigateSpy).toHaveBeenCalledWith("/search", { replace: true });
  });

  it("respects a custom redirectTo target", () => {
    meState.data = { is_admin: false, is_arbiter: false };
    renderHook(() => useAdminRedirect({ redirectTo: "/profile" }), { wrapper });
    expect(navigateSpy).toHaveBeenCalledWith("/profile", { replace: true });
  });

  it("blocks arbiters by default", () => {
    meState.data = { is_admin: false, is_arbiter: true };
    const { result } = renderHook(() => useAdminRedirect(), { wrapper });
    expect(result.current.shouldRender).toBe(false);
    expect(navigateSpy).toHaveBeenCalled();
  });

  it("allowArbiter=true lets arbiters through", () => {
    meState.data = { is_admin: false, is_arbiter: true };
    const { result } = renderHook(
      () => useAdminRedirect({ allowArbiter: true }),
      { wrapper },
    );
    expect(result.current.shouldRender).toBe(true);
    expect(navigateSpy).not.toHaveBeenCalled();
  });
});
