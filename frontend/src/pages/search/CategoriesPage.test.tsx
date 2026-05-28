import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
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
}));

vi.mock("@/api/hooks", () => ({
  useCategories: () => categoriesState,
  useServices: () => servicesState,
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

beforeEach(() => {
  categoriesState.data = undefined;
  categoriesState.isLoading = false;
  servicesState.data = undefined;
  servicesState.isLoading = false;
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
        category: categoriesState.data[0],
      },
    ];
    renderPage("/search/categories/dev");
    expect(screen.getByText("Поиск ограничен")).toBeInTheDocument();
    expect(screen.getByText(/просмотр каталога услуг доступен только участникам/)).toBeInTheDocument();
  });
});
