import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, useLocation } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type {
  AdminListUsersQuery,
  AdminUserListDto,
} from "@/api/types";

/**
 * Tests for `/admin/users`.
 *
 * Covers URL-driven filters (role/status/page/q), search-on-Enter +
 * onBlur with trim, filter visibility toggle, list row rendering with
 * Бан/Заморожен badges, pagination prev/next gating, empty state and
 * admin guard.
 */

const mockState = vi.hoisted(() => ({
  list: undefined as AdminUserListDto | undefined,
  loading: false,
  shouldRender: true as boolean,
  lastQuery: undefined as AdminListUsersQuery | undefined,
}));

vi.mock("@/api/admin/hooks", () => ({
  useAdminUsers: (q: AdminListUsersQuery) => {
    mockState.lastQuery = q;
    return { data: mockState.list, isLoading: mockState.loading };
  },
}));

vi.mock("@/hooks/useAdminRedirect", () => ({
  useAdminRedirect: () => ({ shouldRender: mockState.shouldRender }),
}));

vi.mock("@/lib/tg", () => ({
  useTelegramViewport: () => null,
  haptic: () => {},
  showBackButton: () => () => {},
}));

import AdminUsersPage from "./AdminUsersPage";

function LocationProbe() {
  const loc = useLocation();
  return (
    <span data-testid="path">
      {loc.pathname}
      {loc.search}
    </span>
  );
}

function renderPage(initialEntries: string[] = ["/admin/users"]) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={initialEntries}>
        <AdminUsersPage />
        <LocationProbe />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function makeUser(
  overrides: Partial<AdminUserListDto["items"][number]> = {},
): AdminUserListDto["items"][number] {
  return {
    id: 1,
    tg_user_id: 12345,
    username: "alice",
    display_name: "Alice Smith",
    photo_url: null,
    prefix: null,
    is_admin: false,
    is_arbiter: false,
    is_vip: false,
    is_banned: false,
    is_frozen: false,
    trust_deposit_balance: 5,
    rating: 4.85,
    deals_total: 3,
    deals_success: 2,
    last_ip: null,
    last_login_at: null,
    created_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

beforeEach(() => {
  mockState.list = undefined;
  mockState.loading = false;
  mockState.shouldRender = true;
  mockState.lastQuery = undefined;
});

describe("<AdminUsersPage />", () => {
  it("returns null when guard rejects the visitor", () => {
    mockState.shouldRender = false;
    renderPage();
    expect(screen.queryByText("Пользователи")).not.toBeInTheDocument();
  });

  it("renders skeleton rows while loading", () => {
    mockState.loading = true;
    const { container } = renderPage();
    expect(container.querySelectorAll(".rounded-card.h-16").length).toBe(6);
  });

  it("renders empty state when items is empty", () => {
    mockState.list = { items: [], total: 0, page: 1, page_size: 20 };
    renderPage();
    expect(screen.getByText("Никого не найдено")).toBeInTheDocument();
  });

  it("renders malformed list totals as a neutral dash", () => {
    mockState.list = {
      items: [],
      total: "1e2" as unknown as number,
      page: 1,
      page_size: 20,
    };
    renderPage();
    expect(screen.getByText(/\u2014 всего/)).toBeInTheDocument();
    expect(screen.queryByText(/1e2/)).not.toBeInTheDocument();
  });

  it("reads URL filter params and passes them into useAdminUsers", () => {
    mockState.list = { items: [], total: 0, page: 1, page_size: 20 };
    renderPage(["/admin/users?role=admin&status=banned&page=2&q=alice"]);
    expect(mockState.lastQuery).toEqual({
      q: "alice",
      role: "admin",
      status: "banned",
      page: 2,
      page_size: 20,
    });
  });

  it.each(["-5", "1e2", "0x10"])(
    "falls back to page 1 for ambiguous page param %s",
    (page) => {
      mockState.list = { items: [], total: 0, page: 1, page_size: 20 };
      renderPage([`/admin/users?page=${page}`]);

      expect(mockState.lastQuery?.page).toBe(1);
    },
  );

  it("renders a user row with Бан + Заморожен badges", () => {
    mockState.list = {
      items: [
        makeUser({ is_banned: true, is_frozen: true, display_name: "Bob" }),
      ],
      total: 1,
      page: 1,
      page_size: 20,
    };
    renderPage();
    expect(screen.getByText("Bob")).toBeInTheDocument();
    expect(screen.getByText("Бан")).toBeInTheDocument();
    expect(screen.getByText("Заморожен")).toBeInTheDocument();
  });

  it("renders string metric payloads in user rows without crashing", () => {
    mockState.list = {
      items: [
        makeUser({
          rating: "4.5" as unknown as number,
          trust_deposit_balance: "1500.5" as unknown as number,
        }),
      ],
      total: 1,
      page: 1,
      page_size: 20,
    };
    renderPage();
    expect(screen.getAllByText(/4\.5/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/\$1500\.50/).length).toBeGreaterThan(0);
  });

  it("renders malformed user row identifiers and counts as neutral values", () => {
    mockState.list = {
      items: [
        makeUser({
          tg_user_id: "1e2" as unknown as number,
          deals_total: "0x10" as unknown as number,
        }),
      ],
      total: 1,
      page: 1,
      page_size: 20,
    };
    renderPage();

    expect(screen.getByText(/tg \u2014/)).toBeInTheDocument();
    expect(screen.getByText(/Сделок: \u2014/)).toBeInTheDocument();
    expect(screen.queryByText(/1e2|0x10/)).not.toBeInTheDocument();
  });

  it("renders missing usernames as non-handle labels", () => {
    mockState.list = {
      items: [makeUser({ username: null })],
      total: 1,
      page: 1,
      page_size: 20,
    };
    renderPage();
    expect(screen.getByText(/username \u043d\u0435 \u0437\u0430\u0434\u0430\u043d/)).toBeInTheDocument();
    expect(screen.queryByText(/@\u2014/)).not.toBeInTheDocument();
  });

  it("clicking a user row navigates to /admin/users/<id>", async () => {
    mockState.list = {
      items: [makeUser({ id: 99 })],
      total: 1,
      page: 1,
      page_size: 20,
    };
    const user = userEvent.setup();
    renderPage();
    await user.click(screen.getByText("Alice Smith"));
    expect(screen.getByTestId("path").textContent).toBe("/admin/users/99");
  });

  it("typing a search and pressing Enter triggers a query refetch with trimmed q", async () => {
    mockState.list = { items: [], total: 0, page: 1, page_size: 20 };
    renderPage();
    const input = screen.getByPlaceholderText("@username или tg_id");
    fireEvent.change(input, { target: { value: "  bob  " } });
    fireEvent.keyDown(input, { key: "Enter" });
    await waitFor(() =>
      expect(mockState.lastQuery?.q).toBe("bob"),
    );
  });

  it("onBlur with a different value also commits the search", async () => {
    mockState.list = { items: [], total: 0, page: 1, page_size: 20 };
    renderPage();
    const input = screen.getByPlaceholderText("@username или tg_id");
    fireEvent.change(input, { target: { value: "alice" } });
    fireEvent.blur(input);
    await waitFor(() => expect(mockState.lastQuery?.q).toBe("alice"));
  });

  it("opens filter section and applies role chip via URL update", async () => {
    mockState.list = { items: [], total: 0, page: 1, page_size: 20 };
    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByLabelText("Фильтры"));
    expect(screen.getByText("Роль")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Админы" }));
    await waitFor(() => {
      expect(mockState.lastQuery?.role).toBe("admin");
    });
  });

  it("status filter chip 'Активные' sets ?status=active in the URL", async () => {
    mockState.list = { items: [], total: 0, page: 1, page_size: 20 };
    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByLabelText("Фильтры"));
    await user.click(screen.getByRole("button", { name: "Активные" }));
    await waitFor(() => expect(mockState.lastQuery?.status).toBe("active"));
  });

  it("renders pagination + disables 'Назад' on page 1 + advances 'Вперёд'", async () => {
    mockState.list = {
      items: [makeUser()],
      total: 80,
      page: 1,
      page_size: 20,
    };
    const user = userEvent.setup();
    renderPage();

    const prev = screen.getByLabelText("Назад");
    const next = screen.getByLabelText("Вперёд");
    expect(prev).toBeDisabled();
    expect(next).not.toBeDisabled();
    expect(screen.getByText("1 / 4")).toBeInTheDocument();

    await user.click(next);
    await waitFor(() => expect(mockState.lastQuery?.page).toBe(2));
  });

  it("does not render pagination when total <= page_size", () => {
    mockState.list = {
      items: [makeUser()],
      total: 5,
      page: 1,
      page_size: 20,
    };
    renderPage();
    expect(screen.queryByLabelText("Назад")).not.toBeInTheDocument();
  });
});
