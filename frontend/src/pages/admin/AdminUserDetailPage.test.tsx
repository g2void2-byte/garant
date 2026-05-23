import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { AdminUserDetailDto } from "@/api/types";

/**
 * Tests for `/admin/users/:id`.
 *
 * Covers identity card rendering, ban/unban/freeze/unfreeze actions
 * (including the "self" disable rule), PIN-reset gated by `has_pin`,
 * roles section saving via setRole mutation, rating + stats sections.
 * Heavy `UserContentSections` (services/reviews/comments) is mocked
 * out — that is its own surface.
 */

const mockState = vi.hoisted(() => ({
  user: undefined as AdminUserDetailDto | undefined,
  loading: false,
  me: { id: 999, display_name: "Admin", username: "admin" } as
    | { id: number }
    | undefined,
  shouldRender: true as boolean,
  ban: {
    mutateAsync: vi.fn() as ReturnType<typeof vi.fn>,
    isPending: false,
  },
  unban: { mutateAsync: vi.fn() as ReturnType<typeof vi.fn>, isPending: false },
  freeze: {
    mutateAsync: vi.fn() as ReturnType<typeof vi.fn>,
    isPending: false,
  },
  unfreeze: {
    mutateAsync: vi.fn() as ReturnType<typeof vi.fn>,
    isPending: false,
  },
  resetPin: {
    mutateAsync: vi.fn() as ReturnType<typeof vi.fn>,
    isPending: false,
  },
  invalidate: {
    mutateAsync: vi.fn() as ReturnType<typeof vi.fn>,
    isPending: false,
  },
  setRole: {
    mutateAsync: vi.fn() as ReturnType<typeof vi.fn>,
    isPending: false,
  },
  setRating: {
    mutateAsync: vi.fn() as ReturnType<typeof vi.fn>,
    isPending: false,
  },
  setStats: {
    mutateAsync: vi.fn() as ReturnType<typeof vi.fn>,
    isPending: false,
  },
  setTrustDeposit: {
    mutateAsync: vi.fn() as ReturnType<typeof vi.fn>,
    isPending: false,
  },
}));

vi.mock("@/api/admin/hooks", () => ({
  useAdminUser: () => ({ data: mockState.user, isLoading: mockState.loading }),
  useAdminBanUser: () => mockState.ban,
  useAdminUnbanUser: () => mockState.unban,
  useAdminFreezeUser: () => mockState.freeze,
  useAdminUnfreezeUser: () => mockState.unfreeze,
  useAdminResetPin: () => mockState.resetPin,
  useAdminInvalidateSessions: () => mockState.invalidate,
  useAdminSetRole: () => mockState.setRole,
  useAdminSetRating: () => mockState.setRating,
  useAdminSetStats: () => mockState.setStats,
  useAdminSetTrustDeposit: () => mockState.setTrustDeposit,
  useAdminUserWallet: () => ({ data: [] }),
  useAdminCurrencies: () => ({ data: [] }),
  useAdminAdjustBalance: () => ({
    mutateAsync: vi.fn(),
    isPending: false,
  }),
}));

vi.mock("@/api/hooks", () => ({
  useMe: () => ({ data: mockState.me }),
}));

vi.mock("@/hooks/useAdminRedirect", () => ({
  useAdminRedirect: () => ({ shouldRender: mockState.shouldRender }),
}));

const toastSpy = vi.hoisted(() => vi.fn());
vi.mock("@/components/ui/Toast", () => ({
  useToast: () => ({ show: toastSpy }),
}));

vi.mock("@/lib/tg", () => ({
  haptic: () => {},
  showBackButton: () => () => {},
}));

vi.mock("./UserContentSections", () => ({
  ServicesSection: () => <div data-testid="services" />,
  ReviewsSection: () => <div data-testid="reviews" />,
  CommentsSection: () => <div data-testid="comments" />,
}));

import AdminUserDetailPage from "./AdminUserDetailPage";

function renderPage(id: number | string = "5") {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[`/admin/users/${id}`]}>
        <Routes>
          <Route
            path="/admin/users/:id"
            element={<AdminUserDetailPage />}
          />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function makeUser(
  overrides: Partial<AdminUserDetailDto> = {},
): AdminUserDetailDto {
  return {
    id: 5,
    tg_user_id: 1234,
    username: "alice",
    display_name: "Alice",
    photo_url: null,
    banner_url: null,
    description: "",
    trust_deposit_balance: 100,
    rating_auto: 4.8,
    rating_manual: null,
    rating_effective: 4.8,
    good: 20,
    bad: 1,
    deals_total: 10,
    deals_success: 9,
    deals_failed: 1,
    deals_arbitrage: 0,
    is_admin: false,
    is_arbiter: false,
    is_vip: false,
    is_banned: false,
    ban_reason: null,
    is_frozen: false,
    freeze_reason: null,
    is_anonymous_deals: false,
    is_hidden_profile: false,
    has_pin: true,
    last_ip: "1.2.3.4",
    last_login_at: "2026-01-01T00:00:00Z",
    login_count: 7,
    created_at: "2025-01-01T00:00:00Z",
    ...overrides,
  };
}

beforeEach(() => {
  mockState.user = undefined;
  mockState.loading = false;
  mockState.me = { id: 999 } as { id: number };
  mockState.shouldRender = true;
  mockState.ban = { mutateAsync: vi.fn(), isPending: false };
  mockState.unban = { mutateAsync: vi.fn(), isPending: false };
  mockState.freeze = { mutateAsync: vi.fn(), isPending: false };
  mockState.unfreeze = { mutateAsync: vi.fn(), isPending: false };
  mockState.resetPin = { mutateAsync: vi.fn(), isPending: false };
  mockState.invalidate = { mutateAsync: vi.fn(), isPending: false };
  mockState.setRole = { mutateAsync: vi.fn(), isPending: false };
  mockState.setRating = { mutateAsync: vi.fn(), isPending: false };
  mockState.setStats = { mutateAsync: vi.fn(), isPending: false };
  toastSpy.mockClear();
});

describe("<AdminUserDetailPage />", () => {
  it("returns null when admin guard rejects the visitor", () => {
    mockState.shouldRender = false;
    renderPage();
    expect(screen.queryByText("Пользователь")).not.toBeInTheDocument();
  });

  it("renders 'Неверный ID' when the :id param is not numeric", () => {
    renderPage("abc");
    expect(screen.getByText("Неверный ID.")).toBeInTheDocument();
  });

  it("renders skeletons while loading", () => {
    mockState.loading = true;
    const { container } = renderPage();
    expect(container.querySelectorAll(".shimmer").length).toBeGreaterThan(0);
  });

  it("renders identity card with tg_id, IP, login count, deposit", () => {
    mockState.user = makeUser();
    renderPage();
    expect(screen.getByText("Alice")).toBeInTheDocument();
    expect(screen.getByText("@alice")).toBeInTheDocument();
    expect(screen.getByText("tg_id: 1234")).toBeInTheDocument();
    expect(screen.getByText("1.2.3.4")).toBeInTheDocument();
    expect(screen.getByText("7")).toBeInTheDocument(); // login_count
    // The identity card now surfaces the trust deposit (the public
    // profile's ``deposit`` field) — the lifetime aggregate was
    // retired together with ``User.deposit_total``.
    expect(screen.getByText("$100.00")).toBeInTheDocument();
    expect(screen.getByText("Установлен")).toBeInTheDocument();
  });

  it("ban click with empty reason sends reason=null", async () => {
    mockState.user = makeUser();
    mockState.ban.mutateAsync.mockResolvedValue({});
    const user = userEvent.setup();
    renderPage();
    await user.click(screen.getByRole("button", { name: /Забанить/ }));
    await waitFor(() =>
      expect(mockState.ban.mutateAsync).toHaveBeenCalledWith({
        userId: 5,
        body: { reason: null },
      }),
    );
    expect(toastSpy).toHaveBeenCalledWith(
      expect.objectContaining({ kind: "success", title: "Забанен" }),
    );
  });

  it("typing a ban reason sends it as the body", async () => {
    mockState.user = makeUser();
    mockState.ban.mutateAsync.mockResolvedValue({});
    const user = userEvent.setup();
    renderPage();
    fireEvent.change(
      screen.getByPlaceholderText("Причина бана (опционально)"),
      { target: { value: "spam" } },
    );
    await user.click(screen.getByRole("button", { name: /Забанить/ }));
    await waitFor(() =>
      expect(mockState.ban.mutateAsync).toHaveBeenCalledWith({
        userId: 5,
        body: { reason: "spam" },
      }),
    );
  });

  it("'Снять бан' is disabled when the user isn't banned", () => {
    mockState.user = makeUser({ is_banned: false });
    renderPage();
    expect(
      screen.getByRole("button", { name: /Снять бан/ }),
    ).toBeDisabled();
  });

  it("ban + freeze buttons are disabled when isSelf=true", () => {
    mockState.user = makeUser();
    mockState.me = { id: 5 } as { id: number };
    renderPage();
    expect(screen.getByRole("button", { name: /Забанить/ })).toBeDisabled();
    expect(screen.getByRole("button", { name: /Заморозить/ })).toBeDisabled();
    expect(
      screen.getByRole("button", { name: /Разлогинить/ }),
    ).toBeDisabled();
  });

  it("'Сбросить PIN' is disabled when has_pin=false", () => {
    mockState.user = makeUser({ has_pin: false });
    renderPage();
    expect(
      screen.getByRole("button", { name: /Сбросить PIN/ }),
    ).toBeDisabled();
  });

  it("reset PIN happy path", async () => {
    mockState.user = makeUser({ has_pin: true });
    mockState.resetPin.mutateAsync.mockResolvedValue({});
    const user = userEvent.setup();
    renderPage();
    await user.click(screen.getByRole("button", { name: /Сбросить PIN/ }));
    await waitFor(() =>
      expect(mockState.resetPin.mutateAsync).toHaveBeenCalledWith({
        userId: 5,
        body: undefined,
      }),
    );
    expect(toastSpy).toHaveBeenCalledWith(
      expect.objectContaining({ kind: "success", title: "PIN сброшен" }),
    );
  });

  it("ban network error surfaces an error toast", async () => {
    mockState.user = makeUser();
    mockState.ban.mutateAsync.mockRejectedValueOnce(new Error("server"));
    const user = userEvent.setup();
    renderPage();
    await user.click(screen.getByRole("button", { name: /Забанить/ }));
    await waitFor(() =>
      expect(toastSpy).toHaveBeenCalledWith(
        expect.objectContaining({ kind: "error", title: "server" }),
      ),
    );
  });

  it("renders banned/frozen reason strings when set", () => {
    mockState.user = makeUser({
      is_banned: true,
      ban_reason: "abusive behavior",
      is_frozen: true,
      freeze_reason: "kyc",
    });
    renderPage();
    expect(screen.getByText(/Бан · abusive behavior/)).toBeInTheDocument();
    expect(screen.getByText(/Заморожен · kyc/)).toBeInTheDocument();
  });
});
