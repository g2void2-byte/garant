import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type {
  AdminDealDetailDto,
  AdminBalanceSnapshotDto,
} from "@/api/types";

type MessageDto = {
  id: number;
  deal_id: number;
  sender_id: number;
  sender_username: string | null;
  text: string;
  attachments: unknown[];
  created_at: string;
};

/**
 * Tests for `/admin/deals/:id`.
 *
 * Covers status banner labels + colours, balance snapshot, ActionPanel
 * visibility gating by `me.is_admin`, force-release/refund/split
 * (terminal status disables actions), events timeline rendering, and
 * admin guard with allowArbiter=true.
 */

const mockState = vi.hoisted(() => ({
  deal: undefined as AdminDealDetailDto | undefined,
  lastDealId: undefined as number | undefined,
  loading: false,
  me: { id: 999, is_admin: true } as
    | { id: number; is_admin: boolean }
    | undefined,
  shouldRender: true as boolean,
  lastRedirectOpts: undefined as { allowArbiter?: boolean } | undefined,
  messages: [] as MessageDto[] | undefined,
  messagesLoading: false,
  release: { mutateAsync: vi.fn() as ReturnType<typeof vi.fn>, isPending: false },
  refund: { mutateAsync: vi.fn() as ReturnType<typeof vi.fn>, isPending: false },
  split: { mutateAsync: vi.fn() as ReturnType<typeof vi.fn>, isPending: false },
  approve: { mutateAsync: vi.fn() as ReturnType<typeof vi.fn>, isPending: false },
  reject: { mutateAsync: vi.fn() as ReturnType<typeof vi.fn>, isPending: false },
  arb: { mutateAsync: vi.fn() as ReturnType<typeof vi.fn>, isPending: false },
  assign: { mutateAsync: vi.fn() as ReturnType<typeof vi.fn>, isPending: false },
  del: { mutateAsync: vi.fn() as ReturnType<typeof vi.fn>, isPending: false },
  loadOlder: { mutateAsync: vi.fn() as ReturnType<typeof vi.fn>, isPending: false },
  sendMessage: { mutateAsync: vi.fn() as ReturnType<typeof vi.fn>, isPending: false },
}));

vi.mock("@/api/admin/hooks", () => ({
  useAdminDeal: (dealId: number | undefined) => {
    mockState.lastDealId = dealId;
    return { data: mockState.deal, isLoading: mockState.loading };
  },
  useAdminForceRelease: () => mockState.release,
  useAdminForceRefund: () => mockState.refund,
  useAdminSplitDeal: () => mockState.split,
  useAdminApproveDealApproval: () => mockState.approve,
  useAdminRejectDealApproval: () => mockState.reject,
  useAdminForceArbitration: () => mockState.arb,
  useAdminAssignArbiter: () => mockState.assign,
  useAdminDeleteDeal: () => mockState.del,
}));

vi.mock("@/api/hooks", () => ({
  DEAL_MESSAGE_PAGE_SIZE: 50,
  useDealMessages: () => ({ data: mockState.messages, isLoading: mockState.messagesLoading }),
  useLoadOlderDealMessages: () => mockState.loadOlder,
  useSendDealMessage: () => mockState.sendMessage,
  useMe: () => ({ data: mockState.me }),
}));

vi.mock("@/hooks/useAdminRedirect", () => ({
  useAdminRedirect: (opts?: { allowArbiter?: boolean }) => {
    mockState.lastRedirectOpts = opts;
    return { shouldRender: mockState.shouldRender };
  },
}));

const toastSpy = vi.hoisted(() => vi.fn());
const apiGetSpy = vi.hoisted(() => vi.fn());
vi.mock("@/components/ui/Toast", () => ({
  useToast: () => ({ show: toastSpy }),
}));

vi.mock("@/lib/tg", () => ({
  useTelegramViewport: () => null,
  haptic: () => {},
  showBackButton: () => () => {},
}));

vi.mock("@/api/client", () => ({
  api: {
    get: apiGetSpy,
    post: () => ({
      json: async () => ({}),
    }),
  },
}));

import AdminDealDetailPage from "./AdminDealDetailPage";

function renderPage(id: number | string = "10") {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[`/admin/deals/${id}`]}>
        <Routes>
          <Route path="/admin/deals/:id" element={<AdminDealDetailPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function makeSnap(
  overrides: Partial<AdminBalanceSnapshotDto> = {},
): AdminBalanceSnapshotDto {
  return {
    user_id: 1,
    username: "alice",
    display_name: "Alice",
    currency_code: "USDT",
    amount: "10.0000",
    locked: "5.0000",
    total: "15.0000",
    ...overrides,
  };
}

function makeDeal(
  overrides: Partial<AdminDealDetailDto> = {},
): AdminDealDetailDto {
  return {
    id: 10,
    status: "in_progress",
    description: "Buying widgets",
    currency_code: "USDT",
    amount: "150.00",
    commission_amount: "3.00",
    commission_paid: true,
    topup_deposit_id: null,
    buyer: makeSnap({ user_id: 1, username: "buyer", display_name: "Buyer" }),
    seller: makeSnap({ user_id: 2, username: "seller", display_name: "Seller" }),
    created_at: "2026-01-01T00:00:00Z",
    in_progress_at: "2026-01-02T00:00:00Z",
    completed_at: null,
    cancellation_initiator: null,
    cancellation_reason: null,
    cancellation_requested_at: null,
    arbitration_initiator: null,
    arbitration_reason: null,
    arbitration_resolved_by_id: null,
    arbitration_resolved_by_username: null,
    arbitration_resolution: null,
    arbitration_resolved_at: null,
    confirm_buyer: false,
    confirm_seller: false,
    events: [
      {
        at: "2026-01-01T00:00:00Z",
        kind: "created",
        actor: "buyer",
        description: "Сделка создана",
      },
      {
        at: "2026-01-02T00:00:00Z",
        kind: "in_progress",
        actor: "seller",
        description: "Подтверждено",
      },
    ],
    messages: [],
    ...overrides,
  };
}

function makeMessage(overrides: Partial<MessageDto> = {}): MessageDto {
  return {
    id: 1,
    deal_id: 10,
    sender_id: 1,
    sender_username: "buyer",
    text: "message",
    attachments: [],
    created_at: "2026-01-03T00:00:00Z",
    ...overrides,
  };
}

function getLoadOlderButton(): HTMLElement | undefined {
  return screen
    .getAllByRole("button")
    .find((button) => button.className.includes("underline-offset-2"));
}

beforeEach(() => {
  mockState.deal = undefined;
  mockState.lastDealId = undefined;
  mockState.loading = false;
  mockState.me = { id: 999, is_admin: true };
  mockState.shouldRender = true;
  mockState.lastRedirectOpts = undefined;
  mockState.messages = [];
  mockState.messagesLoading = false;
  mockState.release = { mutateAsync: vi.fn(), isPending: false };
  mockState.refund = { mutateAsync: vi.fn(), isPending: false };
  mockState.split = { mutateAsync: vi.fn(), isPending: false };
  mockState.approve = { mutateAsync: vi.fn(), isPending: false };
  mockState.reject = { mutateAsync: vi.fn(), isPending: false };
  mockState.arb = { mutateAsync: vi.fn(), isPending: false };
  mockState.assign = { mutateAsync: vi.fn(), isPending: false };
  mockState.del = { mutateAsync: vi.fn(), isPending: false };
  mockState.loadOlder = { mutateAsync: vi.fn(), isPending: false };
  mockState.sendMessage = { mutateAsync: vi.fn(), isPending: false };
  toastSpy.mockClear();
  apiGetSpy.mockReset();
  apiGetSpy.mockReturnValue({
    json: async () => ({ items: [] }),
  });
});

describe("<AdminDealDetailPage />", () => {
  it("returns null when admin guard rejects the visitor", () => {
    mockState.shouldRender = false;
    renderPage();
    expect(screen.queryByText(/Сделка/)).not.toBeInTheDocument();
  });

  it("requests allowArbiter=true from useAdminRedirect", () => {
    mockState.deal = makeDeal();
    renderPage();
    expect(mockState.lastRedirectOpts).toEqual({ allowArbiter: true });
  });

  it.each(["xyz", "0", "1e2", "0x10"])(
    "renders 'Неверный ID' for invalid :id=%s without querying detail",
    (id) => {
      renderPage(id);
      expect(mockState.lastDealId).toBeUndefined();
      expect(screen.getByText("Неверный ID.")).toBeInTheDocument();
    },
  );

  it("passes canonical route ids to useAdminDeal", () => {
    mockState.deal = makeDeal();
    renderPage("10");
    expect(mockState.lastDealId).toBe(10);
  });

  it("renders status banner with description + status label", () => {
    mockState.deal = makeDeal();
    renderPage();
    expect(screen.getByText("Buying widgets")).toBeInTheDocument();
    expect(screen.getAllByText("В работе").length).toBeGreaterThan(0);
  });

  it("renders balance snapshot for buyer + seller cards", () => {
    mockState.deal = makeDeal();
    renderPage();
    expect(screen.getByText("Покупатель")).toBeInTheDocument();
    expect(screen.getByText("Продавец")).toBeInTheDocument();
    expect(screen.getByText("Buyer")).toBeInTheDocument();
    expect(screen.getByText("Seller")).toBeInTheDocument();
    expect(screen.getByText("$150.00")).toBeInTheDocument();
  });

  it("renders string and malformed finance fields without numeric coercion", () => {
    mockState.deal = makeDeal({
      amount: "150.5",
      commission_amount: "1e3",
      buyer: makeSnap({ user_id: 1, username: "buyer", display_name: "Buyer", amount: "12.3456", locked: "0x10" }),
    });
    renderPage();
    expect(screen.getByText("$150.50")).toBeInTheDocument();
    expect(screen.getByText("12.3456")).toBeInTheDocument();
    expect(screen.queryByText("0.00")).not.toBeInTheDocument();
    expect(screen.queryByText("0.0000")).not.toBeInTheDocument();
  });

  it("renders missing snapshot and chat usernames as non-handle labels", () => {
    mockState.deal = makeDeal({
      buyer: makeSnap({ user_id: 1, username: null, display_name: "Buyer" }),
      seller: makeSnap({ user_id: 2, username: null, display_name: "Seller" }),
    });
    mockState.messages = [makeMessage({ sender_username: null })];
    renderPage();
    expect(screen.getAllByText(/username \u043d\u0435 \u0437\u0430\u0434\u0430\u043d/).length).toBeGreaterThan(0);
    expect(screen.queryByText(/@\u2014/)).not.toBeInTheDocument();
  });

  it("does not double-prefix admin chat usernames with @", () => {
    mockState.deal = makeDeal();
    mockState.messages = [makeMessage({ sender_username: "buyer" })];
    renderPage();
    expect(screen.getAllByText(/@buyer/).length).toBeGreaterThan(0);
    expect(screen.queryByText(/@@buyer/)).not.toBeInTheDocument();
  });

  it("renders malformed event and message timestamps as neutral values", () => {
    mockState.deal = makeDeal({
      events: [
        {
          at: "not-a-date",
          kind: "created",
          actor: "buyer",
          description: "bad timestamp",
        },
      ],
    });
    mockState.messages = [makeMessage({ created_at: "not-a-date" })];
    renderPage();
    expect(
      screen.getAllByText((_, element) => Boolean(element?.textContent?.includes("\u2014"))).length,
    ).toBeGreaterThan(0);
    expect(screen.queryByText(/Invalid Date/)).not.toBeInTheDocument();
  });

  it("shows arbitration-danger banner when status=arbitration with reason", () => {
    mockState.deal = makeDeal({
      status: "arbitration",
      arbitration_reason: "товар не пришёл",
    });
    renderPage();
    expect(
      screen.getByText(/Причина арбитража: товар не пришёл/),
    ).toBeInTheDocument();
  });

  it("hides ActionPanel when me.is_admin is false (arbiter view)", () => {
    mockState.me = { id: 999, is_admin: false };
    mockState.deal = makeDeal();
    renderPage();
    expect(
      screen.queryByRole("button", { name: /Принудительное завершение/ }),
    ).not.toBeInTheDocument();
  });

  it("renders all action buttons when me.is_admin is true", () => {
    mockState.deal = makeDeal();
    renderPage();
    expect(
      screen.getByRole("button", { name: /Принудительное завершение/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /Возврат покупателю/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /Сплит-выплата/i }),
    ).toBeInTheDocument();
  });

  it("disables money-moving admin actions when the deal amount is malformed", () => {
    mockState.deal = makeDeal({ amount: "1e3" as unknown as string });
    renderPage();

    expect(screen.getByText("\u2014")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /Принудительное завершение/i }),
    ).toBeDisabled();
    expect(
      screen.getByRole("button", { name: /Возврат покупателю/i }),
    ).toBeDisabled();
    expect(
      screen.getByRole("button", { name: /Сплит-выплата/i }),
    ).toBeDisabled();
    expect(
      screen.getByRole("button", { name: /Открыть арбитраж/i }),
    ).toBeEnabled();
    expect(
      screen.getByRole("button", { name: /Удалить сделку/i }),
    ).toBeEnabled();
  });

  it("looks up an assigned arbiter through a first-page exact search", async () => {
    mockState.deal = makeDeal({ status: "arbitration" });
    mockState.assign.mutateAsync.mockResolvedValue({});
    apiGetSpy.mockReturnValueOnce({
      json: async () => ({
        items: [{ id: 777, username: "arbiter1", is_arbiter: true }],
      }),
    });
    const user = userEvent.setup();

    renderPage();
    await user.click(
      screen.getByRole("button", { name: /\u041d\u0430\u0437\u043d\u0430\u0447\u0438\u0442\u044c/i }),
    );
    await user.type(screen.getByPlaceholderText("@arbiter1"), "@arbiter1");
    const confirmBtns = await screen.findAllByRole("button", {
      name: /\u041f\u043e\u0434\u0442\u0432\u0435\u0440\u0434\u0438\u0442\u044c/i,
    });
    await user.click(confirmBtns[confirmBtns.length - 1]);

    await waitFor(() =>
      expect(apiGetSpy).toHaveBeenCalledWith("api/admin/users", {
        searchParams: { q: "@arbiter1", page: "1", page_size: "1" },
      }),
    );
    await waitFor(() =>
      expect(mockState.assign.mutateAsync).toHaveBeenCalledWith({
        dealId: 10,
        body: { arbiter_id: 777 },
      }),
    );
  });

  it("opens release sheet, fires force-release with reason", async () => {
    mockState.deal = makeDeal();
    mockState.release.mutateAsync.mockResolvedValue({});
    const user = userEvent.setup();
    renderPage();
    await user.click(
      screen.getByRole("button", { name: /Принудительное завершение/i }),
    );
    const confirmBtns = await screen.findAllByRole("button", {
      name: /Подтвердить/i,
    });
    await user.click(confirmBtns[confirmBtns.length - 1]);
    await waitFor(() =>
      expect(mockState.release.mutateAsync).toHaveBeenCalledWith(
        expect.objectContaining({ dealId: 10 }),
      ),
    );
  });

  it("blocks exponent split percent before sending an admin split", async () => {
    mockState.deal = makeDeal();
    const user = userEvent.setup();

    renderPage();
    await user.click(screen.getByRole("button", { name: /Сплит-выплата/i }));
    fireEvent.change(await screen.findByRole("spinbutton", { name: /Доля покупателя/i }), {
      target: { value: "1e2" },
    });
    const confirmBtns = screen.getAllByRole("button", { name: /Подтвердить/i });
    await user.click(confirmBtns[confirmBtns.length - 1]);

    expect(mockState.split.mutateAsync).not.toHaveBeenCalled();
    expect(toastSpy).toHaveBeenCalledWith(
      expect.objectContaining({ kind: "error", title: "Доля покупателя должна быть 0..100" }),
    );
  });

  it("blocks ambiguous approval ids before force-release", async () => {
    mockState.deal = makeDeal();
    const user = userEvent.setup();

    renderPage();
    await user.click(
      screen.getByRole("button", { name: /Принудительное завершение/i }),
    );
    fireEvent.change(await screen.findByLabelText("Approval ID"), {
      target: { value: "0x10" },
    });
    const confirmBtns = screen.getAllByRole("button", { name: /Подтвердить/i });
    await user.click(confirmBtns[confirmBtns.length - 1]);

    expect(mockState.release.mutateAsync).not.toHaveBeenCalled();
    expect(toastSpy).toHaveBeenCalledWith(
      expect.objectContaining({ kind: "error", title: "Неверный Approval ID" }),
    );
  });

  it("renders the events timeline with all event descriptions", () => {
    mockState.deal = makeDeal();
    renderPage();
    expect(screen.getByText("Создана")).toBeInTheDocument();
    expect(screen.getByText("Запущена")).toBeInTheDocument();
  });

  it("loads older chat messages through the cursor hook", async () => {
    mockState.deal = makeDeal();
    mockState.messages = Array.from({ length: 50 }, (_, index) =>
      makeMessage({ id: 100 + index, text: `message ${index}` }),
    );
    mockState.loadOlder.mutateAsync.mockResolvedValue([
      makeMessage({ id: 99, text: "older" }),
    ]);
    const user = userEvent.setup();

    renderPage();
    const loadOlderButton = getLoadOlderButton();
    expect(loadOlderButton).toBeDefined();
    await user.click(loadOlderButton!);

    await waitFor(() =>
      expect(mockState.loadOlder.mutateAsync).toHaveBeenCalledWith({ beforeId: 100 }),
    );
    await waitFor(() => expect(getLoadOlderButton()).toBeUndefined());
  });

  it("sends admin chat messages through the shared message hook", async () => {
    mockState.deal = makeDeal();
    mockState.messages = [makeMessage({ id: 1, text: "existing" })];
    mockState.sendMessage.mutateAsync.mockResolvedValue(makeMessage({ id: 2, text: "hello" }));
    const user = userEvent.setup();

    renderPage();
    await user.type(screen.getByRole("textbox"), "hello");
    const buttons = screen.getAllByRole("button");
    await user.click(buttons[buttons.length - 1]);

    await waitFor(() =>
      expect(mockState.sendMessage.mutateAsync).toHaveBeenCalledWith({
        text: "hello",
        attachments: [],
      }),
    );
  });

  it("disables admin action buttons when status is terminal (completed)", () => {
    mockState.deal = makeDeal({ status: "completed" });
    renderPage();
    expect(
      screen.getByRole("button", { name: /Принудительное завершение/i }),
    ).toBeDisabled();
    expect(
      screen.getByRole("button", { name: /Возврат покупателю/i }),
    ).toBeDisabled();
  });
});
