import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { AdminCurrencyDto, AdminUserBalanceDto, AdminUserDetailDto } from "@/api/types";

const mockState = vi.hoisted(() => ({
  user: undefined as AdminUserDetailDto | undefined,
  setRating: { mutateAsync: vi.fn() as ReturnType<typeof vi.fn>, isPending: false },
  setStats: { mutateAsync: vi.fn() as ReturnType<typeof vi.fn>, isPending: false },
  setTrustDeposit: { mutateAsync: vi.fn() as ReturnType<typeof vi.fn>, isPending: false },
  adjustBalance: { mutateAsync: vi.fn() as ReturnType<typeof vi.fn>, isPending: false },
  walletBalances: [] as AdminUserBalanceDto[],
  currencies: [] as AdminCurrencyDto[],
}));

vi.mock("@/api/admin/hooks", () => ({
  useAdminUser: () => ({ data: mockState.user, isLoading: false }),
  useAdminBanUser: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useAdminUnbanUser: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useAdminFreezeUser: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useAdminUnfreezeUser: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useAdminResetPin: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useAdminInvalidateSessions: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useAdminSetRole: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useAdminSetRating: () => mockState.setRating,
  useAdminSetStats: () => mockState.setStats,
  useAdminSetTrustDeposit: () => mockState.setTrustDeposit,
  useAdminUserWallet: () => ({ data: mockState.walletBalances }),
  useAdminCurrencies: () => ({ data: mockState.currencies }),
  useAdminAdjustBalance: () => mockState.adjustBalance,
}));

vi.mock("@/api/hooks", () => ({
  useMe: () => ({ data: { id: 999 } }),
}));

vi.mock("@/hooks/useAdminRedirect", () => ({
  useAdminRedirect: () => ({ shouldRender: true }),
}));

const toastSpy = vi.hoisted(() => vi.fn());
vi.mock("@/components/ui/Toast", () => ({
  useToast: () => ({ show: toastSpy }),
}));

vi.mock("@/lib/tg", () => ({
  useTelegramViewport: () => null,
  haptic: () => {},
  showBackButton: () => () => {},
}));

vi.mock("./UserContentSections", () => ({
  ServicesSection: () => <div />,
  ReviewsSection: () => <div />,
  CommentsSection: () => <div />,
}));

import AdminUserDetailPage from "./AdminUserDetailPage";

function makeUser(overrides: Partial<AdminUserDetailDto> = {}): AdminUserDetailDto {
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
    deals_sum_override: 0,
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
    sessions_count: 2,
    created_at: "2025-01-01T00:00:00Z",
    ...overrides,
  };
}

function makeWalletBalance(overrides: Partial<AdminUserBalanceDto> = {}): AdminUserBalanceDto {
  return {
    user_id: 5,
    username: "alice",
    display_name: "Alice",
    currency_id: 1,
    currency_code: "USDT",
    currency_name: "Tether",
    decimals: 2,
    amount: "10.00",
    locked: "0.00",
    total: "10.00",
    usd_rate: null,
    usd_estimate: null,
    usd_rate_source: null,
    usd_rate_observed_at: null,
    updated_at: null,
    ...overrides,
  };
}

function makeCurrency(overrides: Partial<AdminCurrencyDto> = {}): AdminCurrencyDto {
  return {
    id: 1,
    code: "USDT",
    name: "Tether",
    network: "TRC20",
    icon_url: "",
    decimals: 2,
    min_deposit: 5,
    min_withdraw: 10,
    is_active: true,
    sort_order: 0,
    address_regex: "",
    kind: "crypto",
    ...overrides,
  };
}

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={["/admin/users/5"]}>
        <Routes>
          <Route path="/admin/users/:id" element={<AdminUserDetailPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  mockState.user = makeUser();
  mockState.setRating = { mutateAsync: vi.fn(), isPending: false };
  mockState.setStats = { mutateAsync: vi.fn(), isPending: false };
  mockState.setTrustDeposit = { mutateAsync: vi.fn(), isPending: false };
  mockState.adjustBalance = { mutateAsync: vi.fn(), isPending: false };
  mockState.walletBalances = [];
  mockState.currencies = [];
  toastSpy.mockReset();
});

describe("<AdminUserDetailPage /> numeric forms", () => {
  it.each(["1e0", "5.1"])("blocks ambiguous manual rating %s", async (badRating) => {
    const user = userEvent.setup();
    renderPage();

    fireEvent.change(screen.getByPlaceholderText(/4\.8/), {
      target: { value: badRating },
    });
    await user.click(screen.getByRole("button", { name: "Сохранить" }));

    expect(mockState.setRating.mutateAsync).not.toHaveBeenCalled();
    expect(toastSpy).toHaveBeenCalledWith(
      expect.objectContaining({ kind: "error", title: "Неверное число" }),
    );
  });

  it.each(["1e2", "1.9"])("blocks non-strict integer stat %s", async (badValue) => {
    const user = userEvent.setup();
    renderPage();

    fireEvent.change(screen.getByRole("spinbutton", { name: /Сделок всего/i }), {
      target: { value: badValue },
    });
    await user.click(screen.getByRole("button", { name: /Сохранить статистику/i }));

    expect(mockState.setStats.mutateAsync).not.toHaveBeenCalled();
    expect(toastSpy).toHaveBeenCalledWith(
      expect.objectContaining({ kind: "error", title: expect.stringContaining("Неверное число") }),
    );
  });

  it("submits deals_sum_override as an exact decimal string", async () => {
    mockState.setStats.mutateAsync.mockResolvedValue({});
    const user = userEvent.setup();
    renderPage();

    const inputs = screen.getAllByRole("spinbutton");
    fireEvent.change(inputs[5], {
      target: { value: "123456789.123456789123456789" },
    });
    const saveStats = screen
      .getAllByRole("button")
      .find((button) => button.textContent === "\u0421\u043e\u0445\u0440\u0430\u043d\u0438\u0442\u044c \u0441\u0442\u0430\u0442\u0438\u0441\u0442\u0438\u043a\u0443");
    expect(saveStats).toBeDefined();
    await user.click(saveStats!);

    await waitFor(() =>
      expect(mockState.setStats.mutateAsync).toHaveBeenCalledWith({
        userId: 5,
        body: expect.objectContaining({
          deals_sum_override: "123456789.123456789123456789",
        }),
      }),
    );
  });

  it("blocks exponent trust deposit values", async () => {
    const user = userEvent.setup();
    renderPage();

    fireEvent.change(screen.getByRole("spinbutton", { name: /Новое значение/i }), {
      target: { value: "1e2" },
    });
    await user.click(screen.getByRole("button", { name: /Сохранить трастовый депозит/i }));

    expect(mockState.setTrustDeposit.mutateAsync).not.toHaveBeenCalled();
    expect(toastSpy).toHaveBeenCalledWith(
      expect.objectContaining({ kind: "error", title: "Введите неотрицательное число" }),
    );
  });

  it("submits trust deposit as an exact decimal string", async () => {
    mockState.setTrustDeposit.mutateAsync.mockResolvedValue({});
    const user = userEvent.setup();
    renderPage();

    fireEvent.change(screen.getAllByRole("spinbutton")[8], {
      target: { value: "0.123456789123456789" },
    });
    const saveTrust = screen
      .getAllByRole("button")
      .find((button) => button.textContent === "\u0421\u043e\u0445\u0440\u0430\u043d\u0438\u0442\u044c \u0442\u0440\u0430\u0441\u0442\u043e\u0432\u044b\u0439 \u0434\u0435\u043f\u043e\u0437\u0438\u0442");
    expect(saveTrust).toBeDefined();
    await user.click(saveTrust!);

    await waitFor(() =>
      expect(mockState.setTrustDeposit.mutateAsync).toHaveBeenCalledWith({
        userId: 5,
        body: {
          amount: "0.123456789123456789",
          reason: null,
        },
      }),
    );
  });

  it("keeps per-user balance adjustment disabled for exponent amounts", () => {
    renderPage();

    fireEvent.change(screen.getByPlaceholderText("25.5"), {
      target: { value: "1e2" },
    });

    expect(screen.getByRole("button", { name: /Зачислить/i })).toBeDisabled();
    expect(screen.getByRole("button", { name: /Списать/i })).toBeDisabled();
    expect(mockState.adjustBalance.mutateAsync).not.toHaveBeenCalled();
  });

  it("renders malformed per-user wallet totals as neutral values", () => {
    mockState.walletBalances = [
      makeWalletBalance({
        currency_code: "BAD",
        total: "1e2",
      }),
      makeWalletBalance({
        currency_code: "BROKEN",
        decimals: "2" as unknown as number,
        total: "10.00",
      }),
    ];

    const { container } = renderPage();

    expect(screen.getByText("BAD")).toBeInTheDocument();
    expect(screen.getByText("BROKEN")).toBeInTheDocument();
    expect(container.textContent).toContain("\u2014");
    expect(container.textContent).not.toMatch(/1e2/);
  });

  it("normalizes per-user wallet currency labels before display", () => {
    mockState.walletBalances = [
      makeWalletBalance({
        currency_code: " usdt ",
        total: "10.00",
      }),
      makeWalletBalance({
        currency_id: 2,
        currency_code: "../TON",
        total: "2.00",
      }),
    ];

    const { container } = renderPage();

    expect(container.textContent).toContain("USDT");
    expect(container.textContent).toContain("\u2014");
    expect(container.textContent).not.toMatch(/ usdt /);
    expect(container.textContent).not.toMatch(/\.\.\/TON/);
  });

  it("normalizes the default per-user balance adjustment currency before submitting", async () => {
    mockState.walletBalances = [
      makeWalletBalance({
        currency_id: 2,
        currency_code: " ton ",
        total: "10.00",
      }),
    ];
    mockState.currencies = [
      makeCurrency(),
      makeCurrency({ id: 2, code: "TON", name: "TON" }),
    ];
    mockState.adjustBalance.mutateAsync.mockResolvedValue({});
    const user = userEvent.setup();
    renderPage();

    fireEvent.change(screen.getByPlaceholderText("25.5"), {
      target: { value: "5" },
    });
    await user.click(screen.getByRole("button", { name: /Зачислить/i }));

    await waitFor(() => {
      expect(mockState.adjustBalance.mutateAsync).toHaveBeenCalledWith({
        currency_code: "TON",
        amount: "5",
        reason: undefined,
      });
    });
  });

  it("submits plain per-user balance adjustment amounts", async () => {
    mockState.adjustBalance.mutateAsync.mockResolvedValue({});
    const user = userEvent.setup();
    renderPage();

    fireEvent.change(screen.getByPlaceholderText("25.5"), {
      target: { value: ".5" },
    });
    await user.click(screen.getByRole("button", { name: /Зачислить/i }));

    await waitFor(() => {
      expect(mockState.adjustBalance.mutateAsync).toHaveBeenCalledWith({
        currency_code: "USDT",
        amount: ".5",
        reason: undefined,
      });
    });
  });

  it("submits precise per-user balance debits as signed strings", async () => {
    mockState.adjustBalance.mutateAsync.mockResolvedValue({});
    const user = userEvent.setup();
    renderPage();

    fireEvent.change(screen.getByPlaceholderText("25.5"), {
      target: { value: "0.123456789123456789" },
    });
    const debit = screen
      .getAllByRole("button")
      .find((button) => button.textContent?.includes("\u0421\u043f\u0438\u0441\u0430\u0442\u044c"));
    expect(debit).toBeDefined();
    await user.click(debit!);

    await waitFor(() => {
      expect(mockState.adjustBalance.mutateAsync).toHaveBeenCalledWith({
        currency_code: "USDT",
        amount: "-0.123456789123456789",
        reason: undefined,
      });
    });
  });
});
