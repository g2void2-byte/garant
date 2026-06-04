import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { AdminAuditLogListDto } from "@/api/types";

/**
 * Tests for `/admin/audit`.
 *
 * Covers loading skeleton, empty state, log row rendering (action,
 * actor, target, reason, payload truncation), filter inputs (action +
 * actor_id) propagation to the query, pagination next/prev gating, and
 * the `useAdminRedirect` gate.
 */

const mockState = vi.hoisted(() => ({
  list: undefined as AdminAuditLogListDto | undefined,
  loading: false,
  shouldRender: true as boolean,
  lastQuery: {} as {
    action?: string;
    actor_id?: number;
    page?: number;
    page_size?: number;
  },
}));

vi.mock("@/api/admin/hooks", () => ({
  useAdminAuditLog: (query: {
    action?: string;
    actor_id?: number;
    page?: number;
    page_size?: number;
  }) => {
    mockState.lastQuery = query;
    return { data: mockState.list, isLoading: mockState.loading };
  },
}));

vi.mock("@/hooks/useAdminRedirect", () => ({
  useAdminRedirect: () => ({ shouldRender: mockState.shouldRender }),
}));

import AdminAuditPage from "./AdminAuditPage";

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <AdminAuditPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function makeRow(
  overrides: Partial<AdminAuditLogListDto["items"][number]> = {},
): AdminAuditLogListDto["items"][number] {
  return {
    id: 1,
    actor_id: 5,
    actor_username: "admin",
    action: "user.ban",
    target_type: "user",
    target_id: 42,
    reason: "spam",
    payload: { note: "test" },
    ip: "1.2.3.4",
    created_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

beforeEach(() => {
  mockState.list = undefined;
  mockState.loading = false;
  mockState.shouldRender = true;
  mockState.lastQuery = {};
});

describe("<AdminAuditPage />", () => {
  it("returns null when admin guard rejects the visitor", () => {
    mockState.shouldRender = false;
    renderPage();
    expect(screen.queryByText("Аудит")).not.toBeInTheDocument();
  });

  it("renders skeleton rows while the log is loading", () => {
    mockState.loading = true;
    const { container } = renderPage();
    expect(container.querySelectorAll(".rounded-card.h-16").length).toBe(10);
  });

  it("renders an empty state when no items match", () => {
    mockState.list = { items: [], total: 0, page: 1, page_size: 50 };
    renderPage();
    expect(screen.getByText("Событий не найдено")).toBeInTheDocument();
  });

  it("renders a single row with action, actor, target, reason, ip", () => {
    mockState.list = { items: [makeRow()], total: 1, page: 1, page_size: 50 };
    renderPage();
    expect(screen.getByText("user.ban")).toBeInTheDocument();
    expect(screen.getByText(/by @admin/)).toBeInTheDocument();
    expect(screen.getByText(/target: user#42/)).toBeInTheDocument();
    expect(screen.getByText(/1\.2\.3\.4/)).toBeInTheDocument();
    expect(screen.getByText(/Причина: spam/)).toBeInTheDocument();
  });

  it("falls back to actor_id without pretending it is a username, and to 'system' when actor_id is also null", () => {
    mockState.list = {
      items: [
        makeRow({ id: 1, actor_username: null, actor_id: 7 }),
        makeRow({ id: 2, actor_username: null, actor_id: null }),
      ],
      total: 2,
      page: 1,
      page_size: 50,
    };
    renderPage();
    expect(screen.getByText(/by user #7/)).toBeInTheDocument();
    expect(screen.getByText(/by system/)).toBeInTheDocument();
    expect(screen.queryByText(/by @7/)).not.toBeInTheDocument();
    expect(screen.queryByText(/by @system/)).not.toBeInTheDocument();
  });

  it("renders malformed created_at as a neutral timestamp", () => {
    mockState.list = {
      items: [makeRow({ created_at: "not-a-date" })],
      total: 1,
      page: 1,
      page_size: 50,
    };
    renderPage();
    expect(screen.getByText("\u2014")).toBeInTheDocument();
    expect(screen.queryByText(/Invalid Date/)).not.toBeInTheDocument();
  });

  it("renders payload as a truncated JSON block when it has keys", () => {
    mockState.list = {
      items: [
        makeRow({
          payload: { a: 1, b: "hello".repeat(60) },
        }),
      ],
      total: 1,
      page: 1,
      page_size: 50,
    };
    const { container } = renderPage();
    const pre = container.querySelector("pre");
    expect(pre).not.toBeNull();
    expect(pre!.textContent!.length).toBeLessThanOrEqual(243);
    expect(pre!.textContent).toContain("...");
  });

  it("does not render a payload block when payload is empty", () => {
    mockState.list = {
      items: [makeRow({ payload: {} })],
      total: 1,
      page: 1,
      page_size: 50,
    };
    const { container } = renderPage();
    expect(container.querySelector("pre")).toBeNull();
  });

  it("filters toggle hides/shows the filter inputs", async () => {
    mockState.list = { items: [], total: 0, page: 1, page_size: 50 };
    const user = userEvent.setup();
    renderPage();

    expect(screen.queryByPlaceholderText(/^action /)).not.toBeInTheDocument();

    const filterBtn = document.querySelector(
      'button[type="button"] svg.lucide-funnel, button[type="button"] svg.lucide-filter',
    )?.closest("button") as HTMLButtonElement | null;
    expect(filterBtn).not.toBeNull();
    await user.click(filterBtn!);

    expect(screen.getByPlaceholderText(/action \(e\.g\./)).toBeInTheDocument();
    expect(screen.getByPlaceholderText("actor_id")).toBeInTheDocument();
  });

  it("typing in 'action' filter passes a trimmed query and resets page to 1", async () => {
    mockState.list = {
      items: [],
      total: 100,
      page: 3,
      page_size: 50,
    };
    const user = userEvent.setup();
    renderPage();

    const filterBtn = document
      .querySelector("svg.lucide-filter, svg.lucide-funnel")
      ?.closest("button") as HTMLButtonElement;
    await user.click(filterBtn);
    const actionInput = screen.getByPlaceholderText(/action \(e\.g\./);
    fireEvent.change(actionInput, { target: { value: "  user.ban  " } });
    await waitFor(() =>
      expect(mockState.lastQuery.action).toBe("user.ban"),
    );
    expect(mockState.lastQuery.page).toBe(1);
  });

  it("typing in 'actor_id' filter passes a numeric value", async () => {
    mockState.list = { items: [], total: 0, page: 1, page_size: 50 };
    const user = userEvent.setup();
    renderPage();

    const filterBtn = document
      .querySelector("svg.lucide-filter, svg.lucide-funnel")
      ?.closest("button") as HTMLButtonElement;
    await user.click(filterBtn);
    fireEvent.change(screen.getByPlaceholderText("actor_id"), {
      target: { value: "42" },
    });
    await waitFor(() => expect(mockState.lastQuery.actor_id).toBe(42));
  });

  it("does not send invalid actor_id filters", async () => {
    mockState.list = { items: [], total: 0, page: 1, page_size: 50 };
    const user = userEvent.setup();
    renderPage();

    const filterBtn = document
      .querySelector("svg.lucide-filter, svg.lucide-funnel")
      ?.closest("button") as HTMLButtonElement;
    await user.click(filterBtn);
    fireEvent.change(screen.getByPlaceholderText("actor_id"), {
      target: { value: "0" },
    });
    await waitFor(() => expect(mockState.lastQuery.actor_id).toBeUndefined());

    fireEvent.change(screen.getByPlaceholderText("actor_id"), {
      target: { value: "abc" },
    });
    await waitFor(() => expect(mockState.lastQuery.actor_id).toBeUndefined());
  });

  it("renders pagination when total > page_size and disables 'Назад' on page 1", () => {
    mockState.list = { items: [makeRow()], total: 120, page: 1, page_size: 50 };
    renderPage();
    const prev = screen.getByRole("button", { name: /Назад/ });
    const next = screen.getByRole("button", { name: /Вперёд/ });
    expect(prev).toBeDisabled();
    expect(next).not.toBeDisabled();
    expect(screen.getByText("1 / 3")).toBeInTheDocument();
  });

  it("'Вперёд' click advances the page", async () => {
    mockState.list = { items: [makeRow()], total: 200, page: 1, page_size: 50 };
    const user = userEvent.setup();
    renderPage();
    await user.click(screen.getByRole("button", { name: /Вперёд/ }));
    await waitFor(() => expect(mockState.lastQuery.page).toBe(2));
  });

  it("does NOT render pagination when total <= page_size", () => {
    mockState.list = { items: [makeRow()], total: 1, page: 1, page_size: 50 };
    renderPage();
    expect(
      screen.queryByRole("button", { name: /Вперёд/ }),
    ).not.toBeInTheDocument();
  });

  it("does not coerce malformed totals into pagination", () => {
    mockState.list = {
      items: [makeRow()],
      total: "1e2" as unknown as number,
      page: 1,
      page_size: 50,
    };
    renderPage();
    expect(screen.queryByText("1e2")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /Вперёд/ }),
    ).not.toBeInTheDocument();
  });
});
