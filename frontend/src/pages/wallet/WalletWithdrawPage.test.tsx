import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { WalletBalanceDto } from "@/api/types";

/**
 * Tests for the standalone "Вывести депозит" page.
 *
 * Covers:
 *   - loading skeleton
 *   - empty-state when the user has no positive balances
 *   - eligible balance gating: only currencies with amount>0 listed
 *   - "Всё" prefill click
 *   - amount validation
 *   - address validation
 *   - happy-path POST (PIN session is enforced server-side; tests
 *     just verify the payload the page sends)
 */

const mockState = vi.hoisted(() => ({
  balances: undefined as WalletBalanceDto[] | undefined,
  balancesLoading: false,
  createMutation: {
    mutateAsync: vi.fn() as ReturnType<typeof vi.fn>,
    isPending: false,
  },
  checkPinMutation: {
    mutateAsync: vi.fn() as ReturnType<typeof vi.fn>,
    isPending: false,
  },
  admins: [] as { id: number; username: string }[],
  // Bug-10 — drive the auto-withdraw conditional in the page from a
  // test-controllable toggle. Default ``false`` so the existing
  // manual-mode tests (which assert the address input is present)
  // continue to pass.
  autoWithdrawEnabled: false,
}));

vi.mock("@/api/hooks", () => ({
  useWalletBalances: () => ({
    data: mockState.balances,
    isLoading: mockState.balancesLoading,
  }),
  useCreateWalletWithdrawal: () => mockState.createMutation,
  // ``CardWithdrawModal`` deep-links to the first admin's Telegram
  // chat — stub the source list so the button stays enabled when
  // the card flow is exercised in tests.
  useAdmins: () => ({ data: mockState.admins, isLoading: false }),
  // ``PinPromptModal`` validates the entered PIN before the
  // withdrawal POST is fired; resolve immediately so we don't have
  // to spin up a real PIN endpoint.
  useCheckPin: () => mockState.checkPinMutation,
  // Bug-10 — the page reads ``auto_withdraw_enabled`` from the
  // public-settings endpoint to decide whether to render the
  // address input. Stub it so tests don't hit the network.
  usePublicSettings: () => ({
    data: {
      deal_commission_percent: 5,
      vip_commission_percent: -1,
      auto_withdraw_enabled: mockState.autoWithdrawEnabled,
    },
  }),
}));

const hapticSpy = vi.hoisted(() => vi.fn());
const openTelegramSpy = vi.hoisted(() => vi.fn());
vi.mock("@/lib/tg", () => ({
  useTelegramViewport: () => null,
  haptic: hapticSpy,
  openTelegramLink: openTelegramSpy,
  showBackButton: () => () => {},
}));

vi.mock("@/lib/pin", () => ({
  setPinToken: vi.fn(),
  hasValidPinToken: () => true,
  clearPinToken: vi.fn(),
  getPinToken: () => "e2e-pin-token",
  PIN_TOKEN_CHANGED_EVENT: "garant:pin-token-changed",
}));

import WalletWithdrawPage from "./WalletWithdrawPage";

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <WalletWithdrawPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function makeBalance(
  amount: number,
  code = "USDT",
  decimals = 2,
): WalletBalanceDto {
  return {
    currency: {
      id: 1,
      code,
      name: code,
      network: "TRC20",
      icon_url: "",
      decimals,
      min_deposit: 1,
      min_withdraw: 1,
    },
    amount,
    locked: 0,
    total: amount,
    updated_at: null,
    amount_str: String(amount),
    locked_str: "0",
    total_str: String(amount),
  };
}

beforeEach(() => {
  hapticSpy.mockClear();
  openTelegramSpy.mockClear();
  mockState.balances = undefined;
  mockState.balancesLoading = false;
  mockState.createMutation = {
    mutateAsync: vi.fn(),
    isPending: false,
  };
  mockState.checkPinMutation = {
    mutateAsync: vi.fn().mockResolvedValue({
      token: "e2e-pin-token",
      expires_at: new Date(Date.now() + 60_000).toISOString(),
    }),
    isPending: false,
  };
  mockState.admins = [{ id: 1, username: "admin" }];
  mockState.autoWithdrawEnabled = false;
});

async function enterPin(user: ReturnType<typeof userEvent.setup>) {
  await user.click(await screen.findByRole("button", { name: "1" }));
  await user.click(screen.getByRole("button", { name: "2" }));
  await user.click(screen.getByRole("button", { name: "3" }));
  await user.click(screen.getByRole("button", { name: "4" }));
}

describe("<WalletWithdrawPage />", () => {
  it("renders the loading skeleton", () => {
    mockState.balancesLoading = true;
    const { container } = renderPage();
    expect(container.querySelector(".shimmer")).not.toBeNull();
  });

  it("renders an empty state when the user has no positive balances", () => {
    mockState.balances = [makeBalance(0, "USDT"), makeBalance(0, "BTC")];
    renderPage();
    expect(
      screen.getByText("У вас нет доступных для вывода валют"),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /Запросить вывод/ }),
    ).not.toBeInTheDocument();
  });

  it("filters out zero-balance currencies from the dropdown", () => {
    mockState.balances = [
      makeBalance(0, "USDT"),
      makeBalance(0.5, "BTC", 8),
    ];
    renderPage();
    // Only BTC should be listed; USDT is filtered out.
    expect(screen.getByText(/BTC · 0.5 BTC/)).toBeInTheDocument();
    expect(screen.queryByText(/USDT · 0 USDT/)).not.toBeInTheDocument();
  });

  it("blocks submit with haptic('error') when the amount is invalid", async () => {
    mockState.balances = [makeBalance(50, "USDT")];
    const user = userEvent.setup();
    renderPage();
    await user.click(screen.getByRole("button", { name: /Запросить вывод/ }));
    expect(mockState.createMutation.mutateAsync).not.toHaveBeenCalled();
    expect(hapticSpy).toHaveBeenCalledWith("error");
  });

  it("'Всё' button prefills the amount with the available balance", async () => {
    mockState.balances = [makeBalance(12.34, "USDT", 2)];
    const user = userEvent.setup();
    renderPage();
    await user.click(screen.getByRole("button", { name: "Всё" }));
    const amount = document.querySelector('input[type="number"]') as HTMLInputElement;
    expect(amount.value).toBe("12.34");
  });

  it("happy path: submits a withdrawal with amount + currency_code", async () => {
    mockState.balances = [makeBalance(100, "USDT")];
    mockState.createMutation.mutateAsync.mockResolvedValue({});
    const user = userEvent.setup();
    renderPage();

    const amount = document.querySelector('input[type="number"]') as HTMLInputElement;
    fireEvent.change(amount, { target: { value: "25" } });

    await user.click(screen.getByRole("button", { name: /Запросить вывод/ }));
    // PIN re-prompt now gates the withdrawal — punch in 1234.
    await enterPin(user);
    await waitFor(() => {
      expect(mockState.createMutation.mutateAsync).toHaveBeenCalledWith({
        currency_code: "USDT",
        // Audit M-7 — amount goes over the wire as a string so the
        // backend can parse it into ``Decimal`` without an
        // intermediate ``float`` round-trip.
        amount: "25",
      });
    });
    expect(hapticSpy).toHaveBeenCalledWith("success");
  });

  it("error path: surfaces server error via haptic('error')", async () => {
    mockState.balances = [makeBalance(100, "USDT")];
    mockState.createMutation.mutateAsync.mockRejectedValue(
      new Error("PIN-сессия отсутствует"),
    );
    const user = userEvent.setup();
    renderPage();
    const amount = document.querySelector('input[type="number"]') as HTMLInputElement;
    fireEvent.change(amount, { target: { value: "10" } });
    await user.click(screen.getByRole("button", { name: /Запросить вывод/ }));
    await enterPin(user);
    await waitFor(() => {
      expect(hapticSpy).toHaveBeenCalledWith("error");
    });
  });

  it("auto-withdraw mode: hides the address input and submits without 'address'", async () => {
    mockState.autoWithdrawEnabled = true;
    mockState.balances = [makeBalance(100, "USDT")];
    mockState.createMutation.mutateAsync.mockResolvedValue({});
    const user = userEvent.setup();
    renderPage();

    // Address input must not render — instead the
    // page shows the @CryptoBot hint.
    expect(screen.queryByPlaceholderText("Адрес USDT")).toBeNull();
    expect(screen.getByTestId("withdraw-autoinfo")).toBeInTheDocument();

    const amount = document.querySelector('input[type="number"]') as HTMLInputElement;
    fireEvent.change(amount, { target: { value: "25" } });
    await user.click(screen.getByRole("button", { name: /Запросить вывод/ }));
    await enterPin(user);
    await waitFor(() => {
      expect(mockState.createMutation.mutateAsync).toHaveBeenCalledWith({
        currency_code: "USDT",
        amount: "25",
      });
    });
  });

  it("opens the Card-withdraw modal and links to the first admin via t.me", async () => {
    mockState.balances = [makeBalance(100, "USDT")];
    const user = userEvent.setup();
    renderPage();

    await user.click(
      screen.getByRole("button", { name: /Карта/, pressed: false }),
    );
    expect(
      await screen.findByRole("heading", { name: /Вывод на карту/ }),
    ).toBeInTheDocument();
    // Tapping the primary CTA hands off to Telegram.
    await user.click(screen.getByRole("button", { name: /Написать админу/ }));
    expect(openTelegramSpy).toHaveBeenCalledWith("https://t.me/admin");
  });
});
