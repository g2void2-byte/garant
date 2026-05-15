import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type {
  ServiceCommentDto,
  ServiceDetailDto,
  UserCardDto,
} from "@/api/types";

const serviceState = vi.hoisted(() => ({
  data: undefined as ServiceDetailDto | undefined,
  isLoading: false,
}));
const commentsState = vi.hoisted(() => ({ data: undefined as ServiceCommentDto[] | undefined }));
const meState = vi.hoisted(() => ({ data: undefined as UserCardDto | undefined }));

vi.mock("@/api/hooks", () => ({
  useServiceDetail: () => serviceState,
  useServiceComments: () => commentsState,
  useMe: () => meState,
  useCreateServiceComment: () => ({
    mutate: vi.fn(),
    mutateAsync: vi.fn(),
    isPending: false,
  }),
  useDeleteServiceComment: () => ({
    mutate: vi.fn(),
    mutateAsync: vi.fn(),
    isPending: false,
  }),
}));

vi.mock("@/lib/tg", () => ({
  openTelegramLink: vi.fn(),
  showBackButton: () => () => {},
  haptic: vi.fn(),
}));

import ServiceDetailPage from "./ServiceDetailPage";

function makeService(overrides: Partial<ServiceDetailDto> = {}): ServiceDetailDto {
  return {
    id: 7,
    owner_username: "bob",
    title: "Тестовый сервис",
    description: "Делаю красиво и быстро",
    price: 100,
    currency: "USD",
    status: "active",
    category: {
      id: 1,
      slug: "dev",
      name: "Разработка",
      icon_key: "code",
      services_count: 1,
    },
    created_at: "2026-01-01T00:00:00Z",
    owner: {
      id: 2,
      username: "bob",
      display_name: "Bob",
      photo_url: null,
      rating: 4.8,
      deals_count: 20,
      good: 18,
      bad: 2,
      is_admin: false,
      is_arbiter: false,
    },
    comments_count: 0,
    rating_avg: 4.5,
    rating_count: 10,
    ...overrides,
  };
}

function makeUser(overrides: Partial<UserCardDto> = {}): UserCardDto {
  return {
    id: 99,
    user_id: 99,
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
      <MemoryRouter initialEntries={[`/services/${id}`]}>
        <Routes>
          <Route path="/services/:id" element={<ServiceDetailPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  serviceState.data = undefined;
  serviceState.isLoading = false;
  commentsState.data = undefined;
  meState.data = makeUser();
});

describe("<ServiceDetailPage />", () => {
  it("renders skeletons while loading", () => {
    serviceState.isLoading = true;
    const { container } = renderAt(7);
    expect(container.querySelectorAll(".shimmer").length).toBeGreaterThan(0);
  });

  it("renders the service hero, owner and stats for another user's service", () => {
    serviceState.data = makeService();
    commentsState.data = [];
    renderAt(7);
    expect(screen.getByRole("heading", { name: "Тестовый сервис" })).toBeInTheDocument();
    expect(screen.getByText("Делаю красиво и быстро")).toBeInTheDocument();
    expect(screen.getByText("Bob")).toBeInTheDocument();
    expect(screen.getByText(/@bob/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Сделка/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Написать/i })).toBeInTheDocument();
  });

  it("hides 'Сделка/Написать' when viewing one's own service", () => {
    meState.data = makeUser({ username: "bob" });
    serviceState.data = makeService();
    commentsState.data = [];
    renderAt(7);
    expect(screen.queryByRole("button", { name: /Сделка/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Написать/i })).not.toBeInTheDocument();
  });

  it("renders the rating + comments stat tiles", () => {
    serviceState.data = makeService({ rating_avg: 4.5, rating_count: 10, comments_count: 3 });
    commentsState.data = [];
    renderAt(7);
    expect(screen.getByText("Рейтинг")).toBeInTheDocument();
    expect(screen.getAllByText("Комментарии").length).toBeGreaterThan(0);
    expect(screen.getAllByText("4.5").length).toBeGreaterThan(0);
    expect(screen.getByText("3")).toBeInTheDocument();
  });

  it("renders the description block when present", () => {
    serviceState.data = makeService({ description: "Очень длинное описание" });
    commentsState.data = [];
    renderAt(7);
    expect(screen.getByText("Очень длинное описание")).toBeInTheDocument();
    expect(screen.getByText("Описание")).toBeInTheDocument();
  });
});
