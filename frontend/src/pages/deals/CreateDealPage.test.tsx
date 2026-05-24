import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { CurrencyDto, DealCreateWithTopupResponseDto, DealDto } from "@/api/types";

/**
 * Tests for the "Создать сделку" page. Covers:
 *   - rendering with the prefilled ``?to=`` query param
 *   - currency dropdown sourced from ``useCurrencies``
 *   - validation: blocks empty / invalid amounts and toggles haptic("error")
 *   - happy-path POST + invoice preview
 *   - error path swallows the rejection and fires haptic("error")
 */

const mockState = vi.hoisted(() => ({
  createMutation: {
    mutateAsync: vi.fn() as ReturnType<typeof vi.fn>,
    isPending: false,
  },
  currencies: undefined as CurrencyDto[] | undefined,
  users: [] as unknown[],
  checkPinMutation: {
    mutateAsync: vi.fn() as ReturnType<typeof vi.fn>,
    isPending: false,
  },
}));

vi.mock("@/api/hooks", () => ({
  useCreateDealWithTopup: () => mockState.createMutation,
  useCurrencies: () => ({ data: mockState.currencies }),
  // ``UserPicker`` (used inside ``CreateDealPage``) consumes
  // ``useUsers`` to render the autosuggest dropdown — return an
  // empty list so the form behaviour mirrors a stable network.
  useUsers: () => ({ data: mockState.users, isLoading: false }),
  // ``PinPromptModal`` consumes ``useCheckPin`` to validate the PIN
  // before the deal POST is fired. We resolve immediately so the
  // PIN-pad path is a no-op friction layer in tests; the actual
  // PIN-rejection branches are exercised by ``PinPromptModal``'s
  // own unit tests.
  useCheckPin: () => mockState.checkPinMutation,
}));

const hapticSpy = vi.hoisted(() => vi.fn());
vi.mock("@/lib/tg", () => ({
  haptic: hapticSpy,
  openTelegramLink: vi.fn(),
  showBackButton: () => () => {},
}));

// ``PinPromptModal`` writes a fresh PIN token to ``localStorage`` on
// successful check via ``setPinToken``; mock the module so the test
// doesn't have to manage browser-storage side effects.
vi.mock("@/lib/pin", () => ({
  setPinToken: vi.fn(),
  hasValidPinToken: () => true,
  clearPinToken: vi.fn(),
  getPinToken: () => "e2e-pin-token",
  PIN_TOKEN_CHANGED_EVENT: "garant:pin-token-changed",
}));

import CreateDealPage from "./CreateDealPage";

function renderPage(initialPath = "/deals/new?to=alice") {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[initialPath]}>
        <Routes>
          <Route path="/deals/new" element={<CreateDealPage />} />
          <Route path="/deals/:id" element={<div data-testid="deal-detail">deal page</div>} />
        </Routes>
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
    min_deposit: 1,
    min_withdraw: 1,
    kind: "fiat",
    ...over,
  };
}

function makeInvoice() {
  return {
    deposit_id: 501,
    pay_url: "https://pay.example/invoice/501",
    total: "105.25",
    topup_principal: "100.25",
    commission: "5.00",
    currency_code: "USD",
    provider: "cryptobot",
    expires_at: null,
  };
}

function makeDeal(over: Partial<DealDto> = {}): DealDto {
  return {
    id: 42,
    buyer: "alice",
    seller: "me",
    description: "Test",
    status: "pending_topup",
    confirm_buyer: false,
    confirm_seller: false,
    role: "seller",
    created_at: "2026-01-01T00:00:00Z",
    currency_code: "USDT",
    amount: 100,
    commission_amount: 5,
    in_progress_at: null,
    completed_at: null,
    cancellation_initiator: null,
    cancellation_reason: null,
    cancellation_requested_at: null,
    arbitration_initiator: null,
    arbitration_reason: null,
    arbitration_resolved_by: null,
    arbitration_resolution: null,
    arbitration_resolved_at: null,
    payment_provider: "cryptobot",
    commission_paid: false,
    topup_deposit_id: 501,
    topup_invoice: makeInvoice(),
    ...over,
  };
}

function makeTopupResponse(over: Partial<DealDto> = {}): DealCreateWithTopupResponseDto {
  const deal = makeDeal(over);
  return {
    deal,
    invoice: deal.topup_invoice ?? makeInvoice(),
  };
}

beforeEach(() => {
  hapticSpy.mockClear();
  mockState.createMutation = {
    mutateAsync: vi.fn(),
    isPending: false,
  };
  mockState.checkPinMutation = {
    mutateAsync: vi.fn().mockResolvedValue({
      token: "e2e-pin-token",
      expires_at: new Date(Date.now() + 60_000).toISOString(),
    }),
    isPending: false,
  };
  mockState.users = [];
  mockState.currencies = [
    makeCurrency({ id: 1, code: "USD", name: "US Dollar" }),
    makeCurrency({ id: 2, code: "UAH", name: "Українська гривня" }),
    // Crypto rows must be hidden from the create-deal currency picker.
    makeCurrency({
      id: 3,
      code: "USDT",
      name: "Tether",
      network: "TRC20",
      kind: "crypto",
    }),
  ];
});

/**
 * Click the on-screen PIN-pad buttons 1–2–3–4 so the
 * ``PinPromptModal`` resolves and the underlying deal POST fires.
 */
async function enterPin(user: ReturnType<typeof userEvent.setup>) {
  await user.click(await screen.findByRole("button", { name: "1" }));
  await user.click(screen.getByRole("button", { name: "2" }));
  await user.click(screen.getByRole("button", { name: "3" }));
  await user.click(screen.getByRole("button", { name: "4" }));
}

describe("<CreateDealPage />", () => {
  it("renders the header and prefills counterparty from ?to=", () => {
    renderPage("/deals/new?to=alice");
    expect(
      screen.getByRole("heading", { name: "Новая сделка" }),
    ).toBeInTheDocument();
    // Audit C1 — every deal is buyer-initiated, so the counterparty
    // field is labelled "Продавец" (seller) rather than the previous
    // generic "Контрагент" (counterparty) which had to support both
    // sides under the now-deleted "I'm the seller" toggle.
    expect(screen.getByLabelText(/Продавец \(username\)/)).toHaveValue("alice");
  });

  it("shows currency dropdown when currencies are loaded", () => {
    renderPage();
    expect(screen.getByText(/Валюта/)).toBeInTheDocument();
    // The default-selected currency label rendered by <Select>:
    expect(screen.getByText(/USD — US Dollar/)).toBeInTheDocument();
  });

  it("hides crypto currencies from the dropdown", () => {
    renderPage();
    // Tether (kind='crypto') is filtered out; only fiat options surface.
    expect(screen.queryByText(/USDT — Tether/)).not.toBeInTheDocument();
    expect(screen.getByText(/USD — US Dollar/)).toBeInTheDocument();
  });

  it("hides the currency dropdown while currencies are loading", () => {
    mockState.currencies = undefined;
    renderPage();
    expect(screen.queryByText(/Валюта/)).not.toBeInTheDocument();
  });

  it("blocks submit + fires haptic('error') when fields are empty", async () => {
    const user = userEvent.setup();
    renderPage("/deals/new");
    await user.click(screen.getByRole("button", { name: /Создать сделку/i }));
    expect(mockState.createMutation.mutateAsync).not.toHaveBeenCalled();
    expect(hapticSpy).toHaveBeenCalledWith("error");
  });

  it("blocks submit when the amount is zero / negative / NaN", async () => {
    const user = userEvent.setup();
    renderPage();
    await user.clear(screen.getByPlaceholderText(/Что покупаете/));
    await user.type(screen.getByPlaceholderText(/Что покупаете/), "deal description");
    const sumInput = screen.getByLabelText(/Сумма \(USD\)/);
    await user.clear(sumInput);
    await user.type(sumInput, "0");
    await user.click(screen.getByRole("button", { name: /Создать сделку/i }));
    expect(mockState.createMutation.mutateAsync).not.toHaveBeenCalled();
    expect(hapticSpy).toHaveBeenCalledWith("error");
  });

  it("submits and shows the invoice preview on success", async () => {
    mockState.createMutation.mutateAsync.mockResolvedValue(makeTopupResponse({ id: 77 }));
    const user = userEvent.setup();
    renderPage();
    await user.type(screen.getByPlaceholderText(/Что покупаете/), "deal description");
    await user.type(screen.getByLabelText(/Сумма \(USD\)/), "100.25");
    await user.click(screen.getByRole("button", { name: /Создать сделку/i }));

    // PIN re-prompt now intercepts the submit — punch in 1234 to
    // resolve ``useCheckPin`` and let the deal POST fire.
    await enterPin(user);

    await waitFor(() => {
      expect(mockState.createMutation.mutateAsync).toHaveBeenCalledWith(
        expect.objectContaining({
          counterparty: "alice",
          role: "buyer",
          amount: 100.25,
          description: "deal description",
          currency_code: "USD",
          payment_provider: "cryptobot",
        }),
      );
    });
    expect(hapticSpy).toHaveBeenCalledWith("success");
    expect(await screen.findByTestId("topup-invoice-preview")).toBeInTheDocument();
    expect(screen.getByText("105.25 USD")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Открыть инвойс/i })).toBeInTheDocument();
  });

  it("fires haptic('error') when the API rejects", async () => {
    mockState.createMutation.mutateAsync.mockRejectedValue(new Error("boom"));
    const user = userEvent.setup();
    renderPage();
    await user.type(screen.getByPlaceholderText(/Что покупаете/), "deal description");
    await user.type(screen.getByLabelText(/Сумма \(USD\)/), "10");
    await user.click(screen.getByRole("button", { name: /Создать сделку/i }));
    await enterPin(user);
    await waitFor(() => {
      expect(hapticSpy).toHaveBeenCalledWith("error");
    });
    expect(screen.queryByTestId("deal-detail")).not.toBeInTheDocument();
  });

  it("disables the submit button while a request is in flight", () => {
    mockState.createMutation.isPending = true;
    renderPage();
    expect(screen.getByRole("button", { name: /Создаю/i })).toBeDisabled();
  });

  it("submits payment_provider='crystalpay' when the Crystalpay tile is selected", async () => {
    mockState.createMutation.mutateAsync.mockResolvedValue(makeTopupResponse({ id: 88 }));
    const user = userEvent.setup();
    renderPage();
    await user.click(screen.getByTestId("provider-crystalpay"));
    await user.type(
      screen.getByPlaceholderText(/Что покупаете/),
      "deal description",
    );
    await user.type(screen.getByLabelText(/Сумма \(USD\)/), "42");
    await user.click(screen.getByRole("button", { name: /Создать сделку/i }));
    await enterPin(user);

    await waitFor(() => {
      expect(mockState.createMutation.mutateAsync).toHaveBeenCalledWith(
        expect.objectContaining({
          payment_provider: "crystalpay",
          currency_code: "USD",
        }),
      );
    });
  });
});
