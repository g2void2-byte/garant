import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReviewDto, ServiceDto, UserCardDto } from "@/api/types";

const meState = vi.hoisted(() => ({ data: undefined as UserCardDto | undefined }));
const userState = vi.hoisted(() => ({
  data: undefined as UserCardDto | undefined,
  isLoading: false,
  lastUsername: undefined as string | undefined,
}));
const servicesState = vi.hoisted(() => ({
  data: undefined as ServiceDto[] | undefined,
  lastParams: undefined as unknown,
  lastOptions: undefined as unknown,
}));
const reviewsState = vi.hoisted(() => ({
  data: undefined as ReviewDto[] | undefined,
  lastParams: undefined as unknown,
  lastUsername: undefined as string | undefined,
}));
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
  useUser: (username: string | undefined) => {
    userState.lastUsername = username;
    return userState;
  },
  useServices: (params: unknown, options: unknown) => {
    servicesState.lastParams = params;
    servicesState.lastOptions = options;
    return { data: servicesState.data };
  },
  useReviews: (username: string | undefined, params: unknown) => {
    reviewsState.lastUsername = username;
    reviewsState.lastParams = params;
    return { data: reviewsState.data };
  },
}));

vi.mock("@/lib/tg", () => ({
  useTelegramViewport: () => null,
  openTelegramLink: vi.fn(),
  openExternalLink: vi.fn(),
  showBackButton: () => () => {},
  haptic: vi.fn(),
  getTelegramUser: () => undefined,
}));

import UserProfilePage from "./UserProfilePage";

function makeUser(overrides: Partial<UserCardDto> = {}): UserCardDto {
  return {
    id: 1,
    user_id: 1,
    username: "alice",
    display_name: "Alice",
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
    target_username: "alice",
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
    owner_username: "alice",
    created_at: "2026-01-01T00:00:00Z",
    category: { id: 10, name: "Development", slug: "dev", icon_key: "code", services_count: 60 },
    ...overrides,
  };
}

function renderAt(username: string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[`/u/${username}`]}>
        <Routes>
          <Route path="/u/:username" element={<UserProfilePage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  apiGetMock.mockReset();
  meState.data = makeUser({ id: 99, user_id: 99, username: "me" });
  userState.data = undefined;
  userState.isLoading = false;
  userState.lastUsername = undefined;
  servicesState.data = undefined;
  servicesState.lastParams = undefined;
  servicesState.lastOptions = undefined;
  reviewsState.data = undefined;
  reviewsState.lastParams = undefined;
  reviewsState.lastUsername = undefined;
});

describe("<UserProfilePage />", () => {
  it("rejects unsafe route usernames before public profile queries", () => {
    renderAt("..%2Fadmin");
    expect(screen.getByText(/\u041f\u043e\u043b\u044c\u0437\u043e\u0432\u0430\u0442\u0435\u043b\u044c \u043d\u0435 \u043d\u0430\u0439\u0434\u0435\u043d/)).toBeInTheDocument();
    expect(userState.lastUsername).toBeUndefined();
    expect(servicesState.lastOptions).toEqual({ enabled: false });
    expect(reviewsState.lastUsername).toBeUndefined();
  });

  it("renders skeletons while the user is loading", () => {
    userState.isLoading = true;
    const { container } = renderAt("alice");
    expect(container.querySelectorAll(".shimmer").length).toBeGreaterThan(0);
    expect(screen.queryByText("Alice")).not.toBeInTheDocument();
  });

  it("renders the profile, action buttons and empty service list for another user", () => {
    userState.data = makeUser({ username: "alice", display_name: "Alice" });
    servicesState.data = [];
    reviewsState.data = [];
    renderAt("alice");
    expect(screen.getAllByText(/Alice/).length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: /Сделка/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Написать/i })).toBeInTheDocument();
    expect(screen.getByText("Услуги отсутствуют")).toBeInTheDocument();
  });

  it("hides 'Сделка/Написать' actions when viewing one's own profile", () => {
    meState.data = makeUser({ username: "alice" });
    userState.data = makeUser({ username: "alice" });
    servicesState.data = [];
    reviewsState.data = [];
    renderAt("alice");
    expect(screen.queryByRole("button", { name: /Сделка/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Написать/i })).not.toBeInTheDocument();
  });

  it("disables deal and Telegram actions when the public username is missing", () => {
    userState.data = makeUser({ username: null, display_name: "Alice" });
    servicesState.data = [];
    reviewsState.data = [];
    renderAt("alice");
    expect(screen.getByText("username не задан")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Сделка/i })).toBeDisabled();
    expect(screen.getByRole("button", { name: /Написать/i })).toBeDisabled();
    expect(screen.queryByText("@null")).not.toBeInTheDocument();
  });

  it("renders the empty reviews state when the reviews tab has no data", () => {
    userState.data = makeUser({ username: "alice" });
    servicesState.data = [];
    reviewsState.data = [];
    renderAt("alice");
    expect(screen.getByText("Услуги отсутствуют")).toBeInTheDocument();
  });

  it("requests the first reviews page", () => {
    userState.data = makeUser({ username: "alice", reviews_count: 0 });
    servicesState.data = [];
    reviewsState.data = [];
    renderAt("alice");
    expect(reviewsState.lastParams).toEqual({ limit: 50, offset: 0 });
  });

  it("renders malformed public review ratings as a neutral dash", async () => {
    userState.data = makeUser({ username: "alice", reviews_count: 1 });
    servicesState.data = [];
    reviewsState.data = [makeReview(1, { rating: "1e1" as unknown as number })];
    const user = userEvent.setup();

    renderAt("alice");
    await user.click(screen.getByRole("button", { name: /\u041e\u0442\u0437\u044b\u0432\u044b/i }));

    expect(screen.getByText(/\u2605 \u2014/)).toBeInTheDocument();
    expect(screen.queryByText(/\u2605 0\.0/)).not.toBeInTheDocument();
  });

  it("requests the first services page", () => {
    userState.data = makeUser({ username: "alice" });
    servicesState.data = [];
    reviewsState.data = [];
    renderAt("alice");
    expect(servicesState.lastParams).toEqual({ owner: "alice", limit: 50, offset: 0 });
  });

  it("loads more public-profile services with the backend offset", async () => {
    userState.data = makeUser({ username: "alice" });
    servicesState.data = Array.from({ length: 50 }, (_, idx) => makeService(idx + 1));
    reviewsState.data = [];
    apiGetMock.mockReturnValue({ json: async () => [makeService(51)] });

    const user = userEvent.setup();
    renderAt("alice");
    await user.click(screen.getByRole("button", { name: "Показать еще" }));

    await waitFor(() => expect(apiGetMock).toHaveBeenCalledTimes(1));
    expect(apiGetMock).toHaveBeenCalledWith("api/services", {
      searchParams: { owner: "alice", limit: "50", offset: "50" },
    });
  });

  it("loads more public-profile reviews with the backend offset", async () => {
    userState.data = makeUser({ username: "alice", reviews_count: 51 });
    servicesState.data = [];
    reviewsState.data = Array.from({ length: 50 }, (_, idx) => makeReview(idx + 1));
    apiGetMock.mockReturnValue({ json: async () => [makeReview(51)] });

    const user = userEvent.setup();
    renderAt("alice");
    await user.click(screen.getByRole("button", { name: /Отзывы/i }));
    await user.click(screen.getByRole("button", { name: "Показать еще" }));

    await waitFor(() => expect(apiGetMock).toHaveBeenCalledTimes(1));
    expect(apiGetMock).toHaveBeenCalledWith("api/reviews", {
      searchParams: { user: "alice", limit: "50", offset: "50" },
    });
  });
});
