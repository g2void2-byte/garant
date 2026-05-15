import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { UserCardDto } from "@/api/types";

const mockState = vi.hoisted(() => ({
  data: undefined as UserCardDto[] | undefined,
  isLoading: false,
}));

vi.mock("@/api/hooks", () => ({
  useUsers: () => mockState,
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
  useUI.setState({ searchMode: "users" });
});

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
    good: 5,
    bad: 0,
    deposit: 0,
    rating: 5,
    reviews_count: 5,
    deals_count: 10,
    deals_sum: 1000,
    online: true,
    description: "",
    forums: [],
    ...overrides,
  };
}

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
});
