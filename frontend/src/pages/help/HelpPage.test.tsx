import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import HelpPage from "./HelpPage";

/**
 * Tests for the in-app FAQ page (renamed from the old "Поддержка"
 * admin/arbiter contacts view in V14). The page is now a static
 * accordion of rules / billing / dispute sections — no external
 * data dependency — so the tests just verify the header,
 * welcome card, and accordion toggle behaviour.
 */
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

describe("<HelpPage />", () => {
  it("renders the header and the welcome card", () => {
    renderPage();
    expect(screen.getByRole("heading", { name: "Помощь" })).toBeInTheDocument();
    expect(screen.getByText(/FAQ EW Гарант/)).toBeInTheDocument();
  });

  it("renders all FAQ rows collapsed by default", () => {
    renderPage();
    expect(screen.getByRole("button", { name: /Полные правила/ })).toHaveAttribute(
      "aria-expanded",
      "false",
    );
    expect(
      screen.getByRole("button", { name: /Пользовательское соглашение/ }),
    ).toHaveAttribute("aria-expanded", "false");
  });

  it("expands an FAQ section when its row is clicked", async () => {
    const user = userEvent.setup();
    renderPage();
    const row = screen.getByRole("button", { name: /Полные правила/ });
    await user.click(row);
    expect(row).toHaveAttribute("aria-expanded", "true");
  });

  it("collapses the previously expanded section when another row is opened", async () => {
    const user = userEvent.setup();
    renderPage();
    const first = screen.getByRole("button", { name: /Полные правила/ });
    const second = screen.getByRole("button", {
      name: /Пользовательское соглашение/,
    });
    await user.click(first);
    expect(first).toHaveAttribute("aria-expanded", "true");
    await user.click(second);
    expect(first).toHaveAttribute("aria-expanded", "false");
    expect(second).toHaveAttribute("aria-expanded", "true");
  });
});
