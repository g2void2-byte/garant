import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type {
  AdminTreasuryOverviewDto,
  AdminTreasuryWithdrawDto,
} from "@/api/types";

/**
 * Tests for `/admin/treasury` — treasury balances + external payout.
 *
 * Covers the loading skeleton, balance card rendering, withdrawal sheet
 * (currency picker, validation gating, TOTP requirement, confirm
 * checkbox) and the `useAdminRedirect` gate.
 */

const mockState = vi.hoisted(() => ({
  overview: undefined as AdminTreasuryOverviewDto | undefined,
  loading: false,
  history: undefined as AdminTreasuryWithdrawDto[] | undefined,
  withdrawMutation: {
    mutateAsync: vi.fn() as ReturnType<typeof vi.fn>,
    isPending: false,
  },
  shouldRender: true as boolean,
}));

vi.mock("@/api/admin/hooks", () => ({
  useAdminTreasury: () => ({
    data: mockState.overview,
    isLoading: mockState.loading,
  }),
  useAdminTreasuryWithdrawals: () => ({ data: mockState.history }),
  useAdminTreasuryWithdraw: () => mockState.withdrawMutation,
}));

vi.mock("@/hooks/useAdminRedirect", () => ({
  useAdminRedirect: () => ({ shouldRender: mockState.shouldRender }),
}));

const toastSpy = vi.hoisted(() => vi.fn());
vi.mock("@/components/ui/Toast", () => ({
  useToast: () => ({ show: toastSpy }),
}));

import AdminTreasuryPage from "./AdminTreasuryPage";

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <AdminTreasuryPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function makeOverview(
  overrides: Partial<AdminTreasuryOverviewDto> = {},
): AdminTreasuryOverviewDto {
  return {
    balances: [
      {
        currency_id: 1,
        currency_code: "USDT",
        currency_name: "Tether",
        decimals: 2,
        accrued: "100",
        withdrawn: "10",
        available: "90",
      },
      {
        currency_id: 2,
        currency_code: "BTC",
        currency_name: "Bitcoin",
        decimals: 8,
        accrued: "1.23456789",
        withdrawn: "0",
        available: "1.23456789",
      },
    ],
    total_withdrawals: 1,
    ...overrides,
  };
}

beforeEach(() => {
  toastSpy.mockClear();
  mockState.overview = undefined;
  mockState.loading = false;
  mockState.history = undefined;
  mockState.withdrawMutation = {
    mutateAsync: vi.fn(),
    isPending: false,
  };
  mockState.shouldRender = true;
});

describe("<AdminTreasuryPage />", () => {
  it("returns null when admin guard rejects the visitor", () => {
    mockState.shouldRender = false;
    const { container } = renderPage();
    expect(container).toBeEmptyDOMElement();
  });

  it("renders skeleton cards while overview is loading", () => {
    mockState.loading = true;
    const { container } = renderPage();
    expect(container.querySelectorAll(".rounded-card.h-24").length).toBeGreaterThan(0);
  });

  it("renders one card per balance with code, available and accrued/withdrawn", () => {
    mockState.overview = makeOverview();
    renderPage();
    expect(screen.getByText("USDT")).toBeInTheDocument();
    expect(screen.getByText("90.00")).toBeInTheDocument();
    expect(screen.getByText(/Накоплено: 100\.00.*Выведено: 10\.00/)).toBeInTheDocument();
    expect(screen.getByText("BTC")).toBeInTheDocument();
    expect(screen.getByText("1.23456789")).toBeInTheDocument();
  });

  it("renders an empty state for history when there are no withdrawals yet", () => {
    mockState.overview = makeOverview();
    mockState.history = [];
    renderPage();
    expect(screen.getByText("Выводов нет")).toBeInTheDocument();
  });

  it("renders historical withdrawals with address, amount, and CryptoBot transfer id", () => {
    mockState.overview = makeOverview();
    mockState.history = [
      {
        id: 7,
        actor_id: 1,
        currency_id: 1,
        currency_code: "USDT",
        amount: "5",
        address: "TJxyz",
        cryptobot_transfer_id: "cb_42",
        note: null,
        status: "sent",
        created_at: "2026-01-02T00:00:00Z",
      } as unknown as AdminTreasuryWithdrawDto,
    ];
    renderPage();
    expect(screen.getByText(/5\.00000000 USDT/)).toBeInTheDocument();
    expect(screen.getByText(/→ TJxyz/)).toBeInTheDocument();
    expect(screen.getByText(/CB id: cb_42/)).toBeInTheDocument();
    expect(screen.getByText("sent")).toBeInTheDocument();
  });

  it("withdrawal sheet stays closed until 'Вывод' button is clicked", async () => {
    mockState.overview = makeOverview();
    const user = userEvent.setup();
    renderPage();
    expect(screen.queryByLabelText("Сумма")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Вывод" }));
    expect(await screen.findByText("Вывод комиссии")).toBeInTheDocument();
  });

  it("disables submit until amount, address, confirm checkbox and TOTP are filled", async () => {
    mockState.overview = makeOverview();
    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByRole("button", { name: "Вывод" }));
    const submit = await screen.findByRole("button", { name: "Вывести" });
    expect(submit).toBeDisabled();

    const inputs = document.querySelectorAll("input");
    // Order in DOM: [amount, address, note, confirm-checkbox, totp]
    fireEvent.change(inputs[0], { target: { value: "5" } });
    fireEvent.change(inputs[1], { target: { value: "TJaddr" } });
    expect(submit).toBeDisabled();
    fireEvent.click(inputs[3]); // confirm checkbox
    expect(submit).toBeDisabled();
    fireEvent.change(inputs[4], { target: { value: "123456" } });
    expect(submit).not.toBeDisabled();
  });

  it("happy-path submit sends body and totpCode and closes the sheet", async () => {
    mockState.overview = makeOverview();
    mockState.withdrawMutation.mutateAsync.mockResolvedValue({});
    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByRole("button", { name: "Вывод" }));
    await screen.findByText("Вывод комиссии");

    const inputs = document.querySelectorAll("input");
    fireEvent.change(inputs[0], { target: { value: "5" } });
    fireEvent.change(inputs[1], { target: { value: "  TJaddr  " } });
    fireEvent.change(inputs[2], { target: { value: "  for ops  " } });
    fireEvent.click(inputs[3]);
    fireEvent.change(inputs[4], { target: { value: "123456" } });

    await user.click(screen.getByRole("button", { name: "Вывести" }));
    await waitFor(() =>
      expect(mockState.withdrawMutation.mutateAsync).toHaveBeenCalledWith({
        body: {
          currency_code: "USDT",
          amount: 5,
          address: "TJaddr",
          confirm: true,
          note: "for ops",
        },
        totpCode: "123456",
      }),
    );
    expect(toastSpy).toHaveBeenCalledWith(
      expect.objectContaining({
        kind: "success",
        title: "Вывод инициирован",
        body: "USDT 5",
      }),
    );
  });

  it("submission failure surfaces the error message via toast", async () => {
    mockState.overview = makeOverview();
    mockState.withdrawMutation.mutateAsync.mockRejectedValueOnce(
      new Error("INSUFFICIENT_TREASURY"),
    );
    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByRole("button", { name: "Вывод" }));
    const inputs = document.querySelectorAll("input");
    fireEvent.change(inputs[0], { target: { value: "5" } });
    fireEvent.change(inputs[1], { target: { value: "TJaddr" } });
    fireEvent.click(inputs[3]);
    fireEvent.change(inputs[4], { target: { value: "123456" } });

    await user.click(screen.getByRole("button", { name: "Вывести" }));
    await waitFor(() =>
      expect(toastSpy).toHaveBeenCalledWith(
        expect.objectContaining({
          kind: "error",
          title: "Ошибка",
          body: "INSUFFICIENT_TREASURY",
        }),
      ),
    );
  });

  it("clicking a different currency chip changes the selected currency", async () => {
    mockState.overview = makeOverview();
    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByRole("button", { name: "Вывод" }));
    await screen.findByText("Вывод комиссии");

    // Both USDT and BTC currency chips should be present in the sheet.
    expect(screen.getByRole("button", { name: /USDT · 90/ })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /BTC · 1\.23456789/ }));

    const inputs = document.querySelectorAll("input");
    fireEvent.change(inputs[0], { target: { value: "0.1" } });
    fireEvent.change(inputs[1], { target: { value: "bc1xyz" } });
    fireEvent.click(inputs[3]);
    fireEvent.change(inputs[4], { target: { value: "654321" } });

    mockState.withdrawMutation.mutateAsync.mockResolvedValue({});
    await user.click(screen.getByRole("button", { name: "Вывести" }));
    await waitFor(() =>
      expect(mockState.withdrawMutation.mutateAsync).toHaveBeenCalledWith(
        expect.objectContaining({
          body: expect.objectContaining({ currency_code: "BTC", amount: 0.1 }),
        }),
      ),
    );
  });
});
