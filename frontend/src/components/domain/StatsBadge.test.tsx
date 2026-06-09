import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { StatsBadge } from "./StatsBadge";

function renderBadge(stats: { users: unknown; deals: unknown; total_usd: unknown }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <StatsBadge title="" subtitle="" variant="compact" stats={stats} />
    </QueryClientProvider>,
  );
}

function finishAnimation() {
  act(() => {
    vi.advanceTimersByTime(1300);
  });
}

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("<StatsBadge />", () => {
  it("accepts canonical decimal-string runtime stats", () => {
    renderBadge({ users: "42", deals: "7", total_usd: "1500.5" });

    finishAnimation();

    expect(screen.getByText("42")).toBeInTheDocument();
    expect(screen.getByText("7")).toBeInTheDocument();
    expect(screen.getByText("$1,5K")).toBeInTheDocument();
  });

  it("does not coerce malformed runtime stats into public counters", () => {
    renderBadge({ users: "1e2", deals: "0x10", total_usd: "bad" });

    finishAnimation();

    expect(screen.queryByText("100")).not.toBeInTheDocument();
    expect(screen.queryByText("16")).not.toBeInTheDocument();
    expect(document.body).not.toHaveTextContent(/NaN/i);
    expect(screen.getAllByText("0").length).toBeGreaterThanOrEqual(2);
    expect(screen.getByText("$0")).toBeInTheDocument();
  });
});
