import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { DealDto, ReviewDto, UserCardDto } from "@/api/types";

const dealState = vi.hoisted(() => ({
  data: undefined as DealDto | undefined,
  isLoading: false,
  lastId: undefined as number | undefined,
}));
const meState = vi.hoisted(() => ({ data: undefined as UserCardDto | undefined }));
const reviewsState = vi.hoisted(() => ({ data: undefined as ReviewDto[] | undefined }));
const reviewsCall = vi.hoisted(() => ({
  username: undefined as string | undefined,
  params: undefined as unknown,
}));
const actionStub = vi.hoisted(() => () => ({
  mutate: vi.fn(),
  mutateAsync: vi.fn(),
  isPending: false,
}));
const cancelTopupState = vi.hoisted(() => ({
  mutateAsync: vi.fn() as ReturnType<typeof vi.fn>,
  isPending: false,
}));

vi.mock("@/api/hooks", () => ({
  useDeal: (id: number | undefined) => {
    dealState.lastId = id;
    return dealState;
  },
  useMe: () => meState,
  useReviews: (username: string | undefined, params: unknown) => {
    reviewsCall.username = username;
    reviewsCall.params = params;
    return reviewsState;
  },
  useDealAction: () => actionStub(),
  useCancelPendingTopup: () => cancelTopupState,
  useCreateReview: () => actionStub(),
  useWalletDeposit: () => ({ data: undefined, isLoading: false }),
}));

vi.mock("@/lib/tg", () => ({
  useTelegramViewport: () => null,
  haptic: vi.fn(),
  openTelegramLink: vi.fn(),
  openPaymentLink: vi.fn(),
  showBackButton: () => () => {},
}));

vi.mock("./DealChatPanel", () => ({
  DealChatPanel: () => null,
}));

import DealDetailPage from "./DealDetailPage";
import { ToastProvider } from "@/components/ui/Toast";

function makeDeal(overrides: Partial<DealDto> = {}): DealDto {
  return {
    id: 42,
    buyer: "alice",
    seller: "bob",
    description: "Лендинг под ключ",
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
    commission_paid: true,
    topup_deposit_id: null,
    topup_invoice: null,
    payment_provider: "cryptobot",
    ...overrides,
  };
}

function makeUser(overrides: Partial<UserCardDto> = {}): UserCardDto {
  return {
    id: 1,
    user_id: 1,
    username: "alice",
    display_name: "Alice",
    photo_url: null,
    admin: 0,
    prefix: null,
    good: 0,
    bad: 0,
    deposit: 0,
    rating: 5,
    reviews_count: 0,
    deals_count: 0,
    deals_success: 0,
    deals_failed: 0,
    deals_arbitrage: 0,
    deals_sum: 0,
    online: true,
    description: "",
    forums: [],
    ...overrides,
  };
}

function makeReview(overrides: Partial<ReviewDto> = {}): ReviewDto {
  return {
    id: 501,
    deal_id: 42,
    author_username: "alice",
    target_username: "bob",
    rating: 5,
    text: "ok",
    created_at: "2026-01-02T00:00:00Z",
    ...overrides,
  };
}

function renderAt(id: number | string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <ToastProvider>
        <MemoryRouter initialEntries={[`/deals/${id}`]}>
          <Routes>
            <Route path="/deals/:id" element={<DealDetailPage />} />
          </Routes>
        </MemoryRouter>
      </ToastProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  dealState.data = undefined;
  dealState.isLoading = false;
  dealState.lastId = undefined;
  meState.data = makeUser({ username: "alice" });
  reviewsState.data = [];
  reviewsCall.username = undefined;
  reviewsCall.params = undefined;
  cancelTopupState.mutateAsync = vi.fn().mockResolvedValue(makeDeal({ status: "cancelled" }));
  cancelTopupState.isPending = false;
});

describe("<DealDetailPage />", () => {
  it("rejects ambiguous route ids before querying the deal detail", () => {
    renderAt("1e2");
    expect(dealState.lastId).toBeUndefined();
    expect(screen.getByText("Сделка не найдена")).toBeInTheDocument();
  });

  it("renders skeletons while the deal is loading", () => {
    dealState.isLoading = true;
    const { container } = renderAt(42);
    expect(container.querySelectorAll(".shimmer").length).toBeGreaterThan(0);
  });

  it("renders the deal header, counterparty and core details", () => {
    dealState.data = makeDeal({ id: 42, buyer: "alice", seller: "bob", role: "buyer" });
    renderAt(42);
    expect(screen.getByRole("heading", { name: /Сделка #42/ })).toBeInTheDocument();
    expect(screen.getByText("@bob")).toBeInTheDocument();
    expect(screen.getByText("Лендинг под ключ")).toBeInTheDocument();
    expect(screen.getByText("Комиссия оплачена")).toBeInTheDocument();
  });

  it("does not render @null actions when the counterparty username is missing", () => {
    dealState.data = makeDeal({
      id: 42,
      buyer: "alice",
      seller: null,
      role: "buyer",
      status: "completed",
    });
    renderAt(42);
    expect(screen.getByText("Контрагент недоступен")).toBeInTheDocument();
    expect(screen.queryByText("@null")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Оставить отзыв/i })).not.toBeInTheDocument();
    expect(reviewsCall.username).toBeUndefined();
  });

  it("does not render profile or review actions for unsafe counterparty usernames", () => {
    dealState.data = makeDeal({
      id: 42,
      buyer: "alice",
      seller: "../admin",
      role: "buyer",
      status: "completed",
    });
    renderAt(42);
    expect(screen.queryByText("@../admin")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /admin/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /\u041e\u0441\u0442\u0430\u0432\u0438\u0442\u044c \u043e\u0442\u0437\u044b\u0432/i })).not.toBeInTheDocument();
    expect(reviewsCall.username).toBeUndefined();
  });

  it("shows the 'confirm execution' CTA for buyer on an in-progress deal", () => {
    dealState.data = makeDeal({ status: "in_progress", role: "buyer" });
    renderAt(42);
    expect(screen.getByRole("button", { name: /Подтвердить исполнение/i })).toBeInTheDocument();
  });

  it("shows a topup invoice banner and cancel CTA for buyer on pending_topup", () => {
    dealState.data = makeDeal({
      status: "pending_topup",
      role: "buyer",
      commission_paid: false,
      topup_deposit_id: 501,
      topup_invoice: {
        deposit_id: 501,
        pay_url: "https://pay.example/invoice/501",
        total: 105,
        topup_principal: 100,
        commission: 5,
        paid_total: 0,
        currency_code: "USD",
        provider: "cryptobot",
        expires_at: null,
      },
    });
    renderAt(42);
    expect(screen.getAllByText("Ожидает оплаты инвойса")[0]).toBeInTheDocument();
    expect(screen.getByText("105 USD")).toBeInTheDocument();
    expect(screen.getByText(/Оплатите инвойс, чтобы сделка активировалась/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Открыть оплату/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^Отменить$/i })).toBeInTheDocument();
  });

  it("does not append currency to topup invoice metadata or show malformed paid totals", () => {
    dealState.data = makeDeal({
      status: "pending_topup",
      role: "buyer",
      commission_paid: false,
      topup_deposit_id: 501,
      topup_invoice: {
        deposit_id: 501,
        pay_url: "https://pay.example/invoice/501",
        total: 105,
        topup_principal: 100,
        commission: 5,
        paid_total: "0x10",
        currency_code: "USD",
        provider: "cryptobot",
        expires_at: "2026-01-01T00:00:00Z",
      } as unknown as NonNullable<DealDto["topup_invoice"]>,
    });
    renderAt(42);

    expect(screen.getByText("CryptoBot")).toBeInTheDocument();
    expect(screen.queryByText("CryptoBot USD")).not.toBeInTheDocument();
    expect(screen.queryByText("0x10 USD")).not.toBeInTheDocument();
  });

  it("renders malformed topup invoice expiry as a neutral timestamp", () => {
    dealState.data = makeDeal({
      status: "pending_topup",
      role: "buyer",
      commission_paid: false,
      topup_deposit_id: 501,
      topup_invoice: {
        deposit_id: 501,
        pay_url: "https://pay.example/invoice/501",
        total: 105,
        topup_principal: 100,
        commission: 5,
        paid_total: 0,
        currency_code: "USD",
        provider: "cryptobot",
        expires_at: "not-a-date",
      },
    });
    renderAt(42);

    expect(screen.getByText("\u2014")).toBeInTheDocument();
    expect(screen.queryByText(/Invalid Date/)).not.toBeInTheDocument();
  });

  it("shows the accept/decline CTAs for seller on a pending_confirmation deal", () => {
    dealState.data = makeDeal({ status: "pending_confirmation", role: "seller" });
    renderAt(42);
    expect(screen.getByRole("button", { name: /Принять/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Отклонить/i })).toBeInTheDocument();
  });

  it("checks review status with a deal-scoped reviews query", () => {
    dealState.data = makeDeal({
      id: 77,
      buyer: "alice",
      seller: "bob",
      role: "buyer",
      status: "completed",
    });

    renderAt(77);

    expect(reviewsCall.username).toBe("bob");
    expect(reviewsCall.params).toEqual({ deal_id: 77, limit: 1 });
    expect(screen.getByRole("button", { name: /Оставить отзыв/i })).toBeInTheDocument();
  });

  it("hides the review CTA when the deal-scoped query returns my review", () => {
    dealState.data = makeDeal({
      id: 77,
      buyer: "alice",
      seller: "bob",
      role: "buyer",
      status: "completed",
    });
    reviewsState.data = [makeReview({ deal_id: 77, author_username: "alice" })];

    renderAt(77);

    expect(screen.queryByRole("button", { name: /Оставить отзыв/i })).not.toBeInTheDocument();
    expect(screen.getByText(/уже оставили отзыв/i)).toBeInTheDocument();
  });

  it("renders the arbitration reason when status is arbitration", () => {
    dealState.data = makeDeal({
      status: "arbitration",
      arbitration_initiator: "buyer",
      arbitration_reason: "Не доставлен товар",
    });
    renderAt(42);
    expect(screen.getByText("Причина арбитража")).toBeInTheDocument();
    expect(screen.getByText("Не доставлен товар")).toBeInTheDocument();
  });
});
