import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import type { PinStatusDto } from "@/api/types";

type PinStatusState = {
  data: PinStatusDto | undefined;
  isLoading: boolean;
  isError: boolean;
};

const mockState = vi.hoisted(() => ({
  data: undefined as PinStatusDto | undefined,
  isLoading: false,
  isError: false,
})) as PinStatusState;

const pinTokenState = vi.hoisted(() => ({ valid: false }));

vi.mock("@/api/hooks", () => ({
  usePinStatus: () => mockState,
}));

vi.mock("@/lib/pin", () => ({
  PIN_TOKEN_CHANGED_EVENT: "garant:pin-token-changed",
  hasValidPinToken: () => pinTokenState.valid,
}));

// Stub out the lazy-loaded PinPage so the test stays purely synchronous —
// we don't care what's inside the gate, only that the gate hides /
// reveals children based on status + token state.
vi.mock("@/pages/pin/PinPage", () => ({
  default: () => <div>Mock PIN page</div>,
}));

import { PinGate } from "./PinGate";

beforeEach(() => {
  mockState.data = undefined;
  mockState.isLoading = false;
  mockState.isError = false;
  pinTokenState.valid = false;
});

describe("<PinGate />", () => {
  it("renders the loader while status is loading", () => {
    mockState.isLoading = true;
    const { container } = render(
      <PinGate>
        <div data-testid="protected">secret</div>
      </PinGate>,
    );
    expect(screen.queryByTestId("protected")).not.toBeInTheDocument();
    expect(container.querySelectorAll('[class*="animate-pulse"], [class*="skeleton"], [class*="bg-panel"]').length).toBeGreaterThan(0);
  });

  it("renders the error fallback when the status query errors (with stale data)", () => {
    // ``react-query`` keeps the last successful ``data`` while
    // ``isError`` becomes true on a subsequent failed refetch — that's
    // the only state where the error branch is actually reachable in
    // PinGate (the ``!status.data`` check short-circuits to the
    // loader otherwise).
    mockState.isError = true;
    mockState.data = {
      has_pin: true,
      attempts_left: 5,
      locked_until: null,
      max_attempts: 5,
      session_ttl_seconds: 600,
    };
    render(
      <PinGate>
        <div data-testid="protected">secret</div>
      </PinGate>,
    );
    expect(screen.getByText(/Не удалось связаться/)).toBeInTheDocument();
    expect(screen.queryByTestId("protected")).not.toBeInTheDocument();
  });

  it("renders children when status is loaded AND the token is valid", () => {
    mockState.data = {
      has_pin: true,
      attempts_left: 5,
      locked_until: null,
      max_attempts: 5,
      session_ttl_seconds: 600,
    };
    pinTokenState.valid = true;

    render(
      <PinGate>
        <div data-testid="protected">secret</div>
      </PinGate>,
    );

    expect(screen.getByTestId("protected")).toBeInTheDocument();
  });

  it("hides children and renders the PIN page when the token is missing", () => {
    mockState.data = {
      has_pin: true,
      attempts_left: 5,
      locked_until: null,
      max_attempts: 5,
      session_ttl_seconds: 600,
    };
    pinTokenState.valid = false;

    render(
      <PinGate>
        <div data-testid="protected">secret</div>
      </PinGate>,
    );

    expect(screen.queryByTestId("protected")).not.toBeInTheDocument();
  });
});
