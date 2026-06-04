import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { CurrencyDto, WalletDepositDto } from "@/api/types";

const mockState = vi.hoisted(() => ({
  currencies: undefined as CurrencyDto[] | undefined,
  currenciesLoading: false,
  me: { deposit: 0 },
  admins: [] as { username: string | null }[],
  createMutation: {
    mutateAsync: vi.fn() as ReturnType<typeof vi.fn>,
    isPending: false,
  },
}));

vi.mock("@/api/hooks", () => ({
  useCurrencies: () => ({
    data: mockState.currencies,
    isLoading: mockState.currenciesLoading,
  }),
  useMe: () => ({ data: mockState.me }),
  useAdmins: () => ({ data: mockState.admins }),
  useCreateWalletDeposit: () => mockState.createMutation,
}));

const hapticSpy = vi.hoisted(() => vi.fn());
const openPaymentLinkSpy = vi.hoisted(() => vi.fn());
const openTelegramLinkSpy = vi.hoisted(() => vi.fn());
vi.mock("@/lib/tg", () => ({
  useTelegramViewport: () => null,
  haptic: hapticSpy,
  openPaymentLink: openPaymentLinkSpy,
  openTelegramLink: openTelegramLinkSpy,
  showBackButton: () => () => {},
}));

import WalletTrustDepositPage from "./WalletTrustDepositPage";

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <WalletTrustDepositPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function makeCurrency(over: Partial<CurrencyDto> = {}): CurrencyDto {
  return {
    id: 1,
    code: "USD",
    name: "US Dollar",
    network: "",
    icon_url: "",
    decimals: 2,
    min_deposit: 5,
    min_withdraw: 1,
    kind: "fiat",
    ...over,
  };
}

function makeDeposit(over: Partial<WalletDepositDto> = {}): WalletDepositDto {
  return {
    id: 1,
    amount: 10,
    pay_url: "https://t.me/CryptoBot?start=trust",
    invoice_id: "INV-TRUST",
    status: "pending",
    purpose: "trust",
    provider: "cryptobot",
    created_at: "2026-01-01T00:00:00Z",
    paid_at: null,
    currency: makeCurrency(),
    ...over,
  };
}

beforeEach(() => {
  hapticSpy.mockClear();
  openPaymentLinkSpy.mockClear();
  openTelegramLinkSpy.mockClear();
  mockState.currenciesLoading = false;
  mockState.currencies = [makeCurrency()];
  mockState.me = { deposit: 0 };
  mockState.admins = [];
  mockState.createMutation = {
    mutateAsync: vi.fn(),
    isPending: false,
  };
});

describe("<WalletTrustDepositPage />", () => {
  it("hides malformed currency rows and submits normalized trust deposits", async () => {
    mockState.currencies = [
      makeCurrency({ id: 1, code: "USD/../admin", name: "Broken Dollar" }),
      makeCurrency({ id: 2, code: " uah ", name: "Hryvnia", min_deposit: 50 }),
    ];
    mockState.createMutation.mutateAsync.mockResolvedValue(
      makeDeposit({ currency: makeCurrency({ code: "UAH", name: "Hryvnia" }) }),
    );
    const user = userEvent.setup();
    renderPage();

    expect(screen.queryByText(/Broken Dollar/)).not.toBeInTheDocument();
    expect(await screen.findByText(/Hryvnia \(UAH\)/)).toBeInTheDocument();

    const amount = screen.getByDisplayValue("50") as HTMLInputElement;
    fireEvent.change(amount, { target: { value: "75" } });
    await user.click(screen.getByRole("button", { name: /^Пополнить$/ }));

    await waitFor(() => {
      expect(mockState.createMutation.mutateAsync).toHaveBeenCalledWith({
        currency_code: "UAH",
        amount: "75",
        purpose: "trust",
      });
    });
    expect(openPaymentLinkSpy).toHaveBeenCalledWith("https://t.me/CryptoBot?start=trust");
  });
});
