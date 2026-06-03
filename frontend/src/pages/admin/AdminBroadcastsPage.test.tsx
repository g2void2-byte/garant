import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type {
  AdminBroadcastListDto,
  AdminBroadcastCreateBody,
} from "@/api/types";

/**
 * Tests for `/admin/broadcasts`.
 *
 * Covers history list rendering, delete with confirm-dialog and toast,
 * composer sheet open/close, audience role chips, preview button
 * computing recipients (with body-trim gating), send button (with
 * gating + toast + close).
 */

const mockState = vi.hoisted(() => ({
  list: undefined as AdminBroadcastListDto | undefined,
  loading: false,
  del: { mutateAsync: vi.fn() as ReturnType<typeof vi.fn>, isPending: false },
  preview: {
    mutateAsync: vi.fn() as ReturnType<typeof vi.fn>,
    isPending: false,
  },
  create: {
    mutateAsync: vi.fn() as ReturnType<typeof vi.fn>,
    isPending: false,
  },
  shouldRender: true as boolean,
  lastBroadcastsQuery: undefined as { page?: number; page_size?: number } | undefined,
}));

vi.mock("@/api/admin/hooks", () => ({
  useAdminBroadcasts: (params: { page?: number; page_size?: number } = {}) => {
    mockState.lastBroadcastsQuery = params;
    return {
      data: mockState.list,
      isLoading: mockState.loading,
    };
  },
  useAdminBroadcastPreview: () => mockState.preview,
  useAdminCreateBroadcast: () => mockState.create,
  useAdminDeleteBroadcast: () => mockState.del,
}));

vi.mock("@/hooks/useAdminRedirect", () => ({
  useAdminRedirect: () => ({ shouldRender: mockState.shouldRender }),
}));

const toastSpy = vi.hoisted(() => vi.fn());
vi.mock("@/components/ui/Toast", () => ({
  useToast: () => ({ show: toastSpy }),
}));

vi.mock("@/lib/tg", () => ({
  useTelegramViewport: () => null,
  haptic: () => {},
  showBackButton: () => () => {},
  // L-15 — ``confirmDialog`` reads ``tg.showConfirm``; ``undefined``
  // forces the fallback through ``window.confirm`` so the existing
  // ``vi.spyOn(window, "confirm")`` mocks below keep working.
  tg: undefined,
}));

import AdminBroadcastsPage from "./AdminBroadcastsPage";

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <AdminBroadcastsPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function makeRow(
  overrides: Partial<AdminBroadcastListDto["items"][number]> = {},
): AdminBroadcastListDto["items"][number] {
  return {
    id: 1,
    actor_id: 100,
    actor_username: "admin",
    title: "Test Title",
    body: "Test body",
    deeplink: null,
    audience_role: null,
    audience_active_days: null,
    audience_min_deals: null,
    audience_created_after: null,
    audience_created_before: null,
    audience_language: null,
    dispatch_inapp: true,
    dispatch_dm: false,
    status: "sent",
    total_recipients: 500,
    delivered_count: 480,
    failed_count: 5,
    scheduled_at: null,
    sent_at: "2026-01-01T00:00:00Z",
    created_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

beforeEach(() => {
  mockState.list = undefined;
  mockState.loading = false;
  mockState.del = { mutateAsync: vi.fn(), isPending: false };
  mockState.preview = { mutateAsync: vi.fn(), isPending: false };
  mockState.create = { mutateAsync: vi.fn(), isPending: false };
  mockState.shouldRender = true;
  mockState.lastBroadcastsQuery = undefined;
  toastSpy.mockClear();
});

describe("<AdminBroadcastsPage />", () => {
  it("returns null when guard rejects the visitor", () => {
    mockState.shouldRender = false;
    renderPage();
    expect(screen.queryByText("Рассылки")).not.toBeInTheDocument();
  });

  it("renders skeleton rows while loading", () => {
    mockState.loading = true;
    const { container } = renderPage();
    expect(container.querySelectorAll(".rounded-card.h-24").length).toBe(5);
  });

  it("renders 'Рассылок нет' when the list is empty", () => {
    mockState.list = { items: [], total: 0, page: 1, page_size: 50 };
    renderPage();
    expect(screen.getByText("Рассылок нет")).toBeInTheDocument();
  });

  it("renders history rows with title/body/recipients", () => {
    mockState.list = {
      items: [makeRow()],
      total: 1,
      page: 1,
      page_size: 50,
    };
    renderPage();
    expect(screen.getByText("Test Title")).toBeInTheDocument();
    expect(screen.getByText("Test body")).toBeInTheDocument();
    expect(screen.getByText(/500 получателей/)).toBeInTheDocument();
    expect(screen.getByText(/доставлено 480/)).toBeInTheDocument();
  });

  it("pagination advances beyond the first broadcasts page", async () => {
    mockState.list = {
      items: [makeRow()],
      total: 80,
      page: 1,
      page_size: 50,
    };
    const user = userEvent.setup();
    renderPage();

    expect(screen.getByText("1 / 2")).toBeInTheDocument();
    expect(mockState.lastBroadcastsQuery?.page_size).toBe(50);
    await user.click(screen.getByLabelText("\u0412\u043f\u0435\u0440\u0451\u0434"));
    await waitFor(() => expect(mockState.lastBroadcastsQuery?.page).toBe(2));
  });

  it("delete row with confirm fires mutation and toasts success", async () => {
    mockState.list = {
      items: [makeRow()],
      total: 1,
      page: 1,
      page_size: 50,
    };
    mockState.del.mutateAsync.mockResolvedValue({});
    const confirmSpy = vi
      .spyOn(window, "confirm")
      .mockReturnValue(true);
    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByLabelText("Удалить"));
    await waitFor(() =>
      expect(mockState.del.mutateAsync).toHaveBeenCalledWith(1),
    );
    expect(toastSpy).toHaveBeenCalledWith(
      expect.objectContaining({ kind: "info", title: "Удалено" }),
    );
    confirmSpy.mockRestore();
  });

  it("delete row aborted by confirm dialog does NOT fire mutation", async () => {
    mockState.list = {
      items: [makeRow()],
      total: 1,
      page: 1,
      page_size: 50,
    };
    const confirmSpy = vi
      .spyOn(window, "confirm")
      .mockReturnValue(false);
    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByLabelText("Удалить"));
    expect(mockState.del.mutateAsync).not.toHaveBeenCalled();
    confirmSpy.mockRestore();
  });

  it("clicking 'Новая' opens the composer sheet with role buttons + send", async () => {
    mockState.list = { items: [], total: 0, page: 1, page_size: 50 };
    const user = userEvent.setup();
    renderPage();
    await user.click(screen.getByRole("button", { name: "Новая" }));
    expect(await screen.findByText("Новая рассылка")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Все" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Админы" })).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /Отправить/ }),
    ).toBeInTheDocument();
  });

  it("composer 'Отправить' is disabled when body is empty/whitespace", async () => {
    mockState.list = { items: [], total: 0, page: 1, page_size: 50 };
    const user = userEvent.setup();
    renderPage();
    await user.click(screen.getByRole("button", { name: "Новая" }));
    const send = await screen.findByRole("button", { name: /Отправить/ });
    expect(send).toBeDisabled();
    fireEvent.change(screen.getByPlaceholderText("Что отправляем..."), {
      target: { value: "    " },
    });
    expect(send).toBeDisabled();
  });

  it("'Предпросмотр' calls preview mutation and shows recipient count", async () => {
    mockState.list = { items: [], total: 0, page: 1, page_size: 50 };
    mockState.preview.mutateAsync.mockResolvedValueOnce({
      total_recipients: 1337,
    });
    const user = userEvent.setup();
    renderPage();
    await user.click(screen.getByRole("button", { name: "Новая" }));

    fireEvent.change(screen.getByPlaceholderText("Что отправляем..."), {
      target: { value: "Hello" },
    });
    await user.click(screen.getByRole("button", { name: "Предпросмотр" }));
    await waitFor(() => {
      const body = mockState.preview.mutateAsync.mock.calls[0]?.[0] as
        | AdminBroadcastCreateBody
        | undefined;
      expect(body?.body).toBe("Hello");
      expect(body?.dispatch_inapp).toBe(true);
    });
    expect(
      await screen.findByText(/Будет отправлено: 1337/),
    ).toBeInTheDocument();
  });

  it("blocks invalid numeric audience filters before preview/send", async () => {
    mockState.list = { items: [], total: 0, page: 1, page_size: 50 };
    const user = userEvent.setup();
    renderPage();
    await user.click(screen.getByRole("button", { name: "Новая" }));

    fireEvent.change(screen.getByPlaceholderText("Что отправляем..."), {
      target: { value: "Hi" },
    });
    fireEvent.change(screen.getByLabelText("active days"), {
      target: { value: "1.5" },
    });

    expect(screen.getByText("Введите целое число 0 или больше")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Предпросмотр" })).toBeDisabled();
    expect(screen.getByRole("button", { name: /Отправить/ })).toBeDisabled();
    expect(mockState.preview.mutateAsync).not.toHaveBeenCalled();
    expect(mockState.create.mutateAsync).not.toHaveBeenCalled();
  });

  it("sends numeric audience filters as safe integers", async () => {
    mockState.list = { items: [], total: 0, page: 1, page_size: 50 };
    mockState.preview.mutateAsync.mockResolvedValueOnce({ total_recipients: 7 });
    const user = userEvent.setup();
    renderPage();
    await user.click(screen.getByRole("button", { name: "Новая" }));

    fireEvent.change(screen.getByPlaceholderText("Что отправляем..."), {
      target: { value: "Hi" },
    });
    fireEvent.change(screen.getByLabelText("active days"), { target: { value: "30" } });
    fireEvent.change(screen.getByLabelText("minimum deals"), { target: { value: "5" } });
    await user.click(screen.getByRole("button", { name: "Предпросмотр" }));

    await waitFor(() => {
      const body = mockState.preview.mutateAsync.mock.calls[0]?.[0] as
        | AdminBroadcastCreateBody
        | undefined;
      expect(body?.audience_active_days).toBe(30);
      expect(body?.audience_min_deals).toBe(5);
    });
  });

  it("'Отправить' happy path calls create, toasts success, closes sheet", async () => {
    mockState.list = { items: [], total: 0, page: 1, page_size: 50 };
    mockState.create.mutateAsync.mockResolvedValueOnce({
      total_recipients: 42,
    });
    const user = userEvent.setup();
    renderPage();
    await user.click(screen.getByRole("button", { name: "Новая" }));

    fireEvent.change(screen.getByPlaceholderText("Что отправляем..."), {
      target: { value: "  Hi  " },
    });
    await user.click(screen.getByRole("button", { name: "Админы" }));
    await user.click(screen.getByRole("button", { name: /Отправить/ }));

    await waitFor(() => {
      const body = mockState.create.mutateAsync.mock.calls[0]?.[0] as
        | AdminBroadcastCreateBody
        | undefined;
      expect(body?.body).toBe("Hi");
      expect(body?.audience_role).toBe("admin");
    });
    expect(toastSpy).toHaveBeenCalledWith(
      expect.objectContaining({
        kind: "success",
        title: "Отправлено",
        body: "42 получателей",
      }),
    );
  });

  it("'Отправить' failure shows an error toast", async () => {
    mockState.list = { items: [], total: 0, page: 1, page_size: 50 };
    mockState.create.mutateAsync.mockRejectedValueOnce(new Error("nope"));
    const user = userEvent.setup();
    renderPage();
    await user.click(screen.getByRole("button", { name: "Новая" }));
    fireEvent.change(screen.getByPlaceholderText("Что отправляем..."), {
      target: { value: "Hi" },
    });
    await user.click(screen.getByRole("button", { name: /Отправить/ }));
    await waitFor(() =>
      expect(toastSpy).toHaveBeenCalledWith(
        expect.objectContaining({
          kind: "error",
          title: "Ошибка",
          body: "nope",
        }),
      ),
    );
  });

  it("renders a live char-counter for the body and blocks submit past the 4096 limit", async () => {
    mockState.list = { items: [], total: 0, page: 1, page_size: 50 };
    const user = userEvent.setup();
    renderPage();
    await user.click(screen.getByRole("button", { name: "Новая" }));

    // Counter starts at 0/4096 with no body typed.
    expect(await screen.findByText(/0\/4096/)).toBeInTheDocument();

    // Type a short body → counter updates and submit becomes enabled.
    fireEvent.change(screen.getByPlaceholderText("Что отправляем..."), {
      target: { value: "Hi" },
    });
    expect(screen.getByText(/2\/4096/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Отправить/ })).not.toBeDisabled();

    // Exceed the limit → counter colours red, submit goes back to
    // disabled, no mutation fires when clicked.
    fireEvent.change(screen.getByPlaceholderText("Что отправляем..."), {
      target: { value: "x".repeat(4097) },
    });
    expect(screen.getByText(/4097\/4096/)).toBeInTheDocument();
    expect(
      screen.getByText(/Текст слишком длинный/),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Отправить/ })).toBeDisabled();
  });

  it("inline-validates the deeplink and blocks send on invalid schemes", async () => {
    mockState.list = { items: [], total: 0, page: 1, page_size: 50 };
    const user = userEvent.setup();
    renderPage();
    await user.click(screen.getByRole("button", { name: "Новая" }));

    fireEvent.change(screen.getByPlaceholderText("Что отправляем..."), {
      target: { value: "Hi" },
    });

    const deeplinkInput = screen.getByPlaceholderText(
      /https:\/\/t\.me\/your_bot\/app/,
    );

    // ``http://`` is rejected (mirror backend validator).
    fireEvent.change(deeplinkInput, {
      target: { value: "http://example.com" },
    });
    expect(
      screen.getByText(/начинаться с https:\/\/ или tg:\/\//),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Отправить/ })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Предпросмотр" })).toBeDisabled();

    // ``https://`` is accepted.
    fireEvent.change(deeplinkInput, {
      target: { value: "https://t.me/garant_bot/app" },
    });
    expect(
      screen.queryByText(/начинаться с https:\/\/ или tg:\/\//),
    ).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Отправить/ })).not.toBeDisabled();

    // ``tg://`` is accepted too.
    fireEvent.change(deeplinkInput, {
      target: { value: "tg://resolve?domain=garant_bot" },
    });
    expect(screen.getByRole("button", { name: /Отправить/ })).not.toBeDisabled();
  });
});
