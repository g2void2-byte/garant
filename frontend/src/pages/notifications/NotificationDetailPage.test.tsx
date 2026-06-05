import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { NotificationDto } from "@/api/types";

const mockState = vi.hoisted(() => ({
  data: undefined as NotificationDto | undefined,
  isLoading: false,
  isError: false,
  lastId: undefined as number | undefined,
  markRead: { mutate: vi.fn() as ReturnType<typeof vi.fn> },
}));

vi.mock("@/api/hooks", () => ({
  useNotification: (id: number | undefined) => {
    mockState.lastId = id;
    return {
      data: mockState.data,
      isLoading: mockState.isLoading,
      isError: mockState.isError,
    };
  },
  useMarkNotificationRead: () => mockState.markRead,
}));

vi.mock("@/lib/tg", () => ({
  useTelegramViewport: () => null,
  showBackButton: () => () => {},
}));

import NotificationDetailPage from "./NotificationDetailPage";

function makeNotification(
  overrides: Partial<NotificationDto> = {},
): NotificationDto {
  return {
    id: 42,
    type: "deals",
    title: "Сделка создана",
    body: "Новая сделка #42",
    payload: { deal_id: 42 },
    is_read: false,
    created_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

function renderAt(id: number | string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[`/notifications/${id}`]}>
        <Routes>
          <Route path="/notifications/:id" element={<NotificationDetailPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  mockState.data = undefined;
  mockState.isLoading = false;
  mockState.isError = false;
  mockState.lastId = undefined;
  mockState.markRead = { mutate: vi.fn() };
});

describe("<NotificationDetailPage />", () => {
  it("rejects ambiguous route ids before querying the notification detail", () => {
    renderAt("1e2");
    expect(mockState.lastId).toBeUndefined();
    expect(screen.getByText("Уведомление не найдено")).toBeInTheDocument();
  });

  it("marks an unread loaded notification as read", async () => {
    mockState.data = makeNotification();
    renderAt(42);
    await waitFor(() => expect(mockState.markRead.mutate).toHaveBeenCalledWith(42));
  });

  it("uses the canonical route id when marking the loaded notification as read", async () => {
    mockState.data = makeNotification({ id: "0x2" as unknown as number });
    renderAt(42);
    await waitFor(() => expect(mockState.markRead.mutate).toHaveBeenCalledWith(42));
  });

  it("does not build deal links from ambiguous payload or body ids", () => {
    mockState.data = makeNotification({
      payload: { deal_id: "0x2" },
      body: "Новая сделка #0",
    });
    renderAt(42);
    expect(
      screen.queryByRole("button", { name: /Открыть сделку/i }),
    ).not.toBeInTheDocument();
  });
});
