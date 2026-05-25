import { describe, expect, it, vi, beforeEach } from "vitest";
import { act, render, screen, waitFor } from "@testing-library/react";
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

const pinTokenState = vi.hoisted(() => ({ valid: false, cleared: 0 }));

vi.mock("@/api/hooks", () => ({
  usePinStatus: () => mockState,
}));

vi.mock("@/lib/pin", () => ({
  PIN_TOKEN_CHANGED_EVENT: "garant:pin-token-changed",
  hasValidPinToken: () => pinTokenState.valid,
  // Mock matches the real ``clearPinToken`` contract: it wipes the
  // local cache, flips ``hasValidPinToken``'s read-through to
  // ``false``, AND dispatches the ``garant:pin-token-changed`` event
  // that the existing ``PinGate`` listener re-syncs ``unlocked``
  // against. The counter is what the new item-8 test asserts on.
  clearPinToken: () => {
    pinTokenState.cleared += 1;
    pinTokenState.valid = false;
    try {
      window.dispatchEvent(new Event("garant:pin-token-changed"));
    } catch {
      /* DOM unavailable */
    }
  },
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
  pinTokenState.cleared = 0;
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

  it("hides children and renders the PIN page when the token is missing", async () => {
    mockState.data = {
      has_pin: true,
      attempts_left: 5,
      locked_until: null,
      max_attempts: 5,
      session_ttl_seconds: 600,
    };
    pinTokenState.valid = false;

    await act(async () => {
      render(
        <PinGate>
          <div data-testid="protected">secret</div>
        </PinGate>,
      );
    });

    await waitFor(() => {
      expect(screen.getByText("Mock PIN page")).toBeInTheDocument();
    });
    expect(screen.queryByTestId("protected")).not.toBeInTheDocument();
  });

  it("force-clears the local PIN token when status reports has_pin=false (item 8)", async () => {
    // This is the safety-net path: the server already wiped
    // ``pin_hash`` (admin pressed "reset PIN") but the device still
    // holds a non-expired JWT. ``usePinStatus`` refetches on focus
    // and surfaces ``has_pin: false`` — the gate must call
    // ``clearPinToken()`` so children stop rendering and the user
    // lands on the new-PIN setup flow.
    mockState.data = {
      has_pin: false,
      attempts_left: 5,
      locked_until: null,
      max_attempts: 5,
      session_ttl_seconds: 600,
    };
    pinTokenState.valid = true;

    await act(async () => {
      render(
        <PinGate>
          <div data-testid="protected">secret</div>
        </PinGate>,
      );
    });

    await waitFor(() => {
      expect(pinTokenState.cleared).toBe(1);
    });
    // After the effect runs, the gate should be showing PinPage —
    // the mock ``clearPinToken`` dispatches the real
    // ``garant:pin-token-changed`` event that the existing
    // ``PinGate`` listener re-syncs ``unlocked`` against.
    await waitFor(() => {
      expect(screen.queryByText("Mock PIN page")).toBeInTheDocument();
    });
    expect(screen.queryByTestId("protected")).not.toBeInTheDocument();
  });

  it("does not call clearPinToken when has_pin is true (item 8 guard)", async () => {
    // Inverse of the previous test: a healthy session must NOT be
    // torn down. A naive ``if (!status.data.has_pin) clear()``
    // implementation would log a happy-path user out on every focus
    // refetch because of the ``undefined`` → ``true`` transition.
    mockState.data = {
      has_pin: true,
      attempts_left: 5,
      locked_until: null,
      max_attempts: 5,
      session_ttl_seconds: 600,
    };
    pinTokenState.valid = true;

    await act(async () => {
      render(
        <PinGate>
          <div data-testid="protected">secret</div>
        </PinGate>,
      );
    });

    expect(pinTokenState.cleared).toBe(0);
    expect(screen.getByTestId("protected")).toBeInTheDocument();
  });
});
