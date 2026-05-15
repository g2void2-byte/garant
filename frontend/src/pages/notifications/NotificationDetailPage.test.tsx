import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, useLocation } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { NotificationDto } from "@/api/types";

/**
 * Tests for `/notifications/:id` (detail page).
 *
 * Covers: loading skeleton, error/empty state, header + icon mapping per
 * `type` (deals / deposits / system / unknown fallback), the
 * mark-as-read effect contract (fires once when `is_read === false`,
 * never when true), `dealRef` resolution (payload.deal_id wins over
 * body match, falls back to body `#N` match, returns null otherwise),
 * and the navigation wiring for the three CTA buttons (deal, wallet,
 * back to inbox).
 */

const mockState = vi.hoisted(() => ({
  data: undefined as NotificationDto | undefined,
  loading: false,
  isError: false,
  markRead: { mutate: vi.fn() as ReturnType<typeof vi.fn> },
  lastNotificationId: undefined as number | undefined,
}));

vi.mock("@/api/hooks", () => ({
  useNotification: (id: number | undefined) => {
    mockState.lastNotificationId = id;
    return {
      data: mockState.data,
      isLoading: mockState.loading,
      isError: mockState.isError,
    };
  },
  useMarkNotificationRead: () => mockState.markRead,
}));

vi.mock("@/lib/tg", () => ({
  haptic: () => {},
  showBackButton: () => () => {},
}));

import NotificationDetailPage from "./NotificationDetailPage";

function LocationProbe() {
  const loc = useLocation();
  return <span data-testid="path">{loc.pathname}</span>;
}

function renderPage(id: string | number = 1) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[`/notifications/${id}`]}>
        <LocationProbe />
        <NotificationDetailPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function makeNotification(
  overrides: Partial<NotificationDto> = {},
): NotificationDto {
  return {
    id: 1,
    type: "deals",
    title: "Сделка создана",
    body: "У вас новая сделка #42",
    payload: { deal_id: 42 },
    is_read: true,
    created_at: new Date().toISOString(),
    ...overrides,
  };
}

beforeEach(() => {
  mockState.data = undefined;
  mockState.loading = false;
  mockState.isError = false;
  mockState.markRead = { mutate: vi.fn() };
  mockState.lastNotificationId = undefined;
});

describe("<NotificationDetailPage />", () => {
  it("renders skeletons while loading and no header/title", () => {
    mockState.loading = true;
    const { container } = renderPage();
    // The skeletons render with explicit heights (h-32, h-24).
    expect(container.querySelectorAll(".h-32").length).toBeGreaterThan(0);
    expect(container.querySelectorAll(".h-24").length).toBeGreaterThan(0);
    // The empty / detail header copy must NOT render in the loading state.
    expect(screen.queryByText("Уведомление не найдено")).not.toBeInTheDocument();
  });

  it("renders the empty state when useNotification returns isError", () => {
    mockState.isError = true;
    renderPage();
    expect(screen.getByText("Уведомление не найдено")).toBeInTheDocument();
  });

  it("renders the empty state when data is undefined (no error, no loading)", () => {
    // All mockState fields stay at their beforeEach defaults, so:
    //   data = undefined, isError = false, loading = false.
    renderPage();
    expect(screen.getByText("Уведомление не найдено")).toBeInTheDocument();
  });

  it("renders the title, body and 'Сделки' typeLabel for type=deals", () => {
    mockState.data = makeNotification({ type: "deals" });
    renderPage();
    expect(screen.getByText("Сделка создана")).toBeInTheDocument();
    expect(screen.getByText("У вас новая сделка #42")).toBeInTheDocument();
    expect(screen.getByText("Сделки")).toBeInTheDocument();
  });

  it("renders 'Депозиты' typeLabel for type=deposits", () => {
    mockState.data = makeNotification({
      type: "deposits",
      title: "Депозит зачислен",
      body: "100 USDT",
      payload: {},
    });
    renderPage();
    expect(screen.getByText("Депозиты")).toBeInTheDocument();
    expect(screen.getByText("Депозит зачислен")).toBeInTheDocument();
  });

  it("renders 'Системные' typeLabel for type=system", () => {
    mockState.data = makeNotification({
      type: "system",
      title: "Тех. работы",
      body: "Сервис временно недоступен",
      payload: {},
    });
    renderPage();
    expect(screen.getByText("Системные")).toBeInTheDocument();
    expect(screen.getByText("Тех. работы")).toBeInTheDocument();
  });

  it("falls back to 'Системные' label for an unknown notification type", () => {
    mockState.data = makeNotification({
      type: "weird-future-type",
      title: "Что-то новое",
      body: "Без привязки",
      payload: {},
    });
    renderPage();
    expect(screen.getByText("Системные")).toBeInTheDocument();
    expect(screen.getByText("Что-то новое")).toBeInTheDocument();
  });

  it("calls markRead.mutate(data.id) exactly once when is_read=false", () => {
    mockState.data = makeNotification({ id: 77, is_read: false, payload: {} });
    renderPage();
    expect(mockState.markRead.mutate).toHaveBeenCalledTimes(1);
    expect(mockState.markRead.mutate).toHaveBeenCalledWith(77);
  });

  it("does not call markRead.mutate when is_read=true", () => {
    mockState.data = makeNotification({ id: 77, is_read: true, payload: {} });
    renderPage();
    expect(mockState.markRead.mutate).not.toHaveBeenCalled();
  });

  it("uses payload.deal_id as the dealRef when present", () => {
    mockState.data = makeNotification({
      payload: { deal_id: 123 },
      // Body contains a different reference to make sure payload wins.
      body: "Сделка #999 обновилась",
    });
    renderPage();
    expect(
      screen.getByRole("button", { name: /Открыть сделку #123/ }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /Открыть сделку #999/ }),
    ).not.toBeInTheDocument();
  });

  it("falls back to the first '#N' match in body when payload has no deal_id", () => {
    mockState.data = makeNotification({
      payload: {},
      body: "См. сделку #55 и сделку #99",
    });
    renderPage();
    expect(
      screen.getByRole("button", { name: /Открыть сделку #55/ }),
    ).toBeInTheDocument();
  });

  it("does not render the deal button when neither payload nor body provides one", () => {
    mockState.data = makeNotification({
      type: "system",
      payload: {},
      body: "Просто сообщение без ссылок",
    });
    renderPage();
    expect(
      screen.queryByRole("button", { name: /Открыть сделку/ }),
    ).not.toBeInTheDocument();
  });

  it("'Открыть сделку #N' navigates to /deals/N", async () => {
    mockState.data = makeNotification({ payload: { deal_id: 42 } });
    const user = userEvent.setup();
    renderPage();
    await user.click(
      screen.getByRole("button", { name: /Открыть сделку #42/ }),
    );
    expect(screen.getByTestId("path").textContent).toBe("/deals/42");
  });

  it("'Открыть кошелёк' renders only when type=deposits", () => {
    mockState.data = makeNotification({
      type: "deposits",
      payload: {},
      body: "Депозит",
    });
    renderPage();
    expect(
      screen.getByRole("button", { name: /Открыть кошелёк/ }),
    ).toBeInTheDocument();
  });

  it("'Открыть кошелёк' is hidden for non-deposit notifications", () => {
    mockState.data = makeNotification({
      type: "deals",
      payload: { deal_id: 1 },
    });
    renderPage();
    expect(
      screen.queryByRole("button", { name: /Открыть кошелёк/ }),
    ).not.toBeInTheDocument();
  });

  it("'Открыть кошелёк' navigates to /wallet", async () => {
    mockState.data = makeNotification({
      type: "deposits",
      payload: {},
      body: "Депозит зачислен",
    });
    const user = userEvent.setup();
    renderPage();
    await user.click(
      screen.getByRole("button", { name: /Открыть кошелёк/ }),
    );
    expect(screen.getByTestId("path").textContent).toBe("/wallet");
  });

  it("'К оповещениям' back link navigates to /notifications", async () => {
    mockState.data = makeNotification({ payload: {} });
    const user = userEvent.setup();
    renderPage(7);
    await user.click(
      screen.getByRole("button", { name: "К оповещениям" }),
    );
    expect(screen.getByTestId("path").textContent).toBe("/notifications");
  });
});
