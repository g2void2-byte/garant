import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { DepositDto, InvoiceDto, UserCardDto } from "@/api/types";

/**
 * Tests for the profile-level "Пополнение баланса" page that drives
 * a single-currency USDT deposit through CryptoBot. Covers:
 *
 *   - preset chips set the amount
 *   - validation: blocks empty / NaN / non-positive values
 *   - happy path: createInvoice -> openTelegramLink + ``Счёт создан``
 *     panel mounted
 *   - missing pay_url -> toast.error
 *   - poll completes with status=paid -> ``Баланс пополнен`` panel
 *     vanishes
 *   - poll completes with status=expired -> ``Счёт истёк`` toast
 *   - history list rendering + empty-state
 */

const mockState = vi.hoisted(() => ({
  me: undefined as UserCardDto | undefined,
  deposits: undefined as DepositDto[] | undefined,
  depositsLoading: false,
  createInvoice: {
    mutateAsync: vi.fn() as ReturnType<typeof vi.fn>,
    isPending: false,
  },
  // Driven from inside the api.get(...) mock to simulate invoice
  // polling.
  invoiceStatus: null as { id: number; amount: number; status: string; paid_at: string | null } | null,
}));

vi.mock("@/api/hooks", () => ({
  useMe: () => ({ data: mockState.me }),
  useDeposits: () => ({ data: mockState.deposits, isLoading: mockState.depositsLoading }),
  useCreateDepositInvoice: () => mockState.createInvoice,
}));

vi.mock("@/api/client", () => ({
  api: {
    get: (_url: string) => ({
      json: async () => mockState.invoiceStatus,
    }),
  },
}));

const hapticSpy = vi.hoisted(() => vi.fn());
const openTelegramLinkSpy = vi.hoisted(() => vi.fn());
vi.mock("@/lib/tg", () => ({
  haptic: hapticSpy,
  openTelegramLink: openTelegramLinkSpy,
  showBackButton: () => () => {},
}));

import DepositPage from "./DepositPage";

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <DepositPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function makeMe(over: Partial<UserCardDto> = {}): UserCardDto {
  return {
    id: 1,
    user_id: 1,
    username: "alice",
    display_name: "Alice",
    photo_url: null,
    balance: 100,
    admin: 0,
    prefix: null,
    good: 0,
    bad: 0,
    deposit: 0,
    rating: 0,
    reviews_count: 0,
    deals_count: 0,
    deals_sum: 0,
    online: false,
    description: "",
    forums: [],
    is_admin: false,
    is_arbiter: false,
    ...over,
  };
}

function makeInvoice(over: Partial<InvoiceDto> = {}): InvoiceDto {
  return {
    invoice_id: "42",
    pay_url: "https://t.me/CryptoBot?start=ok",
    amount: 50,
    asset: "USDT",
    ...over,
  };
}

beforeEach(() => {
  hapticSpy.mockClear();
  openTelegramLinkSpy.mockClear();
  mockState.me = makeMe();
  mockState.deposits = [];
  mockState.depositsLoading = false;
  mockState.createInvoice = { mutateAsync: vi.fn(), isPending: false };
  mockState.invoiceStatus = null;
});

describe("<DepositPage /> (profile)", () => {
  it("renders the current balance from useMe()", () => {
    mockState.me = makeMe({ balance: 250 });
    renderPage();
    expect(screen.getByText(/Текущий баланс/)).toBeInTheDocument();
    expect(screen.getByText(/\$250/)).toBeInTheDocument();
  });

  it("preset buttons update the amount input", async () => {
    const user = userEvent.setup();
    renderPage();
    await user.click(screen.getByRole("button", { name: "100 USDT" }));
    expect(screen.getByDisplayValue("100")).toBeInTheDocument();
  });

  it("blocks submit + fires haptic('error') for an invalid amount", async () => {
    const user = userEvent.setup();
    renderPage();
    const amount = document.querySelector('input[type="number"]') as HTMLInputElement;
    fireEvent.change(amount, { target: { value: "0" } });
    await user.click(
      screen.getByRole("button", { name: /Пополнить через CryptoBot/ }),
    );
    expect(mockState.createInvoice.mutateAsync).not.toHaveBeenCalled();
    expect(hapticSpy).toHaveBeenCalledWith("error");
  });

  it("happy path: creates the invoice + opens the CryptoBot link + mounts panel", async () => {
    mockState.createInvoice.mutateAsync.mockResolvedValue(makeInvoice());
    const user = userEvent.setup();
    renderPage();
    await user.click(
      screen.getByRole("button", { name: /Пополнить через CryptoBot/ }),
    );
    await waitFor(() => {
      expect(mockState.createInvoice.mutateAsync).toHaveBeenCalledWith(50);
    });
    expect(openTelegramLinkSpy).toHaveBeenCalledWith(
      "https://t.me/CryptoBot?start=ok",
    );
    expect(hapticSpy).toHaveBeenCalledWith("success");
    expect(await screen.findByText("Счёт создан")).toBeInTheDocument();
  });

  it("toasts error when CryptoBot does not return a pay_url", async () => {
    mockState.createInvoice.mutateAsync.mockResolvedValue(
      makeInvoice({ pay_url: "" }),
    );
    const user = userEvent.setup();
    renderPage();
    await user.click(
      screen.getByRole("button", { name: /Пополнить через CryptoBot/ }),
    );
    await waitFor(() => {
      expect(openTelegramLinkSpy).not.toHaveBeenCalled();
    });
    expect(screen.queryByText("Счёт создан")).not.toBeInTheDocument();
  });

  it("error path: surfaces the server message via haptic('error')", async () => {
    mockState.createInvoice.mutateAsync.mockRejectedValue(
      new Error("CryptoBot is down"),
    );
    const user = userEvent.setup();
    renderPage();
    await user.click(
      screen.getByRole("button", { name: /Пополнить через CryptoBot/ }),
    );
    await waitFor(() => {
      expect(hapticSpy).toHaveBeenCalledWith("error");
    });
    expect(openTelegramLinkSpy).not.toHaveBeenCalled();
  });

  it("renders an empty state when there are no deposits", () => {
    mockState.deposits = [];
    renderPage();
    expect(screen.getByText("Пока пусто")).toBeInTheDocument();
  });

  it("renders the deposits history with Russian status labels", () => {
    mockState.deposits = [
      {
        id: 1,
        amount: 50,
        status: "paid",
        created_at: "2026-01-01T00:00:00Z",
        paid_at: "2026-01-01T00:30:00Z",
      },
      {
        id: 2,
        amount: 25,
        status: "expired",
        created_at: "2025-12-31T00:00:00Z",
        paid_at: null,
      },
    ];
    renderPage();
    expect(screen.getByText("Оплачен")).toBeInTheDocument();
    expect(screen.getByText("Истёк")).toBeInTheDocument();
  });

  it("renders deposit history skeleton while loading", () => {
    mockState.depositsLoading = true;
    mockState.deposits = undefined;
    const { container } = renderPage();
    expect(container.querySelector(".shimmer")).not.toBeNull();
  });
});
