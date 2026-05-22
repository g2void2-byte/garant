import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type {
  CurrencyDto,
  WalletBalanceDto,
  WalletDepositDto,
  WalletWithdrawalDto,
} from "@/api/types";

/**
 * Tests for the per-currency wallet page (``/wallet/:code``).
 *
 * The page has four states we exercise:
 *   1. Loading -> skeletons.
 *   2. Unsupported currency code -> "Валюта не поддерживается".
 *   3. Deposit tab (default) -> validates amount + calls
 *      ``useCreateWalletDeposit``.
 *   4. Withdraw tab -> ``useCreateWalletWithdrawal``.
 *   5. History tab -> renders a merged deposits+withdrawals list with
 *      status copy in Russian.
 */

const mockState = vi.hoisted(() => ({
  currencies: undefined as CurrencyDto[] | undefined,
  currenciesLoading: false,
  balances: undefined as WalletBalanceDto[] | undefined,
  balancesLoading: false,
  deposits: [] as WalletDepositDto[],
  depositsLoading: false,
  withdrawals: [] as WalletWithdrawalDto[],
  withdrawalsLoading: false,
  createDeposit: {
    mutateAsync: vi.fn() as ReturnType<typeof vi.fn>,
    isPending: false,
  },
  createWithdrawal: {
    mutateAsync: vi.fn() as ReturnType<typeof vi.fn>,
    isPending: false,
  },
}));

vi.mock("@/api/hooks", () => ({
  useCurrencies: () => ({
    data: mockState.currencies,
    isLoading: mockState.currenciesLoading,
  }),
  useWalletBalances: () => ({
    data: mockState.balances,
    isLoading: mockState.balancesLoading,
  }),
  useWalletDeposits: () => ({
    data: mockState.deposits,
    isLoading: mockState.depositsLoading,
  }),
  useWalletWithdrawals: () => ({
    data: mockState.withdrawals,
    isLoading: mockState.withdrawalsLoading,
  }),
  useCreateWalletDeposit: () => mockState.createDeposit,
  useCreateWalletWithdrawal: () => mockState.createWithdrawal,
}));

const hapticSpy = vi.hoisted(() => vi.fn());
const openTelegramLinkSpy = vi.hoisted(() => vi.fn());
vi.mock("@/lib/tg", () => ({
  haptic: hapticSpy,
  openTelegramLink: openTelegramLinkSpy,
  showBackButton: () => () => {},
}));

import WalletCurrencyPage from "./WalletCurrencyPage";

function renderPage(code = "USDT") {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[`/wallet/${code}`]}>
        <Routes>
          <Route path="/wallet/:code" element={<WalletCurrencyPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function makeCurrency(over: Partial<CurrencyDto> = {}): CurrencyDto {
  return {
    id: 1,
    code: "USDT",
    name: "Tether",
    network: "TRC20",
    icon_url: "",
    decimals: 2,
    min_deposit: 5,
    min_withdraw: 5,
    // Item 15 — keep the test fixtures on the fiat branch so the
    // page renders deposit/withdraw forms; the crypto branch is the
    // one we redirect to ``/wallet`` and is covered by its own
    // dedicated case below.
    kind: "fiat",
    ...over,
  };
}

function makeBalance(amount: number, locked = 0): WalletBalanceDto {
  return {
    currency: makeCurrency(),
    amount,
    locked,
    total: amount + locked,
    updated_at: null,
  };
}

beforeEach(() => {
  hapticSpy.mockClear();
  openTelegramLinkSpy.mockClear();
  mockState.currenciesLoading = false;
  mockState.balancesLoading = false;
  mockState.depositsLoading = false;
  mockState.withdrawalsLoading = false;
  mockState.currencies = [makeCurrency()];
  mockState.balances = [makeBalance(100)];
  mockState.deposits = [];
  mockState.withdrawals = [];
  mockState.createDeposit = { mutateAsync: vi.fn(), isPending: false };
  mockState.createWithdrawal = { mutateAsync: vi.fn(), isPending: false };
});

describe("<WalletCurrencyPage />", () => {
  it("renders the currency header + available balance", () => {
    renderPage("USDT");
    expect(
      screen.getByRole("heading", { name: "Tether" }),
    ).toBeInTheDocument();
    // Available balance: 100 USDT
    expect(screen.getByText(/100 USDT/)).toBeInTheDocument();
  });

  it("shows the 'locked' hint when balance has reserves", () => {
    mockState.balances = [makeBalance(50, 25)];
    renderPage("USDT");
    expect(screen.getByText(/в заявках:/)).toBeInTheDocument();
  });

  it("shows the loading skeleton while currencies / balances load", () => {
    mockState.currenciesLoading = true;
    const { container } = renderPage("USDT");
    expect(container.querySelector(".shimmer")).not.toBeNull();
  });

  it("shows 'Валюта не поддерживается' for an unknown code", () => {
    mockState.currencies = [makeCurrency({ code: "USDT" })];
    renderPage("DOGE");
    expect(screen.getByText("Валюта не поддерживается.")).toBeInTheDocument();
  });

  it("redirects crypto currencies to /wallet (Item 15)", () => {
    mockState.currencies = [makeCurrency({ code: "USDT", kind: "crypto" })];
    renderPage("USDT");
    // The Navigate replaces the route; rendered output should be
    // empty (no header, no balance copy).
    expect(
      screen.queryByRole("heading", { name: "Tether" }),
    ).not.toBeInTheDocument();
  });

  it("submits a deposit from the deposit tab", async () => {
    mockState.createDeposit.mutateAsync.mockResolvedValue({
      pay_url: "https://t.me/CryptoBot?start=abc",
      currency: makeCurrency(),
      amount: 20,
    });
    const user = userEvent.setup();
    renderPage("USDT");

    // The deposit form is mounted by default — its amount seed is
    // ``min_deposit`` (5).
    const amount = document.querySelector('input[type="number"]') as HTMLInputElement;
    fireEvent.change(amount, { target: { value: "20" } });
    await user.click(screen.getByRole("button", { name: /Пополнить через CryptoBot/ }));

    await waitFor(() => {
      expect(mockState.createDeposit.mutateAsync).toHaveBeenCalledWith({
        currency_code: "USDT",
        amount: 20,
      });
    });
    expect(openTelegramLinkSpy).toHaveBeenCalledWith(
      "https://t.me/CryptoBot?start=abc",
    );
    expect(hapticSpy).toHaveBeenCalledWith("success");
  });

  it("switches to the withdraw tab and submits a withdrawal", async () => {
    mockState.createWithdrawal.mutateAsync.mockResolvedValue({});
    const user = userEvent.setup();
    renderPage("USDT");
    await user.click(screen.getByRole("button", { name: /Вывести/ }));

    const amount = document.querySelector('input[type="number"]') as HTMLInputElement;
    fireEvent.change(amount, { target: { value: "10" } });
    const address = screen.getByPlaceholderText("Адрес USDT") as HTMLInputElement;
    fireEvent.change(address, { target: { value: "TX-addr" } });
    await user.click(screen.getByRole("button", { name: /Запросить вывод/ }));

    await waitFor(() => {
      expect(mockState.createWithdrawal.mutateAsync).toHaveBeenCalledWith({
        currency_code: "USDT",
        amount: 10,
        address: "TX-addr",
      });
    });
    expect(hapticSpy).toHaveBeenCalledWith("success");
  });

  it("withdraw 'Всё' button copies available balance into the amount", async () => {
    const user = userEvent.setup();
    renderPage("USDT");
    await user.click(screen.getByRole("button", { name: /Вывести/ }));
    await user.click(screen.getByRole("button", { name: "Всё" }));
    const amount = document.querySelector('input[type="number"]') as HTMLInputElement;
    expect(amount.value).toBe("100");
  });

  it("history tab merges deposits + withdrawals with Russian status text", async () => {
    mockState.deposits = [
      {
        id: 1,
        currency: makeCurrency(),
        amount: 50,
        status: "paid",
        pay_url: "",
        invoice_id: "I1",
        purpose: "wallet",
        provider: "cryptobot",
        created_at: "2026-01-02T00:00:00Z",
        paid_at: "2026-01-02T01:00:00Z",
      },
      {
        id: 2,
        currency: makeCurrency(),
        amount: 7,
        status: "pending",
        pay_url: "https://t.me/CryptoBot?start=pending",
        invoice_id: "I2",
        purpose: "wallet",
        provider: "crystalpay",
        created_at: "2026-01-03T00:00:00Z",
        paid_at: null,
      },
    ];
    mockState.withdrawals = [
      {
        id: 9,
        currency: makeCurrency(),
        amount: 30,
        address: "TX-1",
        status: "approved",
        admin_note: "",
        created_at: "2026-01-01T00:00:00Z",
        processed_at: null,
      },
    ];
    const user = userEvent.setup();
    renderPage("USDT");
    await user.click(screen.getByRole("button", { name: /История/ }));

    expect(screen.getAllByText("Пополнение")).toHaveLength(2);
    expect(screen.getByText("Вывод")).toBeInTheDocument();
    expect(screen.getByText("Зачислено")).toBeInTheDocument();
    expect(screen.getByText(/Одобрена/)).toBeInTheDocument();
  });

  it("history tab shows empty-state when no rows", async () => {
    const user = userEvent.setup();
    renderPage("USDT");
    await user.click(screen.getByRole("button", { name: /История/ }));
    expect(screen.getByText("Операций пока нет")).toBeInTheDocument();
  });
});
