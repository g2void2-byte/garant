import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { CurrencyDto, WalletBalanceDto, WalletDepositDto } from "@/api/types";

/**
 * Tests for the "Пополнение депозита" page (currency picker +
 * amount + CryptoBot invoice opener). Covers:
 *   - currency dropdown + auto-pick of first currency
 *   - validation of the amount input
 *   - successful invoice creation -> openTelegramLink + toast.success
 *   - error path -> toast.error + haptic('error')
 */

const mockState = vi.hoisted(() => ({
  currencies: undefined as CurrencyDto[] | undefined,
  currenciesLoading: false,
  balances: undefined as WalletBalanceDto[] | undefined,
  createMutation: {
    mutateAsync: vi.fn() as ReturnType<typeof vi.fn>,
    isPending: false,
  },
}));

vi.mock("@/api/hooks", () => ({
  useCurrencies: () => ({
    data: mockState.currencies,
    isLoading: mockState.currenciesLoading,
  }),
  useWalletBalances: () => ({ data: mockState.balances }),
  useCreateWalletDeposit: () => mockState.createMutation,
}));

const hapticSpy = vi.hoisted(() => vi.fn());
const openTelegramLinkSpy = vi.hoisted(() => vi.fn());
const openExternalLinkSpy = vi.hoisted(() => vi.fn());
vi.mock("@/lib/tg", () => ({
  haptic: hapticSpy,
  openTelegramLink: openTelegramLinkSpy,
  openExternalLink: openExternalLinkSpy,
  showBackButton: () => () => {},
}));

import WalletDepositPage from "./WalletDepositPage";

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <WalletDepositPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function makeCurrency(over: Partial<CurrencyDto> = {}): CurrencyDto {
  return {
    id: 1,
    code: "USD",
    name: "US Dollar",
    network: "",
    icon_url: "",
    decimals: 2,
    min_deposit: 5,
    min_withdraw: 1,
    kind: "fiat",
    ...over,
  };
}

function makeDeposit(over: Partial<WalletDepositDto> = {}): WalletDepositDto {
  return {
    id: 1,
    amount: 10,
    pay_url: "https://t.me/CryptoBot?start=invoice_abc",
    invoice_id: "INV-1",
    status: "pending",
    // Default to legacy ``"wallet"`` routing; trust-deposit tests
    // can override via ``over``.
    purpose: "wallet",
    provider: "cryptobot",
    created_at: "2026-01-01T00:00:00Z",
    paid_at: null,
    currency: makeCurrency(),
    ...over,
  };
}

beforeEach(() => {
  hapticSpy.mockClear();
  openTelegramLinkSpy.mockClear();
  openExternalLinkSpy.mockClear();
  mockState.currenciesLoading = false;
  mockState.currencies = [
    makeCurrency({ id: 1, code: "USD", name: "US Dollar" }),
    makeCurrency({ id: 2, code: "UAH", name: "Українська гривня", min_deposit: 50 }),
    // A leftover crypto row must be filtered out of the dropdown.
    makeCurrency({
      id: 3,
      code: "USDT",
      name: "Tether",
      network: "TRC20",
      kind: "crypto",
    }),
  ];
  mockState.balances = [];
  mockState.createMutation = {
    mutateAsync: vi.fn(),
    isPending: false,
  };
});

describe("<WalletDepositPage />", () => {
  it("renders the header and the submit button", () => {
    renderPage();
    expect(
      screen.getByRole("heading", { name: "Пополнение депозита" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /Пополнить депозит/ }),
    ).toBeInTheDocument();
  });

  it("auto-selects USD and seeds the amount from min_deposit", () => {
    renderPage();
    // The select reflects the USD fiat currency (default fallback).
    expect(screen.getByText(/US Dollar · USD/)).toBeInTheDocument();
    expect(screen.getByDisplayValue("5")).toBeInTheDocument();
  });

  it("shows the min-deposit hint for the selected currency", () => {
    renderPage();
    expect(screen.getByText(/Минимум: 5 USD/)).toBeInTheDocument();
  });

  it("hides crypto currencies from the dropdown", () => {
    renderPage();
    // Tether (kind='crypto') is filtered out; only fiat rows remain.
    expect(screen.queryByText(/Tether/)).not.toBeInTheDocument();
    expect(screen.getByText(/US Dollar · USD/)).toBeInTheDocument();
  });

  it("renders a loading skeleton while currencies are loading", () => {
    mockState.currenciesLoading = true;
    mockState.currencies = undefined;
    const { container } = renderPage();
    expect(container.querySelector(".shimmer")).not.toBeNull();
  });

  it("blocks submit + toasts an error when the amount is invalid (-1)", async () => {
    const user = userEvent.setup();
    renderPage();
    const amount = screen.getByDisplayValue("5") as HTMLInputElement;
    // ``fireEvent.change`` bypasses the useEffect that re-seeds the
    // amount to ``min_deposit`` whenever ``amount`` is empty.
    fireEvent.change(amount, { target: { value: "-1" } });
    await user.click(screen.getByRole("button", { name: /Пополнить депозит/ }));
    expect(mockState.createMutation.mutateAsync).not.toHaveBeenCalled();
    expect(hapticSpy).toHaveBeenCalledWith("error");
  });

  it("happy path: creates the deposit + opens the CryptoBot invoice URL", async () => {
    mockState.createMutation.mutateAsync.mockResolvedValue(
      makeDeposit({ pay_url: "https://t.me/CryptoBot?start=ok", amount: 10 }),
    );
    const user = userEvent.setup();
    renderPage();
    const amount = screen.getByDisplayValue("5") as HTMLInputElement;
    fireEvent.change(amount, { target: { value: "10" } });
    await user.click(screen.getByRole("button", { name: /Пополнить депозит/ }));

    await waitFor(() => {
      expect(mockState.createMutation.mutateAsync).toHaveBeenCalledWith({
        currency_code: "USD",
        amount: 10,
        provider: "cryptobot",
      });
    });
    expect(openTelegramLinkSpy).toHaveBeenCalledWith(
      "https://t.me/CryptoBot?start=ok",
    );
    expect(hapticSpy).toHaveBeenCalledWith("success");
  });

  it("submits provider='crystalpay' when the Crystalpay tile is selected", async () => {
    mockState.createMutation.mutateAsync.mockResolvedValue(
      makeDeposit({
        pay_url: "https://pay.crystalpay.io/cp-1",
        amount: 10,
        provider: "crystalpay",
      }),
    );
    const user = userEvent.setup();
    renderPage();
    await user.click(screen.getByTestId("provider-crystalpay"));
    const amount = screen.getByDisplayValue("5") as HTMLInputElement;
    fireEvent.change(amount, { target: { value: "10" } });
    await user.click(screen.getByRole("button", { name: /Пополнить депозит/ }));

    await waitFor(() => {
      expect(mockState.createMutation.mutateAsync).toHaveBeenCalledWith({
        currency_code: "USD",
        amount: 10,
        provider: "crystalpay",
      });
    });
    expect(openExternalLinkSpy).toHaveBeenCalledWith(
      "https://pay.crystalpay.io/cp-1",
    );
    expect(openTelegramLinkSpy).not.toHaveBeenCalled();
  });

  it("error path: surfaces server error via haptic('error')", async () => {
    mockState.createMutation.mutateAsync.mockRejectedValue(new Error("Минимум 5"));
    const user = userEvent.setup();
    renderPage();
    await user.click(screen.getByRole("button", { name: /Пополнить депозит/ }));
    await waitFor(() => {
      expect(hapticSpy).toHaveBeenCalledWith("error");
    });
    expect(openTelegramLinkSpy).not.toHaveBeenCalled();
    expect(openExternalLinkSpy).not.toHaveBeenCalled();
  });

  it("shows '...' while the mutation is pending and disables the button", () => {
    mockState.createMutation.isPending = true;
    renderPage();
    const btn = screen.getByRole("button", { name: /Создаю депозит/ });
    expect(btn).toBeDisabled();
  });
});
