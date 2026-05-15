import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { SupportPersonDto } from "@/api/types";

/**
 * Tests for the "Поддержка" help page that shows two tabs of
 * support staff — administrators and arbiters — fetched from the
 * matching list endpoints.
 */

const mockState = vi.hoisted(() => ({
  admins: undefined as SupportPersonDto[] | undefined,
  arbiters: undefined as SupportPersonDto[] | undefined,
  loadingAdmins: false,
  loadingArbiters: false,
}));

vi.mock("@/api/hooks", () => ({
  useAdmins: () => ({
    data: mockState.admins,
    isLoading: mockState.loadingAdmins,
  }),
  useArbiters: () => ({
    data: mockState.arbiters,
    isLoading: mockState.loadingArbiters,
  }),
}));

import HelpPage from "./HelpPage";

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <HelpPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function makeSupport(over: Partial<SupportPersonDto> = {}): SupportPersonDto {
  return {
    id: 1,
    user_id: 1,
    username: "support",
    display_name: "Support",
    photo_url: null,
    admin: 1,
    prefix: "admin",
    ...over,
  };
}

beforeEach(() => {
  mockState.admins = [];
  mockState.arbiters = [];
  mockState.loadingAdmins = false;
  mockState.loadingArbiters = false;
});

describe("<HelpPage />", () => {
  it("renders the header and tab labels", () => {
    renderPage();
    expect(
      screen.getByRole("heading", { name: "Поддержка" }),
    ).toBeInTheDocument();
    expect(screen.getByText(/Администрация/)).toBeInTheDocument();
    expect(screen.getByText(/Арбитры/)).toBeInTheDocument();
  });

  it("shows the loading skeleton while admins are loading", () => {
    mockState.loadingAdmins = true;
    mockState.admins = undefined;
    const { container } = renderPage();
    expect(container.querySelector(".shimmer")).not.toBeNull();
  });

  it("renders the empty-state when the admins list is empty", () => {
    renderPage();
    expect(screen.getByText("Никого нет в этой группе")).toBeInTheDocument();
  });

  it("renders the admins list and switches to the arbiters tab on click", async () => {
    mockState.admins = [
      makeSupport({ id: 11, username: "ops", display_name: "Ops", prefix: "admin" }),
    ];
    mockState.arbiters = [
      makeSupport({ id: 22, username: "jury", display_name: "Jury", prefix: "arbiter" }),
    ];

    const user = userEvent.setup();
    renderPage();
    expect(screen.getByText("Ops")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /Арбитры/ }));
    expect(screen.getByText("Jury")).toBeInTheDocument();
  });
});
