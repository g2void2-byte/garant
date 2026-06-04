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

  it("renders neutral KPI values for malformed runtime counters and volume", () => {
    mockState.kpi = {
      ...kpiData(),
      dau: "1e2" as unknown as number,
      wau: "50" as unknown as number,
      deals_volume_usd_30d: "0x10" as unknown as number,
      open_arbitration: "1.5" as unknown as number,
      pending_withdrawals: -1,
    };

    renderPage();

    expect(screen.getByText(`\u2014 / 50 / 200`)).toBeInTheDocument();
    expect(screen.queryByText(/1e2|0x10|1\.5/)).not.toBeInTheDocument();
    expect(screen.getAllByText("\u2014").length).toBeGreaterThanOrEqual(3);
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

  it("drops malformed sparkline values before plotting or displaying them", () => {
    mockState.series = {
      deals_count_30d: [
        { date: "2026-01-01", value: "1e2" as unknown as number },
        { date: "2026-01-02", value: "2" as unknown as number },
      ],
      deals_volume_30d: [
        { date: "2026-01-01", value: "1500.5" as unknown as number },
        { date: "2026-01-02", value: "0x10" as unknown as number },
      ],
      new_users_30d: [],
      deposits_30d: [],
      withdrawals_30d: [],
    };

    const { container } = renderPage();

    expect(screen.queryByText(/1e2|0x10/)).not.toBeInTheDocument();
    expect(screen.getByText("$1,501")).toBeInTheDocument();
    for (const polyline of container.querySelectorAll("polyline")) {
      expect(polyline.getAttribute("points") ?? "").not.toMatch(/NaN|Infinity/);
    }
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
    expect(screen.getByText("username \u043d\u0435 \u0437\u0430\u0434\u0430\u043d")).toBeInTheDocument();
    expect(screen.queryByText("@—")).not.toBeInTheDocument();
    expect(screen.getByText("9")).toBeInTheDocument();
  });

  it("renders neutral top-list values for malformed runtime metrics", () => {
    mockState.top = {
      top_sellers: [
        { user_id: 1, username: "alice", display_name: "Alice", value: "1e2" as unknown as number },
      ],
      top_buyers: [
        { user_id: 2, username: "bob", display_name: "Bob", value: "1500.5" as unknown as number },
      ],
      top_arbiters: [
        { user_id: 3, username: "carol", display_name: "Carol", value: "1.5" as unknown as number },
      ],
    };

    renderPage();

    expect(screen.queryByText(/1e2/)).not.toBeInTheDocument();
    expect(screen.queryByText("1.5")).not.toBeInTheDocument();
    expect(screen.getByText("1,500.5")).toBeInTheDocument();
    expect(screen.getAllByText("\u2014").length).toBeGreaterThanOrEqual(2);
  });

  it("renders skeletons while series is loading", () => {
    mockState.seriesLoading = true;
    const { container } = renderPage();
    expect(container.querySelectorAll(".rounded-card.h-20").length).toBeGreaterThanOrEqual(5);
  });
});
