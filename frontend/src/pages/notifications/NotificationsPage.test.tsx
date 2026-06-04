import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, useLocation } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type {
  NotificationDto,
  NotificationCountersDto,
} from "@/api/types";

/**
 * Tests for `/notifications` (list page).
 *
 * Covers: tab filtering passing the right `type` to useNotifications,
 * skeletons, empty state, list rendering grouped by day, mark-all-read
 * button visibility/click, mark-single-read via row click, DM
 * preferences toggle wired to useUpdateMe.
 */

const mockState = vi.hoisted(() => ({
  counters: undefined as NotificationCountersDto | undefined,
  list: undefined as NotificationDto[] | undefined,
  loading: false,
  me: { id: 1, dm_deals: true, dm_deposits: true, dm_system: true } as {
    id: number;
    dm_deals?: boolean;
    dm_deposits?: boolean;
    dm_system?: boolean;
  } | undefined,
  lastType: undefined as string | undefined,
  lastParams: undefined as Record<string, unknown> | undefined,
  updateMe: { mutate: vi.fn() as ReturnType<typeof vi.fn> },
  markRead: { mutate: vi.fn() as ReturnType<typeof vi.fn> },
  markAll: { mutate: vi.fn() as ReturnType<typeof vi.fn> },
}));
const apiMock = vi.hoisted(() => ({ get: vi.fn() }));
const buildNotificationsSearchParamsMock = vi.hoisted(() =>
  vi.fn((params: Record<string, unknown>) => {
    const searchParams: Record<string, string> = {};
    for (const [key, value] of Object.entries(params)) {
      if (value === undefined || value === "") continue;
      searchParams[key] = String(value);
    }
    return searchParams;
  }),
);

vi.mock("@/api/hooks", () => ({
  buildNotificationsSearchParams: buildNotificationsSearchParamsMock,
  useMe: () => ({ data: mockState.me }),
  useNotificationCounters: () => ({ data: mockState.counters }),
  useNotifications: (params: Record<string, unknown>) => {
    mockState.lastParams = params;
    mockState.lastType = params.type as string | undefined;
    return { data: mockState.list, isLoading: mockState.loading };
  },
  useUpdateMe: () => mockState.updateMe,
  useMarkNotificationRead: () => mockState.markRead,
  useMarkAllRead: () => mockState.markAll,
}));

vi.mock("@/api/client", () => ({
  api: apiMock,
}));

vi.mock("@/lib/tg", () => ({
  useTelegramViewport: () => null,
  haptic: () => {},
}));

import NotificationsPage from "./NotificationsPage";

function LocationProbe() {
  const loc = useLocation();
  return <span data-testid="path">{loc.pathname}</span>;
}

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={["/notifications"]}>
        <NotificationsPage />
        <LocationProbe />
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
    is_read: false,
    created_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

beforeEach(() => {
  mockState.counters = undefined;
  mockState.list = undefined;
  mockState.loading = false;
  mockState.me = { id: 1, dm_deals: true, dm_deposits: true, dm_system: true };
  mockState.lastType = undefined;
  mockState.lastParams = undefined;
  mockState.updateMe = { mutate: vi.fn() };
  mockState.markRead = { mutate: vi.fn() };
  mockState.markAll = { mutate: vi.fn() };
  apiMock.get.mockReset();
  buildNotificationsSearchParamsMock.mockClear();
});

describe("<NotificationsPage />", () => {
  it("renders skeletons while loading", () => {
    mockState.loading = true;
    const { container } = renderPage();
    expect(container.querySelectorAll(".h-20").length).toBeGreaterThan(0);
  });

  it("renders the empty state when there are no notifications", () => {
    mockState.list = [];
    renderPage();
    expect(screen.getByText("Уведомлений нет")).toBeInTheDocument();
  });

  it("renders notification rows with title/body when data is present", () => {
    mockState.list = [makeNotification()];
    renderPage();
    expect(screen.getByText("Сделка создана")).toBeInTheDocument();
    expect(screen.getByText("У вас новая сделка #42")).toBeInTheDocument();
  });

  it("renders unread badge in header subtitle when counters.unread > 0", () => {
    mockState.counters = {
      all: 5,
      deals: 3,
      deposits: 1,
      system: 1,
      unread: 3,
    };
    mockState.list = [];
    renderPage();
    expect(screen.getByText(/3 непрочитанных/)).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Прочитать все" }),
    ).toBeInTheDocument();
  });

  it("does not coerce malformed unread counters into header actions", () => {
    mockState.counters = {
      all: 5,
      deals: 3,
      deposits: 1,
      system: 1,
      unread: "1e2" as unknown as number,
    };
    mockState.list = [];
    renderPage();
    expect(screen.queryByText(/непрочитанных/)).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /Прочитать все/i }),
    ).not.toBeInTheDocument();
  });

  it("'Прочитать все' calls useMarkAllRead.mutate", async () => {
    mockState.counters = { all: 1, deals: 1, deposits: 0, system: 0, unread: 1 };
    mockState.list = [];
    const user = userEvent.setup();
    renderPage();
    await user.click(screen.getByRole("button", { name: "Прочитать все" }));
    expect(mockState.markAll.mutate).toHaveBeenCalled();
  });

  it("hides 'Прочитать все' when there are no unread notifications", () => {
    mockState.counters = { all: 2, deals: 1, deposits: 1, system: 0, unread: 0 };
    mockState.list = [];
    renderPage();
    expect(
      screen.queryByRole("button", { name: "Прочитать все" }),
    ).not.toBeInTheDocument();
  });

  it("'all' tab passes type=undefined to useNotifications", () => {
    mockState.list = [];
    renderPage();
    expect(mockState.lastType).toBeUndefined();
    expect(mockState.lastParams).toEqual({ type: undefined, limit: 50 });
  });

  it("clicking a tab passes the matching type to useNotifications", async () => {
    mockState.list = [];
    const user = userEvent.setup();
    renderPage();
    await user.click(screen.getByRole("button", { name: /^Депозиты/ }));
    await waitFor(() => expect(mockState.lastType).toBe("deposits"));
  });

  it("loads older notifications with a keyset cursor", async () => {
    const user = userEvent.setup();
    mockState.list = Array.from({ length: 50 }, (_, idx) =>
      makeNotification({
        id: 100 - idx,
        title: `Notification ${idx}`,
        created_at: `2026-01-01T00:${String(59 - idx).padStart(2, "0")}:00Z`,
      }),
    );
    apiMock.get.mockReturnValue({
      json: async () => [makeNotification({ id: 49, title: "Older notification" })],
    });

    renderPage();
    await user.click(screen.getByRole("button", { name: "Показать еще" }));

    expect(apiMock.get).toHaveBeenCalledWith("api/notifications", {
      searchParams: {
        limit: "50",
        before_created_at: "2026-01-01T00:10:00Z",
        before_id: "51",
      },
    });
    expect(await screen.findByText("Older notification")).toBeInTheDocument();
  });

  it("does not send load-more when the keyset cursor is malformed", async () => {
    const user = userEvent.setup();
    const loadMoreName = /\u041f\u043e\u043a\u0430\u0437\u0430\u0442\u044c \u0435\u0449\u0435/;
    const loadMoreError = "\u041d\u0435 \u0443\u0434\u0430\u043b\u043e\u0441\u044c \u0437\u0430\u0433\u0440\u0443\u0437\u0438\u0442\u044c \u0435\u0449\u0435 \u0443\u0432\u0435\u0434\u043e\u043c\u043b\u0435\u043d\u0438\u0439";

    mockState.list = Array.from({ length: 50 }, (_, idx) =>
      makeNotification({
        id: idx === 49 ? 0 : 100 - idx,
        title: `Notification ${idx}`,
        created_at: idx === 49
          ? "not-a-date"
          : `2026-01-01T00:${String(59 - idx).padStart(2, "0")}:00Z`,
      }),
    );

    renderPage();
    await user.click(screen.getByRole("button", { name: loadMoreName }));

    expect(apiMock.get).not.toHaveBeenCalled();
    expect(screen.getByText(loadMoreError)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: loadMoreName })).not.toBeInTheDocument();
  });

  it("clicking a notification row navigates to /notifications/<id>", async () => {
    mockState.list = [makeNotification({ id: 99 })];
    const user = userEvent.setup();
    renderPage();
    await user.click(screen.getByText("Сделка создана"));
    await waitFor(() =>
      expect(screen.getByTestId("path").textContent).toBe(
        "/notifications/99",
      ),
    );
  });

  it("DM toggles dispatch updateMe with the matching key", async () => {
    mockState.list = [];
    const user = userEvent.setup();
    renderPage();
    // The <details> is closed by default; open it.
    const summary = screen.getByText("Присылать в Telegram");
    await user.click(summary);
    // Find the description text (unique) then walk up to the Switch label
    // and click its button to flip the state.
    const description = await screen.findByText(
      "Пополнения и выводы",
    );
    const labelEl = description.closest("label");
    const toggleBtn = labelEl?.querySelector("button");
    expect(toggleBtn).toBeTruthy();
    await user.click(toggleBtn!);
    expect(mockState.updateMe.mutate).toHaveBeenCalledWith({
      dm_deposits: false,
    });
  });
});
