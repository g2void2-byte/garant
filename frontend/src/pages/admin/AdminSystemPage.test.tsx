import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { AdminSystemStatusDto } from "@/api/types";

/**
 * Tests for `/admin/system`.
 *
 * Covers lamp rendering for db/redis/bot/cryptobot, latency text,
 * flush-redis (confirm prompt, success + error path), button gated by
 * `data.redis_ok`, admin guard, loading skeleton.
 */

const mockState = vi.hoisted(() => ({
  data: undefined as AdminSystemStatusDto | undefined,
  loading: false,
  flush: {
    mutateAsync: vi.fn() as ReturnType<typeof vi.fn>,
    isPending: false,
  },
  shouldRender: true as boolean,
}));

vi.mock("@/api/admin/hooks", () => ({
  useAdminSystemStatus: () => ({
    data: mockState.data,
    isLoading: mockState.loading,
  }),
  useAdminFlushRedis: () => mockState.flush,
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

import AdminSystemPage from "./AdminSystemPage";

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <AdminSystemPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function makeStatus(
  overrides: Partial<AdminSystemStatusDto> = {},
): AdminSystemStatusDto {
  return {
    db_ok: true,
    db_latency_ms: 1.234,
    redis_ok: true,
    redis_latency_ms: 0.5,
    cryptobot_configured: true,
    bot_configured: true,
    backend_version: "1.2.3",
    started_at: "2026-01-01T00:00:00Z",
    uptime_seconds: 3600,
    ...overrides,
  };
}

beforeEach(() => {
  mockState.data = undefined;
  mockState.loading = false;
  mockState.flush = { mutateAsync: vi.fn(), isPending: false };
  mockState.shouldRender = true;
  toastSpy.mockClear();
});

describe("<AdminSystemPage />", () => {
  it("returns null when admin guard rejects the visitor", () => {
    mockState.shouldRender = false;
    renderPage();
    expect(screen.queryByText("Система")).not.toBeInTheDocument();
  });

  it("renders skeletons while loading", () => {
    mockState.loading = true;
    const { container } = renderPage();
    expect(container.querySelectorAll(".rounded-card.h-16").length).toBe(4);
  });

  it("renders all four lamps with their detail text and version", () => {
    mockState.data = makeStatus();
    renderPage();
    expect(screen.getByText("Postgres")).toBeInTheDocument();
    expect(screen.getByText("Redis")).toBeInTheDocument();
    expect(screen.getByText("Telegram Bot")).toBeInTheDocument();
    expect(screen.getByText("CryptoBot")).toBeInTheDocument();
    expect(screen.getByText("1.2ms")).toBeInTheDocument(); // db_latency_ms
    expect(screen.getByText("0.5ms")).toBeInTheDocument();
    expect(screen.getByText("токен настроен")).toBeInTheDocument();
    expect(screen.getByText(/Версия: 1\.2\.3/)).toBeInTheDocument();
  });

  it("renders string and malformed system numeric fields without crashing", () => {
    mockState.data = makeStatus({
      db_latency_ms: "1.25" as unknown as number,
      redis_latency_ms: "1e1" as unknown as number,
      uptime_seconds: "not-a-number" as unknown as number,
    });
    renderPage();

    expect(screen.getByText("1.3ms")).toBeInTheDocument();
    expect(screen.getAllByText("\u2014").length).toBeGreaterThan(0);
    expect(screen.queryByText(/10\.0ms/)).not.toBeInTheDocument();
    expect(screen.queryByText(/NaN/)).not.toBeInTheDocument();
  });

  it("renders malformed started_at as a neutral timestamp", () => {
    mockState.data = makeStatus({ started_at: "not-a-date" });
    renderPage();
    expect(
      screen.getAllByText((_, element) => Boolean(element?.textContent?.includes("(с \u2014)"))).length,
    ).toBeGreaterThan(0);
    expect(screen.queryByText(/Invalid Date/)).not.toBeInTheDocument();
  });

  it("renders danger detail when redis is not configured", () => {
    mockState.data = makeStatus({
      redis_ok: false,
      redis_latency_ms: null,
    });
    renderPage();
    expect(
      screen.getByText("не настроен / недоступен"),
    ).toBeInTheDocument();
  });

  it("flush redis button is disabled when redis_ok is false", () => {
    mockState.data = makeStatus({ redis_ok: false, redis_latency_ms: null });
    renderPage();
    const btn = screen.getByRole("button", { name: /Очистить Redis/ });
    expect(btn).toBeDisabled();
  });

  it("flush redis happy path: confirm → success toast", async () => {
    mockState.data = makeStatus();
    mockState.flush.mutateAsync.mockResolvedValue({
      ok: true,
      message: "Done",
    });
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);
    const user = userEvent.setup();
    renderPage();
    await user.click(screen.getByRole("button", { name: /Очистить Redis/ }));
    await waitFor(() =>
      expect(toastSpy).toHaveBeenCalledWith(
        expect.objectContaining({
          kind: "success",
          title: "Redis очищен",
          body: "Done",
        }),
      ),
    );
    confirmSpy.mockRestore();
  });

  it("flush redis confirm-rejected does NOT call mutation", async () => {
    mockState.data = makeStatus();
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(false);
    const user = userEvent.setup();
    renderPage();
    await user.click(screen.getByRole("button", { name: /Очистить Redis/ }));
    expect(mockState.flush.mutateAsync).not.toHaveBeenCalled();
    confirmSpy.mockRestore();
  });

  it("flush redis network error surfaces an error toast", async () => {
    mockState.data = makeStatus();
    mockState.flush.mutateAsync.mockRejectedValueOnce(new Error("nope"));
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);
    const user = userEvent.setup();
    renderPage();
    await user.click(screen.getByRole("button", { name: /Очистить Redis/ }));
    await waitFor(() =>
      expect(toastSpy).toHaveBeenCalledWith(
        expect.objectContaining({
          kind: "error",
          title: "Ошибка",
          body: "nope",
        }),
      ),
    );
    confirmSpy.mockRestore();
  });
});
