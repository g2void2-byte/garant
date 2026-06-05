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
  lastPage: 1 as number | undefined,
}));

vi.mock("@/api/admin/hooks", () => ({
  useAdminWithdrawals: ({ status, page }: { status: string; page?: number }) => {
    mockState.lastStatus = status;
    mockState.lastPage = page;
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

function renderedNeutralIds(container: HTMLElement): number {
  return (container.textContent ?? "").match(/#\s*\u2014/g)?.length ?? 0;
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
  mockState.lastPage = 1;
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

  it("does not coerce malformed status counters into badges or pagination", () => {
    mockState.list = {
      items: [makeItem()],
      counters: {
        pending: "1e2" as unknown as number,
        sent: "0x10" as unknown as number,
      },
    };
    renderPage();
    expect(screen.queryByText("1e2")).not.toBeInTheDocument();
    expect(screen.queryByText("0x10")).not.toBeInTheDocument();
    expect(screen.queryByText(/1 \/ 2/)).not.toBeInTheDocument();
  });

  it("renders missing withdrawal username as a non-handle label", () => {
    mockState.list = { items: [makeItem({ username: null })], counters: {} };
    renderPage();
    expect(screen.getByText(/username \u043d\u0435 \u0437\u0430\u0434\u0430\u043d/)).toBeInTheDocument();
    expect(screen.queryByText(/@\u2014/)).not.toBeInTheDocument();
  });

  it("renders malformed created_at as a neutral timestamp", () => {
    mockState.list = { items: [makeItem({ created_at: "not-a-date" })], counters: {} };
    renderPage();
    expect(screen.getByText("\u2014")).toBeInTheDocument();
    expect(screen.queryByText(/Invalid Date/)).not.toBeInTheDocument();
  });

  it("switches status when a different tab is clicked", async () => {
    mockState.list = { items: [], counters: {} };
    const user = userEvent.setup();
    renderPage();
    expect(mockState.lastStatus).toBe("pending");
    await user.click(screen.getByRole("button", { name: /Отправленные/ }));
    await waitFor(() => expect(mockState.lastStatus).toBe("sent"));
  });

  it("pagination advances beyond page one and resets when status changes", async () => {
    mockState.list = {
      items: [makeItem()],
      counters: { pending: 80, sent: 70 },
    };
    const user = userEvent.setup();
    renderPage();

    expect(screen.getByText("1 / 2")).toBeInTheDocument();
    await user.click(screen.getByLabelText("Вперёд"));
    await waitFor(() => expect(mockState.lastPage).toBe(2));

    await user.click(screen.getByRole("button", { name: /Отправленные/ }));
    await waitFor(() => {
      expect(mockState.lastStatus).toBe("sent");
      expect(mockState.lastPage).toBe(1);
    });
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

  it("renders malformed withdrawal amounts as a neutral dash", () => {
    mockState.list = { items: [makeItem({ amount: "1e1" })], counters: { pending: 1 } };
    renderPage();
    expect(screen.getByText(/\u2014 USDT/)).toBeInTheDocument();
    expect(screen.queryByText(/0\.00000000 USDT/)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", {
      name: /\u041e\u0434\u043e\u0431\u0440\u0438\u0442\u044c/,
    })).not.toBeInTheDocument();
    expect(screen.getByRole("button", {
      name: /\u041e\u0442\u043a\u043b\u043e\u043d\u0438\u0442\u044c/,
    })).toBeInTheDocument();
  });

  it("does not expose pending actions when the pending tab contains a non-pending row", () => {
    mockState.list = {
      items: [makeItem({ status: "provider_reconciled" })],
      counters: { pending: 1 },
    };
    renderPage();

    expect(screen.queryByRole("button", {
      name: /\u041e\u0434\u043e\u0431\u0440\u0438\u0442\u044c/,
    })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", {
      name: /\u041e\u0442\u043a\u043b\u043e\u043d\u0438\u0442\u044c/,
    })).not.toBeInTheDocument();
  });

  it("does not expose decision actions for malformed runtime withdrawal ids", () => {
    mockState.list = {
      items: [makeItem({ id: "0x1" as unknown as number })],
      counters: { pending: 1 },
    };

    const { container } = renderPage();

    expect(renderedNeutralIds(container)).toBe(1);
    expect(screen.queryByText(/0x1/)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", {
      name: /\u041e\u0434\u043e\u0431\u0440\u0438\u0442\u044c/,
    })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", {
      name: /\u041e\u0442\u043a\u043b\u043e\u043d\u0438\u0442\u044c/,
    })).not.toBeInTheDocument();
  });

  it("normalizes withdrawal currency labels before display", () => {
    mockState.list = {
      items: [
        makeItem({ currency_code: " usdt " }),
        makeItem({ id: 2, amount: "13.50000000", currency_code: "../USDT" }),
      ],
      counters: { pending: 2 },
    };
    renderPage();

    expect(screen.getByText(/12\.50000000 USDT/)).toBeInTheDocument();
    expect(screen.getByText(/13\.50000000 \u2014/)).toBeInTheDocument();
    expect(screen.queryByText(/ usdt /)).not.toBeInTheDocument();
    expect(screen.queryByText(/\.\.\/USDT/)).not.toBeInTheDocument();
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

  it("does not expose mark-sent for approved withdrawals with malformed amounts", async () => {
    mockState.list = {
      items: [makeItem({ amount: "1e1", status: "approved" })],
      counters: {},
    };
    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByRole("button", {
      name: /\u041e\u0434\u043e\u0431\u0440\u0435\u043d\u043d\u044b\u0435/,
    }));

    expect(screen.getByText(/\u2014 USDT/)).toBeInTheDocument();
    expect(screen.queryByRole("button", {
      name: /\u041e\u0442\u043c\u0435\u0447\u0435\u043d\u043e \u043e\u0442\u043f\u0440\u0430\u0432\u043b\u0435\u043d\u043e/,
    })).not.toBeInTheDocument();
  });

  it("does not expose mark-sent when the approved tab contains a non-approved row", async () => {
    mockState.list = {
      items: [makeItem({ status: "sent" })],
      counters: {},
    };
    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByRole("button", {
      name: /\u041e\u0434\u043e\u0431\u0440\u0435\u043d\u043d\u044b\u0435/,
    }));

    expect(screen.queryByRole("button", {
      name: /\u041e\u0442\u043c\u0435\u0447\u0435\u043d\u043e \u043e\u0442\u043f\u0440\u0430\u0432\u043b\u0435\u043d\u043e/,
    })).not.toBeInTheDocument();
  });

  it("does not expose mark-sent for approved withdrawals with malformed runtime ids", async () => {
    mockState.list = {
      items: [makeItem({ id: "0x2" as unknown as number, status: "approved" })],
      counters: {},
    };
    const user = userEvent.setup();
    const { container } = renderPage();

    await user.click(screen.getByRole("button", {
      name: /\u041e\u0434\u043e\u0431\u0440\u0435\u043d\u043d\u044b\u0435/,
    }));

    expect(renderedNeutralIds(container)).toBe(1);
    expect(screen.queryByText(/0x2/)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", {
      name: /\u041e\u0442\u043c\u0435\u0447\u0435\u043d\u043e \u043e\u0442\u043f\u0440\u0430\u0432\u043b\u0435\u043d\u043e/,
    })).not.toBeInTheDocument();
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
