import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { DealDto } from "@/api/types";

const mockState = vi.hoisted(() => ({
  data: undefined as DealDto[] | undefined,
  isLoading: false,
}));

vi.mock("@/api/hooks", () => ({
  useDeals: () => mockState,
}));

import DealsPage from "./DealsPage";

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <DealsPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  mockState.data = undefined;
  mockState.isLoading = false;
});

function makeDeal(overrides: Partial<DealDto> = {}): DealDto {
  return {
    id: 1,
    buyer: "alice",
    seller: "bob",
    description: "Test deal",
    pay_comission: "buyer",
    status: "in_progress",
    confirm_buyer: true,
    confirm_seller: true,
    role: "buyer",
    created_at: "2026-01-01T00:00:00Z",
    currency_code: "USDT",
    amount: 100,
    commission_amount: 5,
    in_progress_at: "2026-01-01T00:00:00Z",
    completed_at: null,
    cancellation_initiator: null,
    cancellation_reason: null,
    cancellation_requested_at: null,
    arbitration_initiator: null,
    arbitration_reason: null,
    arbitration_resolved_by: null,
    arbitration_resolution: null,
    arbitration_resolved_at: null,
    ...overrides,
  };
}

describe("<DealsPage />", () => {
  it("renders the page header and the 'new deal' CTA", () => {
    mockState.data = [];
    renderPage();
    expect(screen.getByRole("heading", { name: "Ваши сделки" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Новая/i })).toBeInTheDocument();
  });

  it("renders skeletons while loading and no empty state", () => {
    mockState.isLoading = true;
    renderPage();
    expect(screen.queryByText("Сделок пока нет")).not.toBeInTheDocument();
  });

  it("renders the empty state when the API returns no deals", () => {
    mockState.data = [];
    renderPage();
    expect(screen.getByText("Сделок пока нет")).toBeInTheDocument();
  });

  it("renders deal rows when the API returns data", () => {
    mockState.data = [makeDeal({ id: 1, description: "First" }), makeDeal({ id: 2, description: "Second" })];
    renderPage();
    expect(screen.getByText("First")).toBeInTheDocument();
    expect(screen.getByText("Second")).toBeInTheDocument();
  });

  it("offers the role + status filters", () => {
    mockState.data = [];
    renderPage();
    // ToggleTabs renders the role choices as buttons.
    expect(screen.getByRole("button", { name: "Покупки" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Продажи" })).toBeInTheDocument();
    // Select dropdown is present.
    expect(screen.getByText("Все статусы")).toBeInTheDocument();
  });
});
