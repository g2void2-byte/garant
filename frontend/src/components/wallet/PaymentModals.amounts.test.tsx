import { act, fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ReactElement } from "react";
import type { WalletDepositDto } from "@/api/types";
import { ToastProvider } from "@/components/ui/Toast";
import { DealInvoiceModal } from "./DealInvoiceModal";
import { DepositStatusModal } from "./DepositStatusModal";

const hookState = vi.hoisted(() => ({
  dealStatus: "pending_topup" as string | undefined,
  dealId: undefined as number | undefined,
  liveDeposit: undefined as WalletDepositDto | undefined,
  walletDepositId: undefined as number | undefined,
}));

const openPaymentLinkSpy = vi.hoisted(() => vi.fn());
const refetchSpy = vi.hoisted(() => vi.fn().mockResolvedValue({ data: undefined }));

vi.mock("@/api/hooks", () => ({
  useDeal: (id: number | undefined) => {
    hookState.dealId = id;
    return {
      data: hookState.dealStatus ? { status: hookState.dealStatus } : undefined,
      refetch: refetchSpy,
    };
  },
  useWalletDeposit: (id: number | undefined) => {
    hookState.walletDepositId = id;
    return {
      data: hookState.liveDeposit,
      isLoading: false,
      refetch: refetchSpy,
    };
  },
}));

vi.mock("@/lib/tg", () => ({
  haptic: vi.fn(),
  openPaymentLink: openPaymentLinkSpy,
}));

function renderWithProviders(ui: ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <ToastProvider>{ui}</ToastProvider>
    </QueryClientProvider>,
  );
}

function makeDeposit(overrides: Partial<WalletDepositDto> = {}): WalletDepositDto {
  return {
    id: 501,
    amount: 10,
    pay_url: "https://t.me/CryptoBot?start=invoice_501",
    invoice_id: "INV-501",
    status: "pending",
    purpose: "wallet",
    provider: "cryptobot",
    created_at: "2026-01-01T00:00:00Z",
    paid_at: null,
    currency: {
      id: 1,
      code: "USD",
      name: "US Dollar",
      network: "",
      icon_url: "",
      decimals: 2,
      min_deposit: 1,
      min_withdraw: 1,
      kind: "fiat",
    },
    ...overrides,
  };
}

function runtimeNumber(value: unknown): number {
  return value as number;
}

beforeEach(() => {
  vi.useFakeTimers();
  hookState.dealStatus = "pending_topup";
  hookState.dealId = undefined;
  hookState.liveDeposit = undefined;
  hookState.walletDepositId = undefined;
  openPaymentLinkSpy.mockClear();
  refetchSpy.mockClear();
});

afterEach(() => {
  vi.clearAllTimers();
  vi.useRealTimers();
});

describe("payment modal amount guards", () => {
  it("does not auto-open or render a pay CTA for malformed deal invoice amounts", () => {
    renderWithProviders(
      <DealInvoiceModal
        open
        onClose={vi.fn()}
        dealId={42}
        depositId={501}
        payUrl="https://t.me/CryptoBot?start=deal_501"
        amount={"1e2" as unknown as number}
        currencyCode="USD"
        provider="cryptobot"
        onSuccess={vi.fn()}
        autoOpenDelayMs={1000}
      />,
    );

    expect(screen.getAllByText("\u2014 USD").length).toBeGreaterThan(0);
    expect(screen.getAllByRole("button")).toHaveLength(3);

    act(() => {
      vi.advanceTimersByTime(1000);
    });

    expect(openPaymentLinkSpy).not.toHaveBeenCalled();
  });

  it("normalizes deal invoice modal currency codes before rendering amounts", () => {
    renderWithProviders(
      <DealInvoiceModal
        open
        onClose={vi.fn()}
        dealId={42}
        depositId={501}
        payUrl="https://t.me/CryptoBot?start=deal_501"
        amount={10}
        currencyCode="../USD"
        provider="cryptobot"
        onSuccess={vi.fn()}
        autoOpenDelayMs={1000}
      />,
    );

    expect(screen.getAllByText("10 USD").length).toBeGreaterThan(0);
    expect(screen.queryByText(/\.\.\/USD/)).not.toBeInTheDocument();
  });

  it("renders unknown deal invoice providers as neutral labels", () => {
    renderWithProviders(
      <DealInvoiceModal
        open
        onClose={vi.fn()}
        dealId={42}
        depositId={501}
        payUrl="https://t.me/CryptoBot?start=deal_501"
        amount={10}
        currencyCode="USD"
        provider="provider_reconciled"
        onSuccess={vi.fn()}
        autoOpenDelayMs={1000}
      />,
    );

    expect(screen.getByText(/Провайдер неизвестен/)).toBeInTheDocument();
    expect(screen.queryByText(/provider_reconciled/)).not.toBeInTheDocument();
    expect(screen.queryByText(/^CryptoBot$/)).not.toBeInTheDocument();
  });

  it("normalizes deal invoice ids before polling status", () => {
    renderWithProviders(
      <DealInvoiceModal
        open
        onClose={vi.fn()}
        dealId={runtimeNumber("42")}
        depositId={runtimeNumber("501")}
        payUrl="https://t.me/CryptoBot?start=deal_501"
        amount={10}
        currencyCode="USD"
        provider="cryptobot"
        onSuccess={vi.fn()}
        autoOpenDelayMs={1000}
      />,
    );

    expect(hookState.dealId).toBe(42);
    expect(hookState.walletDepositId).toBe(501);
    expect(hookState.walletDepositId).not.toBe("501");
  });

  it("does not start deal invoice deposit polling for malformed runtime ids", () => {
    renderWithProviders(
      <DealInvoiceModal
        open
        onClose={vi.fn()}
        dealId={42}
        depositId={runtimeNumber("0x501")}
        payUrl="https://t.me/CryptoBot?start=deal_501"
        amount={10}
        currencyCode="USD"
        provider="cryptobot"
        onSuccess={vi.fn()}
        autoOpenDelayMs={1000}
      />,
    );

    expect(screen.getByTestId("deal-invoice-modal")).toBeInTheDocument();
    expect(hookState.walletDepositId).toBeUndefined();
  });

  it("does not auto-open or click through malformed deposit invoice amounts", () => {
    const deposit = makeDeposit({ amount: "0x10" as unknown as number });

    renderWithProviders(
      <DepositStatusModal
        deposit={deposit}
        open
        onClose={vi.fn()}
        autoOpenDelayMs={1000}
      />,
    );

    expect(screen.getAllByText("\u2014 USD").length).toBeGreaterThan(0);
    const buttons = screen.getAllByRole("button");
    const payButton = buttons[buttons.length - 1];
    expect(payButton).toBeDisabled();

    act(() => {
      vi.advanceTimersByTime(1000);
    });
    if (payButton) fireEvent.click(payButton);

    expect(openPaymentLinkSpy).not.toHaveBeenCalled();
  });

  it("normalizes string deposit ids before polling status", () => {
    const deposit = makeDeposit({ id: runtimeNumber("501") });

    renderWithProviders(
      <DepositStatusModal
        deposit={deposit}
        open
        onClose={vi.fn()}
        autoOpenDelayMs={1000}
      />,
    );

    expect(hookState.walletDepositId).toBe(501);
    expect(hookState.walletDepositId).not.toBe("501");
  });

  it("does not start deposit polling for malformed runtime ids", () => {
    const deposit = makeDeposit({ id: runtimeNumber("0x501") });

    renderWithProviders(
      <DepositStatusModal
        deposit={deposit}
        open
        onClose={vi.fn()}
        autoOpenDelayMs={1000}
      />,
    );

    expect(screen.getByTestId("deposit-status-modal")).toBeInTheDocument();
    expect(hookState.walletDepositId).toBeUndefined();
  });

  it("normalizes deposit status modal currency codes before rendering amounts", () => {
    const base = makeDeposit();
    const deposit = makeDeposit({
      currency: {
        ...base.currency,
        code: "../USD",
      },
    });

    renderWithProviders(
      <DepositStatusModal
        deposit={deposit}
        open
        onClose={vi.fn()}
        autoOpenDelayMs={1000}
      />,
    );

    expect(screen.getAllByText("10 USD").length).toBeGreaterThan(0);
    expect(screen.queryByText(/\.\.\/USD/)).not.toBeInTheDocument();
  });

  it("renders unknown deposit status providers as neutral labels", () => {
    const deposit = makeDeposit({ provider: "provider_reconciled" });

    renderWithProviders(
      <DepositStatusModal
        deposit={deposit}
        open
        onClose={vi.fn()}
        autoOpenDelayMs={1000}
      />,
    );

    expect(screen.getByText(/Провайдер неизвестен/)).toBeInTheDocument();
    expect(screen.queryByText(/provider_reconciled/)).not.toBeInTheDocument();
    expect(screen.queryByText(/^CryptoBot$/)).not.toBeInTheDocument();
  });
});
