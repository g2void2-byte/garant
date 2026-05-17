import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type {
  AdminDealDetailDto,
  AdminBalanceSnapshotDto,
} from "@/api/types";

/**
 * Tests for `/admin/deals/:id`.
 *
 * Covers status banner labels + colours, balance snapshot, ActionPanel
 * visibility gating by `me.is_admin`, force-release/refund/split
 * (terminal status disables actions), events timeline rendering, and
 * admin guard with allowArbiter=true.
 */

const mockState = vi.hoisted(() => ({
  deal: undefined as AdminDealDetailDto | undefined,
  loading: false,
  me: { id: 999, is_admin: true } as
    | { id: number; is_admin: boolean }
    | undefined,
  shouldRender: true as boolean,
  lastRedirectOpts: undefined as { allowArbiter?: boolean } | undefined,
  release: { mutateAsync: vi.fn() as ReturnType<typeof vi.fn>, isPending: false },
  refund: { mutateAsync: vi.fn() as ReturnType<typeof vi.fn>, isPending: false },
  split: { mutateAsync: vi.fn() as ReturnType<typeof vi.fn>, isPending: false },
  arb: { mutateAsync: vi.fn() as ReturnType<typeof vi.fn>, isPending: false },
  assign: { mutateAsync: vi.fn() as ReturnType<typeof vi.fn>, isPending: false },
  del: { mutateAsync: vi.fn() as ReturnType<typeof vi.fn>, isPending: false },
}));

vi.mock("@/api/admin/hooks", () => ({
  useAdminDeal: () => ({ data: mockState.deal, isLoading: mockState.loading }),
  useAdminForceRelease: () => mockState.release,
  useAdminForceRefund: () => mockState.refund,
  useAdminSplitDeal: () => mockState.split,
  useAdminForceArbitration: () => mockState.arb,
  useAdminAssignArbiter: () => mockState.assign,
  useAdminDeleteDeal: () => mockState.del,
}));

vi.mock("@/api/hooks", () => ({
  useMe: () => ({ data: mockState.me }),
}));

vi.mock("@/hooks/useAdminRedirect", () => ({
  useAdminRedirect: (opts?: { allowArbiter?: boolean }) => {
    mockState.lastRedirectOpts = opts;
    return { shouldRender: mockState.shouldRender };
  },
}));

const toastSpy = vi.hoisted(() => vi.fn());
vi.mock("@/components/ui/Toast", () => ({
  useToast: () => ({ show: toastSpy }),
}));

vi.mock("@/lib/tg", () => ({
  haptic: () => {},
  showBackButton: () => () => {},
}));

vi.mock("@/api/client", () => ({
  api: {
    get: () => ({
      json: async () => ({ items: [] }),
    }),
    post: () => ({
      json: async () => ({}),
    }),
  },
}));

import AdminDealDetailPage from "./AdminDealDetailPage";

function renderPage(id: number | string = "10") {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[`/admin/deals/${id}`]}>
        <Routes>
          <Route path="/admin/deals/:id" element={<AdminDealDetailPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function makeSnap(
  overrides: Partial<AdminBalanceSnapshotDto> = {},
): AdminBalanceSnapshotDto {
  return {
    user_id: 1,
    username: "alice",
    display_name: "Alice",
    currency_code: "USDT",
    amount: "10.0000",
    locked: "5.0000",
    total: "15.0000",
    ...overrides,
  };
}

function makeDeal(
  overrides: Partial<AdminDealDetailDto> = {},
): AdminDealDetailDto {
  return {
    id: 10,
    status: "in_progress",
    description: "Buying widgets",
    currency_code: "USDT",
    amount: "150.00",
    commission_amount: "3.00",
    pay_commission: "buyer",
    buyer: makeSnap({ user_id: 1, username: "buyer", display_name: "Buyer" }),
    seller: makeSnap({ user_id: 2, username: "seller", display_name: "Seller" }),
    created_at: "2026-01-01T00:00:00Z",
    in_progress_at: "2026-01-02T00:00:00Z",
    completed_at: null,
    cancellation_initiator: null,
    cancellation_reason: null,
    cancellation_requested_at: null,
    arbitration_initiator: null,
    arbitration_reason: null,
    arbitration_resolved_by_id: null,
    arbitration_resolved_by_username: null,
    arbitration_resolution: null,
    arbitration_resolved_at: null,
    confirm_buyer: false,
    confirm_seller: false,
    events: [
      {
        at: "2026-01-01T00:00:00Z",
        kind: "created",
        actor: "buyer",
        description: "Сделка создана",
      },
      {
        at: "2026-01-02T00:00:00Z",
        kind: "in_progress",
        actor: "seller",
        description: "Подтверждено",
      },
    ],
    messages: [],
    ...overrides,
  };
}

beforeEach(() => {
  mockState.deal = undefined;
  mockState.loading = false;
  mockState.me = { id: 999, is_admin: true };
  mockState.shouldRender = true;
  mockState.lastRedirectOpts = undefined;
  mockState.release = { mutateAsync: vi.fn(), isPending: false };
  mockState.refund = { mutateAsync: vi.fn(), isPending: false };
  mockState.split = { mutateAsync: vi.fn(), isPending: false };
  mockState.arb = { mutateAsync: vi.fn(), isPending: false };
  mockState.assign = { mutateAsync: vi.fn(), isPending: false };
  mockState.del = { mutateAsync: vi.fn(), isPending: false };
  toastSpy.mockClear();
});

describe("<AdminDealDetailPage />", () => {
  it("returns null when admin guard rejects the visitor", () => {
    mockState.shouldRender = false;
    renderPage();
    expect(screen.queryByText(/Сделка/)).not.toBeInTheDocument();
  });

  it("requests allowArbiter=true from useAdminRedirect", () => {
    mockState.deal = makeDeal();
    renderPage();
    expect(mockState.lastRedirectOpts).toEqual({ allowArbiter: true });
  });

  it("renders 'Неверный ID' when :id is not numeric", () => {
    renderPage("xyz");
    expect(screen.getByText("Неверный ID.")).toBeInTheDocument();
  });

  it("renders status banner with description + status label", () => {
    mockState.deal = makeDeal();
    renderPage();
    expect(screen.getByText("Buying widgets")).toBeInTheDocument();
    expect(screen.getAllByText("В работе").length).toBeGreaterThan(0);
  });

  it("renders balance snapshot for buyer + seller cards", () => {
    mockState.deal = makeDeal();
    renderPage();
    expect(screen.getByText("Покупатель")).toBeInTheDocument();
    expect(screen.getByText("Продавец")).toBeInTheDocument();
    expect(screen.getByText("Buyer")).toBeInTheDocument();
    expect(screen.getByText("Seller")).toBeInTheDocument();
    expect(screen.getByText("$150.00")).toBeInTheDocument();
  });

  it("shows arbitration-danger banner when status=arbitration with reason", () => {
    mockState.deal = makeDeal({
      status: "arbitration",
      arbitration_reason: "товар не пришёл",
    });
    renderPage();
    expect(
      screen.getByText(/Причина арбитража: товар не пришёл/),
    ).toBeInTheDocument();
  });

  it("hides ActionPanel when me.is_admin is false (arbiter view)", () => {
    mockState.me = { id: 999, is_admin: false };
    mockState.deal = makeDeal();
    renderPage();
    expect(
      screen.queryByRole("button", { name: /Принудительное завершение/ }),
    ).not.toBeInTheDocument();
  });

  it("renders all action buttons when me.is_admin is true", () => {
    mockState.deal = makeDeal();
    renderPage();
    expect(
      screen.getByRole("button", { name: /Принудительное завершение/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /Возврат покупателю/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /Сплит-выплата/i }),
    ).toBeInTheDocument();
  });

  it("opens release sheet, fires force-release with reason", async () => {
    mockState.deal = makeDeal();
    mockState.release.mutateAsync.mockResolvedValue({});
    const user = userEvent.setup();
    renderPage();
    await user.click(
      screen.getByRole("button", { name: /Принудительное завершение/i }),
    );
    const confirmBtns = await screen.findAllByRole("button", {
      name: /Подтвердить/i,
    });
    await user.click(confirmBtns[confirmBtns.length - 1]);
    await waitFor(() =>
      expect(mockState.release.mutateAsync).toHaveBeenCalledWith(
        expect.objectContaining({ dealId: 10 }),
      ),
    );
  });

  it("renders the events timeline with all event descriptions", () => {
    mockState.deal = makeDeal();
    renderPage();
    expect(screen.getByText("Создана")).toBeInTheDocument();
    expect(screen.getByText("Запущена")).toBeInTheDocument();
  });

  it("disables admin action buttons when status is terminal (completed)", () => {
    mockState.deal = makeDeal({ status: "completed" });
    renderPage();
    expect(
      screen.getByRole("button", { name: /Принудительное завершение/i }),
    ).toBeDisabled();
    expect(
      screen.getByRole("button", { name: /Возврат покупателю/i }),
    ).toBeDisabled();
  });
});
