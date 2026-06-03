import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
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
  lastId: undefined as number | undefined,
}));
const commentsState = vi.hoisted(() => ({
  data: undefined as ServiceCommentDto[] | undefined,
  lastParams: undefined as unknown,
}));
const meState = vi.hoisted(() => ({ data: undefined as UserCardDto | undefined }));
const apiGetMock = vi.hoisted(() => vi.fn());

vi.mock("@/api/client", () => ({
  api: { get: apiGetMock },
}));

vi.mock("@/api/hooks", () => ({
  buildServiceCommentsSearchParams: (params: { limit?: number; offset?: number }) => {
    const searchParams: Record<string, string> = {};
    if (params.limit !== undefined) searchParams.limit = String(params.limit);
    if (params.offset !== undefined) searchParams.offset = String(params.offset);
    return searchParams;
  },
  useServiceDetail: (id: number | undefined) => {
    serviceState.lastId = id;
    return serviceState;
  },
  useServiceComments: (_id: number | undefined, params: unknown) => {
    commentsState.lastParams = params;
    return { data: commentsState.data };
  },
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
  useTelegramViewport: () => null,
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

function makeComment(id: number, overrides: Partial<ServiceCommentDto> = {}): ServiceCommentDto {
  return {
    id,
    service_id: 7,
    author_id: 100 + id,
    author_username: `commenter${id}`,
    author_display_name: `Commenter ${id}`,
    author_photo_url: null,
    text: `Comment ${id}`,
    rating: 5,
    created_at: `2026-01-${String(Math.min(id, 28)).padStart(2, "0")}T00:00:00Z`,
    ...overrides,
  };
}

function renderAt(id: number | string) {
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
  apiGetMock.mockReset();
  serviceState.data = undefined;
  serviceState.isLoading = false;
  serviceState.lastId = undefined;
  commentsState.data = undefined;
  commentsState.lastParams = undefined;
  meState.data = makeUser();
});

describe("<ServiceDetailPage />", () => {
  it("rejects ambiguous route ids before querying the service detail", () => {
    renderAt("1e2");
    expect(serviceState.lastId).toBeUndefined();
    expect(screen.getByText("Услуга не найдена")).toBeInTheDocument();
  });

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

  it("filters unsafe service gallery image URLs before rendering", () => {
    serviceState.data = makeService({
      photo_urls: [
        "/media/service/ok.png",
        "javascript:alert(1)",
        "/media/../admin/deals",
      ],
    });
    commentsState.data = [];
    const { container } = renderAt(7);

    const images = Array.from(container.querySelectorAll("img"));
    expect(images).toHaveLength(1);
    expect(images[0].getAttribute("src")).toBe("/media/service/ok.png");
  });

  it("does not build owner links or actions when the owner username is missing", () => {
    serviceState.data = makeService({
      owner_username: null,
      owner: {
        id: 2,
        username: null,
        display_name: "Bob",
        photo_url: null,
        rating: 4.8,
        deals_count: 20,
        good: 18,
        bad: 2,
        is_admin: false,
        is_arbiter: false,
      },
    });
    commentsState.data = [];
    renderAt(7);
    expect(screen.getByText("Bob")).toBeInTheDocument();
    expect(screen.getByText(/Профиль недоступен/)).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Bob/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Сделка/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Написать/i })).not.toBeInTheDocument();
  });

  it("does not build owner links or actions for unsafe owner usernames", () => {
    serviceState.data = makeService({
      owner_username: "../admin",
      owner: {
        id: 2,
        username: "../admin",
        display_name: "Bob",
        photo_url: null,
        rating: 4.8,
        deals_count: 20,
        good: 18,
        bad: 2,
        is_admin: false,
        is_arbiter: false,
      },
    });
    commentsState.data = [];
    renderAt(7);
    expect(screen.getByText("Bob")).toBeInTheDocument();
    expect(screen.queryByText("@../admin")).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Bob/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /\u0421\u0434\u0435\u043b\u043a\u0430/i })).not.toBeInTheDocument();
  });

  it("does not build profile routes for unsafe comment author usernames", () => {
    serviceState.data = makeService();
    commentsState.data = [makeComment(1, { author_username: "../admin", author_display_name: "Mallory" })];
    renderAt(7);
    expect(screen.getByText("Mallory")).toBeInTheDocument();
    const unsafeLinks = screen
      .getAllByRole("link")
      .filter((link) => link.getAttribute("href")?.includes("../admin"));
    expect(unsafeLinks).toHaveLength(0);
  });

  it("requests the first comments page", () => {
    serviceState.data = makeService();
    commentsState.data = [];
    renderAt(7);
    expect(commentsState.lastParams).toEqual({ limit: 50, offset: 0 });
  });

  it("loads more comments with the backend offset", async () => {
    serviceState.data = makeService({ comments_count: 51 });
    commentsState.data = Array.from({ length: 50 }, (_, idx) => makeComment(idx + 1));
    apiGetMock.mockReturnValue({ json: async () => [makeComment(51)] });

    const user = userEvent.setup();
    renderAt(7);
    await user.click(screen.getByRole("button", { name: "Показать еще" }));

    await waitFor(() => expect(apiGetMock).toHaveBeenCalledTimes(1));
    expect(apiGetMock).toHaveBeenCalledWith("api/services/7/comments", {
      searchParams: { limit: "50", offset: "50" },
    });
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
