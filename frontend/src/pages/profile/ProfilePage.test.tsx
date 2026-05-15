import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReviewDto, ServiceDto, UserCardDto } from "@/api/types";

const meState = vi.hoisted(() => ({
  data: undefined as UserCardDto | undefined,
  isLoading: false,
}));
const servicesState = vi.hoisted(() => ({ data: undefined as ServiceDto[] | undefined }));
const reviewsState = vi.hoisted(() => ({ data: undefined as ReviewDto[] | undefined }));
const updateMutate = vi.hoisted(() => vi.fn());
const deleteMutate = vi.hoisted(() => vi.fn());

vi.mock("@/api/hooks", () => ({
  useMe: () => meState,
  useServices: () => servicesState,
  useReviews: () => reviewsState,
  useUpdateService: () => ({ mutate: updateMutate }),
  useDeleteService: () => ({ mutate: deleteMutate }),
}));

vi.mock("@/lib/tg", () => ({
  haptic: vi.fn(),
  showBackButton: () => () => {},
  openTelegramLink: vi.fn(),
}));

import ProfilePage from "./ProfilePage";

function makeUser(overrides: Partial<UserCardDto> = {}): UserCardDto {
  return {
    id: 1,
    user_id: 1,
    username: "me",
    display_name: "Me",
    photo_url: null,
    balance: 0,
    admin: 0,
    prefix: null,
    good: 5,
    bad: 0,
    deposit: 0,
    rating: 5,
    reviews_count: 0,
    deals_count: 10,
    deals_sum: 1000,
    online: true,
    description: "",
    forums: [],
    ...overrides,
  };
}

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <ProfilePage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  meState.data = undefined;
  meState.isLoading = false;
  servicesState.data = undefined;
  reviewsState.data = undefined;
  updateMutate.mockReset();
  deleteMutate.mockReset();
});

describe("<ProfilePage />", () => {
  it("renders skeletons while 'me' is loading", () => {
    meState.isLoading = true;
    const { container } = renderPage();
    expect(container.querySelectorAll(".shimmer").length).toBeGreaterThan(0);
  });

  it("renders the main CTAs for a normal user", () => {
    meState.data = makeUser();
    servicesState.data = [];
    reviewsState.data = [];
    renderPage();
    expect(screen.getByRole("button", { name: /Добавить услугу/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^Депозит$/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Настройки/i })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Админ-панель/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Очередь арбитража/i })).not.toBeInTheDocument();
  });

  it("renders the admin CTA when the user is an admin", () => {
    meState.data = makeUser({ is_admin: true });
    servicesState.data = [];
    reviewsState.data = [];
    renderPage();
    expect(screen.getByRole("button", { name: /Админ-панель/i })).toBeInTheDocument();
  });

  it("renders the arbiter CTA when the user is an arbiter but not admin", () => {
    meState.data = makeUser({ is_admin: false, is_arbiter: true });
    servicesState.data = [];
    reviewsState.data = [];
    renderPage();
    expect(screen.getByRole("button", { name: /Очередь арбитража/i })).toBeInTheDocument();
  });

  it("renders the empty state when the user has no services", () => {
    meState.data = makeUser();
    servicesState.data = [];
    reviewsState.data = [];
    renderPage();
    expect(screen.getByText("Услуги отсутствуют")).toBeInTheDocument();
  });
});
