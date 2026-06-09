import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { DealDto, UserCardDto } from "@/api/types";

const apiMock = vi.hoisted(() => ({
  get: vi.fn(),
}));

const meState = vi.hoisted(() => ({
  data: {
    id: 1,
    user_id: 1,
    username: "arbiter",
    display_name: "Arbiter",
    photo_url: null,
    banner_url: null,
    admin: 0,
    prefix: null,
    good: 0,
    bad: 0,
    deposit: 0,
    rating: 0,
    reviews_count: 0,
    deals_count: 10,
    deals_success: 10,
    deals_failed: 0,
    deals_arbitrage: 1,
    deals_sum: 100,
    online: true,
    description: "",
    forums: [],
    is_admin: false,
    is_arbiter: true,
  } as UserCardDto,
}));

vi.mock("@/api/client", () => ({
  api: apiMock,
}));

vi.mock("@/api/hooks", () => ({
  useMe: () => meState,
}));

import ArbitrationPage from "./ArbitrationPage";

function makeDeal(overrides: Partial<DealDto> = {}): DealDto {
  return {
    id: 1,
    buyer: "buyer",
    seller: "seller",
    buyer_photo_url: null,
    seller_photo_url: null,
    description: "arbitration case",
    topup_deposit_id: null,
    commission_paid: true,
    topup_invoice: null,
    status: "arbitration",
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
    arbitration_initiator: "buyer",
    arbitration_reason: "reason",
    arbitration_resolved_by: null,
    arbitration_resolution: null,
    arbitration_resolved_at: null,
    ...overrides,
  };
}

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={["/arbitration"]}>
        <ArbitrationPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  apiMock.get.mockReset();
  meState.data = { ...meState.data, deals_count: 10, is_admin: false, is_arbiter: true };
});

describe("<ArbitrationPage />", () => {
  it("loads more arbitration deals with the backend offset", async () => {
    const firstPage = Array.from({ length: 50 }, (_, index) =>
      makeDeal({ id: index + 1, description: `case ${index}` }),
    );
    const secondPage = [makeDeal({ id: 51, description: "case 50" })];
    apiMock.get.mockImplementation((_url: string, opts?: { searchParams?: { offset?: number } }) => {
      const offset = Number(opts?.searchParams?.offset ?? 0);
      return { json: async () => (offset === 0 ? firstPage : secondPage) };
    });
    const user = userEvent.setup();

    renderPage();

    expect(await screen.findByText("case 0")).toBeInTheDocument();
    expect(screen.getByText("case 49")).toBeInTheDocument();
    expect(apiMock.get).toHaveBeenCalledWith("api/arbitration/deals", {
      searchParams: { limit: 50, offset: 0 },
    });

    await user.click(screen.getByRole("button"));

    expect(await screen.findByText("case 50")).toBeInTheDocument();
    expect(apiMock.get).toHaveBeenLastCalledWith("api/arbitration/deals", {
      searchParams: { limit: 50, offset: 50 },
    });
    await waitFor(() => expect(screen.queryByRole("button")).not.toBeInTheDocument());
  });
});
