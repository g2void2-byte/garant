import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { DealDto } from "@/api/types";

const mockState = vi.hoisted(() => ({
  data: undefined as DealDto[] | undefined,
  isLoading: false,
}));
const useDealsCalls = vi.hoisted(() => [] as Array<Record<string, unknown>>);
const apiMock = vi.hoisted(() => ({ get: vi.fn() }));
const buildDealsSearchParamsMock = vi.hoisted(() =>
  vi.fn((params: Record<string, unknown>) => {
    const searchParams: Record<string, string> = {};
    for (const [key, value] of Object.entries(params)) {
      if (value === undefined || value === "" || (key === "role" && value === "all")) {
        continue;
      }
      searchParams[key] = String(value);
    }
    return searchParams;
  }),
);

vi.mock("@/api/hooks", () => ({
  buildDealsSearchParams: buildDealsSearchParamsMock,
  useDeals: (params: Record<string, unknown>) => {
    useDealsCalls.push(params);
    return mockState;
  },
}));

vi.mock("@/api/client", () => ({
  api: apiMock,
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
  useDealsCalls.length = 0;
  apiMock.get.mockReset();
  buildDealsSearchParamsMock.mockClear();
});

function makeDeal(overrides: Partial<DealDto> = {}): DealDto {
  return {
    id: 1,
    buyer: "alice",
    seller: "bob",
    description: "Test deal",
    status: "in_progress",
    confirm_buyer: true,
    confirm_seller: true,
    role: "buyer",
    created_at: "2026-01-01T00:00:00Z",
    currency_code: "USDT",
    amount: 100,
    commission_amount: 5,
    commission_paid: true,
    topup_deposit_id: null,
    topup_invoice: null,
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

  it("omits role=all and requests the first page", () => {
    mockState.data = [];
    renderPage();

    expect(useDealsCalls.at(-1)).toEqual({
      role: undefined,
      status: undefined,
      limit: 50,
      offset: 0,
    });
  });

  it("loads the next deal-list page by offset", async () => {
    const user = userEvent.setup();
    mockState.data = Array.from({ length: 50 }, (_, idx) =>
      makeDeal({ id: idx + 1, description: `Deal ${idx + 1}` }),
    );
    apiMock.get.mockReturnValue({
      json: async () => [makeDeal({ id: 51, description: "Deal 51" })],
    });

    renderPage();
    await user.click(screen.getByRole("button", { name: "Показать еще" }));

    expect(apiMock.get).toHaveBeenCalledWith("api/deals", {
      searchParams: { limit: "50", offset: "50" },
    });
    expect(await screen.findByText("Deal 51")).toBeInTheDocument();
  });
});
