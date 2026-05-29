import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { PinStatusDto, PinTokenDto } from "@/api/types";

/**
 * Tests for the gating `PinPage`.
 *
 * Covers four state-machine paths:
 *   1. check  — existing PIN: correct/incorrect/locked, attempts_left
 *   2. setup_first → setup_confirm → setupPin mutation
 *   3. setup_confirm mismatch → roll back to setup_first
 *   4. reset_code → reset_new → reset_new_confirm → confirmReset
 *
 * Mocks `@/api/hooks` PIN-related mutations, `setPinToken` and toasts.
 */

const mockState = vi.hoisted(() => ({
  setup: {
    mutateAsync: vi.fn() as ReturnType<typeof vi.fn>,
    isPending: false,
  },
  check: {
    mutateAsync: vi.fn() as ReturnType<typeof vi.fn>,
    isPending: false,
  },
  requestReset: {
    mutateAsync: vi.fn() as ReturnType<typeof vi.fn>,
    isPending: false,
  },
  confirmReset: {
    mutateAsync: vi.fn() as ReturnType<typeof vi.fn>,
    isPending: false,
  },
}));

vi.mock("@/api/hooks", () => ({
  useSetupPin: () => mockState.setup,
  useCheckPin: () => mockState.check,
  useRequestPinReset: () => mockState.requestReset,
  useConfirmPinReset: () => mockState.confirmReset,
  // PinResetPaywallModal (imported by PinPage) uses useAdmins to
  // decide which Telegram username to DM. Stub it out so the modal
  // can render in tests without hitting the network.
  useAdmins: () => ({ data: [], isLoading: false }),
}));

const setPinTokenSpy = vi.hoisted(() => vi.fn());
vi.mock("@/lib/pin", () => ({
  setPinToken: setPinTokenSpy,
}));

const toastSpy = vi.hoisted(() => vi.fn());
vi.mock("@/components/ui/Toast", () => ({
  useToast: () => ({ show: toastSpy }),
}));

vi.mock("@/lib/tg", () => ({
  useTelegramViewport: () => null,
  haptic: () => {},
}));

import PinPage from "./PinPage";

function renderPage(
  status: Partial<PinStatusDto>,
  onUnlocked: () => void = () => {},
) {
  const full: PinStatusDto = {
    has_pin: true,
    attempts_left: 5,
    locked_until: null,
    max_attempts: 5,
    session_ttl_seconds: 300,
    ...status,
  };
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <PinPage status={full} onUnlocked={onUnlocked} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

async function typePin(user: ReturnType<typeof userEvent.setup>, digits: string) {
  for (const d of digits) {
    await user.click(screen.getByRole("button", { name: d }));
  }
}

beforeEach(() => {
  mockState.setup = { mutateAsync: vi.fn(), isPending: false };
  mockState.check = { mutateAsync: vi.fn(), isPending: false };
  mockState.requestReset = { mutateAsync: vi.fn(), isPending: false };
  mockState.confirmReset = { mutateAsync: vi.fn(), isPending: false };
  setPinTokenSpy.mockClear();
  toastSpy.mockClear();
});

describe("<PinPage />", () => {
  it("renders 'Введите PIN-код' heading when has_pin=true", () => {
    renderPage({ has_pin: true });
    expect(screen.getByText("Введите PIN-код")).toBeInTheDocument();
    expect(screen.getByText(/Осталось попыток: 5/)).toBeInTheDocument();
  });

  it("renders setup subtitle when has_pin=false (setup_first mode)", () => {
    renderPage({ has_pin: false });
    expect(screen.getByText("Введите PIN-код")).toBeInTheDocument();
    expect(screen.getByText(/Придумайте 4 цифры/)).toBeInTheDocument();
  });

  it("check happy path: 4 digits → checkPin → setPinToken + onUnlocked", async () => {
    const onUnlocked = vi.fn();
    const token: PinTokenDto = {
      token: "tok-xyz",
      expires_at: "2026-01-01T00:00:00Z",
    };
    mockState.check.mutateAsync.mockResolvedValue(token);
    const user = userEvent.setup();
    renderPage({ has_pin: true }, onUnlocked);
    await typePin(user, "1234");
    await waitFor(() =>
      expect(mockState.check.mutateAsync).toHaveBeenCalledWith("1234"),
    );
    expect(setPinTokenSpy).toHaveBeenCalledWith(
      "tok-xyz",
      "2026-01-01T00:00:00Z",
    );
    expect(onUnlocked).toHaveBeenCalled();
  });

  it("check failure shows error toast and clears the pin", async () => {
    mockState.check.mutateAsync.mockRejectedValue(new Error("Неверный PIN"));
    const user = userEvent.setup();
    renderPage({ has_pin: true });
    await typePin(user, "0000");
    await waitFor(() =>
      expect(toastSpy).toHaveBeenCalledWith(
        expect.objectContaining({ kind: "error", title: "Неверный PIN" }),
      ),
    );
  });

  it("renders locked banner when locked_until is in the future", () => {
    const future = new Date(Date.now() + 5 * 60_000).toISOString();
    renderPage({ has_pin: true, locked_until: future });
    expect(screen.getByText(/Слишком много попыток/)).toBeInTheDocument();
  });

  it("setup_first → setup_confirm flow: typing two matching PINs calls setupPin", async () => {
    const token: PinTokenDto = {
      token: "tok-new",
      expires_at: "2026-01-02T00:00:00Z",
    };
    mockState.setup.mutateAsync.mockResolvedValue(token);
    const onUnlocked = vi.fn();
    const user = userEvent.setup();
    renderPage({ has_pin: false }, onUnlocked);
    await typePin(user, "1357");
    expect(
      await screen.findByText("Подтвердите PIN-код"),
    ).toBeInTheDocument();
    await typePin(user, "1357");
    await waitFor(() =>
      expect(mockState.setup.mutateAsync).toHaveBeenCalledWith("1357"),
    );
    expect(setPinTokenSpy).toHaveBeenCalledWith(
      "tok-new",
      "2026-01-02T00:00:00Z",
    );
    expect(onUnlocked).toHaveBeenCalled();
  });

  it("setup_confirm mismatch shows toast and rolls back to setup_first", async () => {
    const user = userEvent.setup();
    renderPage({ has_pin: false });
    await typePin(user, "1111");
    await typePin(user, "2222");
    await waitFor(() =>
      expect(toastSpy).toHaveBeenCalledWith(
        expect.objectContaining({
          kind: "error",
          title: expect.stringContaining("PIN не совпадает"),
        }),
      ),
    );
    expect(screen.getByText(/Придумайте 4 цифры/)).toBeInTheDocument();
    expect(mockState.setup.mutateAsync).not.toHaveBeenCalled();
  });

  it("'Забыли PIN?' click opens the paid-reset paywall modal", async () => {
    // V14 — the "Забыли PIN?" button no longer calls /reset/request
    // directly. It opens the ``PinResetPaywallModal`` which shows
    // the admin-configured price and, on payment, sends the 6-digit
    // code via Telegram. The legacy flow (instant DM, no charge) was
    // removed in favour of this paywall — covered separately by the
    // paywall's own integration tests.
    const user = userEvent.setup();
    renderPage({ has_pin: true });
    await user.click(screen.getByRole("button", { name: /Забыли PIN/ }));
    // The paywall renders via React portal — assert by its test id.
    expect(
      await screen.findByTestId("pin-reset-paywall"),
    ).toBeInTheDocument();
    expect(mockState.requestReset.mutateAsync).not.toHaveBeenCalled();
  });
});
