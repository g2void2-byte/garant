import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { UserCardDto, CategoryDto, ServiceDto } from "@/api/types";

const makeUser = vi.hoisted(() => (overrides: Partial<UserCardDto> = {}): UserCardDto => {
  return {
    id: 1,
    user_id: 1,
    username: "alice",
    display_name: "Alice",
    photo_url: null,
    banner_url: null,
    admin: 0,
    prefix: null,
    good: 5,
    bad: 0,
    deposit: 0,
    rating: 5,
    reviews_count: 5,
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
});

const meState = vi.hoisted(() => ({
  data: makeUser({ id: 100, deals_count: 5, is_admin: false }),
  isLoading: false,
}));

const categoriesState = vi.hoisted(() => ({
  data: undefined as CategoryDto[] | undefined,
  isLoading: false,
}));

const servicesState = vi.hoisted(() => ({
  data: undefined as ServiceDto[] | undefined,
  isLoading: false,
  lastParams: undefined as unknown,
}));
const apiGetMock = vi.hoisted(() => vi.fn());

vi.mock("@/api/client", () => ({
  api: { get: apiGetMock },
}));

vi.mock("@/api/hooks", () => ({
  useCategories: () => categoriesState,
  buildServicesSearchParams: (params: { category?: string; limit?: number; offset?: number }) => {
    const searchParams: Record<string, string> = {};
    if (params.category) searchParams.category = params.category;
    if (params.limit !== undefined) searchParams.limit = String(params.limit);
    if (params.offset !== undefined) searchParams.offset = String(params.offset);
    return searchParams;
  },
  useServices: (params: unknown) => {
    servicesState.lastParams = params;
    return { data: servicesState.data, isLoading: servicesState.isLoading };
  },
  useMe: () => meState,
}));

import CategoriesPage from "./CategoriesPage";

function renderPage(initialRoute = "/search/categories") {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[initialRoute]}>
        <Routes>
          <Route path="/search/categories" element={<CategoriesPage />} />
          <Route path="/search/categories/:slug" element={<CategoriesPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function makeService(id: number, category: CategoryDto, overrides: Partial<ServiceDto> = {}): ServiceDto {
  return {
    id,
    title: `Service ${id}`,
    description: "Service description",
    price: 100,
    currency: "USD",
    status: "active",
    owner_username: "alice",
    created_at: "2026-01-01T00:00:00Z",
    category,
    ...overrides,
  };
}

beforeEach(() => {
  apiGetMock.mockReset();
  categoriesState.data = undefined;
  categoriesState.isLoading = false;
  servicesState.data = undefined;
  servicesState.isLoading = false;
  servicesState.lastParams = undefined;
  meState.data = makeUser({ id: 100, deals_count: 5, is_admin: false });
  meState.isLoading = false;
});

describe("<CategoriesPage />", () => {
  it("renders the categories header", () => {
    categoriesState.data = [];
    renderPage();
    expect(screen.getByRole("heading", { name: "Категории" })).toBeInTheDocument();
  });

  it("renders categories when data is available", () => {
    categoriesState.data = [
      { id: 1, name: "Development", slug: "dev", icon_key: "code", services_count: 5 },
    ];
    renderPage();
    expect(screen.getByText("Development")).toBeInTheDocument();
  });

  it("renders warning overlay when user has 0 deals and is not admin", () => {
    meState.data = makeUser({ id: 100, deals_count: 0, is_admin: false });
    categoriesState.data = [
      { id: 1, name: "Development", slug: "dev", icon_key: "code", services_count: 5 },
    ];
    renderPage();
    expect(screen.getByText("Поиск ограничен")).toBeInTheDocument();
    expect(screen.getByText(/каталог категорий доступен только участникам/)).toBeInTheDocument();
  });

  it("renders service detail page and warns when user has 0 deals and is not admin", () => {
    meState.data = makeUser({ id: 100, deals_count: 0, is_admin: false });
    categoriesState.data = [
      { id: 1, name: "Development", slug: "dev", icon_key: "code", services_count: 5 },
    ];
    servicesState.data = [
      {
        id: 1,
        title: "Coding Service",
        description: "Will code for food",
        price: 10,
        currency: "USD",
        status: "active",
        owner_username: "bob",
        created_at: "2026-01-01T00:00:00Z",
        category: categoriesState.data[0],
      },
    ];
    renderPage("/search/categories/dev");
    expect(screen.getByText("Поиск ограничен")).toBeInTheDocument();
    expect(screen.getByText(/просмотр каталога услуг доступен только участникам/)).toBeInTheDocument();
  });

  it("requests the first category service page", () => {
    categoriesState.data = [
      { id: 1, name: "Development", slug: "dev", icon_key: "code", services_count: 0 },
    ];
    servicesState.data = [];
    renderPage("/search/categories/dev");
    expect(servicesState.lastParams).toEqual({ category: "dev", limit: 50, offset: 0 });
  });

  it("loads more category services with the backend offset", async () => {
    const category = { id: 1, name: "Development", slug: "dev", icon_key: "code", services_count: 51 };
    categoriesState.data = [category];
    servicesState.data = Array.from({ length: 50 }, (_, idx) => makeService(idx + 1, category));
    apiGetMock.mockReturnValue({ json: async () => [makeService(51, category)] });

    const user = userEvent.setup();
    renderPage("/search/categories/dev");
    await user.click(screen.getByRole("button", { name: "Показать еще" }));

    await waitFor(() => expect(apiGetMock).toHaveBeenCalledTimes(1));
    expect(apiGetMock).toHaveBeenCalledWith("api/services", {
      searchParams: { category: "dev", limit: "50", offset: "50" },
    });
  });
});
