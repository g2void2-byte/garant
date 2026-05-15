import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, useLocation } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { AdminDashboardDto } from "@/api/types";

/**
 * Tests for the `/admin` dashboard landing page.
 *
 * Covers admin redirect gate, loading skeleton, error banner, KPI tile
 * values, the "accent" highlight on open arbitration / banned users,
 * tile-onClick navigation (e.g. `/admin/users?status=banned`), and the
 * NavTile router-link grid.
 */

const mockState = vi.hoisted(() => ({
  data: undefined as AdminDashboardDto | undefined,
  loading: false,
  error: null as unknown as Error | null,
  shouldRender: true as boolean,
}));

vi.mock("@/api/admin/hooks", () => ({
  useAdminDashboard: () => ({
    data: mockState.data,
    isLoading: mockState.loading,
    error: mockState.error,
  }),
}));

vi.mock("@/hooks/useAdminRedirect", () => ({
  useAdminRedirect: () => ({ shouldRender: mockState.shouldRender }),
}));

import AdminDashboardPage from "./AdminDashboardPage";

function LocationProbe() {
  const loc = useLocation();
  return (
    <span data-testid="path">
      {loc.pathname}
      {loc.search}
    </span>
  );
}

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={["/admin"]}>
        <AdminDashboardPage />
        <LocationProbe />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function makeData(overrides: Partial<AdminDashboardDto> = {}): AdminDashboardDto {
  return {
    total_users: 1234,
    new_users_24h: 12,
    new_users_7d: 80,
    online_users_5min: 5,
    total_deals: 200,
    open_deals: 30,
    open_arbitration: 0,
    total_services: 60,
    active_services: 45,
    banned_users: 0,
    frozen_users: 0,
    admins: 3,
    arbiters: 2,
    vips: 7,
    ...overrides,
  };
}

beforeEach(() => {
  mockState.data = undefined;
  mockState.loading = false;
  mockState.error = null;
  mockState.shouldRender = true;
});

describe("<AdminDashboardPage />", () => {
  it("returns null when admin guard rejects the visitor", () => {
    mockState.shouldRender = false;
    renderPage();
    expect(screen.queryByText("Админ-панель")).not.toBeInTheDocument();
  });

  it("renders the dashboard skeleton while loading", () => {
    mockState.loading = true;
    const { container } = renderPage();
    expect(container.querySelectorAll(".shimmer").length).toBeGreaterThan(0);
  });

  it("renders an error banner when the dashboard query fails", () => {
    mockState.error = new Error("boom");
    renderPage();
    expect(
      screen.getByText("Не удалось загрузить статистику"),
    ).toBeInTheDocument();
  });

  it("renders KPI values from the dashboard payload", () => {
    mockState.data = makeData();
    renderPage();
    expect(screen.getByText("1234")).toBeInTheDocument(); // total_users
    expect(screen.getByText("12")).toBeInTheDocument(); // new_users_24h
    expect(screen.getByText("80")).toBeInTheDocument(); // new_users_7d
    expect(screen.getByText("5")).toBeInTheDocument(); // online_users_5min
    expect(screen.getByText("200")).toBeInTheDocument(); // total_deals
  });

  it("applies the accent ring to 'open arbitration' tile when count > 0", () => {
    mockState.data = makeData({ open_arbitration: 4 });
    const { container } = renderPage();
    const arbBtn = Array.from(
      container.querySelectorAll<HTMLButtonElement>("button"),
    ).find((b) => b.textContent?.includes("В арбитраже"));
    expect(arbBtn).toBeDefined();
    expect(arbBtn!.className).toMatch(/ring-1 ring-accent/);
  });

  it("does NOT apply the accent ring to 'open arbitration' tile when count is 0", () => {
    mockState.data = makeData({ open_arbitration: 0 });
    const { container } = renderPage();
    const arbBtn = Array.from(
      container.querySelectorAll<HTMLButtonElement>("button"),
    ).find((b) => b.textContent?.includes("В арбитраже"));
    expect(arbBtn).toBeDefined();
    expect(arbBtn!.className).not.toMatch(/ring-1 ring-accent/);
  });

  it("tile without onClick is rendered as disabled (new_users_24h)", () => {
    mockState.data = makeData();
    const { container } = renderPage();
    const newBtn = Array.from(
      container.querySelectorAll<HTMLButtonElement>("button"),
    ).find((b) => b.textContent?.includes("Новые за 24ч"));
    expect(newBtn).toBeDefined();
    expect(newBtn!.disabled).toBe(true);
  });

  it("clicking 'Всего' under Сделки navigates to /admin/deals", async () => {
    mockState.data = makeData();
    const user = userEvent.setup();
    renderPage();
    const dealsCol = screen.getByText("Сделки").parentElement!;
    const totalBtn = Array.from(
      dealsCol.querySelectorAll<HTMLButtonElement>("button"),
    ).find((b) => b.textContent?.includes("Всего"));
    expect(totalBtn).toBeDefined();
    await user.click(totalBtn!);
    expect(screen.getByTestId("path").textContent).toBe("/admin/deals");
  });

  it("clicking 'Открытые' navigates to /admin/deals?status=in_progress", async () => {
    mockState.data = makeData();
    const user = userEvent.setup();
    renderPage();
    await user.click(
      screen.getByRole("button", { name: /Открытые/ }),
    );
    expect(screen.getByTestId("path").textContent).toBe(
      "/admin/deals?status=in_progress",
    );
  });

  it("NavTile 'Treasury' navigates to /admin/treasury", async () => {
    mockState.data = makeData();
    const user = userEvent.setup();
    renderPage();
    await user.click(screen.getByRole("button", { name: /Treasury/ }));
    expect(screen.getByTestId("path").textContent).toBe("/admin/treasury");
  });

  it("NavTile '2FA' navigates to /admin/2fa", async () => {
    mockState.data = makeData();
    const user = userEvent.setup();
    renderPage();
    await user.click(screen.getByRole("button", { name: /2FA/ }));
    expect(screen.getByTestId("path").textContent).toBe("/admin/2fa");
  });
});
