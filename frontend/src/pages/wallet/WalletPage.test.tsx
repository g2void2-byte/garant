import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { UserCardDto, WalletBalanceDto } from "@/api/types";

/**
 * Hoisted mock state — the ``vi.mock`` factory below runs *before* any
 * import, so we have to reach the data through a hoisted holder.
 */
const mockState = vi.hoisted(() => ({
  data: undefined as WalletBalanceDto[] | undefined,
  isLoading: false,
  // ``useMe`` powers the "Депозит доверия" pill at the bottom of the
  // page; the wallet page reads ``me.data.deposit`` which is the
  // trust-deposit balance after the country-deposit-filter refactor.
  me: undefined as Partial<UserCardDto> | undefined,
}));

vi.mock("@/api/hooks", () => ({
  useWalletBalances: () => mockState,
  useMe: () => ({ data: mockState.me }),
}));

import WalletPage from "./WalletPage";

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <WalletPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  mockState.data = undefined;
  mockState.isLoading = false;
  mockState.me = undefined;
});

describe("<WalletPage />", () => {
  it("renders the page header", () => {
    mockState.data = [];
    renderPage();
    expect(screen.getByRole("heading", { name: "Кошелёк" })).toBeInTheDocument();
  });

  it("renders the empty state when there are no balances", () => {
    mockState.data = [];
    renderPage();
    expect(screen.getByText("Пока пусто")).toBeInTheDocument();
  });

  it("renders balance rows with formatted amounts", () => {
    mockState.data = [
      {
        currency: {
          id: 1,
          code: "USD",
          name: "US Dollar",
          network: "",
          icon_url: "",
          decimals: 2,
          min_deposit: 1,
          min_withdraw: 1,
          kind: "fiat",
        },
        amount: 123.456,
        locked: 0,
        total: 123.456,
        updated_at: null,
        amount_str: "123.456",
        locked_str: "0",
        total_str: "123.456",
      },
    ];
    renderPage();
    expect(screen.getByText("US Dollar")).toBeInTheDocument();
    expect(screen.getByText(/123\.46 USD/)).toBeInTheDocument();
  });

  it("renders malformed available balance strings as neutral", () => {
    mockState.data = [
      {
        currency: {
          id: 1,
          code: "USD",
          name: "US Dollar",
          network: "",
          icon_url: "",
          decimals: 2,
          min_deposit: 1,
          min_withdraw: 1,
          kind: "fiat",
        },
        amount: "1e2" as unknown as number,
        locked: 0,
        total: 100,
        updated_at: null,
        amount_str: "1e2",
        locked_str: "0",
        total_str: "100",
      },
    ];
    renderPage();

    expect(screen.getByText("\u2014 USD")).toBeInTheDocument();
    expect(screen.queryByText(/0 USD/)).not.toBeInTheDocument();
    expect(screen.queryByText(/1e2/)).not.toBeInTheDocument();
  });

  it("wraps each balance row in a Link to /wallet/<code>", () => {
    mockState.data = [
      {
        currency: {
          id: 1,
          code: "USD",
          name: "US Dollar",
          network: "",
          icon_url: "",
          decimals: 2,
          min_deposit: 1,
          min_withdraw: 1,
          kind: "fiat",
        },
        amount: 1,
        locked: 0,
        total: 1,
        updated_at: null,
        amount_str: "1",
        locked_str: "0",
        total_str: "1",
      },
      {
        currency: {
          id: 2,
          code: "UAH",
          name: "Українська гривня",
          network: "",
          icon_url: "",
          decimals: 2,
          min_deposit: 50,
          min_withdraw: 50,
          kind: "fiat",
        },
        amount: 2,
        locked: 0,
        total: 2,
        updated_at: null,
        amount_str: "2",
        locked_str: "0",
        total_str: "2",
      },
    ];
    renderPage();
    const usd = screen.getByRole("link", { name: /US Dollar/ });
    expect(usd).toHaveAttribute("href", "/wallet/USD");
    const uah = screen.getByRole("link", { name: /гривня/ });
    expect(uah).toHaveAttribute("href", "/wallet/UAH");
  });

  it("hides crypto balance rows from the wallet list", () => {
    mockState.data = [
      {
        currency: {
          id: 1,
          code: "USDT",
          name: "Tether",
          network: "TRC20",
          icon_url: "",
          decimals: 2,
          min_deposit: 1,
          min_withdraw: 1,
          kind: "crypto",
        },
        amount: 5,
        locked: 0,
        total: 5,
        updated_at: null,
        amount_str: "5",
        locked_str: "0",
        total_str: "5",
      },
    ];
    renderPage();
    // Crypto balance must be filtered out; the empty-state copy is
    // rendered instead because no fiat rows remain.
    expect(screen.queryByText("Tether")).not.toBeInTheDocument();
    expect(screen.getByText("Пока пусто")).toBeInTheDocument();
  });

  it("hides fiat balance rows with malformed currency codes", () => {
    mockState.data = [
      {
        currency: {
          id: 1,
          code: "USD/../admin",
          name: "Broken Dollar",
          network: "",
          icon_url: "",
          decimals: 2,
          min_deposit: 1,
          min_withdraw: 1,
          kind: "fiat",
        },
        amount: 5,
        locked: 0,
        total: 5,
        updated_at: null,
        amount_str: "5",
        locked_str: "0",
        total_str: "5",
      },
    ];
    renderPage();
    expect(screen.queryByText("Broken Dollar")).not.toBeInTheDocument();
  });

  it('renders the "locked" hint when balance has reserves', () => {
    mockState.data = [
      {
        currency: {
          id: 2,
          code: "USD",
          name: "US Dollar",
          network: "",
          icon_url: "",
          decimals: 2,
          min_deposit: 1,
          min_withdraw: 1,
          kind: "fiat",
        },
        amount: 0.5,
        locked: 0.1,
        total: 0.6,
        updated_at: null,
        amount_str: "0.5",
        locked_str: "0.1",
        total_str: "0.6",
      },
    ];
    renderPage();
    expect(screen.getByText(/в заявках/)).toBeInTheDocument();
  });

  it("does not render the locked hint for malformed runtime locked values", () => {
    mockState.data = [
      {
        currency: {
          id: 2,
          code: "USD",
          name: "US Dollar",
          network: "",
          icon_url: "",
          decimals: 2,
          min_deposit: 1,
          min_withdraw: 1,
          kind: "fiat",
        },
        amount: 0.5,
        locked: "1e1" as unknown as number,
        total: 10.5,
        updated_at: null,
        amount_str: "0.5",
        locked_str: "1e1",
        total_str: "10.5",
      },
    ];
    renderPage();
    expect(screen.queryByText(/РІ Р·Р°СЏРІРєР°С…/)).not.toBeInTheDocument();
  });

  it("renders deposit and withdrawal action tiles", () => {
    mockState.data = [];
    renderPage();
    expect(screen.getByText(/Пополнить/)).toBeInTheDocument();
    expect(screen.getByText(/Вывести/)).toBeInTheDocument();
  });

  it("renders the trust-deposit section with the current balance", () => {
    mockState.data = [];
    mockState.me = { deposit: 250 };
    renderPage();
    expect(
      screen.getByRole("heading", { name: /Депозит доверия/ }),
    ).toBeInTheDocument();
    expect(screen.getByText(/250/)).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /Управление депозитом/ }),
    ).toBeInTheDocument();
  });

  it("renders malformed trust-deposit balances as neutral", () => {
    mockState.data = [];
    mockState.me = { deposit: "1e2" as unknown as number };
    renderPage();

    expect(screen.getByText("\u2014")).toBeInTheDocument();
    expect(screen.queryByText("$0")).not.toBeInTheDocument();
    expect(screen.queryByText(/1e2/)).not.toBeInTheDocument();
  });
});
