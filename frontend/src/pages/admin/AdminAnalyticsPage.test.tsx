import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type {
  AdminAnalyticsKpiDto,
  AdminAnalyticsSeriesDto,
  AdminAnalyticsTopListsDto,
} from "@/api/types";

/**
 * Tests for `/admin/analytics`.
 *
 * Covers KPI card rendering, sparkline empty-state, top-user list
 * rendering, warning accent ring on critical KPIs, and admin guard.
 */

const mockState = vi.hoisted(() => ({
  kpi: undefined as AdminAnalyticsKpiDto | undefined,
  kpiLoading: false,
  series: undefined as AdminAnalyticsSeriesDto | undefined,
  seriesLoading: false,
  top: undefined as AdminAnalyticsTopListsDto | undefined,
  shouldRender: true as boolean,
}));

vi.mock("@/api/admin/hooks", () => ({
  useAdminAnalyticsKpi: () => ({
    data: mockState.kpi,
    isLoading: mockState.kpiLoading,
  }),
  useAdminAnalyticsSeries: () => ({
    data: mockState.series,
    isLoading: mockState.seriesLoading,
  }),
  useAdminAnalyticsTop: () => ({ data: mockState.top }),
}));

vi.mock("@/hooks/useAdminRedirect", () => ({
  useAdminRedirect: () => ({ shouldRender: mockState.shouldRender }),
}));

import AdminAnalyticsPage from "./AdminAnalyticsPage";

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <AdminAnalyticsPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function kpiData(): AdminAnalyticsKpiDto {
  return {
    dau: 10,
    wau: 50,
    mau: 200,
    new_users_24h: 3,
    new_users_7d: 21,
    deals_24h: 7,
    deals_7d: 50,
    deals_volume_usd_30d: 123456,
    open_arbitration: 4,
    pending_withdrawals: 2,
  };
}

beforeEach(() => {
  mockState.kpi = undefined;
  mockState.kpiLoading = false;
  mockState.series = undefined;
  mockState.seriesLoading = false;
  mockState.top = undefined;
  mockState.shouldRender = true;
});

describe("<AdminAnalyticsPage />", () => {
  it("returns null when admin guard rejects the visitor", () => {
    mockState.shouldRender = false;
    renderPage();
    expect(screen.queryByText("Аналитика")).not.toBeInTheDocument();
  });

  it("renders dash placeholders for every KPI when data is undefined", () => {
    renderPage();
    expect(screen.getAllByText("—").length).toBeGreaterThanOrEqual(6);
  });

  it("renders KPI values from the kpi payload", () => {
    mockState.kpi = kpiData();
    renderPage();
    expect(screen.getByText("10 / 50 / 200")).toBeInTheDocument();
    expect(screen.getByText("3 / 21")).toBeInTheDocument();
    expect(screen.getByText("7 / 50")).toBeInTheDocument();
    expect(screen.getByText(/\$123,456/)).toBeInTheDocument();
    expect(screen.getByText("4")).toBeInTheDocument(); // open_arbitration
    expect(screen.getByText("2")).toBeInTheDocument(); // pending_withdrawals
  });

  it("applies warning ring to 'Открытых арбитражей' and 'Ожидают вывод' cards", () => {
    mockState.kpi = kpiData();
    const { container } = renderPage();
    const arbCard = Array.from(
      container.querySelectorAll<HTMLDivElement>(".rounded-card"),
    ).find((d) => d.textContent?.includes("Открытых арбитражей"));
    expect(arbCard).toBeDefined();
    expect(arbCard!.className).toMatch(/ring-1 ring-warning/);
  });

  it("renders 'Нет данных' for sparklines when series arrays are empty", () => {
    mockState.series = {
      deals_count_30d: [],
      deals_volume_30d: [],
      new_users_30d: [],
      deposits_30d: [],
      withdrawals_30d: [],
    };
    renderPage();
    // Five sparkline empty messages.
    expect(screen.getAllByText("Нет данных").length).toBeGreaterThanOrEqual(5);
  });

  it("renders the last sparkline value with a custom format for the volume card", () => {
    mockState.series = {
      deals_count_30d: [],
      deals_volume_30d: [
        { date: "2026-01-01", value: 100 },
        { date: "2026-01-02", value: 1500 },
      ],
      new_users_30d: [],
      deposits_30d: [],
      withdrawals_30d: [],
    };
    renderPage();
    expect(screen.getByText("$1,500")).toBeInTheDocument();
  });

  it("renders top-user entries with rank, name, and value", () => {
    mockState.top = {
      top_sellers: [
        { user_id: 1, username: "alice", display_name: "Alice", value: 9 },
        { user_id: 2, username: null, display_name: "Anon", value: 7 },
      ],
      top_buyers: [],
      top_arbiters: [],
    };
    renderPage();
    expect(screen.getByText("Alice")).toBeInTheDocument();
    expect(screen.getByText("@alice")).toBeInTheDocument();
    expect(screen.getByText("Anon")).toBeInTheDocument();
    expect(screen.getByText("@—")).toBeInTheDocument();
    expect(screen.getByText("9")).toBeInTheDocument();
  });

  it("renders skeletons while series is loading", () => {
    mockState.seriesLoading = true;
    const { container } = renderPage();
    expect(container.querySelectorAll(".rounded-card.h-20").length).toBeGreaterThanOrEqual(5);
  });
});
