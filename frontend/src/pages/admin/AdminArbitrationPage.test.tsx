import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, useLocation } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { AdminArbitrationListDto } from "@/api/types";

/**
 * Tests for `/admin/arbitration` (3-tab queue).
 *
 * Covers tab switching with counter badges, claim mutation (success +
 * 409 conflict + generic error), navigation to deal detail, empty
 * states per tab, and the `useAdminRedirect({ allowArbiter: true })`
 * gate.
 */

const mockState = vi.hoisted(() => ({
  list: undefined as AdminArbitrationListDto | undefined,
  loading: false,
  claimMutation: {
    mutateAsync: vi.fn() as ReturnType<typeof vi.fn>,
    isPending: false,
  },
  shouldRender: true as boolean,
  lastQueue: "new" as string,
  lastPage: 1 as number | undefined,
  lastPageSize: 20 as number | undefined,
  lastRedirectOpts: undefined as
    | { allowArbiter?: boolean; redirectTo?: string }
    | undefined,
}));

vi.mock("@/api/admin/hooks", () => ({
  useAdminArbitration: (queue: string, page?: number, pageSize?: number) => {
    mockState.lastQueue = queue;
    mockState.lastPage = page;
    mockState.lastPageSize = pageSize;
    return { data: mockState.list, isLoading: mockState.loading };
  },
  useAdminClaimArbitration: () => mockState.claimMutation,
}));

vi.mock("@/hooks/useAdminRedirect", () => ({
  useAdminRedirect: (opts?: { allowArbiter?: boolean }) => {
    mockState.lastRedirectOpts = opts;
    return { shouldRender: mockState.shouldRender };
  },
}));

const toastSpy = vi.hoisted(() => vi.fn());
vi.mock("@/components/ui/Toast", () => ({
  useToast: () => ({ show: toastSpy }),
}));

const hapticSpy = vi.hoisted(() => vi.fn());
vi.mock("@/lib/tg", () => ({
  useTelegramViewport: () => null,
  haptic: hapticSpy,
  showBackButton: () => () => {},
}));

import AdminArbitrationPage from "./AdminArbitrationPage";

function LocationProbe() {
  const loc = useLocation();
  return <span data-testid="path">{loc.pathname}</span>;
}

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={["/admin/arbitration"]}>
        <AdminArbitrationPage />
        <LocationProbe />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function makeItem(
  overrides: Partial<AdminArbitrationListDto["items"][number]> = {},
): AdminArbitrationListDto["items"][number] {
  return {
    id: 7,
    status: "arbitration",
    currency_code: "USDT",
    amount: "147",
    commission_amount: "3",
    buyer_id: 1,
    buyer_username: "buyer1",
    seller_id: 2,
    seller_username: "seller2",
    created_at: "2026-01-01T00:00:00Z",
    in_progress_at: null,
    completed_at: null,
    has_arbitration: true,
    has_cancel_request: false,
    ...overrides,
  };
}

beforeEach(() => {
  mockState.list = undefined;
  mockState.loading = false;
  mockState.claimMutation = {
    mutateAsync: vi.fn(),
    isPending: false,
  };
  mockState.shouldRender = true;
  mockState.lastQueue = "new";
  mockState.lastPage = 1;
  mockState.lastPageSize = 20;
  toastSpy.mockClear();
  hapticSpy.mockClear();
});

describe("<AdminArbitrationPage />", () => {
  it("passes allowArbiter:true to the admin guard", () => {
    renderPage();
    expect(mockState.lastRedirectOpts).toEqual({ allowArbiter: true });
  });

  it("returns null when guard rejects the visitor", () => {
    mockState.shouldRender = false;
    renderPage();
    expect(screen.queryByText("Арбитраж")).not.toBeInTheDocument();
  });

  it("renders skeleton rows while loading", () => {
    mockState.loading = true;
    const { container } = renderPage();
    expect(container.querySelectorAll(".shimmer.h-24").length).toBe(3);
  });

  it("renders the queue empty state when the items list is empty (new queue)", () => {
    mockState.list = {
      items: [],
      counters: { new: 0, in_progress: 0, closed: 0 },
      queue: "new",
    };
    renderPage();
    expect(screen.getByText("Очередь пуста")).toBeInTheDocument();
    expect(
      screen.getByText("Новые споры появятся здесь."),
    ).toBeInTheDocument();
  });

  it("clicking 'В работе' switches the queue", async () => {
    mockState.list = {
      items: [],
      counters: { new: 1, in_progress: 0, closed: 0 },
      queue: "new",
    };
    const user = userEvent.setup();
    renderPage();
    expect(mockState.lastQueue).toBe("new");
    await user.click(screen.getByRole("button", { name: /В работе/ }));
    await waitFor(() => expect(mockState.lastQueue).toBe("in_progress"));
    expect(hapticSpy).toHaveBeenCalledWith("light");
  });

  it("renders missing party usernames as non-handle labels", () => {
    mockState.list = {
      items: [makeItem({ buyer_username: null, seller_username: null })],
      counters: { new: 1, in_progress: 0, closed: 0 },
      queue: "new",
    };
    renderPage();
    expect(screen.getAllByText(/username \u043d\u0435 \u0437\u0430\u0434\u0430\u043d/).length).toBeGreaterThan(0);
    expect(screen.queryByText(/@\u2014/)).not.toBeInTheDocument();
  });

  it("pagination advances beyond the first queue page and resets when tab changes", async () => {
    mockState.list = {
      items: [makeItem()],
      counters: { new: 45, in_progress: 22, closed: 0 },
      queue: "new",
    };
    const user = userEvent.setup();
    renderPage();

    expect(screen.getByText("1 / 3")).toBeInTheDocument();
    expect(mockState.lastPageSize).toBe(20);
    await user.click(screen.getByLabelText("\u0412\u043f\u0435\u0440\u0451\u0434"));
    await waitFor(() => expect(mockState.lastPage).toBe(2));

    await user.click(screen.getByRole("button", { name: /\u0412 \u0440\u0430\u0431\u043e\u0442\u0435/ }));
    await waitFor(() => {
      expect(mockState.lastQueue).toBe("in_progress");
      expect(mockState.lastPage).toBe(1);
    });
  });

  it("renders deal rows with parties, amount and currency", () => {
    mockState.list = {
      items: [makeItem()],
      counters: { new: 1, in_progress: 0, closed: 0 },
      queue: "new",
    };
    renderPage();
    expect(screen.getByText(/#7/)).toBeInTheDocument();
    expect(screen.getByText(/@buyer1.*@seller2/)).toBeInTheDocument();
    expect(screen.getByText(/147\.00 USDT/)).toBeInTheDocument();
  });

  it("renders 'Взять в работу' button on 'new' rows only", () => {
    mockState.list = {
      items: [makeItem()],
      counters: { new: 1, in_progress: 0, closed: 0 },
      queue: "new",
    };
    renderPage();
    expect(
      screen.getByRole("button", { name: /Взять в работу/ }),
    ).toBeInTheDocument();
  });

  it("claim happy path fires mutation, toasts success, switches to in_progress", async () => {
    mockState.list = {
      items: [makeItem()],
      counters: { new: 1, in_progress: 0, closed: 0 },
      queue: "new",
    };
    mockState.claimMutation.mutateAsync.mockResolvedValue({});
    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByRole("button", { name: /Взять в работу/ }));
    await waitFor(() =>
      expect(mockState.claimMutation.mutateAsync).toHaveBeenCalledWith(7),
    );
    expect(toastSpy).toHaveBeenCalledWith(
      expect.objectContaining({ kind: "success", title: "Дело взято в работу" }),
    );
    expect(hapticSpy).toHaveBeenCalledWith("medium");
    await waitFor(() => expect(mockState.lastQueue).toBe("in_progress"));
  });

  it("claim 409 conflict surfaces a 'дело уже занято' toast", async () => {
    mockState.list = {
      items: [makeItem()],
      counters: { new: 1, in_progress: 0, closed: 0 },
      queue: "new",
    };
    mockState.claimMutation.mutateAsync.mockRejectedValueOnce({
      response: { status: 409 },
      message: "Conflict",
    });
    const user = userEvent.setup();
    renderPage();
    await user.click(screen.getByRole("button", { name: /Взять в работу/ }));
    await waitFor(() =>
      expect(toastSpy).toHaveBeenCalledWith(
        expect.objectContaining({
          kind: "error",
          title: "Дело уже занято",
          body: "Кто-то опередил вас",
        }),
      ),
    );
    // Queue stays on "new" so the user sees the now-claimed row disappear.
    expect(mockState.lastQueue).toBe("new");
  });

  it("claim generic error surfaces 'не удалось взять' toast with message body", async () => {
    mockState.list = {
      items: [makeItem()],
      counters: { new: 1, in_progress: 0, closed: 0 },
      queue: "new",
    };
    mockState.claimMutation.mutateAsync.mockRejectedValueOnce(
      new Error("network"),
    );
    const user = userEvent.setup();
    renderPage();
    await user.click(screen.getByRole("button", { name: /Взять в работу/ }));
    await waitFor(() =>
      expect(toastSpy).toHaveBeenCalledWith(
        expect.objectContaining({
          kind: "error",
          title: "Не удалось взять",
          body: "network",
        }),
      ),
    );
  });

  it("clicking the row navigates to /admin/deals/<id>", async () => {
    mockState.list = {
      items: [makeItem()],
      counters: { new: 1, in_progress: 0, closed: 0 },
      queue: "new",
    };
    const user = userEvent.setup();
    renderPage();
    await user.click(screen.getByText(/@buyer1/));
    expect(screen.getByTestId("path").textContent).toBe("/admin/deals/7");
  });

  it("'in_progress' tab empty state reads 'Нет активных дел'", async () => {
    mockState.list = {
      items: [],
      counters: { new: 0, in_progress: 0, closed: 0 },
      queue: "in_progress",
    };
    const user = userEvent.setup();
    renderPage();
    await user.click(screen.getByRole("button", { name: /В работе/ }));
    expect(await screen.findByText("Нет активных дел")).toBeInTheDocument();
  });
});
