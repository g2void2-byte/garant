import { Suspense } from "react";
import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ErrorBoundary } from "@/components/ErrorBoundary";

import { lazyWithRetry } from "./lazyWithRetry";

function installReloadSpy() {
  const reload = vi.fn();
  const originalLocation = window.location;
  Object.defineProperty(window, "location", {
    configurable: true,
    value: { ...originalLocation, reload },
  });
  return {
    reload,
    restore: () => {
      Object.defineProperty(window, "location", {
        configurable: true,
        value: originalLocation,
      });
    },
  };
}

describe("lazyWithRetry", () => {
  let restoreLocation: (() => void) | null = null;
  let consoleErrorSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    window.sessionStorage.clear();
    consoleErrorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
  });

  afterEach(() => {
    restoreLocation?.();
    restoreLocation = null;
    vi.restoreAllMocks();
    window.sessionStorage.clear();
  });

  it("reloads once and stores a session guard on the first chunk import failure", async () => {
    const { reload, restore } = installReloadSpy();
    restoreLocation = restore;
    const Chunk = lazyWithRetry(() => Promise.reject(new Error("chunk failed")), "FirstFailure");

    render(
      <ErrorBoundary fallback={(error) => <div data-testid="caught">{error.message}</div>}>
        <Suspense fallback={<div data-testid="loading">loading</div>}>
          <Chunk />
        </Suspense>
      </ErrorBoundary>,
    );

    await waitFor(() => expect(reload).toHaveBeenCalledTimes(1));
    expect(window.sessionStorage.getItem("garant.chunk_reload:FirstFailure")).toBe("1");
    expect(screen.getByTestId("loading")).toBeInTheDocument();
    expect(screen.queryByTestId("caught")).not.toBeInTheDocument();
  });

  it("throws the original chunk error when sessionStorage is blocked", async () => {
    const { reload, restore } = installReloadSpy();
    restoreLocation = restore;
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new DOMException("blocked", "SecurityError");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new DOMException("blocked", "SecurityError");
    });
    const Chunk = lazyWithRetry(() => Promise.reject(new Error("chunk failed")), "BlockedStorage");

    render(
      <ErrorBoundary fallback={(error) => <div data-testid="caught">{error.message}</div>}>
        <Suspense fallback={<div data-testid="loading">loading</div>}>
          <Chunk />
        </Suspense>
      </ErrorBoundary>,
    );

    expect(await screen.findByTestId("caught")).toHaveTextContent("chunk failed");
    expect(reload).not.toHaveBeenCalled();
    expect(consoleErrorSpy).toHaveBeenCalled();
  });
});
