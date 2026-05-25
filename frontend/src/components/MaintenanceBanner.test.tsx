/**
 * Tests for ``<MaintenanceBanner />``.
 *
 * The banner mounts under ``QueryClientProvider`` in ``App.tsx`` and
 * polls ``/api/settings/maintenance`` every 30 s. It renders nothing
 * unless the response has ``enabled: true`` — then a warning banner
 * with the server-provided message appears at the top of the screen.
 *
 * Covers (V12-M5 — maintenance-баннер):
 * - hidden when the API has not responded yet,
 * - hidden when ``enabled: false``,
 * - visible with the server message when ``enabled: true``.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const jsonMock = vi.hoisted(() => vi.fn());

vi.mock("@/api/client", () => ({
  api: {
    get: () => ({ json: jsonMock }),
  },
}));

import { MaintenanceBanner } from "./MaintenanceBanner";

function renderBanner() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <MaintenanceBanner />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  jsonMock.mockReset();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("<MaintenanceBanner />", () => {
  it("renders nothing while the maintenance query is pending", () => {
    // Promise never resolves — query stays in the loading state, the
    // ``data?.enabled`` short-circuit must keep the banner hidden so a
    // stale render doesn't flash a banner with ``undefined`` text.
    jsonMock.mockReturnValue(new Promise(() => {}));

    const { container } = renderBanner();
    expect(container).toBeEmptyDOMElement();
  });

  it("renders nothing when the API reports maintenance disabled", async () => {
    jsonMock.mockResolvedValue({ enabled: false, message: null });

    const { container } = renderBanner();

    // Wait one microtask flush so React Query commits the resolved data.
    await waitFor(() => {
      expect(jsonMock).toHaveBeenCalled();
    });
    expect(container).toBeEmptyDOMElement();
  });

  it("renders the warning banner with the server message when enabled", async () => {
    jsonMock.mockResolvedValue({
      enabled: true,
      message: "Ведутся работы, депозиты временно недоступны.",
    });

    renderBanner();

    expect(
      await screen.findByText("Технические работы"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Ведутся работы, депозиты временно недоступны."),
    ).toBeInTheDocument();
  });
});
