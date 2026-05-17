import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { DealDto, WalletBalanceDto } from "@/api/types";

/**
 * Tests for the standalone "Оплата сделки" page reached from the
 * "Оплатить" CTA on a deal in ``pending_payment``. Covers the four
 * states the user can land in:
 *   1. Loading skeleton (deal undefined / isLoading)
 *   2. Wrong-status deal -> EmptyState explanation
 *   3. pending_payment + sufficient balance -> "Оплатить" enabled
 *   4. pending_payment + insufficient balance -> "Внести депозит" fallback
 */

const mockState = vi.hoisted(() => ({
  deal: undefined as DealDto | undefined,
  dealIsLoading: false,
  balances: undefined as WalletBalanceDto[] | undefined,
}));

vi.mock("@/api/hooks", () => ({
  useDeal: () => ({ data: mockState.deal, isLoading: mockState.dealIsLoading }),
  useWalletBalances: () => ({ data: mockState.balances }),
}));

vi.mock("@/lib/tg", () => ({
  haptic: vi.fn(),
  showBackButton: () => () => {},
}));

import DealPaymentPage from "./DealPaymentPage";

function renderPage(dealId = 11) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[`/deals/${dealId}/pay`]}>
        <Routes>
          <Route path="/deals/:id/pay" element={<DealPaymentPage />} />
          <Route path="/wallet/deposit" element={<div data-testid="wallet-deposit">deposit page</div>} />
          <Route path="/deals/:id" element={<div data-testid="deal-detail">deal page</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function makeDeal(over: Partial<DealDto> = {}): DealDto {
  return {
    id: 11,
    buyer: "alice",
    seller: "bob",
    description: "Test",
    pay_comission: "buyer",
    status: "pending_payment",
    confirm_buyer: false,
    confirm_seller: false,
    role: "buyer",
    created_at: "2026-01-01T00:00:00Z",
    currency_code: "USDT",
    amount: 100,
    commission_amount: 5,
    in_progress_at: null,
    completed_at: null,
    cancellation_initiator: null,
    cancellation_reason: null,
    cancellation_requested_at: null,
    arbitration_initiator: null,
    arbitration_reason: null,
    arbitration_resolved_by: null,
    arbitration_resolution: null,
    arbitration_resolved_at: null,
    ...over,
  };
}

function makeBalance(amount: number, code = "USDT", decimals = 2): WalletBalanceDto {
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
  };
}

beforeEach(() => {
  mockState.deal = undefined;
  mockState.dealIsLoading = false;
  mockState.balances = undefined;
});

describe("<DealPaymentPage />", () => {
  it("renders skeletons while the deal is loading", () => {
    mockState.dealIsLoading = true;
    const { container } = renderPage();
    // Skeleton uses the ``shimmer`` className (see Skeleton.tsx).
    expect(container.querySelector(".shimmer")).not.toBeNull();
    expect(screen.getByRole("heading", { name: "Оплата сделки" })).toBeInTheDocument();
  });

  it("renders the wrong-status empty state when the deal is not pending_payment", () => {
    mockState.deal = makeDeal({ status: "in_progress" });
    renderPage();
    expect(screen.getByText("Сделка не требует оплаты")).toBeInTheDocument();
    expect(screen.getByText(/Текущий статус: in_progress/)).toBeInTheDocument();
  });

  it("shows the amount due, balance, and 'достаточно средств' when the user has enough", () => {
    mockState.deal = makeDeal({ amount: 100, currency_code: "USDT" });
    mockState.balances = [makeBalance(150, "USDT", 2)];
    renderPage();

    expect(screen.getByText("Сумма к оплате")).toBeInTheDocument();
    expect(screen.getByText(/100 USDT/)).toBeInTheDocument();
    expect(screen.getByText("достаточно средств")).toBeInTheDocument();
    const payBtn = screen.getByRole("button", { name: /^Оплатить$/ });
    expect(payBtn).not.toBeDisabled();
    expect(screen.queryByRole("button", { name: /Внести депозит/ })).not.toBeInTheDocument();
  });

  it("shows the 'Внести депозит' fallback CTA when the balance is too low", () => {
    mockState.deal = makeDeal({ amount: 100, currency_code: "USDT" });
    mockState.balances = [makeBalance(10, "USDT", 2)];
    renderPage();

    expect(screen.getByText("недостаточно средств")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /Внести депозит/ }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^Оплатить$/ })).toBeDisabled();
  });

  it("renders the deal id and counterparty username in the header", () => {
    mockState.deal = makeDeal({ id: 17, buyer: "alice", seller: "bob", role: "buyer" });
    mockState.balances = [makeBalance(500)];
    renderPage();
    // role=buyer -> counterparty is the seller
    expect(screen.getByText(/Сделка #17/)).toBeInTheDocument();
    expect(screen.getByText(/@bob/)).toBeInTheDocument();
  });

  it("falls back to 0 balance for currencies the user does not hold", () => {
    mockState.deal = makeDeal({ amount: 100, currency_code: "BTC" });
    mockState.balances = [makeBalance(500, "USDT")];
    renderPage();
    expect(screen.getByText("недостаточно средств")).toBeInTheDocument();
    // The balance row should render ``0 BTC`` once (the amount-due
    // tile shows the deal amount, not the user balance).
    const balanceLabel = screen.getByText("Баланс BTC");
    expect(balanceLabel.parentElement?.textContent).toMatch(/0 BTC/);
  });
});
