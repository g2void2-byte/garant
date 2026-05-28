import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { UserCardDto } from "@/api/types";

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

const mockState = vi.hoisted(() => ({
  data: undefined as UserCardDto[] | undefined,
  isLoading: false,
}));

vi.mock("@/api/hooks", () => ({
  useUsers: () => mockState,
  useMe: () => meState,
}));

import SearchPage from "./SearchPage";
import { useUI } from "@/stores/ui";

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <SearchPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  mockState.data = undefined;
  mockState.isLoading = false;
  meState.data = makeUser({ id: 100, deals_count: 5, is_admin: false });
  meState.isLoading = false;
  useUI.setState({ searchMode: "users" });
});

describe("<SearchPage />", () => {
  it("renders the search header and the search input", () => {
    mockState.data = [];
    renderPage();
    expect(screen.getByRole("heading", { name: "Поиск" })).toBeInTheDocument();
    expect(screen.getByPlaceholderText("Поиск пользователей")).toBeInTheDocument();
  });

  it("renders skeletons while loading", () => {
    mockState.isLoading = true;
    renderPage();
    expect(screen.queryByText("Никого не найдено")).not.toBeInTheDocument();
  });

  it("shows the empty state when no users match", () => {
    mockState.data = [];
    renderPage();
    expect(screen.getByText("Никого не найдено")).toBeInTheDocument();
  });

  it("renders user cards when the API returns data", () => {
    mockState.data = [
      makeUser({ id: 1, username: "alice", display_name: "Alice" }),
      makeUser({ id: 2, username: "bob", display_name: "Bob" }),
    ];
    renderPage();
    expect(screen.getByText("Alice")).toBeInTheDocument();
    expect(screen.getByText("Bob")).toBeInTheDocument();
  });

  it("offers the filter toggle and the filter sheet button", () => {
    mockState.data = [];
    renderPage();
    expect(screen.getByRole("button", { name: /Открыть фильтры/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Услуги" })).toBeInTheDocument();
  });

  it("renders security warning overlay when user has 0 deals and is not admin", () => {
    meState.data = makeUser({ id: 100, deals_count: 0, is_admin: false });
    mockState.data = [
      makeUser({ id: 1, username: "alice", display_name: "Alice" }),
    ];
    renderPage();
    expect(screen.getByText("Поиск ограничен")).toBeInTheDocument();
    expect(screen.getByText(/В целях безопасности и защиты от спама/)).toBeInTheDocument();
    expect(screen.queryByText("Alice")).not.toBeInTheDocument();
  });

  it("does not render warning overlay when user has deals", () => {
    meState.data = makeUser({ id: 100, deals_count: 1, is_admin: false });
    mockState.data = [
      makeUser({ id: 1, username: "alice", display_name: "Alice" }),
    ];
    renderPage();
    expect(screen.queryByText("Поиск ограничен")).not.toBeInTheDocument();
    expect(screen.getByText("Alice")).toBeInTheDocument();
  });

  it("does not render warning overlay when user is admin even with 0 deals", () => {
    meState.data = makeUser({ id: 100, deals_count: 0, is_admin: true });
    mockState.data = [
      makeUser({ id: 1, username: "alice", display_name: "Alice" }),
    ];
    renderPage();
    expect(screen.queryByText("Поиск ограничен")).not.toBeInTheDocument();
    expect(screen.getByText("Alice")).toBeInTheDocument();
  });
});
