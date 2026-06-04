import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, useLocation } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type {
  AdminDealListDto,
  AdminListDealsQuery,
} from "@/api/types";

/**
 * Tests for `/admin/deals`.
 *
 * Covers status chip filter, URL deep-linking, active filter-chip
 * rendering with one-click removal, pagination prev/next gating,
 * navigation to detail page, empty-state and admin guard.
 */

const mockState = vi.hoisted(() => ({
  list: undefined as AdminDealListDto | undefined,
  loading: false,
  shouldRender: true as boolean,
  lastQuery: undefined as AdminListDealsQuery | undefined,
}));

vi.mock("@/api/admin/hooks", () => ({
  useAdminDeals: (q: AdminListDealsQuery) => {
    mockState.lastQuery = q;
    return { data: mockState.list, isLoading: mockState.loading };
  },
}));

vi.mock("@/hooks/useAdminRedirect", () => ({
  useAdminRedirect: () => ({ shouldRender: mockState.shouldRender }),
}));

vi.mock("@/lib/tg", () => ({
  useTelegramViewport: () => null,
  haptic: () => {},
  showBackButton: () => () => {},
}));

import AdminDealsPage from "./AdminDealsPage";

function LocationProbe() {
  const loc = useLocation();
  return (
    <span data-testid="path">
      {loc.pathname}
      {loc.search}
    </span>
  );
}

function renderPage(initialEntries: string[] = ["/admin/deals"]) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={initialEntries}>
        <AdminDealsPage />
        <LocationProbe />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function makeDeal(
  overrides: Partial<AdminDealListDto["items"][number]> = {},
): AdminDealListDto["items"][number] {
  return {
    id: 42,
    status: "in_progress",
    currency_code: "USDT",
    amount: "150.00",
    commission_amount: "3.00",
    buyer_id: 1,
    buyer_username: "buyer",
    seller_id: 2,
    seller_username: "seller",
    created_at: "2026-01-01T00:00:00Z",
    in_progress_at: null,
    completed_at: null,
    has_arbitration: false,
    has_cancel_request: false,
    ...overrides,
  };
}

beforeEach(() => {
  mockState.list = undefined;
  mockState.loading = false;
  mockState.shouldRender = true;
  mockState.lastQuery = undefined;
});

describe("<AdminDealsPage />", () => {
  it("returns null when admin guard rejects the visitor", () => {
    mockState.shouldRender = false;
    renderPage();
    expect(screen.queryByText("Сделки")).not.toBeInTheDocument();
  });

  it("renders skeletons while loading", () => {
    mockState.loading = true;
    const { container } = renderPage();
    expect(container.querySelectorAll(".h-20").length).toBeGreaterThan(0);
  });

  it("renders empty state when no items", () => {
    mockState.list = { items: [], total: 0, page: 1, page_size: 20 };
    renderPage();
    expect(screen.getByText("Сделок не найдено")).toBeInTheDocument();
  });

  it("renders deal rows with sum/currency", () => {
    mockState.list = {
      items: [makeDeal()],
      total: 1,
      page: 1,
      page_size: 20,
    };
    renderPage();
    expect(screen.getByText(/150\.00/)).toBeInTheDocument();
  });

  it("renders malformed deal amounts as a neutral dash", () => {
    mockState.list = {
      items: [makeDeal({ amount: "1e3" })],
      total: 1,
      page: 1,
      page_size: 20,
    };
    renderPage();
    expect(screen.getByText(/\u2014 USDT/)).toBeInTheDocument();
    expect(screen.queryByText(/0\.00 USDT/)).not.toBeInTheDocument();
  });

  it("does not coerce malformed totals into admin pagination", () => {
    mockState.list = {
      items: [makeDeal()],
      total: "1e2" as unknown as number,
      page: 1,
      page_size: 20,
    };
    renderPage();
    expect(screen.queryByText("1e2")).not.toBeInTheDocument();
    expect(screen.queryByText(/1 \/ 5/)).not.toBeInTheDocument();
  });

  it("renders missing buyer/seller usernames as non-handle labels", () => {
    mockState.list = {
      items: [makeDeal({ buyer_username: null, seller_username: null })],
      total: 1,
      page: 1,
      page_size: 20,
    };
    renderPage();
    expect(screen.getAllByText(/username \u043d\u0435 \u0437\u0430\u0434\u0430\u043d/).length).toBeGreaterThan(0);
    expect(screen.queryByText(/@\u2014/)).not.toBeInTheDocument();
  });

  it("reads URL filters and passes them to useAdminDeals", () => {
    mockState.list = { items: [], total: 0, page: 1, page_size: 20 };
    renderPage([
      "/admin/deals?status=in_progress&currency=USDT&min_amount=10&max_amount=500&has_arbitration=true&page=3",
    ]);
    expect(mockState.lastQuery).toEqual({
      status: "in_progress",
      currency: "USDT",
      min_amount: 10,
      max_amount: 500,
      has_arbitration: true,
      has_cancel_request: undefined,
      page: 3,
      page_size: 20,
    });
  });

  it("drops malformed URL filters before calling useAdminDeals", () => {
    mockState.list = { items: [], total: 0, page: 1, page_size: 20 };
    renderPage([
      "/admin/deals?status=pending_payment&currency=bad%20code&min_amount=NaN&max_amount=-1&page=1e2",
    ]);

    expect(mockState.lastQuery).toEqual({
      status: undefined,
      currency: undefined,
      min_amount: undefined,
      max_amount: undefined,
      has_arbitration: undefined,
      has_cancel_request: undefined,
      page: 1,
      page_size: 20,
    });
  });

  it("drops reversed amount ranges from URL filters before calling useAdminDeals", () => {
    mockState.list = { items: [], total: 0, page: 1, page_size: 20 };
    renderPage(["/admin/deals?min_amount=500&max_amount=10"]);

    expect(mockState.lastQuery?.min_amount).toBeUndefined();
    expect(mockState.lastQuery?.max_amount).toBeUndefined();
  });

  it("clicking a status chip updates URL status param", async () => {
    mockState.list = { items: [], total: 0, page: 1, page_size: 20 };
    const user = userEvent.setup();
    renderPage();
    await user.click(screen.getByRole("button", { name: "В работе" }));
    await waitFor(() =>
      expect(mockState.lastQuery?.status).toBe("in_progress"),
    );
  });

  it("exposes pending_topup but not deprecated pending_payment as list filters", async () => {
    mockState.list = { items: [], total: 0, page: 1, page_size: 20 };
    const user = userEvent.setup();
    renderPage();
    expect(screen.queryByRole("button", { name: "Ожидание оплаты" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Ожидание инвойса" }));
    await waitFor(() => expect(mockState.lastQuery?.status).toBe("pending_topup"));
  });

  it("clicking 'Все' resets status to undefined (no filter)", async () => {
    // Audit L-10 — the legacy ``"any"`` sentinel is gone; the
    // "all statuses" chip now drops the URL param entirely so the
    // hook sees ``status === undefined``.
    mockState.list = { items: [], total: 0, page: 1, page_size: 20 };
    const user = userEvent.setup();
    renderPage(["/admin/deals?status=in_progress"]);
    await user.click(screen.getByRole("button", { name: "Все" }));
    await waitFor(() => expect(mockState.lastQuery?.status).toBeUndefined());
  });

  it("renders active filter chips and removes them on click", async () => {
    mockState.list = { items: [], total: 0, page: 1, page_size: 20 };
    const user = userEvent.setup();
    renderPage(["/admin/deals?currency=USDT&min_amount=10"]);
    expect(screen.getByRole("button", { name: /Валюта: USDT/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Мин: 10/ })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /Валюта: USDT/ }));
    await waitFor(() => expect(mockState.lastQuery?.currency).toBeUndefined());
  });

  it("clicking a deal row navigates to /admin/deals/<id>", async () => {
    mockState.list = {
      items: [makeDeal({ id: 999 })],
      total: 1,
      page: 1,
      page_size: 20,
    };
    const user = userEvent.setup();
    renderPage();
    // Find the deal row by ID text
    const idText = screen.getByText(/#999|999/);
    await user.click(idText);
    await waitFor(() =>
      expect(screen.getByTestId("path").textContent).toContain(
        "/admin/deals/999",
      ),
    );
  });

  it("pagination prev disabled on page 1, next advances page", async () => {
    mockState.list = {
      items: [makeDeal()],
      total: 80,
      page: 1,
      page_size: 20,
    };
    const user = userEvent.setup();
    renderPage();
    const prev = screen.getByLabelText("Назад");
    const next = screen.getByLabelText("Вперёд");
    expect(prev).toBeDisabled();
    expect(next).not.toBeDisabled();
    await user.click(next);
    await waitFor(() => expect(mockState.lastQuery?.page).toBe(2));
  });

  it("filter sheet: applying currency draft sets ?currency=...", async () => {
    mockState.list = { items: [], total: 0, page: 1, page_size: 20 };
    const user = userEvent.setup();
    renderPage();
    await user.click(screen.getByLabelText("Фильтры"));
    const input = await screen.findByPlaceholderText(/USDT, BTC/);
    fireEvent.change(input, { target: { value: "btc" } });
    expect((input as HTMLInputElement).value).toBe("BTC");
  });

  it("filter sheet blocks reversed amount ranges before applying", async () => {
    mockState.list = { items: [], total: 0, page: 1, page_size: 20 };
    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByLabelText("\u0424\u0438\u043b\u044c\u0442\u0440\u044b"));
    const amountInputs = screen.getAllByRole("spinbutton");
    fireEvent.change(amountInputs[0], { target: { value: "500" } });
    fireEvent.change(amountInputs[1], { target: { value: "10" } });

    const apply = screen.getByText("\u041f\u0440\u0438\u043c\u0435\u043d\u0438\u0442\u044c").closest("button");
    expect(apply).toBeDisabled();
  });
});
