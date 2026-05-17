import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";

import { ErrorBoundary } from "./ErrorBoundary";

function Bomb({ message = "boom" }: { message?: string }): null {
  throw new Error(message);
}

function ToggleBomb({ initial = true }: { initial?: boolean }) {
  const [armed, setArmed] = useState(initial);
  return (
    <div>
      <button type="button" onClick={() => setArmed(false)}>
        disarm
      </button>
      {armed ? <Bomb /> : <div data-testid="safe">recovered</div>}
    </div>
  );
}

describe("<ErrorBoundary />", () => {
  // React 18 logs every caught error to ``console.error`` even when the
  // boundary handles it cleanly. Swallow during these tests so the
  // vitest output stays readable.
  let consoleErrorSpy: ReturnType<typeof vi.spyOn>;
  beforeEach(() => {
    consoleErrorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
  });
  afterEach(() => {
    consoleErrorSpy.mockRestore();
  });

  it("renders children when nothing throws", () => {
    render(
      <ErrorBoundary>
        <div data-testid="child">ok</div>
      </ErrorBoundary>,
    );
    expect(screen.getByTestId("child")).toHaveTextContent("ok");
    expect(screen.queryByTestId("error-boundary-overlay")).not.toBeInTheDocument();
  });

  it("renders the default overlay when a child throws and reports via onError", () => {
    const onError = vi.fn();
    render(
      <ErrorBoundary onError={onError}>
        <Bomb message="render exploded" />
      </ErrorBoundary>,
    );
    expect(screen.getByTestId("error-boundary-overlay")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(screen.getByText(/Что-то пошло не так/)).toBeInTheDocument();
    expect(onError).toHaveBeenCalledTimes(1);
    const [err] = onError.mock.calls[0];
    expect((err as Error).message).toBe("render exploded");
  });

  it("uses the provided fallback render-prop when supplied", () => {
    const fallback = vi.fn((error: Error, reset: () => void) => (
      <div>
        <span data-testid="custom-fallback">caught: {error.message}</span>
        <button type="button" onClick={reset}>
          retry
        </button>
      </div>
    ));
    render(
      <ErrorBoundary fallback={fallback}>
        <Bomb message="explicit" />
      </ErrorBoundary>,
    );
    expect(screen.getByTestId("custom-fallback")).toHaveTextContent("caught: explicit");
    expect(screen.queryByTestId("error-boundary-overlay")).not.toBeInTheDocument();
    expect(fallback).toHaveBeenCalled();
  });

  it('"Try again" clears the error and re-renders children once the subtree no longer throws', () => {
    // ``ToggleBomb`` throws on first mount but lets the test flip the
    // ``armed`` flag *before* the boundary's reset triggers a re-render.
    // That makes the recovery path observable without relying on
    // unsafe state mutation inside the assertion.
    const { rerender } = render(
      <ErrorBoundary>
        <ToggleBomb initial />
      </ErrorBoundary>,
    );
    expect(screen.getByTestId("error-boundary-overlay")).toBeInTheDocument();

    // Swap the subtree to a non-throwing version, then click "Try again":
    // the boundary clears ``state.error`` and renders the safe tree.
    rerender(
      <ErrorBoundary>
        <ToggleBomb initial={false} />
      </ErrorBoundary>,
    );
    fireEvent.click(screen.getByRole("button", { name: /Попробовать ещё раз/ }));
    expect(screen.queryByTestId("error-boundary-overlay")).not.toBeInTheDocument();
    expect(screen.getByTestId("safe")).toHaveTextContent("recovered");
  });

  it('"Reload" button calls window.location.reload', () => {
    const reload = vi.fn();
    const originalLocation = window.location;
    Object.defineProperty(window, "location", {
      configurable: true,
      value: { ...originalLocation, reload },
    });
    try {
      render(
        <ErrorBoundary>
          <Bomb />
        </ErrorBoundary>,
      );
      fireEvent.click(screen.getByRole("button", { name: /Перезагрузить/ }));
      expect(reload).toHaveBeenCalledTimes(1);
    } finally {
      Object.defineProperty(window, "location", {
        configurable: true,
        value: originalLocation,
      });
    }
  });
});
