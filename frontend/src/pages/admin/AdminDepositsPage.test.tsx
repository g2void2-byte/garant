import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { AdminDepositListDto } from "@/api/types";

/**
 * Tests for `/admin/deposits`.
 *
 * Covers status filter chips, deposit row rendering with badge, mark-
 * paid mutation (only on 'pending' rows) and refund mutation (only on
 * 'paid' rows), pay_url link rendering, admin guard, loading skeleton,
 * empty state.
 */

const mockState = vi.hoisted(() => ({
  list: undefined as AdminDepositListDto | undefined,
  loading: false,
  markPaid: {
    mutateAsync: vi.fn() as ReturnType<typeof vi.fn>,
    isPending: false,
  },
  refund: {
    mutateAsync: vi.fn() as ReturnType<typeof vi.fn>,
    isPending: false,
  },
  shouldRender: true as boolean,
  lastDepositsQuery: undefined as
    | { status?: string; page?: number; page_size?: number }
    | undefined,
}));

vi.mock("@/api/admin/hooks", () => ({
  useAdminDeposits: (q: {
    status?: string;
    page?: number;
    page_size?: number;
  }) => {
    mockState.lastDepositsQuery = q;
    return { data: mockState.list, isLoading: mockState.loading };
  },
  useAdminDepositMarkPaid: () => mockState.markPaid,
  useAdminDepositRefund: () => mockState.refund,
}));

vi.mock("@/hooks/useAdminRedirect", () => ({
  useAdminRedirect: () => ({ shouldRender: mockState.shouldRender }),
}));

const toastSpy = vi.hoisted(() => vi.fn());
vi.mock("@/components/ui/Toast", () => ({
  useToast: () => ({ show: toastSpy }),
}));

vi.mock("@/lib/tg", () => ({
  useTelegramViewport: () => null,
  haptic: () => {},
  showBackButton: () => () => {},
}));

import AdminDepositsPage from "./AdminDepositsPage";

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <AdminDepositsPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function makeDeposit(
  overrides: Partial<AdminDepositListDto["items"][number]> = {},
): AdminDepositListDto["items"][number] {
  return {
    id: 100,
    user_id: 1,
    username: "alice",
    display_name: "Alice",
    currency_code: "USDT",
    amount: "50.0",
    status: "pending",
    provider_invoice_id: "inv-1",
    pay_url: "https://example.com/pay/inv-1",
    created_at: "2026-01-01T00:00:00Z",
    paid_at: null,
    ...overrides,
  };
}

beforeEach(() => {
  mockState.list = undefined;
  mockState.loading = false;
  mockState.markPaid = { mutateAsync: vi.fn(), isPending: false };
  mockState.refund = { mutateAsync: vi.fn(), isPending: false };
  mockState.shouldRender = true;
  mockState.lastDepositsQuery = undefined;
  toastSpy.mockClear();
});

describe("<AdminDepositsPage />", () => {
  it("returns null when admin guard rejects the visitor", () => {
    mockState.shouldRender = false;
    renderPage();
    expect(screen.queryByText("Депозиты")).not.toBeInTheDocument();
  });

  it("renders skeleton rows while loading", () => {
    mockState.loading = true;
    const { container } = renderPage();
    expect(container.querySelectorAll(".rounded-card.h-24").length).toBe(6);
  });

  it("renders 'Депозитов нет' when the list is empty", () => {
    mockState.list = { items: [], total: 0, page: 1, page_size: 50 };
    renderPage();
    expect(screen.getByText("Депозитов нет")).toBeInTheDocument();
  });

  it("renders deposit rows with amount, user, badge and pay_url link", () => {
    mockState.list = {
      items: [makeDeposit()],
      total: 1,
      page: 1,
      page_size: 50,
    };
    renderPage();
    expect(screen.getByText(/50\.00 USDT/)).toBeInTheDocument();
    expect(screen.getByText(/@alice/)).toBeInTheDocument();
    // The status badge is a <span> with uppercase styles; chips are <button>s.
    expect(
      screen.getByText("pending", { selector: "span" }),
    ).toBeInTheDocument();
    const link = screen.getByRole("link", { name: /pay_url/i });
    expect(link).toHaveAttribute("href", "https://example.com/pay/inv-1");
  });

  it("renders missing depositor username as a non-handle label", () => {
    mockState.list = {
      items: [makeDeposit({ username: null })],
      total: 1,
      page: 1,
      page_size: 50,
    };
    renderPage();
    expect(screen.getByText(/username \u043d\u0435 \u0437\u0430\u0434\u0430\u043d/)).toBeInTheDocument();
    expect(screen.queryByText(/@\u2014/)).not.toBeInTheDocument();
  });

  it("'Зачислить' only appears on pending rows and fires mark-paid", async () => {
    mockState.list = {
      items: [
        makeDeposit(),
        makeDeposit({ id: 101, status: "paid" }),
      ],
      total: 2,
      page: 1,
      page_size: 50,
    };
    mockState.markPaid.mutateAsync.mockResolvedValue({});
    const user = userEvent.setup();
    renderPage();

    const zachislBtns = screen.getAllByRole("button", { name: /Зачислить/ });
    expect(zachislBtns).toHaveLength(1);
    await user.click(zachislBtns[0]);
    await waitFor(() =>
      expect(mockState.markPaid.mutateAsync).toHaveBeenCalledWith({ id: 100 }),
    );
    expect(toastSpy).toHaveBeenCalledWith(
      expect.objectContaining({ kind: "success", title: "Зачислен" }),
    );
  });

  it("'Возврат' only appears on paid rows and fires refund", async () => {
    mockState.list = {
      items: [makeDeposit({ status: "paid", id: 200 })],
      total: 1,
      page: 1,
      page_size: 50,
    };
    mockState.refund.mutateAsync.mockResolvedValue({});
    const user = userEvent.setup();
    renderPage();

    const refundBtn = screen.getByRole("button", { name: /Возврат/ });
    await user.click(refundBtn);
    await waitFor(() =>
      expect(mockState.refund.mutateAsync).toHaveBeenCalledWith({ id: 200 }),
    );
    expect(toastSpy).toHaveBeenCalledWith(
      expect.objectContaining({ kind: "success", title: "Возвращён" }),
    );
  });

  it("clicking a status filter chip updates the query", async () => {
    mockState.list = { items: [], total: 0, page: 1, page_size: 50 };
    const user = userEvent.setup();
    renderPage();
    await user.click(screen.getByRole("button", { name: "paid" }));
    await waitFor(() =>
      expect(mockState.lastDepositsQuery?.status).toBe("paid"),
    );
  });

  it("'Все' filter sends status=undefined", async () => {
    mockState.list = { items: [], total: 0, page: 1, page_size: 50 };
    const user = userEvent.setup();
    renderPage();
    await user.click(screen.getByRole("button", { name: "paid" }));
    await waitFor(() =>
      expect(mockState.lastDepositsQuery?.status).toBe("paid"),
    );
    await user.click(screen.getByRole("button", { name: "Все" }));
    await waitFor(() =>
      expect(mockState.lastDepositsQuery?.status).toBeUndefined(),
    );
  });

  it("pagination advances beyond the first page and resets when status changes", async () => {
    mockState.list = { items: [makeDeposit()], total: 80, page: 1, page_size: 50 };
    const user = userEvent.setup();
    renderPage();

    expect(screen.getByText("1 / 2")).toBeInTheDocument();
    await user.click(screen.getByLabelText("Вперёд"));
    await waitFor(() => expect(mockState.lastDepositsQuery?.page).toBe(2));

    await user.click(screen.getByRole("button", { name: "paid" }));
    await waitFor(() => {
      expect(mockState.lastDepositsQuery?.status).toBe("paid");
      expect(mockState.lastDepositsQuery?.page).toBe(1);
    });
  });

  it("refund failure surfaces an error toast with message body", async () => {
    mockState.list = {
      items: [makeDeposit({ status: "paid" })],
      total: 1,
      page: 1,
      page_size: 50,
    };
    mockState.refund.mutateAsync.mockRejectedValueOnce(
      new Error("server boom"),
    );
    const user = userEvent.setup();
    renderPage();
    await user.click(screen.getByRole("button", { name: /Возврат/ }));
    await waitFor(() =>
      expect(toastSpy).toHaveBeenCalledWith(
        expect.objectContaining({
          kind: "error",
          title: "Ошибка",
          body: "server boom",
        }),
      ),
    );
  });
});
