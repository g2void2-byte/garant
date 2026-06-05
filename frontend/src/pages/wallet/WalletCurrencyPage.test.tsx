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
  lastDepositsParams: undefined as unknown,
  lastDepositsOptions: undefined as unknown,
  lastWithdrawalsParams: undefined as unknown,
  lastWithdrawalsOptions: undefined as unknown,
  createDeposit: {
    mutateAsync: vi.fn() as ReturnType<typeof vi.fn>,
    isPending: false,
  },
  createWithdrawal: {
    mutateAsync: vi.fn() as ReturnType<typeof vi.fn>,
    isPending: false,
  },
}));

const apiGetMock = vi.hoisted(() => vi.fn());

vi.mock("@/api/client", () => ({
  api: { get: apiGetMock },
}));

vi.mock("@/api/hooks", () => ({
  buildWalletHistorySearchParams: (params: {
    currency?: string;
    limit?: number;
    offset?: number;
  }) => {
    const searchParams: Record<string, string> = {};
    if (params.currency) searchParams.currency = params.currency;
    if (params.limit !== undefined) searchParams.limit = String(params.limit);
    if (params.offset !== undefined) searchParams.offset = String(params.offset);
    return searchParams;
  },
  useCurrencies: () => ({
    data: mockState.currencies,
    isLoading: mockState.currenciesLoading,
  }),
  useWalletBalances: () => ({
    data: mockState.balances,
    isLoading: mockState.balancesLoading,
  }),
  useWalletDeposits: (params: unknown, options: unknown) => {
    mockState.lastDepositsParams = params;
    mockState.lastDepositsOptions = options;
    return {
      data: mockState.deposits,
      isLoading: mockState.depositsLoading,
    };
  },
  useWalletWithdrawals: (params: unknown, options: unknown) => {
    mockState.lastWithdrawalsParams = params;
    mockState.lastWithdrawalsOptions = options;
    return {
      data: mockState.withdrawals,
      isLoading: mockState.withdrawalsLoading,
    };
  },
  useCreateWalletDeposit: () => mockState.createDeposit,
  useCreateWalletWithdrawal: () => mockState.createWithdrawal,
}));

const hapticSpy = vi.hoisted(() => vi.fn());
const openTelegramLinkSpy = vi.hoisted(() => vi.fn());
vi.mock("@/lib/tg", () => ({
  useTelegramViewport: () => null,
  haptic: hapticSpy,
  openTelegramLink: openTelegramLinkSpy,
  openPaymentLink: (url: string) => {
    if (url.startsWith("https://t.me/")) {
      openTelegramLinkSpy(url);
    }
  },
  showBackButton: () => () => {},
}));

const toastSpy = vi.hoisted(() => vi.fn());
vi.mock("@/components/ui/Toast", () => ({
  useToast: () => ({ show: toastSpy }),
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
    amount_str: String(amount),
    locked_str: String(locked),
    total_str: String(amount + locked),
  };
}

function makeDeposit(id: number, over: Partial<WalletDepositDto> = {}): WalletDepositDto {
  return {
    id,
    currency: makeCurrency(),
    amount: id,
    status: "paid",
    pay_url: "",
    invoice_id: `I${id}`,
    purpose: "wallet",
    provider: "cryptobot",
    created_at: `2026-01-${String(Math.min(id, 28)).padStart(2, "0")}T00:00:00Z`,
    paid_at: null,
    ...over,
  };
}

function makeWithdrawal(id: number, over: Partial<WalletWithdrawalDto> = {}): WalletWithdrawalDto {
  return {
    id,
    currency: makeCurrency(),
    amount: id,
    address: "TX-1",
    status: "approved",
    admin_note: "",
    created_at: `2026-02-${String(Math.min(id, 28)).padStart(2, "0")}T00:00:00Z`,
    processed_at: null,
    ...over,
  };
}

beforeEach(() => {
  hapticSpy.mockClear();
  openTelegramLinkSpy.mockClear();
  toastSpy.mockClear();
  apiGetMock.mockReset();
  mockState.currenciesLoading = false;
  mockState.balancesLoading = false;
  mockState.depositsLoading = false;
  mockState.withdrawalsLoading = false;
  mockState.lastDepositsParams = undefined;
  mockState.lastDepositsOptions = undefined;
  mockState.lastWithdrawalsParams = undefined;
  mockState.lastWithdrawalsOptions = undefined;
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

  it("normalizes route-matched currency DTO codes before deposit display and submit", async () => {
    mockState.currencies = [makeCurrency({ code: " usdt " })];
    mockState.createDeposit.mutateAsync.mockResolvedValue({
      pay_url: "",
      currency: makeCurrency({ code: " usdt " }),
      amount: 20,
    });
    const user = userEvent.setup();
    renderPage("USDT");

    expect(screen.getByText(/100 USDT/)).toBeInTheDocument();
    expect(document.body.textContent).not.toContain(" usdt ");

    const amount = document.querySelector('input[type="number"]') as HTMLInputElement;
    fireEvent.change(amount, { target: { value: "20" } });
    await user.click(screen.getByRole("button", { name: /CryptoBot/ }));

    await waitFor(() => {
      expect(mockState.createDeposit.mutateAsync).toHaveBeenCalledWith({
        currency_code: "USDT",
        amount: "20",
      });
    });
    await waitFor(() => {
      expect(toastSpy).toHaveBeenCalledWith(
        expect.objectContaining({
          kind: "success",
          body: expect.stringContaining("20 USDT"),
        }),
      );
    });
    const successToast = toastSpy.mock.calls.find(([toast]) => toast.kind === "success")?.[0];
    expect(successToast?.body).not.toContain(" usdt ");
  });

  it("renders malformed available balance strings as neutral", () => {
    const malformed = makeBalance(100);
    malformed.amount = "1e2" as unknown as number;
    malformed.amount_str = "1e2";
    mockState.balances = [malformed];

    renderPage("USDT");

    expect(screen.getByText("\u2014 USDT")).toBeInTheDocument();
    expect(screen.queryByText(/^0 USDT$/)).not.toBeInTheDocument();
    expect(screen.queryByText(/1e2/)).not.toBeInTheDocument();
  });

  it("shows the 'locked' hint when balance has reserves", () => {
    mockState.balances = [makeBalance(50, 25)];
    renderPage("USDT");
    expect(screen.getByText(/в заявках:/)).toBeInTheDocument();
  });

  it("renders locked hints from numeric fallback when the string mirror is blank", () => {
    const balance = makeBalance(50, 25);
    balance.locked_str = "";
    mockState.balances = [balance];

    renderPage("USDT");

    expect(screen.getByText(/25 USDT/)).toBeInTheDocument();
    expect(screen.queryByText(/^0 USDT$/)).not.toBeInTheDocument();
  });

  it("does not show the locked hint for malformed runtime locked values", () => {
    const malformed = makeBalance(50, 25);
    malformed.locked = "1e1" as unknown as number;
    malformed.locked_str = "1e1";
    mockState.balances = [malformed];

    renderPage("USDT");

    expect(screen.queryByText(/РІ Р·Р°СЏРІРєР°С…:/)).not.toBeInTheDocument();
  });

  it("shows the loading skeleton while currencies / balances load", () => {
    mockState.currenciesLoading = true;
    const { container } = renderPage("USDT");
    expect(container.querySelector(".shimmer")).not.toBeNull();
  });

  it("shows 'Валюта не поддерживается' for an unknown code", () => {
    mockState.currencies = [makeCurrency({ code: "USDT" })];
    renderPage("DOGE");
    expect(mockState.lastDepositsOptions).toEqual({ enabled: false });
    expect(mockState.lastWithdrawalsOptions).toEqual({ enabled: false });
    expect(screen.getByText("Валюта не поддерживается.")).toBeInTheDocument();
  });

  it("does not enable wallet history queries for malformed route currency codes", () => {
    renderPage("USD!x");
    expect(mockState.lastDepositsOptions).toEqual({ enabled: false });
    expect(mockState.lastWithdrawalsOptions).toEqual({ enabled: false });
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
        amount: "20",
      });
    });
    expect(openTelegramLinkSpy).toHaveBeenCalledWith(
      "https://t.me/CryptoBot?start=abc",
    );
    expect(hapticSpy).toHaveBeenCalledWith("success");
  });

  it("does not open the deposit pay link when the create response amount is malformed", async () => {
    mockState.createDeposit.mutateAsync.mockResolvedValue({
      pay_url: "https://t.me/CryptoBot?start=bad-amount",
      currency: makeCurrency(),
      amount: "1e2" as unknown as number,
    });
    const user = userEvent.setup();
    renderPage("USDT");

    const amount = document.querySelector('input[type="number"]') as HTMLInputElement;
    fireEvent.change(amount, { target: { value: "20" } });
    await user.click(screen.getByRole("button", {
      name: /\u041f\u043e\u043f\u043e\u043b\u043d\u0438\u0442\u044c \u0447\u0435\u0440\u0435\u0437 CryptoBot/,
    }));

    await waitFor(() => {
      expect(mockState.createDeposit.mutateAsync).toHaveBeenCalled();
    });
    expect(openTelegramLinkSpy).not.toHaveBeenCalled();
  });

  it("does not render the legacy per-currency withdrawal tab", () => {
    renderPage("USDT");
    expect(screen.queryByRole("button", { name: /Вывести/ })).not.toBeInTheDocument();
    expect(mockState.createWithdrawal.mutateAsync).not.toHaveBeenCalled();
  });

  it("requests the first currency-scoped history page", () => {
    renderPage("usdt");
    expect(mockState.lastDepositsParams).toEqual({
      currency: "USDT",
      limit: 50,
      offset: 0,
    });
    expect(mockState.lastDepositsOptions).toEqual({ enabled: true });
    expect(mockState.lastWithdrawalsParams).toEqual({
      currency: "USDT",
      limit: 50,
      offset: 0,
    });
    expect(mockState.lastWithdrawalsOptions).toEqual({ enabled: true });
  });

  it("loads more currency history with backend offsets", async () => {
    mockState.deposits = Array.from({ length: 50 }, (_, idx) => makeDeposit(idx + 1));
    mockState.withdrawals = Array.from({ length: 50 }, (_, idx) => makeWithdrawal(idx + 1));
    apiGetMock.mockImplementation((url: string) => ({
      json: async () =>
        url === "api/wallet/deposits" ? [makeDeposit(101)] : [makeWithdrawal(101)],
    }));

    const user = userEvent.setup();
    renderPage("USDT");
    await user.click(screen.getByRole("button", { name: /История/ }));
    await user.click(screen.getByRole("button", { name: "Показать еще" }));

    await waitFor(() => expect(apiGetMock).toHaveBeenCalledTimes(2));
    expect(apiGetMock).toHaveBeenCalledWith("api/wallet/deposits", {
      searchParams: { currency: "USDT", limit: "50", offset: "50" },
    });
    expect(apiGetMock).toHaveBeenCalledWith("api/wallet/withdrawals", {
      searchParams: { currency: "USDT", limit: "50", offset: "50" },
    });
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
      {
        id: 3,
        currency: makeCurrency(),
        amount: 5,
        status: "refunded",
        pay_url: "",
        invoice_id: "I3",
        purpose: "wallet",
        provider: "cryptobot",
        created_at: "2026-01-04T00:00:00Z",
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

    expect(screen.getAllByText("Пополнение")).toHaveLength(3);
    expect(screen.getByText("Вывод")).toBeInTheDocument();
    expect(screen.getByText("Зачислено")).toBeInTheDocument();
    expect(screen.getByText("Возврат")).toBeInTheDocument();
    expect(screen.getByText(/Одобрена/)).toBeInTheDocument();
  });

  it("history tab renders unknown runtime statuses as neutral labels", async () => {
    mockState.deposits = [
      makeDeposit(1, { status: "provider_reconciled" }),
    ];
    mockState.withdrawals = [
      makeWithdrawal(2, { status: "provider_reconciled", admin_note: "" }),
    ];
    const user = userEvent.setup();
    renderPage("USDT");
    await user.click(screen.getByRole("button", {
      name: /\u0418\u0441\u0442\u043e\u0440\u0438\u044f/,
    }));

    expect(screen.getAllByText("Статус неизвестен")).toHaveLength(2);
    expect(screen.queryByText(/provider_reconciled/)).not.toBeInTheDocument();
  });

  it("history tab renders malformed operation amounts as neutral", async () => {
    mockState.deposits = [
      makeDeposit(1, {
        amount: "1e2" as unknown as number,
        pay_url: "https://t.me/CryptoBot?start=bad-history",
      }),
    ];
    mockState.withdrawals = [
      makeWithdrawal(2, { amount: "0x10" as unknown as number }),
    ];
    const user = userEvent.setup();
    renderPage("USDT");
    await user.click(screen.getByRole("button", {
      name: /\u0418\u0441\u0442\u043e\u0440\u0438\u044f/,
    }));

    expect(screen.getAllByText("\u2014 USDT")).toHaveLength(2);
    expect(screen.queryByText(/\+0 USDT/)).not.toBeInTheDocument();
    expect(screen.queryByText(/-0 USDT/)).not.toBeInTheDocument();
    expect(screen.queryByText(/1e2/)).not.toBeInTheDocument();
    expect(screen.queryByText(/0x10/)).not.toBeInTheDocument();
    expect(screen.queryByRole("link", {
      name: /\u041e\u043f\u043b\u0430\u0442\u0438\u0442\u044c/,
    })).not.toBeInTheDocument();
  });

  it("history tab places malformed timestamps after dated rows", async () => {
    mockState.deposits = [makeDeposit(1, { created_at: "not-a-date" })];
    mockState.withdrawals = [
      makeWithdrawal(2, { created_at: "2026-03-01T00:00:00Z" }),
    ];

    const user = userEvent.setup();
    const historyTabName = /\u0418\u0441\u0442\u043e\u0440\u0438\u044f/;
    renderPage("USDT");
    await user.click(screen.getByRole("button", { name: historyTabName }));

    const rowIds = screen
      .getAllByTestId(/^wallet-history-row-/)
      .map((row) => row.getAttribute("data-testid"));
    expect(rowIds).toEqual([
      "wallet-history-row-w-2",
      "wallet-history-row-d-1",
    ]);
  });

  it("history tab shows empty-state when no rows", async () => {
    const user = userEvent.setup();
    renderPage("USDT");
    await user.click(screen.getByRole("button", { name: /История/ }));
    expect(screen.getByText("Операций пока нет")).toBeInTheDocument();
  });
});
