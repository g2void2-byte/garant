import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
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
  lastParams: undefined as Record<string, unknown> | undefined,
}));

const apiMock = vi.hoisted(() => ({
  get: vi.fn(),
}));

vi.mock("@/api/client", () => ({
  api: apiMock,
}));

vi.mock("@/api/hooks", () => ({
  useUsers: (params: Record<string, unknown>) => {
    mockState.lastParams = params;
    return mockState;
  },
  useMe: () => meState,
  buildUsersSearchParams: (params: Record<string, unknown>) =>
    Object.fromEntries(
      Object.entries(params)
        .filter(([, value]) => value !== undefined && value !== "")
        .map(([key, value]) => [key, String(value)]),
    ),
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
  mockState.lastParams = undefined;
  apiMock.get.mockReset();
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

  it("does not build a profile navigation row for a user without username", () => {
    mockState.data = [makeUser({ id: 3, username: null, display_name: "No Username" })];
    renderPage();
    expect(screen.getByText("No Username")).toBeInTheDocument();
    expect(screen.getByText(/username не задан/)).toBeInTheDocument();
    expect(screen.getByTestId("search-user-3")).toBeDisabled();
    expect(screen.queryByText("@null")).not.toBeInTheDocument();
  });

  it("loads the next user-search page by offset", async () => {
    mockState.data = Array.from({ length: 50 }, (_, index) =>
      makeUser({
        id: index + 1,
        username: `user${index}`,
        display_name: `User ${index}`,
      }),
    );
    apiMock.get.mockReturnValue({
      json: async () => [makeUser({ id: 51, username: "user50", display_name: "User 50" })],
    });
    const user = userEvent.setup();

    renderPage();

    expect(mockState.lastParams).toEqual(expect.objectContaining({ limit: 50, offset: 0 }));
    expect(screen.getByText("User 49")).toBeInTheDocument();
    const buttons = screen.getAllByRole("button");
    await user.click(buttons[buttons.length - 1]);

    expect(await screen.findByText("User 50")).toBeInTheDocument();
    await waitFor(() =>
      expect(apiMock.get).toHaveBeenCalledWith("api/users", {
        searchParams: expect.objectContaining({ limit: "50", offset: "50" }),
      }),
    );
  });

  it("offers the filter toggle and the filter sheet button", () => {
    mockState.data = [];
    renderPage();
    expect(screen.getByRole("button", { name: /Открыть фильтры/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Услуги" })).toBeInTheDocument();
  });

  it("does not offer the retired moderator prefix filter", async () => {
    mockState.data = [];
    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByRole("button", { name: /Открыть фильтры/i }));

    expect(screen.queryByRole("button", { name: "Модератор" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Администратор" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Арбитр" })).toBeInTheDocument();
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
