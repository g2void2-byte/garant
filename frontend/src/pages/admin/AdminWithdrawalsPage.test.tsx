import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { AdminWithdrawalListDto } from "@/api/types";

/**
 * Tests for `/admin/withdrawals` queue page.
 *
 * Covers loading skeleton, tab counters, empty state, approve / reject
 * (with optional `note` prompt) and "mark sent" mutations, and the
 * `useAdminRedirect` gate (non-admin → null render).
 */

const mockState = vi.hoisted(() => ({
  list: undefined as AdminWithdrawalListDto | undefined,
  loading: false,
  decideMutation: {
    mutateAsync: vi.fn() as ReturnType<typeof vi.fn>,
    isPending: false,
  },
  shouldRender: true as boolean,
  lastStatus: "pending" as string,
}));

vi.mock("@/api/admin/hooks", () => ({
  useAdminWithdrawals: ({ status }: { status: string }) => {
    mockState.lastStatus = status;
    return { data: mockState.list, isLoading: mockState.loading };
  },
  useAdminDecideWithdrawal: () => mockState.decideMutation,
}));

vi.mock("@/hooks/useAdminRedirect", () => ({
  useAdminRedirect: () => ({ shouldRender: mockState.shouldRender }),
}));

const toastSpy = vi.hoisted(() => vi.fn());
vi.mock("@/components/ui/Toast", () => ({
  useToast: () => ({ show: toastSpy }),
}));

import AdminWithdrawalsPage from "./AdminWithdrawalsPage";

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <AdminWithdrawalsPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function makeItem(
  overrides: Partial<AdminWithdrawalListDto["items"][number]> = {},
): AdminWithdrawalListDto["items"][number] {
  return {
    id: 1,
    user_id: 10,
    username: "alice",
    display_name: "Alice",
    currency_code: "USDT",
    amount: "12.50000000",
    address: "TJRabPrwbZyABCDEF",
    status: "pending",
    admin_note: "",
    created_at: "2026-01-01T00:00:00Z",
    processed_at: null,
    ...overrides,
  };
}

beforeEach(() => {
  toastSpy.mockClear();
  mockState.list = undefined;
  mockState.loading = false;
  mockState.decideMutation = {
    mutateAsync: vi.fn(),
    isPending: false,
  };
  mockState.shouldRender = true;
  mockState.lastStatus = "pending";
});

describe("<AdminWithdrawalsPage />", () => {
  it("returns null when admin guard rejects the visitor", () => {
    mockState.shouldRender = false;
    const { container } = renderPage();
    expect(container).toBeEmptyDOMElement();
  });

  it("renders skeletons while the list is loading", () => {
    mockState.loading = true;
    const { container } = renderPage();
    expect(container.querySelectorAll(".rounded-card.h-28").length).toBeGreaterThan(0);
  });

  it("renders an empty state when no items are present", () => {
    mockState.list = { items: [], counters: {} };
    renderPage();
    expect(screen.getByText("Заявок нет")).toBeInTheDocument();
  });

  it("shows counters next to status tabs", () => {
    mockState.list = {
      items: [],
      counters: { pending: 3, approved: 0, rejected: 1, sent: 7 },
    };
    renderPage();
    expect(screen.getByText("3")).toBeInTheDocument();
    expect(screen.getByText("1")).toBeInTheDocument();
    expect(screen.getByText("7")).toBeInTheDocument();
    expect(screen.queryByText("0")).not.toBeInTheDocument();
  });

  it("switches status when a different tab is clicked", async () => {
    mockState.list = { items: [], counters: {} };
    const user = userEvent.setup();
    renderPage();
    expect(mockState.lastStatus).toBe("pending");
    await user.click(screen.getByRole("button", { name: /Отправленные/ }));
    await waitFor(() => expect(mockState.lastStatus).toBe("sent"));
  });

  it("renders a pending item with Approve and Reject buttons", () => {
    mockState.list = {
      items: [makeItem()],
      counters: { pending: 1 },
    };
    renderPage();
    expect(screen.getByText(/12.50000000 USDT/)).toBeInTheDocument();
    expect(screen.getByText(/@alice/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Одобрить/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Отклонить/ })).toBeInTheDocument();
  });

  it("approve action calls mutate with action='approve' and toasts success", async () => {
    mockState.list = { items: [makeItem()], counters: {} };
    mockState.decideMutation.mutateAsync.mockResolvedValue({});
    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByRole("button", { name: /Одобрить/ }));
    await waitFor(() =>
      expect(mockState.decideMutation.mutateAsync).toHaveBeenCalledWith({
        id: 1,
        body: { action: "approve" },
      }),
    );
    expect(toastSpy).toHaveBeenCalledWith(
      expect.objectContaining({ kind: "success", title: "Одобрено" }),
    );
  });

  it("reject action collects a note via window.prompt and includes it in the payload", async () => {
    mockState.list = { items: [makeItem()], counters: {} };
    mockState.decideMutation.mutateAsync.mockResolvedValue({});
    const promptSpy = vi
      .spyOn(window, "prompt")
      .mockReturnValue("  Suspicious address  ");
    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByRole("button", { name: /Отклонить/ }));
    await waitFor(() =>
      expect(mockState.decideMutation.mutateAsync).toHaveBeenCalledWith({
        id: 1,
        body: { action: "reject", note: "Suspicious address" },
      }),
    );
    expect(toastSpy).toHaveBeenCalledWith(
      expect.objectContaining({ kind: "info", title: "Отклонено" }),
    );
    promptSpy.mockRestore();
  });

  it("reject without a note sends note=undefined", async () => {
    mockState.list = { items: [makeItem()], counters: {} };
    mockState.decideMutation.mutateAsync.mockResolvedValue({});
    const promptSpy = vi.spyOn(window, "prompt").mockReturnValue("");
    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByRole("button", { name: /Отклонить/ }));
    await waitFor(() =>
      expect(mockState.decideMutation.mutateAsync).toHaveBeenCalledWith({
        id: 1,
        body: { action: "reject", note: undefined },
      }),
    );
    promptSpy.mockRestore();
  });

  it("approve mutation failure surfaces a toast with the error body", async () => {
    mockState.list = { items: [makeItem()], counters: {} };
    mockState.decideMutation.mutateAsync.mockRejectedValueOnce(
      new Error("rate limited"),
    );
    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByRole("button", { name: /Одобрить/ }));
    await waitFor(() =>
      expect(toastSpy).toHaveBeenCalledWith(
        expect.objectContaining({
          kind: "error",
          title: "Ошибка",
          body: "rate limited",
        }),
      ),
    );
  });

  it("approved tab renders a 'Mark sent' button that fires action='mark_sent'", async () => {
    mockState.list = {
      items: [makeItem({ status: "approved" })],
      counters: {},
    };
    mockState.decideMutation.mutateAsync.mockResolvedValue({});
    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByRole("button", { name: /Одобренные/ }));
    const markBtn = await screen.findByRole("button", {
      name: /Отмечено отправлено/,
    });
    await user.click(markBtn);
    await waitFor(() =>
      expect(mockState.decideMutation.mutateAsync).toHaveBeenCalledWith({
        id: 1,
        body: { action: "mark_sent" },
      }),
    );
    expect(toastSpy).toHaveBeenCalledWith(
      expect.objectContaining({
        kind: "success",
        title: "Отмечено как отправлено",
      }),
    );
  });

  it("renders the admin_note when present", () => {
    mockState.list = {
      items: [makeItem({ admin_note: "Suspicious user" })],
      counters: {},
    };
    renderPage();
    expect(screen.getByText(/Комментарий: Suspicious user/)).toBeInTheDocument();
  });

  it("copy button writes the address into the clipboard and toasts info", async () => {
    mockState.list = { items: [makeItem({ address: "TJabc" })], counters: {} };
    // `userEvent.setup()` initialises navigator.clipboard inside the
    // test setup pipeline; spy on the already-installed function so we
    // don't fight test-file ordering and frozen descriptors.
    userEvent.setup();
    const writeSpy = vi.spyOn(navigator.clipboard, "writeText");
    const { container } = renderPage();

    const addressRow = container.querySelector(
      "div.bg-panel-2.rounded-button",
    ) as HTMLElement | null;
    expect(addressRow).not.toBeNull();
    const copyBtn = addressRow!.querySelector(
      "button",
    ) as HTMLButtonElement | null;
    expect(copyBtn).not.toBeNull();
    copyBtn!.click();
    expect(writeSpy).toHaveBeenCalledWith("TJabc");
    expect(toastSpy).toHaveBeenCalledWith(
      expect.objectContaining({ kind: "info", title: "Скопировано" }),
    );
    writeSpy.mockRestore();
  });
});
