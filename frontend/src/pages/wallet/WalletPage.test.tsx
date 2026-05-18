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
});

describe("<WalletPage />", () => {
  it("renders the page header", () => {
    mockState.data = [];
    renderPage();
    expect(screen.getByRole("heading", { name: "Депозит" })).toBeInTheDocument();
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
          code: "USDT",
          name: "Tether",
          network: "TRC20",
          icon_url: "",
          decimals: 2,
          min_deposit: 1,
          min_withdraw: 1,
        },
        amount: 123.456,
        locked: 0,
        total: 123.456,
        updated_at: null,
      },
    ];
    renderPage();
    expect(screen.getByText("Tether")).toBeInTheDocument();
    expect(screen.getByText("TRC20")).toBeInTheDocument();
    expect(screen.getByText(/123\.46 USDT/)).toBeInTheDocument();
  });

  it('renders the "locked" hint when balance has reserves', () => {
    mockState.data = [
      {
        currency: {
          id: 2,
          code: "BTC",
          name: "Bitcoin",
          network: "BTC",
          icon_url: "",
          decimals: 8,
          min_deposit: 0.001,
          min_withdraw: 0.001,
        },
        amount: 0.5,
        locked: 0.1,
        total: 0.6,
        updated_at: null,
      },
    ];
    renderPage();
    expect(screen.getByText(/в заявках/)).toBeInTheDocument();
  });

  it("renders deposit and withdrawal action tiles", () => {
    mockState.data = [];
    renderPage();
    // Two "Внести"-prefixed buttons live on the page after V12 (the
    // legacy wallet-deposit tile and the new trust-deposit CTA), so
    // the assertion checks for *both* matches explicitly to keep the
    // regression detector unambiguous.
    expect(screen.getAllByText(/Внести/).length).toBeGreaterThanOrEqual(2);
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
      screen.getByRole("button", { name: /Внести депозит доверия/ }),
    ).toBeInTheDocument();
  });
});
