import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { DealDto, ReviewDto, UserCardDto } from "@/api/types";

const dealState = vi.hoisted(() => ({
  data: undefined as DealDto | undefined,
  isLoading: false,
}));
const meState = vi.hoisted(() => ({ data: undefined as UserCardDto | undefined }));
const reviewsState = vi.hoisted(() => ({ data: undefined as ReviewDto[] | undefined }));
const actionStub = vi.hoisted(() => () => ({
  mutate: vi.fn(),
  mutateAsync: vi.fn(),
  isPending: false,
}));

vi.mock("@/api/hooks", () => ({
  useDeal: () => dealState,
  useMe: () => meState,
  useReviews: () => reviewsState,
  useDealAction: () => actionStub(),
  useCreateReview: () => actionStub(),
}));

vi.mock("@/lib/tg", () => ({
  haptic: vi.fn(),
  openTelegramLink: vi.fn(),
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
    sum: 100,
    description: "Лендинг под ключ",
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

function makeUser(overrides: Partial<UserCardDto> = {}): UserCardDto {
  return {
    id: 1,
    user_id: 1,
    username: "alice",
    display_name: "Alice",
    photo_url: null,
    balance: 0,
    admin: 0,
    prefix: null,
    good: 0,
    bad: 0,
    deposit: 0,
    rating: 5,
    reviews_count: 0,
    deals_count: 0,
    deals_sum: 0,
    online: true,
    description: "",
    forums: [],
    ...overrides,
  };
}

function renderAt(id: number) {
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
  meState.data = makeUser({ username: "alice" });
  reviewsState.data = [];
});

describe("<DealDetailPage />", () => {
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
    expect(screen.getByText("Покупатель")).toBeInTheDocument();
  });

  it("shows the 'confirm execution' CTA for buyer on an in-progress deal", () => {
    dealState.data = makeDeal({ status: "in_progress", role: "buyer" });
    renderAt(42);
    expect(screen.getByRole("button", { name: /Подтвердить исполнение/i })).toBeInTheDocument();
  });

  it("shows the accept/decline CTAs for seller on a pending_confirmation deal", () => {
    dealState.data = makeDeal({ status: "pending_confirmation", role: "seller" });
    renderAt(42);
    expect(screen.getByRole("button", { name: /Принять/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Отклонить/i })).toBeInTheDocument();
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
