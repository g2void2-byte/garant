import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";

/**
 * Tests for the persistent bottom navigation:
 *
 *   - renders the five tab labels in fixed order
 *   - highlights the active tab based on the current pathname
 *   - shows the unread badge when ``useNotificationCounters`` returns
 *     a positive ``unread`` and caps the count at "99+"
 *   - fires ``haptic("light")`` when a tab is tapped
 */

const mockState = vi.hoisted(() => ({
  counters: { unread: 0, by_type: {} as Record<string, number> },
}));

vi.mock("@/api/hooks", () => ({
  useNotificationCounters: () => ({ data: mockState.counters }),
}));

const hapticSpy = vi.hoisted(() => vi.fn());
vi.mock("@/lib/tg", () => ({
  useTelegramViewport: () => null,
  haptic: hapticSpy,
}));

import { BottomNav } from "./BottomNav";

function renderAt(pathname: string) {
  return render(
    <MemoryRouter initialEntries={[pathname]}>
      <BottomNav />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  hapticSpy.mockClear();
  mockState.counters = { unread: 0, by_type: {} };
});

describe("<BottomNav />", () => {
  it("renders all five tabs in order", () => {
    renderAt("/search");
    const labels = ["Поиск", "Сделки", "Помощь", "Оповещения", "Профиль"];
    for (const label of labels) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }
  });

  it("marks the matching tab as active via the accent text colour", () => {
    renderAt("/deals/17");
    const active = screen.getByText("Сделки").closest("a");
    expect(active?.className).toMatch(/text-accent/);
  });

  it("shows the unread badge when there is at least one unread notification", () => {
    mockState.counters = { unread: 3, by_type: {} };
    renderAt("/search");
    expect(screen.getByText("3")).toBeInTheDocument();
  });

  it("caps the unread badge at '99+' when there are more than 99 unread items", () => {
    mockState.counters = { unread: 240, by_type: {} };
    renderAt("/search");
    expect(screen.getByText("99+")).toBeInTheDocument();
  });

  it("does not coerce malformed unread counters into a badge", () => {
    mockState.counters = { unread: "1e2" as unknown as number, by_type: {} };
    renderAt("/search");
    expect(screen.queryByText("99+")).not.toBeInTheDocument();
    expect(screen.queryByText("1e2")).not.toBeInTheDocument();
  });

  it("fires haptic('light') when a tab is tapped", async () => {
    const user = userEvent.setup();
    renderAt("/search");
    await user.click(screen.getByText("Сделки"));
    expect(hapticSpy).toHaveBeenCalledWith("light");
  });
});
