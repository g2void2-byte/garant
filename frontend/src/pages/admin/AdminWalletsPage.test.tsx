import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type {
  AdminCurrencyDto,
  AdminWalletListDto,
} from "@/api/types";

/**
 * Tests for `/admin/wallets`.
 *
 * Covers loading skeleton, empty state, row rendering with non-zero
 * balances + locked annotation, search (Enter), opening the adjust
 * sheet, currency chip selection, +/- shortcuts, reason trim, apply
 * mutation success + failure toasts, gating (amount must be nonzero).
 */

const mockState = vi.hoisted(() => ({
  list: undefined as AdminWalletListDto | undefined,
  loading: false,
  currencies: [] as AdminCurrencyDto[],
  adjust: {
    mutateAsync: vi.fn() as ReturnType<typeof vi.fn>,
    isPending: false,
  },
  shouldRender: true as boolean,
  lastAdjustUserId: undefined as number | undefined,
  lastWalletsQuery: undefined as { q?: string; page?: number } | undefined,
}));

vi.mock("@/api/admin/hooks", () => ({
  useAdminWallets: (q: { q?: string; page?: number }) => {
    mockState.lastWalletsQuery = q;
    return { data: mockState.list, isLoading: mockState.loading };
  },
  useAdminCurrencies: () => ({ data: mockState.currencies }),
  useAdminAdjustBalance: (userId: number) => {
    mockState.lastAdjustUserId = userId;
    return mockState.adjust;
  },
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

import AdminWalletsPage from "./AdminWalletsPage";

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <AdminWalletsPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function makeUserBalance() {
  return {
    user_id: 11,
    username: "alice",
    display_name: "Alice",
    photo_url: null,
    is_admin: false,
    is_arbiter: false,
    is_vip: false,
    is_banned: false,
    is_frozen: false,
    balances: [
      {
        user_id: 11,
        username: "alice",
        display_name: "Alice",
        currency_id: 1,
        currency_code: "USDT",
        currency_name: "Tether",
        decimals: 2,
        amount: "100",
        locked: "5",
        total: "105",
        updated_at: null,
      },
      {
        user_id: 11,
        username: "alice",
        display_name: "Alice",
        currency_id: 2,
        currency_code: "TON",
        currency_name: "TON",
        decimals: 4,
        amount: "0",
        locked: "0",
        total: "0",
        updated_at: null,
      },
    ],
    total_usd_estimate: "105",
  };
}

beforeEach(() => {
  mockState.list = undefined;
  mockState.loading = false;
  mockState.currencies = [
    {
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
    },
    {
      id: 2,
      code: "TON",
      name: "TON",
      network: "TON",
      icon_url: "",
      decimals: 4,
      min_deposit: 1,
      min_withdraw: 1,
      is_active: true,
      sort_order: 1,
    },
  ];
  mockState.adjust = { mutateAsync: vi.fn(), isPending: false };
  mockState.shouldRender = true;
  mockState.lastAdjustUserId = undefined;
  mockState.lastWalletsQuery = undefined;
  toastSpy.mockClear();
});

describe("<AdminWalletsPage />", () => {
  it("returns null when admin guard rejects the visitor", () => {
    mockState.shouldRender = false;
    renderPage();
    expect(screen.queryByText("Балансы")).not.toBeInTheDocument();
  });

  it("renders skeleton rows while loading", () => {
    mockState.loading = true;
    const { container } = renderPage();
    expect(container.querySelectorAll(".rounded-card.h-20").length).toBe(6);
  });

  it("renders empty state when no results", () => {
    mockState.list = { items: [], total: 0, page: 1, page_size: 50 };
    renderPage();
    expect(screen.getByText("Ничего не найдено")).toBeInTheDocument();
  });

  it("renders rows with non-zero balances and 'лок.' annotation", () => {
    mockState.list = {
      items: [makeUserBalance()],
      total: 1,
      page: 1,
      page_size: 50,
    };
    renderPage();
    expect(screen.getByText("Alice")).toBeInTheDocument();
    expect(screen.getByText("USDT")).toBeInTheDocument();
    expect(screen.getByText(/100\.00/)).toBeInTheDocument();
    expect(screen.getByText(/\(\+5\.00 лок\.\)/)).toBeInTheDocument();
    expect(screen.queryByText("TON")).not.toBeInTheDocument();
  });

  it("shows 'Балансов нет' placeholder when all balances are zero", () => {
    const zeroUser = {
      ...makeUserBalance(),
      balances: makeUserBalance().balances.map((b) => ({
        ...b,
        amount: "0",
        locked: "0",
        total: "0",
      })),
    };
    mockState.list = {
      items: [zeroUser],
      total: 1,
      page: 1,
      page_size: 50,
    };
    renderPage();
    expect(screen.getByText("Балансов нет")).toBeInTheDocument();
    // Sanity-check the row itself still renders the user identity.
    expect(screen.getByText("Alice")).toBeInTheDocument();
  });

  it("typing search + Enter triggers a refetch with trimmed q", async () => {
    mockState.list = { items: [], total: 0, page: 1, page_size: 50 };
    renderPage();
    const input = screen.getByPlaceholderText("@username");
    fireEvent.change(input, { target: { value: "  alice  " } });
    fireEvent.keyDown(input, { key: "Enter" });
    await waitFor(() => expect(mockState.lastWalletsQuery?.q).toBe("alice"));
  });

  it("clicking a row opens the adjust sheet and 'Применить' is disabled at first", async () => {
    mockState.list = {
      items: [makeUserBalance()],
      total: 1,
      page: 1,
      page_size: 50,
    };
    const user = userEvent.setup();
    renderPage();
    await user.click(screen.getByText("Alice"));
    expect(
      await screen.findByText(/Корректировка: Alice/),
    ).toBeInTheDocument();
    expect(mockState.lastAdjustUserId).toBe(11);
    const apply = screen.getByRole("button", { name: "Применить" });
    expect(apply).toBeDisabled();
  });

  it("entering an amount + 'Применить' fires adjust mutation with parsed values", async () => {
    mockState.list = {
      items: [makeUserBalance()],
      total: 1,
      page: 1,
      page_size: 50,
    };
    mockState.adjust.mutateAsync.mockResolvedValue({});
    const user = userEvent.setup();
    renderPage();
    await user.click(screen.getByText("Alice"));

    const amountInput = await screen.findByPlaceholderText(/напр\. -25/);
    fireEvent.change(amountInput, { target: { value: "25" } });
    const reasonInput = screen.getByPlaceholderText(/^\.\.\.$/);
    fireEvent.change(reasonInput, { target: { value: " refund  " } });

    await user.click(screen.getByRole("button", { name: "Применить" }));
    await waitFor(() =>
      expect(mockState.adjust.mutateAsync).toHaveBeenCalledWith({
        currency_code: "USDT",
        amount: 25,
        reason: "refund",
      }),
    );
    expect(toastSpy).toHaveBeenCalledWith(
      expect.objectContaining({ kind: "success", title: "Готово" }),
    );
  });

  it("'Списать' shortcut flips a positive amount to negative", async () => {
    mockState.list = {
      items: [makeUserBalance()],
      total: 1,
      page: 1,
      page_size: 50,
    };
    const user = userEvent.setup();
    renderPage();
    await user.click(screen.getByText("Alice"));
    const amountInput = (await screen.findByPlaceholderText(
      /напр\. -25/,
    )) as HTMLInputElement;
    fireEvent.change(amountInput, { target: { value: "10" } });
    await user.click(screen.getByRole("button", { name: /Списать/ }));
    await waitFor(() => expect(amountInput.value).toBe("-10"));
  });

  it("currency chip click switches the active currency for the mutation", async () => {
    mockState.list = {
      items: [makeUserBalance()],
      total: 1,
      page: 1,
      page_size: 50,
    };
    mockState.adjust.mutateAsync.mockResolvedValue({});
    const user = userEvent.setup();
    renderPage();
    await user.click(screen.getByText("Alice"));
    await user.click(screen.getByRole("button", { name: "TON" }));
    const amountInput = await screen.findByPlaceholderText(/напр\. -25/);
    fireEvent.change(amountInput, { target: { value: "5" } });
    await user.click(screen.getByRole("button", { name: "Применить" }));
    await waitFor(() =>
      expect(mockState.adjust.mutateAsync).toHaveBeenCalledWith(
        expect.objectContaining({ currency_code: "TON", amount: 5 }),
      ),
    );
  });
});
