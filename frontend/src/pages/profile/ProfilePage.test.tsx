import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReviewDto, ServiceDto, UserCardDto } from "@/api/types";

const meState = vi.hoisted(() => ({
  data: undefined as UserCardDto | undefined,
  isLoading: false,
}));
const servicesState = vi.hoisted(() => ({
  data: undefined as ServiceDto[] | undefined,
  lastParams: undefined as unknown,
}));
const reviewsState = vi.hoisted(() => ({
  data: undefined as ReviewDto[] | undefined,
  lastParams: undefined as unknown,
}));
const updateMutate = vi.hoisted(() => vi.fn());
const deleteMutate = vi.hoisted(() => vi.fn());
const apiGetMock = vi.hoisted(() => vi.fn());

vi.mock("@/api/client", () => ({
  api: { get: apiGetMock },
}));

vi.mock("@/api/hooks", () => ({
  buildReviewsSearchParams: (username: string, params: { limit?: number; offset?: number }) => {
    const searchParams: Record<string, string> = { user: username };
    if (params.limit !== undefined) searchParams.limit = String(params.limit);
    if (params.offset !== undefined) searchParams.offset = String(params.offset);
    return searchParams;
  },
  buildServicesSearchParams: (params: { owner?: string; limit?: number; offset?: number }) => {
    const searchParams: Record<string, string> = {};
    if (params.owner) searchParams.owner = params.owner;
    if (params.limit !== undefined) searchParams.limit = String(params.limit);
    if (params.offset !== undefined) searchParams.offset = String(params.offset);
    return searchParams;
  },
  useMe: () => meState,
  useServices: (params: unknown) => {
    servicesState.lastParams = params;
    return { data: servicesState.data };
  },
  useReviews: (_username: string | undefined, params: unknown) => {
    reviewsState.lastParams = params;
    return { data: reviewsState.data };
  },
  useUpdateService: () => ({ mutate: updateMutate }),
  useDeleteService: () => ({ mutate: deleteMutate }),
  // Item 13 — ProfileFiatBalanceCard reads fiat balances. The test
  // doesn't care about the values, but the mock has to exist so the
  // component renders without throwing.
  useWalletBalances: () => ({ data: [], isLoading: false }),
}));

vi.mock("@/lib/tg", () => ({
  useTelegramViewport: () => null,
  haptic: vi.fn(),
  showBackButton: () => () => {},
  openTelegramLink: vi.fn(),
  openExternalLink: vi.fn(),
  getTelegramUser: () => undefined,
}));

import ProfilePage from "./ProfilePage";

function makeUser(overrides: Partial<UserCardDto> = {}): UserCardDto {
  return {
    id: 1,
    user_id: 1,
    username: "me",
    display_name: "Me",
    photo_url: null,
    admin: 0,
    prefix: null,
    good: 5,
    bad: 0,
    deposit: 0,
    rating: 5,
    reviews_count: 0,
    deals_count: 10,
    deals_success: 10,
    deals_failed: 0,
    deals_arbitrage: 0,
    deals_sum: 1000,
    online: true,
    description: "",
    forums: [],
    ...overrides,
  };
}

function makeReview(id: number, overrides: Partial<ReviewDto> = {}): ReviewDto {
  return {
    id,
    deal_id: 1000 + id,
    author_username: `author${id}`,
    target_username: "me",
    rating: 5,
    text: `Review ${id}`,
    created_at: `2026-01-${String(Math.min(id, 28)).padStart(2, "0")}T00:00:00Z`,
    ...overrides,
  };
}

function makeService(id: number, overrides: Partial<ServiceDto> = {}): ServiceDto {
  return {
    id,
    title: `Service ${id}`,
    description: "Service description",
    price: 100,
    currency: "USD",
    status: "active",
    owner_username: "me",
    created_at: "2026-01-01T00:00:00Z",
    category: { id: 10, name: "Development", slug: "dev", icon_key: "code", services_count: 60 },
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
  apiGetMock.mockReset();
  meState.data = undefined;
  meState.isLoading = false;
  servicesState.data = undefined;
  servicesState.lastParams = undefined;
  reviewsState.data = undefined;
  reviewsState.lastParams = undefined;
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

  it("requests the first reviews page", () => {
    meState.data = makeUser({ reviews_count: 0 });
    servicesState.data = [];
    reviewsState.data = [];
    renderPage();
    expect(reviewsState.lastParams).toEqual({ limit: 50, offset: 0 });
  });

  it("renders malformed own review ratings as a neutral dash", async () => {
    meState.data = makeUser({ username: "me", reviews_count: 1 });
    servicesState.data = [];
    reviewsState.data = [makeReview(1, { rating: "1e1" as unknown as number })];
    const user = userEvent.setup();

    renderPage();
    await user.click(screen.getByRole("button", { name: /\u041e\u0442\u0437\u044b\u0432\u044b/i }));

    expect(screen.getByText(/\u2605 \u2014/)).toBeInTheDocument();
    expect(screen.queryByText(/\u2605 0\.0/)).not.toBeInTheDocument();
  });

  it("requests the first services page", () => {
    meState.data = makeUser({ username: "me" });
    servicesState.data = [];
    reviewsState.data = [];
    renderPage();
    expect(servicesState.lastParams).toEqual({ owner: "me", limit: 50, offset: 0 });
  });

  it("loads more own services with the backend offset", async () => {
    meState.data = makeUser({ username: "me" });
    servicesState.data = Array.from({ length: 50 }, (_, idx) => makeService(idx + 1));
    reviewsState.data = [];
    apiGetMock.mockReturnValue({ json: async () => [makeService(51)] });

    const user = userEvent.setup();
    renderPage();
    await user.click(screen.getByRole("button", { name: "Показать еще" }));

    await waitFor(() => expect(apiGetMock).toHaveBeenCalledTimes(1));
    expect(apiGetMock).toHaveBeenCalledWith("api/services", {
      searchParams: { owner: "me", limit: "50", offset: "50" },
    });
  });

  it("loads more own reviews with the backend offset", async () => {
    meState.data = makeUser({ username: "me", reviews_count: 51 });
    servicesState.data = [];
    reviewsState.data = Array.from({ length: 50 }, (_, idx) => makeReview(idx + 1));
    apiGetMock.mockReturnValue({ json: async () => [makeReview(51)] });

    const user = userEvent.setup();
    renderPage();
    await user.click(screen.getByRole("button", { name: /Отзывы/i }));
    await user.click(screen.getByRole("button", { name: "Показать еще" }));

    await waitFor(() => expect(apiGetMock).toHaveBeenCalledTimes(1));
    expect(apiGetMock).toHaveBeenCalledWith("api/reviews", {
      searchParams: { user: "me", limit: "50", offset: "50" },
    });
  });
});
